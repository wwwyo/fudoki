"""Proposed portable reconstruction of reviewed FY2020 Tama scan observations.

Default operation is offline and cache-only. Fresh native recognition is a
separate evidence acquisition step; it never silently replaces reviewed proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import duckdb
if __package__:
    from .native_scan_provider import FrozenNativeProvider
else:
    from native_scan_provider import FrozenNativeProvider


def write_typed(path: Path, rows: list[dict], columns: list[dict]) -> dict:
    if not rows:
        raise ValueError(f'No observed rows: {path.name}')
    names = [x['name'] for x in columns]
    if any(set(row) != set(names) for row in rows):
        raise ValueError(f'Raw schema/field contract differs: {path.name}')
    con = duckdb.connect()
    con.execute('create table observations (' + ', '.join('"' + x['name'] + '" ' + x['type'] for x in columns) + ')')
    con.executemany('insert into observations values (' + ', '.join('?' for _ in columns) + ')', [[row[name] for name in names] for row in rows])
    con.execute('copy observations to ? (format parquet, compression zstd)', [str(path)])
    readback = [json.loads(x[0]) for x in con.execute('select to_json(t) from read_parquet(?) t', [str(path)]).fetchall()]
    if readback != rows:
        raise ValueError(f'Original field/row/position changed: {path.name}')
    body = path.read_bytes()
    return {'role': path.stem, 'path': str(path), 'rows': len(readback), 'bytes': len(body),
        'sha256': hashlib.sha256(body).hexdigest(), 'unique_observed_ids': len({x['observed_id'] for x in readback}),
        'schema': [[x[0], x[1]] for x in con.execute('describe select * from read_parquet(?)', [str(path)]).fetchall()],
        'all_fields_readback_match': True}


def reconstruct(manifest: Path, cache: Path, transcription_path: Path, schema_path: Path, output: Path) -> dict:
    provider = FrozenNativeProvider(manifest, cache)
    verified = provider.verify_all()
    transcription = json.loads(transcription_path.read_text())
    schema = json.loads(schema_path.read_text())
    ledger_proof = provider.validate_source_ledgers(transcription)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tama-native-evidence-') as temporary:
        evidence = Path(temporary)
        provider.hydrate(evidence)
        env = os.environ | {'TAMA_NATIVE_EVIDENCE': str(evidence), 'TAMA_NATIVE_OUTPUT': str(output),
            'TAMA_NATIVE_SCHEMA': str(schema_path.resolve()), 'TAMA_NATIVE_MANIFEST': str(manifest.resolve())}
        subprocess.run([sys.executable, str(Path(__file__).with_name('native_scan_layout.py'))], env=env, check=True)
    summary = write_typed(output / 'independent-account-controls.parquet', transcription['summary_rows'], schema['independent-account-controls'])
    page_roles = {r['printed_page']: r['page_role'] for r in provider.json(transcription['page_roles'])}
    page_rows = []
    for logical, asset in provider.assets.items():
        if not (logical.startswith('pages/') and logical.endswith('.json')):
            continue
        page = provider.json(logical)
        render = provider.assets[logical.removesuffix('.json') + '.png']
        number = page['expected_printed_page']
        original = provider.assets['originals/' + page['origin_sha256'] + '.pdf']
        page_rows.append({'observed_id': page['origin_sha256'] + ':p' + str(page['physical_page']).zfill(3) + ':page',
            'jurisdiction_code': '132241', 'financial_year': 2020, 'origin_sha256': page['origin_sha256'],
            'origin_url': page['origin_url'], 'part': page['part'], 'physical_page': page['physical_page'],
            'printed_page': number, 'page_role': page_roles[number], 'recognition_status': 'unconfirmed',
            'phase': None, 'amount_unit': None, 'amount_multiplier': None,
            'page_width_points': page['page_width'], 'page_height_points': page['page_height'],
            'native_observation_count': len(page['observations']), 'page_observation_sha256': asset['sha256'],
            'page_render_sha256': render['sha256'], 'original_object_key': original['object_key'],
            'page_observation_object_key': asset['object_key'], 'page_render_object_key': render['object_key'],
            'native_page_observations_json': json.dumps(page, ensure_ascii=False, separators=(',', ':'))})
    page_rows.sort(key=lambda r: r['printed_page'])
    pages = write_typed(output / 'page-observations.parquet', page_rows, schema['page-observations'])
    if len(page_rows) != 230 or len({r['observed_id'] for r in page_rows}) != 230:
        raise ValueError('Physical-page conservation failed')
    tables = json.loads((output / 'candidate-manifest.json').read_text()) + [summary, pages]
    con = duckdb.connect()
    comparisons = []
    for expected in transcription['expected']:
        role = expected['role']
        actual = [json.loads(x[0]) for x in con.execute('select to_json(t) from read_parquet(?) t', [str(output / (role + '.parquet'))]).fetchall()]
        reference = [json.loads(line) for line in provider.path(expected['reference']['logical_path']).read_text().splitlines()]
        if actual != reference:
            raise ValueError(f'Accepted original-field correspondence differs: {role}')
        if len(actual) != expected['rows'] or len({x['observed_id'] for x in actual}) != len(actual):
            raise ValueError(f'Original-row conservation/identity failed: {role}')
        comparisons.append({'role': role, 'rows': len(actual), 'every_accepted_field_and_position_equal': True,
            'accepted_jsonl_sha256': expected['reference']['sha256']})
    result = {'network_requests': 0, 'fresh_native_ocr_calls': 0,
        'recognized_text_and_visual_readings_separate': True,
        'canonical_adoption': False, 'recognition_status': 'unconfirmed',
        'immutable_objects': verified, 'ledger_proof': ledger_proof,
        'tables': tables, 'accepted_field_correspondence': comparisons,
        'declaration_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [manifest, transcription_path, schema_path]},
        'runtime_input_paths': {'manifest': str(manifest), 'cache': str(cache), 'transcription': str(transcription_path), 'schema': str(schema_path)}}
    (output / 'reconstruction-readback.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    directory = Path(__file__).resolve().parent
    parser.add_argument('--manifest', type=Path, default=directory / 'evidence-manifest.json')
    parser.add_argument('--transcription', type=Path, default=directory / 'frozen-transcription.json')
    parser.add_argument('--schema', type=Path, default=directory / 'raw-schema.json')
    from ingestion.inputs import OBJECTS
    parser.add_argument('--cache-dir', type=Path, default=OBJECTS)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--partition-output', type=Path)
    args = parser.parse_args()
    result = reconstruct(args.manifest, args.cache_dir, args.transcription, args.schema, args.output)
    if args.partition_output:
        subprocess.run([sys.executable, str(directory / 'native_scan_partitions.py'),
            '--definitions', str(args.manifest.parent), '--raw-dir', str(args.output),
            '--output', str(args.partition_output)], check=True)
    print(json.dumps({'tables': [(Path(x['path']).name, x['rows'], x['sha256']) for x in result['tables']],
        'originals_and_proof_objects_verified': len(result['immutable_objects']), 'ledger_counts': result['ledger_proof']['ledger_counts']}))


if __name__ == '__main__':
    main()
