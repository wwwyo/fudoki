"""Schema-validated CSV/PDF conversion, private storage and bounded summaries."""
from __future__ import annotations

import argparse
import gzip
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import duckdb

from ingestion.fiscal import manifest, unit_checks
from ingestion.fiscal.storage import fetch, fetch_ocr, save, save_ocr, cleanup, verify, write_ocr
from ingestion.paths import BUILD
from ingestion.lib import coverage_checks, digit_recheck, node_tables, source_inconsistencies, tree_checks

MATCH, MISMATCH, NOT_APPLICABLE = '一致', '不一致', '対象外'


def inspect_table(path: Path, metadata: dict | None = None) -> int:
    with duckdb.connect() as con:
        count = con.execute('select count(*) from read_parquet(?, hive_partitioning=false)', [str(path)]).fetchone()[0]
        columns = con.execute('describe select * from read_parquet(?, hive_partitioning=false)', [str(path)]).fetchall()
    if len({row[0] for row in columns}) != len(columns):
        raise ValueError('Duplicate Parquet column')
    if metadata is not None:
        manifest.validate_metadata(metadata, [row[0] for row in columns])
    return count


def original_files(document: dict, *, remote: bool = False, conversion_ids: set[str] | None = None) -> dict[str, str]:
    """Original SHA-256 to its verified local path, restoring missing objects from R2 when ``remote``."""
    selection = manifest.selection_for(document)
    files = {}
    for conversion in document['conversions']:
        if conversion_ids is not None and conversion['id'] not in conversion_ids:
            continue
        for item in manifest.resolved_inputs(document, conversion, selection):
            if item['sha256'] not in files:
                files[item['sha256']] = str(fetch(item, remote=remote))
    return files


