"""Refresh stale input fingerprints by comparing re-converted tables with the saved ones by content.

The fingerprint of the converter code only says "something may have changed". The decision is the
content: when every re-converted table equals its saved table (columns, types, rows and their order, and
the metadata the converter writes to the manifest), only ``input_fingerprint`` in the Git manifest is
rewritten. The saved Parquet, its sha256 and size stay as they are. R2 is read, never written. When any
table differs, or the current save gate would refuse it, the manifest is left untouched.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

import duckdb

from ingestion.fiscal import manifest, run, storage, unit_checks
from ingestion.lib import node_tables
from ingestion.paths import PIPELINE

CURRENT, REFRESHED, WOULD_REFRESH = 'current', 'refreshed', 'would-refresh'
DIFFERENT, BLOCKED, ERROR, NO_TABLES = 'different', 'blocked', 'error', 'no-saved-tables'
SAME = 'same'
EXAMPLES = 5


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def columns_of(con: duckdb.DuckDBPyConnection, path: Path) -> list[tuple[str, str]]:
    rows = con.execute('describe select * from read_parquet(?, hive_partitioning=false)', [str(path)]).fetchall()
    return [(row[0], row[1]) for row in rows]


def differs(left: object, right: object) -> bool:
    return left != right and not (left != left and right != right)


def compare_parquet(saved: Path, candidate: Path, *, examples: int = EXAMPLES) -> dict:
    """Compare two Parquet files by content, never by bytes.

    ``removed``/``added`` are rows only in the saved/candidate file (multiset difference);
    ``changed`` counts positions present in both files whose rows differ, so a pure reorder shows up
    as ``changed`` with nothing added or removed.
    """
    if manifest.sha_file(saved) == manifest.sha_file(candidate):
        return {'same': True, 'identical_bytes': True}
    with duckdb.connect() as con:
        old, new = columns_of(con, saved), columns_of(con, candidate)
        totals = {label: con.execute('select count(*) from read_parquet(?, hive_partitioning=false)',
                                     [str(path)]).fetchone()[0]
                  for label, path in (('saved', saved), ('candidate', candidate))}
        if old != new:
            return {'same': False, 'rows': totals,
                    'schema': {'removed': [name for name, _ in old if name not in dict(new)],
                               'added': [name for name, _ in new if name not in dict(old)],
                               'type_changed': [{'column': name, 'saved': kind, 'candidate': dict(new)[name]}
                                                for name, kind in old if name in dict(new) and dict(new)[name] != kind],
                               'reordered': sorted(n for n, _ in old) == sorted(n for n, _ in new)
                               and [n for n, _ in old] != [n for n, _ in new]}}
        names = [name for name, _ in old]
        select = ', '.join(quote(name) for name in names) or 'null'
        for label, path in (('a', saved), ('b', candidate)):
            con.execute(f'create temp table {label} as select file_row_number as __row, {select} '
                        f'from read_parquet(?, file_row_number=true, hive_partitioning=false)', [str(path)])
        removed = f'select {select} from a except all select {select} from b'
        added = f'select {select} from b except all select {select} from a'
        distinct = ' or '.join(f'a.{quote(name)} is distinct from b.{quote(name)}' for name in names) or 'false'
        counts = {'removed': con.execute(f'select count(*) from ({removed})').fetchone()[0],
                  'added': con.execute(f'select count(*) from ({added})').fetchone()[0],
                  'changed': con.execute(f'select count(*) from a join b using (__row) where {distinct}').fetchone()[0]}
        if not any(counts.values()):
            return {'same': True, 'identical_bytes': False, 'rows': totals}
        result = {'same': False, 'rows': totals, **counts, 'examples': {}}
        order = ', '.join(quote(name) for name in names) or '1'
        for label, query in (('removed', removed), ('added', added)):
            if counts[label]:
                rows = con.execute(f'select * from ({query}) order by {order} limit {examples}').fetchall()
                result['examples'][label] = [dict(zip(names, row)) for row in rows]
        if counts['changed']:
            left = ', '.join(f'a.{quote(name)}' for name in names)
            right = ', '.join(f'b.{quote(name)}' for name in names)
            rows = con.execute(f'select a.__row, {left}, {right} from a join b using (__row) '
                               f'where {distinct} order by a.__row limit {examples}').fetchall()
            result['examples']['changed'] = [
                {'row': row[0], 'columns': {name: {'saved': row[1 + index], 'candidate': row[1 + len(names) + index]}
                                            for index, name in enumerate(names)
                                            if differs(row[1 + index], row[1 + len(names) + index])}}
                for row in rows]
        return result


def receipt_shape(table: dict) -> dict:
    """The converter-written part of a table receipt; fingerprint and Parquet bytes are not content."""
    shape = deepcopy(table)
    shape.pop('input_fingerprint', None)
    for reference in manifest.table_references(shape).values():
        reference['object'].pop('sha256', None)
        reference['object'].pop('bytes', None)
    return shape


def flatten(value: dict, prefix: str = '') -> dict:
    flat = {}
    for key, item in value.items():
        if isinstance(item, dict):
            flat.update(flatten(item, f'{prefix}{key}.'))
        else:
            flat[f'{prefix}{key}'] = item
    return flat


def receipt_differences(saved: dict, candidate: dict) -> list[dict]:
    old, new = flatten(receipt_shape(saved)), flatten(receipt_shape(candidate))
    found = []
    for key in sorted(set(old) | set(new)):
        if old.get(key) == new.get(key):
            continue
        item = {'field': key}
        for label, value in (('saved', old.get(key)), ('candidate', new.get(key))):
            if value is None or isinstance(value, (str, int, float, bool)):
                item[label] = value
            else:
                item[label + '_items'] = len(value)
        found.append(item)
    return found


def compare_table(saved: dict, candidate: dict, saved_paths: dict, candidate_paths: dict | Path) -> dict:
    """Receipt and content comparison of one table. ``paths`` are keyed by reference kind (None for CSV)."""
    kinds = set(manifest.table_references(saved))
    if kinds != set(manifest.table_references(candidate)):
        return {'status': DIFFERENT, 'diff': {'structure': {'saved': sorted(map(str, kinds)),
                                                            'candidate': sorted(map(str, manifest.table_references(candidate)))}}}
    diff = {}
    receipt = receipt_differences(saved, candidate)
    if receipt:
        diff['receipt'] = receipt
    content = {}
    for kind in kinds:
        new = candidate_paths[kind] if isinstance(candidate_paths, dict) else candidate_paths
        found = compare_parquet(saved_paths[kind], new)
        if not found['same']:
            content[kind or 'table'] = found
    if content:
        diff['content'] = content
    return {'status': DIFFERENT if diff else SAME, **({'diff': diff} if diff else {})}


def rewrite_fingerprints(path: Path, document: dict, current: dict[str, str], stale: list[str],
                         original_bytes: bytes) -> None:
    updated = deepcopy(document)
    for table in updated['tables']:
        if table['conversion_id'] in stale:
            table['input_fingerprint'] = current[table['conversion_id']]
    if path.read_bytes() != original_bytes:
        raise ValueError('Saved manifest changed during refresh')
    # Recomputed now: the converter code or its inputs must not have moved while we compared.
    manifest.require_current(updated)
    manifest.write(path, updated)
    manifest.require_current(manifest.read(path))


def slug(document: dict) -> str:
    target = document['target']
    return f'{target["jurisdiction"]}-{target["fiscal_year"]}-{manifest.document_slot(target)}-{document["direction"]}'


def refresh_manifest(path: Path, *, remote: bool, dry_run: bool, work: Path) -> dict:
    started = time.monotonic()
    original_bytes = path.read_bytes()
    document = manifest.read(path)
    name = slug(document)
    try:
        label = str(path.resolve().relative_to(PIPELINE))
    except ValueError:
        label = str(path)
    result = {'manifest': label, 'name': name}

    def finish(status: str, **extra) -> dict:
        result.update(status=status, elapsed_seconds=round(time.monotonic() - started, 1), **extra)
        return result

    if not document['tables']:
        return finish(NO_TABLES)
    current = manifest.fingerprints(document)
    stale = sorted({table['conversion_id'] for table in document['tables']
                    if table['input_fingerprint'] != current[table['conversion_id']]})
    if not stale:
        return finish(CURRENT)
    result['stale_conversions'] = stale
    try:
        saved_paths = {table['table_id']: {kind: storage.fetch(reference['object'], remote=remote)
                                           for kind, reference in manifest.table_references(table).items()}
                       for table in document['tables']}
        originals = run.original_files(document, remote=remote, conversion_ids=set(stale))
        # The conversion below reads pinned OCR observations from the cache only.
        for conversion in document['conversions']:
            if conversion['id'] in stale:
                for item in conversion.get('ocr_inputs', []):
                    storage.fetch_ocr(document, item, remote=remote)
    except Exception as error:
        return finish(ERROR, stage='restore', reason=f'{type(error).__name__}: {error}')
    output = work / name
    shutil.rmtree(output, ignore_errors=True)
    try:
        converted = run.convert(path, originals, output, remote=False, conversion_ids=stale)
        result['units'] = converted.get('units', {}).get('counts', {})
        candidate = json.loads((output / 'manifest.json').read_text())
    except Exception as error:
        # The converter or a save gate (tree check, digit coverage) refuses the table today.
        return finish(BLOCKED, stage='convert', reason=f'{type(error).__name__}: {error}', candidate=str(output))
    by_id = {table['table_id']: table for table in candidate['tables']}
    locate = run.candidate_locator(output)
    tables = []
    for table in document['tables']:
        if table['conversion_id'] not in stale:
            continue
        entry = {'table_id': table['table_id'], 'conversion_id': table['conversion_id']}
        tables.append(entry)
        try:
            new = by_id[table['table_id']]
            located = locate(new)
            storage.prepare_save(candidate, new, located, scope=unit_checks.find_scope(
                output, table['table_id'], node_tables.COVERAGE_SIDECAR_SUFFIX))
            entry['units'] = converted.get('units', {}).get('tables', {}).get(table['table_id'])
        except Exception as error:
            entry.update(status=BLOCKED, reason=f'{type(error).__name__}: {error}')
            continue
        entry.update(compare_table(table, new, saved_paths[table['table_id']], located))
    counts = {status: sum(entry['status'] == status for entry in tables) for status in (SAME, DIFFERENT, BLOCKED)}
    result['tables'] = tables
    result['counts'] = counts
    if counts[BLOCKED]:
        return finish(BLOCKED, stage='gate', candidate=str(output))
    if counts[DIFFERENT]:
        return finish(DIFFERENT, candidate=str(output))
    if not dry_run:
        try:
            rewrite_fingerprints(path, document, current, stale, original_bytes)
        except Exception as error:
            return finish(ERROR, stage='rewrite', reason=f'{type(error).__name__}: {error}')
    shutil.rmtree(output, ignore_errors=True)
    return finish(WOULD_REFRESH if dry_run else REFRESHED)


def refresh_all(paths: list[Path], *, remote: bool, dry_run: bool, output: Path) -> dict:
    started = time.monotonic()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / 'candidates'
    manifests = []
    for path in paths:
        try:
            item = refresh_manifest(path, remote=remote, dry_run=dry_run, work=work)
        except Exception as error:
            item = {'manifest': str(path), 'status': ERROR, 'stage': 'read', 'reason': f'{type(error).__name__}: {error}'}
        print(f'{item["manifest"]}: {item["status"]}', file=sys.stderr, flush=True)
        manifests.append(item)
    statuses: dict[str, int] = {}
    tables = {SAME: 0, DIFFERENT: 0, BLOCKED: 0}
    for item in manifests:
        statuses[item['status']] = statuses.get(item['status'], 0) + 1
        for status, count in item.get('counts', {}).items():
            tables[status] += count
    ok = not {DIFFERENT, BLOCKED, ERROR} & set(statuses)
    report = {'ok': ok, 'dry_run': dry_run, 'elapsed_seconds': round(time.monotonic() - started, 1),
              'manifests': manifests}
    # Report first, atomically, so a reader never sees a half-written file.
    with tempfile.NamedTemporaryFile('w', dir=output.parent, delete=False, suffix='.tmp') as stream:
        temporary = Path(stream.name)
        json.dump(report, stream, ensure_ascii=False, indent=1, default=str)
        stream.write('\n')
    os.replace(temporary, output)
    summary = {'ok': ok, 'dry_run': dry_run, 'manifests': statuses, 'tables': tables,
               'elapsed_seconds': report['elapsed_seconds'], 'report': str(output),
               'attention': [{key: item[key] for key in ('manifest', 'status', 'stage', 'reason', 'counts', 'candidate')
                              if key in item} for item in manifests if item['status'] in {DIFFERENT, BLOCKED, ERROR}]}
    return {'ok': ok, 'summary': summary, 'report': report}
