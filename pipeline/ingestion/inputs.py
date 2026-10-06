"""採用した入力の内容を固定し、検査してからローカルへ復元する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import re
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from ingestion.paths import CACHE, PIPELINE, REPO

LOCK = PIPELINE / 'ingestion/fiscal/sources.lock.json'
OBJECTS = CACHE / 'objects'
BUCKET = 'fudoki-inputs'


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '\\' in value or not value or not path.parts or value != str(path) or any(ord(c) < 32 for c in value):
        raise ValueError(f'Unsafe input path: {value}')
    return str(path)


def save_object(kind: str, body: bytes) -> dict:
    if kind not in ['origin', 'table']:
        raise ValueError('Only original documents and tables belong in R2 input storage')
    sha = digest(body)
    key = f'inputs/{kind}/sha256/{sha}'
    out = OBJECTS / key
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and digest(out.read_bytes()) != sha:
        raise ValueError(f'Corrupt cached object: {key}')
    out.write_bytes(body)
    return {'key': key, 'sha256': sha, 'bytes': len(body)}


def verify_object(ref: dict, body: bytes) -> None:
    if digest(body) != ref['sha256'] or len(body) != ref['bytes']:
        raise ValueError(f'Input hash or size mismatch: {ref.get("key", ref.get("path"))}')


# Source declarations are part of the input list; extraction results are regenerated.
SOURCE_FIELDS = frozenset("""source_key request_url final_url original_url source_url document_title resource_name
 dataset_title landing_page fiscal_year_basis resource_url_basis resource_url_declared url_basis
 fund_label fund_basis table_id original_source_table_id observation_role grain namespace account
 account_partition source_amount_unit source_amount_kind unit_multiplier document_label raw_form
 encoding csv_layout pages source_page_range configured_attachment_pages layout extractor
 approval_status approval_date approval_proof approval_evidence approval_url approval_sha256 approval
 recognition_status recognition_basis recognition_proof year_basis legal_correspondence_status
 statutory_correspondence_status project_setsu_linkage phases phase phase_semantics phase_note
 financial_phase amendment_number effective_at effective_at_basis effective_basis effective_date
 effective_date_basis council_resolution_date printed_submission_date submitted_date executive_disposition_date
 original_cover_approval_status original_identity_evidence visual_ledger_file frozen_native_page_refs
 redistribute redistribute_basis license_id attribution definition_files source_manifest_sha256
 source_spec_sha256 source_spec_bytes printed_total amount_kind nonadditive nonadditive_with
 nonadditive_reason independent_breakdown additive additive_scope additive_within_own_grain
 canonical_initial canonical_changes canonical_executed
 totals date_anomaly first_article_evidence
 source_grain source_position_method original_observation_identity original_raw_row_identity
 immutable_raster_descriptor explanation_dataset_id explanation_statutory_correspondence
 budget_columns_note baseline_status edition_status sign_note""".split())


def source_declaration(metadata: dict) -> dict:
    return {key: value for key, value in metadata.items() if key in SOURCE_FIELDS}


def source_metadata(lock_path: Path, entry: dict) -> dict:
    """Resolve an adopted declaration and inspect its immutable table, without sidecar files."""
    import duckdb
    source = dict(entry['source'])
    original = OBJECTS / safe_relative(entry['origin']['object']['key'])
    verify_object(entry['origin']['object'], original.read_bytes())
    table = OBJECTS / safe_relative(entry['table']['key'])
    verify_object(entry['table'], table.read_bytes())
    with duckdb.connect() as connection:
        schema = connection.execute('describe select * from read_parquet(?, hive_partitioning=false)', [str(table)]).fetchall()
        names = [column[0] for column in schema]
        aggregates = ['count(*)']
        reserve_column = ('setsu_name' if entry['path'].startswith('akishima-initial445/') and 'setsu_name' in names
                          else next((name for name in ('setsu_code', 'printed_setsu_code') if name in names), None))
        amount_column = next((name for name in ('amount_executed', 'executed', 'amount') if name in names), None)
        if entry['path'].startswith('akishima-settlement') and not source.get('canonical_executed'):
            reserve_column = None
            amount_column = None
        aggregates.append(f"count(*) filter (where {reserve_column} is null or cast({reserve_column} as varchar)='')" if reserve_column else '0')
        aggregates.append(f'count(*) filter (where {amount_column}=0)' if amount_column else '0')
        aggregates.append('sum(amount_change)' if 'amount_change' in names else 'NULL')
        count, reserve, zeros, delta = connection.execute(
            'select ' + ','.join(aggregates) + ' from read_parquet(?, hive_partitioning=false)', [str(table)]
        ).fetchone()
        source.update(rows=count, header=[n for n in names if n not in ('source_row', 'source_record')] if source.get('raw_form') == 'verbatim' else names,
                      raw_schema=[dict(name=c[0], type=c[1]) for c in schema], schema=[list(c) for c in schema],
                      reserve_rows=reserve, reserve_null_rows=reserve, printed_zero_rows=zeros,
                      extraction_evidence=dict(reserve_exception_rows=reserve))
        if 'amount_change' in names:
            source['delta_sum'] = delta
    source.update(jurisdiction_code=entry['jurisdiction'], fiscal_year=entry['fiscalYear'],
                  direction=entry['direction'], document_kind=entry['documentKind'],
                  origin_sha256=entry['originEdition'], origin_bytes=entry['origin']['object']['bytes'],
                  raw_table_sha256=entry['table']['sha256'], raw_table_bytes=entry['table']['bytes'],
                  sha256=entry['originEdition'], bytes=entry['origin']['object']['bytes'], input_hashes_verified=True)
    return source


def source_metadata_bytes(lock_path: Path, entry: dict) -> bytes:
    return encode(source_metadata(lock_path, entry))


def record_input(directory: Path, metadata: dict, *, logical_path: str | None = None) -> dict:
    """Write a candidate input list containing identities and declarations, not a run report."""
    directory = Path(directory)
    sha = metadata.get('sha256') or metadata['origin_sha256']
    cached = OBJECTS / f'inputs/origin/sha256/{sha}'
    if not cached.exists():
        raise FileNotFoundError(f'Original not cached: {sha}')
    else:
        origin = save_object('origin', cached.read_bytes())
    if origin['sha256'] != sha:
        raise ValueError('Candidate original identity differs')
    logical_path = logical_path or metadata.get('logical_input_path')
    if logical_path is None:
        parts = directory.parts
        start = next((i for i, part in enumerate(parts) if part.startswith('jurisdiction=')), None)
        if start is None:
            logical_path = (f"jurisdiction={metadata['jurisdiction_code']}/year={metadata['fiscal_year']}/"
                            f"document_kind={metadata.get('document_kind', 'budget')}/edition={sha}/"
                            f"direction={metadata.get('direction') or 'observation'}")
        else:
            logical_path = '/'.join(parts[start:])
        if metadata.get('namespace'):
            logical_path = metadata['namespace'] + '/' + logical_path
    partitions = dict(part.split('=', 1) for part in logical_path.split('/') if '=' in part)
    entry = dict(path=safe_relative(logical_path), jurisdiction=metadata['jurisdiction_code'],
                 fiscalYear=metadata['fiscal_year'], documentKind=metadata.get('document_kind') or partitions.get('document_kind', 'budget'),
                 direction=metadata.get('direction'), originEdition=sha,
                 origin=dict(availability='stored', sha256=sha, object=origin),
                 table=save_object('table', (directory / 'data.parquet').read_bytes()),
                 source=source_declaration(metadata))
    (directory / 'inputs.lock.json').write_bytes(encode(dict(schemaVersion=3, entries=[entry])))
    return entry


def cached_input(directory: Path) -> dict:
    """Validate a cached candidate before reusing its source declaration."""
    entries = read_lock(directory / 'inputs.lock.json')['entries']
    if len(entries) != 1:
        raise ValueError('A candidate directory must contain exactly one input declaration')
    entry = entries[0]
    verify_object(entry['table'], (directory / 'data.parquet').read_bytes())
    verify_object(entry['origin']['object'], (OBJECTS / entry['origin']['object']['key']).read_bytes())
    return entry


def remote_object(ref: dict, operation: str, *, objects_dir: Path | None = None) -> None:
    path = (OBJECTS if objects_dir is None else Path(objects_dir)) / safe_relative(ref['key'])
    if objects_dir is not None:
        from ingestion.fiscal.tama_ordinary_history.contracts import plain_path
        path=plain_path(path)  # Explicit original resource destination; parent cache-writer quiescence still required.
    path.parent.mkdir(parents=True, exist_ok=True)
    command = ['cf', 'r2', 'objects', operation, ref['key'], '--bucket-name', BUCKET, '--quiet']
    if operation == 'put':
        verify_object(ref, path.read_bytes())
        with tempfile.TemporaryFile() as stream:
            existing = subprocess.run(['cf', 'r2', 'objects', 'get', ref['key'], '--bucket-name', BUCKET, '--quiet'], stdout=stream, stderr=subprocess.PIPE)
            if existing.returncode == 0:
                stream.seek(0)
                verify_object(ref, stream.read())
                return
            error = existing.stderr.decode(errors='replace')
            if not re.search(r'(?:HTTP(?: status)?[ :]+404|404 Not Found|"status"\s*:\s*404|NoSuchKey)', error, re.IGNORECASE):
                raise RuntimeError('Cannot establish whether the immutable R2 input already exists')
        subprocess.run(command + ['--file', str(path)], check=True, stdout=sys.stderr)
    elif operation == 'get':
        with tempfile.TemporaryFile() as stream:
            subprocess.run(command, check=True, stdout=stream)
            stream.seek(0)
            body = stream.read()
        verify_object(ref, body)
        path.write_bytes(body)
    else:
        raise ValueError('Unsupported object operation')


def read_lock(path: Path = LOCK) -> dict:
    lock = json.loads(path.read_text())
    if lock['schemaVersion'] != 3 or not lock['entries']:
        raise ValueError('Unsupported or empty input snapshot')
    logical = [safe_relative(e['path']) for e in lock['entries']]
    if len(set(logical)) != len(logical):
        raise ValueError('Duplicate logical input paths')
    for e in lock['entries']:
        if not re.fullmatch(r'\d{6}', e['jurisdiction']) or type(e['fiscalYear']) is not int or not 1900 <= e['fiscalYear'] <= 2200:
            raise ValueError('Invalid input jurisdiction or fiscal year')
        if e['documentKind'] not in ['budget', 'supplementary', 'settlement'] or e['direction'] not in ['expenditure', 'revenue', None]:
            raise ValueError('Invalid document or direction')
        if not re.fullmatch(r'[a-f0-9]{64}', e['originEdition']) or e['origin']['sha256'] != e['originEdition']:
            raise ValueError('Input edition differs from its original document')
        if e['origin'].get('availability') != 'stored' or not e['origin'].get('object'):
            raise ValueError('An input snapshot requires every fixed original document')
        if e['origin']['object']['sha256'] != e['originEdition']:
            raise ValueError('Original document object differs from edition')
        partitions = dict(part.split('=', 1) for part in PurePosixPath(e['path']).parts if '=' in part)
        if partitions.get('jurisdiction') != e['jurisdiction'] or partitions.get('year') != str(e['fiscalYear']):
            raise ValueError('Logical input path differs from its scope')
        if e['direction'] is not None and any(partitions.get(key) != value for key, value in [('document_kind', e['documentKind']), ('edition', e['originEdition']), ('direction', e['direction'])]):
            raise ValueError('Statement input path differs from its document or edition')
        for kind, ref in [('table', e['table']), ('origin', e['origin']['object'])]:
            safe_relative(ref['key'])
            expected = f'inputs/{kind}/sha256/{ref["sha256"]}'
            if ref['key'] != expected or not re.fullmatch(r'[a-f0-9]{64}', ref['sha256']) or type(ref['bytes']) is not int or ref['bytes'] < 0:
                raise ValueError('Input object key does not identify its hash and kind')
        if not isinstance(e.get('source'), dict) or not e['source'].get('request_url'):
            raise ValueError('Input requires a source declaration with its original URL')
        if set(e['source']) - SOURCE_FIELDS:
            raise ValueError('Input source contains execution results rather than declarations')
        if 'provenance' in e:
            raise ValueError('Separate provenance is not part of the input format')
    return lock


def restore(path: Path = LOCK, *, remote: bool = False) -> Path:
    lock = read_lock(path)
    snapshot = digest(path.read_bytes())
    out = CACHE / 'inputs' / snapshot / 'raw'
    expected_paths = set()
    for entry in lock['entries']:
        directory = out / safe_relative(entry['path'])
        ref = entry['table']
        cached = OBJECTS / ref['key']
        if not cached.exists():
            if not remote:
                raise FileNotFoundError(f'Input not cached: {ref["key"]}; run pipeline:inputs restore --remote')
            remote_object(ref, 'get')
        body = cached.read_bytes()
        verify_object(ref, body)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'data.parquet').write_bytes(body)
        expected_paths.add(directory / 'data.parquet')
        ref = entry['origin'].get('object')
        if ref:
            cached = OBJECTS / ref['key']
            if not cached.exists() and remote:
                remote_object(ref, 'get')
            if not cached.exists():
                raise FileNotFoundError(f'Origin not cached: {ref["key"]}')
            verify_object(ref, cached.read_bytes())
    extra = set(out.rglob('*.parquet'))
    if extra - expected_paths:
        raise ValueError('Unexpected files in fixed input snapshot')
    if any(e['path'].startswith('tama-native-settlement/') for e in lock['entries']):
        from ingestion.fiscal.tama_native_settlement.registration import restore_evidence
        restore_evidence(OBJECTS, remote=remote)
    if any(e['path'].startswith('held5-council-approved-detail/') for e in lock['entries']):
        from ingestion.fiscal.held5_council_provider import restore_evidence
        restore_evidence(OBJECTS, remote=remote)
    if any(e['path'].startswith('akishima-settlement2024/') for e in lock['entries']):
        from ingestion.fiscal.extract_akishima_settlement2024 import restore as restore_settlement2024_evidence
        restore_settlement2024_evidence(OBJECTS, remote=remote)
    if any(e['path'].startswith('akishima-settlement2020-2023/') for e in lock['entries']):
        from ingestion.fiscal.extract_akishima_settlement2020_2023 import restore as restore_settlement2020_2023_evidence
        restore_settlement2020_2023_evidence(OBJECTS, remote=remote)
    if any(e['path'].startswith('akishima-settlement2019/') for e in lock['entries']):
        from ingestion.fiscal.extract_akishima_settlement2019 import (
            evidence_objects as settlement2019_evidence_objects,
            restore as restore_settlement2019_evidence,
        )
        for ref in settlement2019_evidence_objects():
            cached = OBJECTS / safe_relative(ref['key'])
            if not cached.exists():
                if not remote:
                    raise FileNotFoundError('Settlement2019 evidence not cached: ' + ref['key'])
                remote_object(ref, 'get')
            verify_object(ref, cached.read_bytes())
        restore_settlement2019_evidence(OBJECTS)
    if any(e['path'].startswith('akishima-supplementary2020-2025/') for e in lock['entries']):
        from ingestion.fiscal.akishima_supplementary_fy2025_01.evidence import restore_evidence
        restore_evidence(OBJECTS, remote=remote)
    if any(e['path'].startswith('chiyoda2021-settlement-native/') for e in lock['entries']):
        from ingestion.fiscal.chiyoda2021_settlement_native.registration import restore_evidence as restore_chiyoda2021_settlement_evidence
        restore_chiyoda2021_settlement_evidence(OBJECTS, remote=remote)
    if any(e['path'].startswith('tama-ordinary-history/') for e in lock['entries']):
        from ingestion.fiscal.tama_ordinary_history.reconstruct import restore_evidence
        restore_evidence(OBJECTS,remote=remote)
    return out


def origin_path(sha: str) -> Path:
    if not re.fullmatch(r'[a-f0-9]{64}', sha):
        raise ValueError('Invalid original document hash')
    path = OBJECTS / f'inputs/origin/sha256/{sha}'
    if not path.exists() or digest(path.read_bytes()) != sha:
        raise FileNotFoundError(f'Fixed origin unavailable: {sha}')
    return path


def locked_objects(lock: dict) -> dict:
    refs = {ref['key']: ref for entry in lock['entries'] for ref in [entry['table'], entry['origin']['object']]}
    if any(e['path'].startswith('tama-native-settlement/') for e in lock['entries']):
        from ingestion.fiscal.tama_native_settlement.registration import evidence_objects
        for ref in evidence_objects():
            if ref['key'] in refs and refs[ref['key']] != ref:
                raise ValueError('Conflicting native proof object identity')
            refs[ref['key']] = ref
    if any(e['path'].startswith('held5-council-approved-detail/') for e in lock['entries']):
        from ingestion.fiscal.held5_council_provider import evidence_objects
        for ref in evidence_objects():
            if ref['key'] in refs and refs[ref['key']] != ref:
                raise ValueError('Conflicting held5 proof object identity')
            refs[ref['key']] = ref
    if any(e['path'].startswith('akishima-settlement2024/') for e in lock['entries']):
        from ingestion.fiscal.extract_akishima_settlement2024 import evidence_objects
        for ref in evidence_objects():
            if ref['key'] in refs and refs[ref['key']] != ref:
                raise ValueError('Conflicting settlement2024 proof object identity')
            refs[ref['key']] = ref
    if any(e['path'].startswith('akishima-settlement2020-2023/') for e in lock['entries']):
        from ingestion.fiscal.extract_akishima_settlement2020_2023 import evidence_objects
        for ref in evidence_objects():
            if ref['key'] in refs and refs[ref['key']] != ref:
                raise ValueError('Conflicting settlement2020-2023 proof object identity')
            refs[ref['key']] = ref
    if any(e['path'].startswith('akishima-supplementary2020-2025/') for e in lock['entries']):
        from ingestion.fiscal.akishima_supplementary_fy2025_01.evidence import evidence_objects
        for ref in evidence_objects():
            if ref['key'] in refs and refs[ref['key']] != ref:
                raise ValueError('Conflicting supplementary FY2025 No.1 evidence identity')
            refs[ref['key']] = ref
    if any(e['path'].startswith('chiyoda2025-native/') for e in lock['entries']):
        from ingestion.fiscal.chiyoda2025_native.registration import evidence_objects
        for ref in evidence_objects():
            if ref['key'] in refs and refs[ref['key']] != ref:
                raise ValueError('Conflicting chiyoda2025 proof object identity')
            refs[ref['key']] = ref
    if any(e['path'].startswith('akishima-settlement2019/') for e in lock['entries']):
        from ingestion.fiscal.extract_akishima_settlement2019 import evidence_objects
        for ref in evidence_objects():
            key = safe_relative(ref['key'])
            if (key not in {f"inputs/{kind}/sha256/{ref['sha256']}" for kind in ('origin', 'proof')}
                    or not re.fullmatch(r'[a-f0-9]{64}', ref['sha256'])
                    or type(ref['bytes']) is not int or ref['bytes'] <= 0):
                raise ValueError('Settlement2019 evidence key/hash/size differs')
            if key in refs and refs[key] != ref:
                raise ValueError('Conflicting settlement2019 proof object identity')
            refs[key] = ref
    if any(e['path'].startswith('chiyoda2021-settlement-native/') for e in lock['entries']):
        from ingestion.fiscal.chiyoda2021_settlement_native.registration import evidence_objects
        for ref in evidence_objects():
            if ref['key'] in refs and refs[ref['key']] != ref:
                raise ValueError('Conflicting chiyoda2021 settlement proof object identity')
            refs[ref['key']] = ref

    if any(e['path'].startswith('tama-ordinary-history/') for e in lock['entries']):
        from ingestion.fiscal.tama_ordinary_history.reconstruct import evidence_objects
        from ingestion.fiscal.tama_ordinary_history.contracts import merge_evidence_refs
        refs=merge_evidence_refs(refs,evidence_objects())
    return refs


def pin_snapshot(draft: Path, target: Path) -> None:
    lock = read_lock(draft)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encode(lock))


def backup(lock_path: Path, output: Path) -> None:
    lock = read_lock(lock_path)
    refs = locked_objects(lock)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', allowZip64=True) as archive:
        archive.writestr('sources.lock.json', lock_path.read_bytes())
        for key, ref in sorted(refs.items()):
            body = (OBJECTS / key).read_bytes()
            verify_object(ref, body)
            archive.writestr(key, body)


def restore_backup(lock_path: Path, archive_path: Path) -> Path:
    lock = read_lock(lock_path)
    refs = locked_objects(lock)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.read('sources.lock.json') != lock_path.read_bytes():
            raise ValueError('Backup belongs to another fixed input snapshot')
        expected = set(refs) | {'sources.lock.json'}
        if len(archive.namelist()) != len(expected) or set(archive.namelist()) != expected:
            raise ValueError('Backup objects differ from the fixed snapshot')
        for key, ref in sorted(refs.items()):
            if archive.getinfo(key).file_size != ref['bytes']:
                raise ValueError('Backup object size differs from fixed snapshot')
            body = archive.read(key)
            verify_object(ref, body)
            out = OBJECTS / safe_relative(key)
            if out.exists():
                verify_object(ref, out.read_bytes())
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(body)
    return restore(lock_path)


def migrate(raw: Path, *, remote: bool = False) -> Path:
    raw = raw.resolve()
    draft = CACHE / 'migration/sources.lock.json'
    entries = []
    # Fixed restore directories contain only tables; their declarations stay in the lock.
    snapshots = sorted(raw.rglob('inputs.lock.json'))
    for snapshot in snapshots:
        for entry in read_lock(snapshot)['entries']:
            # A per-table candidate list describes exactly its sibling Parquet.
            table = snapshot.parent / 'data.parquet'
            verify_object(entry['table'], table.read_bytes())
            entries.append(dict(entry, path=str(snapshot.parent.relative_to(raw))))
    selected = {entry['path'] for entry in entries}
    for entry in (read_lock(LOCK)['entries'] if LOCK.exists() else []):
        table = raw / entry['path'] / 'data.parquet'
        if table.exists() and entry['path'] not in selected:
            verify_object(entry['table'], table.read_bytes())
            entries.append(entry)
            selected.add(entry['path'])
    unlisted = {str(p.parent.relative_to(raw)) for p in raw.rglob('data.parquet')} - selected
    if unlisted:
        raise ValueError('Tables without input declarations: ' + ', '.join(sorted(unlisted)))
    lock = {'schemaVersion': 3, 'entries': sorted(entries, key=lambda e: e['path'])}
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_bytes(encode(lock))
    read_lock(draft)
    if remote:
        if LOCK.exists() and {e['path'] for e in read_lock(LOCK)['entries']} - selected:
            raise ValueError('Cannot omit adopted inputs when pinning a replacement snapshot')
        for ref in locked_objects(lock).values():
            remote_object(ref, 'put')
            remote_object(ref, 'get')
            verify_object(ref, (OBJECTS / ref['key']).read_bytes())
        pin_snapshot(draft, LOCK)
        return LOCK
    return draft


def describe_inputs(lock_path: Path = LOCK, raw: Path | None = None) -> list[dict]:
    entries = read_lock(lock_path)['entries']
    return [dict(path=entry['path'], source=source_metadata(lock_path, entry))
            for entry in entries if raw is None or (raw / entry['path'] / 'data.parquet').exists()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    d = sub.add_parser('describe')
    d.add_argument('--lock', type=Path, default=LOCK)
    r = sub.add_parser('restore')
    r.add_argument('--lock', type=Path, default=LOCK)
    r.add_argument('--remote', action='store_true')
    m = sub.add_parser('migrate')
    m.add_argument('--raw', type=Path, required=True)
    m.add_argument('--remote', action='store_true')
    b = sub.add_parser('backup')
    b.add_argument('--lock', type=Path, default=LOCK)
    b.add_argument('--output', type=Path, required=True)
    b = sub.add_parser('restore-backup')
    b.add_argument('--lock', type=Path, default=LOCK)
    b.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'describe':
        print(json.dumps(describe_inputs(args.lock), ensure_ascii=False))
        return
    if args.command == 'restore':
        out = restore(args.lock, remote=args.remote)
    elif args.command == 'migrate':
        out = migrate(args.raw, remote=args.remote)
    elif args.command == 'backup':
        backup(args.lock, args.output)
        out = args.output
    else:
        out = restore_backup(args.lock, args.archive)
    print(json.dumps({'path': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