def originals(path: Path, output: Path, *, remote: bool = False) -> dict:
    files = original_files(manifest.read(path), remote=remote)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(files, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return {'originals': len(files), 'inputs': str(output)}


def pinned_observation(document: dict, item: dict) -> dict | None:
    """The cached pinned observation, whose VLM answers a re-acquisition reuses."""
    try:
        return json.loads(gzip.decompress(fetch_ocr(document, item).read_bytes()))
    except (ValueError, FileNotFoundError):
        return None


def acquire_ocr(path: Path, local_files: dict[str, str], *, verify_only: bool = False,
                ids: list[str] | None = None) -> dict:
    """Read declared OCR requests outside the converters and pin their observation SHA.

    ``verify_only`` re-reads and compares with the pinned SHA without writing anything.
    Pinning a different SHA makes the conversion's saved tables stale on purpose.
    """
    from ingestion.lib.scan_ocr import acquire
    document = manifest.read(path)
    declared = manifest.ocr_inputs(document)
    chosen = set(ids) if ids is not None else {item['id'] for _, item in declared}
    if not chosen or not chosen <= {item['id'] for _, item in declared}:
        raise ValueError('Unknown or empty OCR input selection')
    result = deepcopy(document)
    report = {}
    for conversion, item in manifest.ocr_inputs(result):
        if item['id'] not in chosen:
            continue
        source = Path(local_files[item['origin_sha256']])
        if manifest.sha_file(source) != item['origin_sha256']:
            raise ValueError('Supplied original differs from the selected byte identity')
        data, run = acquire(source, item['request'], pinned_observation(result, item))
        sha = run['observation_sha256']
        status = 'unchanged' if item.get('sha256') == sha else ('new' if 'sha256' not in item else 'changed')
        report[item['id']] = {'status': status, 'sha256': sha, 'bytes': len(data)}
        if verify_only:
            continue
        write_ocr(result, item, data, run)
        item['sha256'], item['bytes'] = sha, len(data)
    if not verify_only and result != document:
        manifest.write(path, result)
    return {'verified' if verify_only else 'pinned': report}


def table_receipt(document: dict, conversion: dict, table_id: str, path: Path, *, input_fingerprint: str | None = None,
                  metadata: dict | None = None) -> dict:
    fingerprint = input_fingerprint or manifest.fingerprint(document, conversion)
    sha = manifest.sha_file(path)
    previous = next((table for table in document['tables'] if table['table_id'] == table_id), None)
    if metadata is None and previous is not None and 'metadata' in previous:
        if previous['input_fingerprint'] != fingerprint or previous['object']['sha256'] != sha:
            raise ValueError('Changed annotated table requires metadata from its converter')
        metadata = previous['metadata']
    count = inspect_table(path, metadata)
    if count == 0:
        raise ValueError('Empty output is not supported')
    result = {'table_id': table_id, 'conversion_id': conversion['id'],
            'input_fingerprint': fingerprint,
            'object': {'key': manifest.object_key(document, table_id),
                       'sha256': sha, 'bytes': path.stat().st_size},
            'row_count': count}
    if metadata is not None:
        result['metadata'] = deepcopy(metadata)
    return result



def pdf_account(document: dict, conversion: dict, nodes: list[dict]) -> str:
    inputs = manifest.resolved_inputs(document, conversion)
    accounts = {scope['account'] for item in inputs for scope in item['scope']}
    account = conversion['options'].get('account')
    if account is None and len(accounts) == 1:
        account = next(iter(accounts))
    if account is None:
        pages = {node['physical_page'] for node in nodes if node['physical_page'] is not None}
        matches = {scope['account'] for item in inputs for scope in item['scope']
                   if pages and pages <= {p for first, last in scope.get('pages', [])
                                          for p in range(first, last + 1)}}
        if len(matches) == 1:
            account = next(iter(matches))
    if account not in accounts:
        raise ValueError('PDF table needs one account from selected input scopes')
    return account


def unit_gate(document: dict, conversion: dict, table_id: str, tables: node_tables.NodeTables,
              scope: dict | None = None) -> dict:
    """The unit check of one node table (款 sum against the printed 歳出合計, digits of the unit); stops on failure.

    ``scope`` is the converter's digit-coverage scope (its printed words), which is where the printed total
    comes from; a table without one (a scan PDF) is checked on the digits of the unit only.
    """
    result = unit_checks.check_table(
        tables.nodes, tables.amounts, document_kind=document['target']['document_kind'],
        account=pdf_account(document, conversion, tables.nodes),
        partial=bool(conversion['options'].get('partial')), scope=scope,
        statement_kind=conversion.get('statement_kind', 'ordinary'), direction=document['direction'])
    if result['stopped']:
        raise ValueError(f'Unit check failed: {table_id}: {unit_checks.describe(result)}')
    return result


def complete_subject_rows(rows: list[dict], siblings: list[list[dict]]) -> list[dict]:
    """Include printed subjects with no explanation using the same account's detail table.

    No branch or amount is invented: copy only already-extracted 款・項・目 cells.
    The declared grains deduplicate repeated ancestor cells during migration.
    """
    columns = list(rows[0]) if rows else []
    additions = [{c: row.get(c) if c.startswith(('款_', '項_', '目_')) else None for c in columns}
                 for sibling in siblings for row in sibling]
    return [*rows, *additions]


def node_receipt(document: dict, conversion: dict, table_id: str, tables: node_tables.NodeTables,
                 output: Path, *, input_fingerprint: str | None = None, notes: list[str] | None = None,
                 migrated: bool = True) -> tuple[dict, dict]:
    account = pdf_account(document, conversion, tables.nodes)
    paths = node_tables.write_tables(output, table_id, tables, document['target']['document_kind'],
                                     source_inconsistencies.declared_for(document, table_id))
    # A direct converter never counted anything while migrating a wide table: no migration note.
    receipt = {'table_id': table_id, 'conversion_id': conversion['id'],
               'input_fingerprint': input_fingerprint or manifest.fingerprint(document, conversion),
               'account': account, **({'division': conversion['options']['division']}
                                      if conversion['options'].get('division') else {}),
               'notes': [*(notes or []), *([node_tables.MIGRATION_NOTE] if migrated else [])],
               'unread_amount_count': tables.unread_amount_count,
               'unresolved_parent_count': tables.unresolved_parent_count}
    for kind, path in paths.items():
        receipt[kind] = {'object': {'key': manifest.object_key(document, table_id, kind),
                                   'sha256': manifest.sha_file(path), 'bytes': path.stat().st_size},
                         'row_count': inspect_table(path)}
    return receipt, paths

def unchanged_legacy_receipt(document: dict, conversion: dict, table_id: str, file: Path,
                             fingerprint: str, *, remote: bool) -> dict:
    """Retain a failed migration only when its wide bytes match the saved object."""
    previous = next((t for t in document['tables'] if t['table_id'] == table_id), None)
    if previous is None or 'nodes' in previous or previous['conversion_id'] != conversion['id']:
        raise ValueError(f'Failed node migration has no saved legacy table: {table_id}')
    verify(file, previous['object'])
    verify(fetch(previous['object'], remote=remote), previous['object'])
    receipt = deepcopy(previous)
    receipt['input_fingerprint'] = fingerprint
    return receipt

def recheck_store_path(document: dict) -> Path:
    """Jev answers live beside the manifest. The suffix keeps manifest.paths() (`*.json`) from reading them."""
    path = manifest.manifest_path(document['target'], document['direction'])
    return path.with_name(path.stem + digit_recheck.STORE_SUFFIX)


def coverage_peers(document: dict, converted: dict) -> dict:
    """Match all adopted tables from the same original, across conversions.

    Every PDF table currently comes from one original. Physical page numbers
    are meaningful only within that original, never across different PDFs.
    """
    groups, origins = {}, {}
    for conversion in document['conversions']:
        identifiers = [item['table_id'] for item in conversion['expected_tables']
                       if item['table_id'] in converted]
        if not identifiers:
            continue
        inputs = conversion['inputs']
        if len(inputs) != 1:
            raise ValueError('Coverage requires an unambiguous original for each table')
        origin = inputs[0]['sha256']
        for ident in identifiers:
            origins[ident] = origin
            groups.setdefault(origin, []).append(converted[ident])
    pooled = {origin: node_tables.combine_coverage_tables(items) for origin, items in groups.items()}
    return {ident: pooled[origin] for ident, origin in origins.items()}


def convert(path: Path, local_files: dict[str, str], output: Path, *, remote: bool = False,
            conversion_ids: list[str] | None = None, extend_plan: Path | None = None) -> dict:
    document = manifest.read(path)
    original_bytes = None
    if extend_plan is not None:
        original_bytes = path.read_bytes()
        if json.loads(original_bytes) != document:
            raise ValueError('Saved manifest changed while preparing extension')
        plan = manifest.validate(json.loads(extend_plan.read_text()), path=path)
        old = document['conversions']
        if (plan['target'] != document['target'] or plan['direction'] != document['direction']
                or plan['tables'] or len(plan['conversions']) != len(old) + 1
                or plan['conversions'][:-1] != old):
            raise ValueError('Extension must append one conversion to the same target/direction with unchanged definitions and tables=[]')
        added = plan['conversions'][-1]
        if len(added['expected_tables']) != 1:
            raise ValueError('Extension requires exactly one new expected table')
        if conversion_ids is not None and conversion_ids != [added['id']]:
            raise ValueError('Extension conversion selection must be the one new ID')
        manifest.require_current(document)
        retained_tables = deepcopy(document['tables'])
        document = deepcopy(plan)
        document['tables'] = retained_tables
        conversion_ids = [added['id']]
    selection = manifest.selection_for(document)
    all_ids = {conversion['id'] for conversion in document['conversions']}
    chosen = set(conversion_ids) if conversion_ids is not None else all_ids
    if not chosen or not chosen <= all_ids:
        raise ValueError('Unknown or empty conversion selection')
    before = manifest.fingerprints(document)
    output.mkdir(parents=True, exist_ok=False)
    outputs = {}
    tables = []
    pending_pdf = []
    pending_direct = []
    coverage_failures = []
    unit_failures = []
    unit_results = {}
    scopes = {}
    adopted = {}
    checked_pdf = []
    direct = {}
    direct_notes = {}
    for conversion in document['conversions']:
        if conversion['id'] not in chosen:
            retained = [table for table in document['tables'] if table['conversion_id'] == conversion['id']]
            if {table['table_id'] for table in retained} != {item['table_id'] for item in conversion['expected_tables']}:
                raise ValueError('Partial conversion cannot omit unsaved expected tables')
            for table in retained:
                if table['input_fingerprint'] != before[conversion['id']]:
                    raise ValueError('An untouched table is stale; include its conversion')
                for reference in manifest.table_references(table).values():
                    stored = fetch(reference['object'], remote=remote)
                    if extend_plan is not None:
                        verify(stored, reference['object'])
                    count = inspect_table(stored, table.get('metadata'))
                    if extend_plan is not None and count != reference['row_count']:
                        raise ValueError('Retained table row count differs from its receipt')
            for table in retained:
                if 'nodes' in table:
                    adopted[table['table_id']] = node_tables.NodeTables(
                        node_tables.read_rows(fetch(table['nodes']['object'], remote=remote)),
                        node_tables.read_rows(fetch(table['amounts']['object'], remote=remote)))
            tables.extend(retained)
            continue
        inputs = manifest.resolved_inputs(document, conversion, selection)
        for item in inputs:
            source = Path(local_files[item['sha256']])
            if manifest.sha_file(source) != item['sha256']:
                raise ValueError('Supplied original differs from the selected byte identity')
            item['path'] = source
            item['target'] = document['target']
            item['direction'] = document['direction']
            item['ocr'] = [{'id': ocr['id'], 'request': ocr['request'], 'sha256': ocr.get('sha256'),
                            'path': fetch_ocr(document, ocr, remote=remote)}
                           for ocr in conversion.get('ocr_inputs', []) if ocr['origin_sha256'] == item['sha256']]
        code = manifest.code_path(conversion['converter'])
        spec = importlib.util.spec_from_file_location('ingestion_converter_' + conversion['id'], code)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        destination = output
        if {item['format'] for item in inputs} == {'pdf'}:
            # Several account conversions may use the same observation filenames.
            destination = output / conversion['id']
            destination.mkdir()
        generated = module.convert(inputs, destination, conversion['options'])
        expected = {item['table_id'] for item in conversion['expected_tables']}
        if not isinstance(generated, dict) or not expected <= set(generated):
            raise ValueError('Converter did not produce all its declared tables')
        # expected_tables is the registry's allowlist; auxiliary outputs are not adopted.
        generated = {ident: generated[ident] for ident in generated if ident in expected}
        prepared = {}
        # Not `direct`: that one collects the generic converter's tables across conversions.
        descriptors = {ident: value for ident, value in generated.items()
                       if isinstance(value, dict) and 'node_tables' in value}
        for ident, value in descriptors.items():
            # New converters hand over the printed tree itself; write_tables runs the tree check.
            if set(value) - {'node_tables', 'notes'} or not isinstance(value['node_tables'], node_tables.NodeTables):
                raise ValueError('Node converter descriptor requires node_tables and optional notes only')
            unit_results[ident] = unit_gate(document, conversion, ident, value['node_tables'])
            receipt, pair = node_receipt(document, conversion, ident, value['node_tables'], destination,
                                         input_fingerprint=before[conversion['id']],
                                         notes=list(value.get('notes', [])), migrated=False)
            outputs[ident] = pair
            tables.append(receipt)
        generated = {ident: value for ident, value in generated.items() if ident not in descriptors}
        for ident, file in generated.items():
            metadata = None
            if isinstance(file, dict) and {'nodes', 'amounts'} <= set(file) <= {'nodes', 'amounts', 'notes'}:
                # A converter that builds node/amount tables itself: no wide table to migrate. The scope
                # sidecar is named after the table (`<table_id>.coverage.json`) in the same directory.
                pair = {kind: Path(file[kind]) for kind in ('nodes', 'amounts')}
                direct_notes[ident] = [str(note) for note in file.get('notes', [])]
                for item in pair.values():
                    if not item.resolve().is_relative_to(output.resolve()) or item.is_symlink():
                        raise ValueError('Converter output is outside the candidate directory')
                direct[ident] = (pair, pair['nodes'].with_name(f'{ident}.parquet'))
                prepared[ident] = (direct[ident][1], None)
                continue
            if isinstance(file, dict):
                if 'path' not in file or set(file).difference({'path', 'metadata'}):
                    raise ValueError('Converter table descriptor requires path and optional metadata only')
                metadata = file.get('metadata')
                if 'metadata' in file and metadata is None:
                    raise ValueError('Converter metadata must be an object')
                file = file['path']
            file = Path(file)
            if not file.resolve().is_relative_to(output.resolve()) or file.is_symlink():
                raise ValueError('Converter output is outside the candidate directory')
            prepared[ident] = (file, metadata)
        if {item['format'] for item in inputs} == {'pdf'}:
            for ident, (file, metadata) in prepared.items():
                if ident in direct:
                    pair = direct[ident][0]
                    inspect_table(pair['nodes']), inspect_table(pair['amounts'])
                    built = node_tables.NodeTables(node_tables.read_rows(pair['nodes']),
                                                   node_tables.read_rows(pair['amounts']))
                    pending_direct.append((conversion, ident, built, file))
                    continue
                inspect_table(file, metadata)
                rows = node_tables.read_rows(file)
                # Conversions may separate details and notes for the same account.
                try:
                    initial = node_tables.migrate_rows(rows, metadata or {})
                except ValueError:
                    tables.append(unchanged_legacy_receipt(document, conversion, ident, file,
                                  before[conversion['id']], remote=remote))
                    outputs[ident] = file
                    continue
                account = pdf_account(document, conversion, initial.nodes)
                pending_pdf.append((conversion, ident, rows, metadata, account, file))
        else:
            for ident, (file, metadata) in prepared.items():
                outputs[ident] = file
                tables.append(table_receipt(document, conversion, ident, file,
                                            input_fingerprint=before[conversion['id']], metadata=metadata))
    completed_by_id = {}
    for conversion, ident, rows, metadata, account, file in pending_pdf:
        siblings = [other_rows for _, other_ident, other_rows, _, other_account, _ in pending_pdf
                    if other_ident != ident and other_account == account]
        rows = complete_subject_rows(rows, siblings)
        completed_by_id[ident] = rows
        sidecar = node_tables.coverage_sidecar(file)
        if sidecar.exists():
            scope = json.loads(sidecar.read_text())
            scope['excluded_regions'] = [*scope.get('excluded_regions', ()),
                                         *node_tables.quantity_regions(rows, metadata or {})]
            sidecar.write_text(json.dumps(scope, ensure_ascii=False) + '\n')
        try:
            migrated = node_tables.migrate_rows(rows, metadata or {})
        except ValueError:
            migrated = None
        checked = tree_checks.check_tree(migrated.nodes, migrated.amounts, document['target']['document_kind']) if migrated else {'passed': False}
        if (migrated is None or not migrated.nodes or not migrated.amounts or migrated.issues or migrated.unread_amount_count
                or migrated.unresolved_parent_count or not checked['passed']):
            tables.append(unchanged_legacy_receipt(document, conversion, ident, file,
                          before[conversion['id']], remote=remote))
            outputs[ident] = file
            continue
        adopted[ident] = migrated
        checked_pdf.append((conversion, ident, migrated, metadata, file))
    for conversion, ident, built, file in pending_direct:
        # No saved legacy table to fall back to: a table that fails its tree check is a failure.
        checked = tree_checks.check_tree(built.nodes, built.amounts, document['target']['document_kind'],
                                         source_inconsistencies.declared_for(document, ident))
        if not built.nodes or not built.amounts or not checked['passed']:
            raise ValueError(f'Table failed the tree check: {ident}: {checked["counts"]}; {checked["issues"][:5]}')
        completed_by_id[ident] = []
        adopted[ident] = built
        checked_pdf.append((conversion, ident, built, None, file))
    peers = coverage_peers(document, adopted)
    raw_by_id = completed_by_id
    for _, ident, migrated, _, file in checked_pdf:
        adopted[ident] = node_tables.with_annotations(file, migrated, raw_rows=raw_by_id[ident], adopted=peers[ident])
    peers = coverage_peers(document, adopted)
    store = recheck_store_path(document)
    recheck = digit_recheck.Recheck.from_store(store)
    jev_answers = {}

    def write_answers():
        # Answers are a judgment kept in Git, so they follow every run,
        # candidate or saved, failed or passing. Re-run tables keep only the
        # answers they used.
        if jev_answers:
            rows = digit_recheck.read_store(store) if store.is_file() else []
            merged = digit_recheck.merged_rows(rows, jev_answers)
            if merged or store.is_file():
                digit_recheck.write_store(store, merged)
    for conversion, ident, migrated, metadata, file in checked_pdf:
        migrated = adopted[ident]
        inputs = manifest.resolved_inputs(document, conversion, selection)
        text_only = all(item['format'] == 'pdf' and item.get('pdf_type') == 'text' for item in inputs)
        try:
            node_tables.check_table_coverage(file, peers[ident], require=text_only,
                                             control_tables=[adopted[ident]],
                                             recheck=recheck if text_only else None)
            jev_answers[ident] = recheck.take_used()
        except ValueError as error:
            coverage_failures.append(f'{ident}: {error}')
            # Asked answers survive a failed run, so fixing a rule never asks twice.
            if used := recheck.take_used():
                jev_answers[ident] = used
            continue
        except BaseException:
            # An API failure aborts the run; the answers already paid for stay.
            if used := recheck.take_used():
                jev_answers[ident] = used
            write_answers()
            raise
        scope = unit_checks.read_scope(node_tables.coverage_sidecar(file))
        try:
            unit_results[ident] = unit_gate(document, conversion, ident, migrated, scope)
        except ValueError as error:
            unit_failures.append(str(error))
            continue
        scopes[ident] = scope
        receipt, pair = node_receipt(document, conversion, ident, migrated, output,
                                     input_fingerprint=before[conversion['id']],
                                     notes=direct_notes.get(ident) if ident in direct
                                     else [n['text'] for n in (metadata or {}).get('notes', [])],
                                     migrated=ident not in direct)
        outputs[ident] = pair
        tables.append(receipt)
    write_answers()
    if coverage_failures:
        raise ValueError('Digit coverage failed:\n' + '\n'.join(coverage_failures)
                         + '\nJev recheck: ' + json.dumps(recheck.summary(), ensure_ascii=False))
    if unit_failures:
        raise ValueError('\n'.join(unit_failures))
    result = deepcopy(document)
    result['tables'] = tables
    manifest.validate(result)
    used_originals = {item['sha256'] for conversion in document['conversions']
                      if conversion['id'] in chosen for item in conversion['inputs']}
    for sha in sorted(used_originals):
        if manifest.sha_file(Path(local_files[sha])) != sha:
            raise ValueError('Supplied original changed during conversion')
    if before != manifest.fingerprints(result):
        raise ValueError('Input conditions changed during conversion')
    candidate = output / 'manifest.json'
    # Candidate is not a saved manifest; it stays outside the Git registry.
    candidate.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    if remote:
        if original_bytes is not None and path.read_bytes() != original_bytes:
            raise ValueError('Saved manifest changed before extension upload')
        # Observations go first so a saved table never points at a missing OCR input.
        for conversion, item in manifest.ocr_inputs(result):
            if conversion['id'] in chosen:
                save_ocr(result, item)
        for table in tables:
            if table['conversion_id'] not in chosen:
                continue
            save(result, table, outputs[table['table_id']], remote=True, scope=scopes.get(table['table_id']))
        manifest.require_current(result)
        if original_bytes is not None and path.read_bytes() != original_bytes:
            raise ValueError('Saved manifest changed before extension registration')
        manifest.write(path, result)
        # Deletion is always a separate operation, including legacy-only documents.
    return {'status': 'saved' if remote else 'candidate', 'tables': len(tables), 'jev': recheck.summary(),
            'units': {'tables': {ident: item['status'] for ident, item in sorted(unit_results.items())},
                      'counts': unit_checks.summarize(unit_results)},
            'rows': sum(r['row_count'] for t in tables for r in manifest.table_references(t).values()), 'candidate': str(candidate)}


def verify_sums(document: dict, locate, directory: Path | None = None) -> list[dict]:
    """Tree and unit checks of every PDF table; ``locate(table)`` gives its verified Parquet.

    The unit check compares the 款 sum with the printed 歳出合計 when the candidate directory holds the
    table's coverage scope (where the printed words are); a saved table keeps none, so only the digits
    of the unit are checked there.
    """
    selection = manifest.selection_for(document)
    conversions = {conversion['id']: conversion for conversion in document['conversions']}
    formats = {conversion['id']: {item['format'] for item in manifest.resolved_inputs(document, conversion, selection)}
               for conversion in document['conversions']}
    results = []
    for table in document['tables']:
        if formats[table['conversion_id']] == {'csv'}:
            results.append({'table_id': table['table_id'], 'status': NOT_APPLICABLE,
                            'reason': 'CSVは変換時の全セル保持検査で確認する',
                            'counts': {}, 'checks': [], 'results': []})
            continue
        pair = locate(table)
        nodes, amounts = node_tables.read_rows(pair['nodes']), node_tables.read_rows(pair['amounts'])
        checked = tree_checks.check_tree(nodes, amounts, document['target']['document_kind'],
                                         source_inconsistencies.declared_for(document, table['table_id']))
        passed = (checked['passed'] and not table['unread_amount_count'] and not table['unresolved_parent_count'])
        unit = unit_checks.check_table(
            nodes, amounts, document_kind=document['target']['document_kind'], account=table.get('account'),
            partial=bool(conversions[table['conversion_id']]['options'].get('partial')),
            statement_kind=conversions[table['conversion_id']].get('statement_kind', 'ordinary'),
            direction=document['direction'],
            scope=unit_checks.find_scope(directory, table['table_id'], node_tables.COVERAGE_SIDECAR_SUFFIX))
        item = {'table_id': table['table_id'], 'status': MATCH if passed and not unit['stopped'] else MISMATCH,
                'counts': checked['counts'], 'issues': checked['issues'], 'checks': [],
                'results': checked['results'],
                'units': {key: unit.get(key) for key in ('status', 'kan_sum', 'printed_total', 'sum_matches', 'digits_ok',
                                                          'printed_totals', 'partial', 'subject_check')}}
        if unit['stopped']:
            item['reason'] = f'単位の確かめで止まった: {unit_checks.describe(unit)}'
        results.append(item)
    return results


def candidate_locator(directory: Path):
    """Find candidate Parquet files by the SHA-256 recorded in the candidate manifest."""
    by_sha = {manifest.sha_file(path): path for path in directory.rglob('*.parquet') if not path.is_symlink()}

    def locate(table: dict):
        found = {}
        for kind, reference in manifest.table_references(table).items():
            if reference['object']['sha256'] not in by_sha:
                raise FileNotFoundError(f'Candidate Parquet missing: {table["table_id"]}')
            found[kind] = by_sha[reference['object']['sha256']]
        return found if 'nodes' in table else found[None]
    return locate


def verify_coverage(document: dict, locate, directory, recheck=None) -> dict:
    """Digit coverage of candidate tables carrying a converter scope sidecar.

    Saved tables keep no word scope (local-only sidecars are never uploaded),
    so coverage is enforced at convert time and re-run here on candidates.
    Uncovered tables are returned as MISMATCH rather than raised; the
    candidate verify command exits with code 1 for those mismatches.
    """
    outcome = {}
    adopted = {}
    for table in document['tables']:
        if 'nodes' in table and directory is not None:
            try:
                pair = locate(table)
                adopted[table['table_id']] = node_tables.NodeTables(
                    node_tables.read_rows(pair['nodes']), node_tables.read_rows(pair['amounts']))
            except Exception as error:
                outcome[table['table_id']] = {'status': MISMATCH, 'reason': str(error) or type(error).__name__}
    peers = coverage_peers(document, adopted)
    # Read-only: answers come from the manifest's store only (convert asks and
    # writes them). A missing answer stops the table.
    if recheck is None:
        recheck = digit_recheck.Recheck.from_store(recheck_store_path(document), ask_missing=False)
    conversions = {c['id']: c for c in document['conversions']}
    for table in document['tables']:
        if 'nodes' not in table or directory is None or table['table_id'] in outcome:
            continue
        sidecars = sorted(directory.rglob(table['table_id'] + node_tables.COVERAGE_SIDECAR_SUFFIX))
        if not sidecars:
            outcome[table['table_id']] = {'status': NOT_APPLICABLE, 'reason': '網羅検査の対象範囲がない'}
            continue
        try:
            scope = json.loads(sidecars[0].read_text())
            inputs = manifest.resolved_inputs(document, conversions[table['conversion_id']])
            text_only = all(item['format'] == 'pdf' and item.get('pdf_type') == 'text' for item in inputs)
            result = coverage_checks.check_digit_coverage(
                scope['words'], peers[table['table_id']], control_tables=[adopted[table['table_id']]],
                exclusions=scope.get('excluded_regions', ()),
                amount_columns=scope.get('amount_columns', ()), recheck=recheck if text_only else None)
            jev = {k: v for k, v in (result['jev'] or {}).items() if k != 'answers'}
            outcome[table['table_id']] = {'status': MATCH if result['passed'] else MISMATCH,
                                          'counts': result['counts'],
                                          'uncovered': result['uncovered'][:10],
                                          'reported': result['reported'][:10],
                                          'bands_from': result['bands_from'],
                                          'exclusions': result['exclusions'],
                                          'jev': jev,
                                          'elapsed': result['elapsed']}
        except Exception as error:
            outcome[table['table_id']] = {'status': MISMATCH, 'reason': str(error) or type(error).__name__}
    return outcome


def verify_report(path: Path, document: dict, results: list[dict], output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'manifest': str(path), 'target': document['target'], 'direction': document['direction'],
                                  'tables': results}, ensure_ascii=False, indent=1, default=str) + '\n')
    return {'manifest': str(path), 'output': str(output),
            'tables': {item['table_id']: {'status': item['status'], **item['counts'],
                                          **({'units': item['units']['status']} if item.get('units') else {})}
                       for item in results}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('schema')
    origin = sub.add_parser('originals', help='Restore selected originals and write a local input-path map')
    origin.add_argument('--manifest', type=Path, required=True)
    origin.add_argument('--output', type=Path, required=True)
    origin.add_argument('--remote', action='store_true')
    check = sub.add_parser('check')
    check.add_argument('--manifest', type=Path)
    run = sub.add_parser('convert')
    run.add_argument('--manifest', type=Path, required=True)
    run.add_argument('--inputs', type=Path, required=True, help='JSON: original SHA-256 to local file path')
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--remote', action='store_true')
    run.add_argument('--conversion', action='append', help='Re-run these conversion IDs, preserving all untouched tables')
    run.add_argument('--extend-plan', type=Path,
                     help='JSON in the existing manifest schema: same target/direction, unchanged existing conversions plus one new conversion/table, tables=[]. Retains verified saved tables and converts/uploads only the new table; registers only after full success. Local mode writes the candidate only.')
    restore = sub.add_parser('restore')
    restore.add_argument('--manifest', type=Path, required=True)
    restore.add_argument('--remote', action='store_true')
    check_sums = sub.add_parser('verify', help='Hierarchy sum checks of saved or candidate PDF tables; details go to files')
    check_sums.add_argument('--manifest', type=Path, action='append', help='Saved manifest(s); default: all')
    check_sums.add_argument('--candidate', type=Path, help='Candidate directory from convert (uses its manifest.json)')
    check_sums.add_argument('--output', type=Path, help='Detail directory (default: .build/ingestion-verify)')
    check_sums.add_argument('--remote', action='store_true', help='Restore missing saved tables from R2')
    refresh = sub.add_parser('refresh', help='Re-convert stale tables, compare contents with the saved ones, and rewrite only the fingerprints of unchanged manifests')
    refresh.add_argument('--manifest', type=Path, action='append', help='Saved manifest(s); default: all')
    refresh.add_argument('--output', type=Path, help='Report file (default: .build/ingestion-refresh/report.json)')
    refresh.add_argument('--remote', action='store_true', help='Restore missing originals and saved tables from R2 (read only; nothing is uploaded)')
    refresh.add_argument('--dry-run', action='store_true', help='Compare only; do not rewrite any manifest')
    ocr = sub.add_parser('ocr', help='Read declared OCR requests and pin observation SHA (Vision; run outside the sandbox)')
    ocr.add_argument('--manifest', type=Path, required=True)
    ocr.add_argument('--inputs', type=Path, required=True, help='JSON: original SHA-256 to local file path')
    ocr.add_argument('--id', action='append', help='Only these OCR input IDs')
    ocr.add_argument('--verify', action='store_true', help='Re-read and compare with the pinned SHA; write nothing')
    clean = sub.add_parser('cleanup')
    clean.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'schema':
        print(manifest.SCHEMA.read_text())
    elif args.command == 'check':
        paths = [args.manifest] if args.manifest else manifest.paths()
        count = ready = tables = 0
        for path in paths:
            document = manifest.read(path)
            for conversion in document['conversions']:
                manifest.resolved_inputs(document, conversion)
            if document['tables']:
                manifest.require_current(document)
                ready += 1
            count += 1
            tables += len(document['tables'])
        print(json.dumps({'valid': True, 'manifests': count, 'ready': ready, 'saved_tables': tables}))
    elif args.command == 'ocr':
        print(json.dumps(acquire_ocr(args.manifest, json.loads(args.inputs.read_text()),
                                     verify_only=args.verify, ids=args.id), ensure_ascii=False))
    elif args.command == 'originals':
        print(json.dumps(originals(args.manifest, args.output, remote=args.remote)))
    elif args.command == 'convert':
        print(json.dumps(convert(args.manifest, json.loads(args.inputs.read_text()), args.output,
                                 remote=args.remote, conversion_ids=args.conversion, extend_plan=args.extend_plan)))
    elif args.command == 'verify':
        output = args.output or BUILD / 'ingestion-verify'
        if args.candidate is not None:
            if args.manifest:
                raise ValueError('Use either --candidate or --manifest')
            document = manifest.validate(json.loads((args.candidate / 'manifest.json').read_text()))
            runs = [(args.candidate / 'manifest.json', document, candidate_locator(args.candidate))]
        else:
            runs = []
            for path in args.manifest or manifest.paths():
                document = manifest.read(path)
                runs.append((path, document, lambda table: ({kind: fetch(ref['object'], remote=args.remote)
                    for kind, ref in manifest.table_references(table).items()} if 'nodes' in table
                    else fetch(table['object'], remote=args.remote))))
        summary = {}
        failed = False
        for path, document, locate in runs:
            target = document['target']
            name = f'{target["jurisdiction"]}-{target["fiscal_year"]}-{manifest.document_slot(target)}-{document["direction"]}'
            results = verify_sums(document, locate, args.candidate)
            recheck = digit_recheck.Recheck.from_store(recheck_store_path(document), ask_missing=False)
            coverage = verify_coverage(document, locate, args.candidate, recheck)
            for item in results:
                if item['table_id'] in coverage:
                    item['coverage'] = coverage[item['table_id']]
            report = verify_report(path, document, results, output / f'{name}.json')
            if recheck.stats['questions']:
                report['jev'] = recheck.summary()
            print(json.dumps(report, ensure_ascii=False))
            for item in results:
                summary[item['status']] = summary.get(item['status'], 0) + 1
                failed |= item['status'] == MISMATCH
                # Candidate coverage reruns stop here too; saved tables keep
                # no word scope, so their reports carry no coverage status.
                failed |= item.get('coverage', {}).get('status') == MISMATCH
        print(json.dumps({'manifests': len(runs), 'tables': summary}, ensure_ascii=False))
        raise SystemExit(1 if failed else 0)
    elif args.command == 'restore':
        document = manifest.read(args.manifest)
        manifest.require_current(document)
        for table in document['tables']:
            for reference in manifest.table_references(table).values():
                restored = fetch(reference['object'], remote=args.remote)
                if inspect_table(restored, table.get('metadata')) != reference['row_count']:
                    raise ValueError('Restored table row count differs from receipt')
        print(json.dumps({'restored': len(document['tables'])}))
    elif args.command == 'refresh':
        from ingestion.fiscal.refresh import refresh_all
        report = refresh_all(args.manifest or manifest.paths(), remote=args.remote, dry_run=args.dry_run,
                             output=args.output or BUILD / 'ingestion-refresh' / 'report.json')
        print(json.dumps(report['summary'], ensure_ascii=False))
        raise SystemExit(0 if report['ok'] else 1)
    else:
        print(json.dumps({'removed': cleanup(manifest.read(args.manifest))}))


if __name__ == '__main__':
    main()
