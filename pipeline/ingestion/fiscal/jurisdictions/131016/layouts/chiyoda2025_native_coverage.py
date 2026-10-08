"""Direct whole-field checks for the 8 FY2025 Chiyoda native observation datasets.

Printed moku/legal/explanation observations keep separate, nonadditive grains. Phase and
recognition/correspondence always remain 'unconfirmed'; the phantom cell stays NULL.
"""
from __future__ import annotations

from importlib import import_module as _ingestion_module
from ingestion.inputs import source_metadata_bytes

import json
from collections import defaultdict
from pathlib import Path

import duckdb

from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, verify_object
records = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.native_settlement_coverage').records

NAMESPACE = 'chiyoda2025-native'
JURISDICTION = '131016'
EXPECTED_TABLES = ['native-pages', 'native-observations', 'native-focused_observations',
                   'native-financial_cells', 'native-moku_controls', 'native-legal_amounts',
                   'native-explanation_amounts', 'native-unresolved_cells']
EXPECTED_MOKU_TOTALS = {'general': 75353052, 'national-health': 6553113,
                        'care': 5190760, 'elderly': 2348146}
EXPECTED_UNRESOLVED_ROWS = 1
FIELDS = ['dataset_id', 'jurisdiction_code', 'fiscal_year', 'document_kind',
          'origin_sha256', 'structure_json', 'source_json', 'phases_json',
          'line_count', 'direction']
DATASET_SELECT = ('select ' + ', '.join(FIELDS) + ' from int_fiscal_datasets')


def compound_key(table_id: str) -> list[str]:
    if table_id == 'native-pages':
        return ['physical_page']
    return ['observed_id']


def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path,
                    datasets: list[dict]) -> None:
    entries = [entry for entry in read_lock(lock_path)['entries']
               if entry['path'].startswith(NAMESPACE + '/')]
    if not entries:
        return
    selected = [row for row in datasets
                if json.loads(row['source_json']).get('provider') == 'chiyoda2025-native']
    seen = {row['dataset_id'] for row in selected}
    registry = {}
    for values in connection.execute(
            DATASET_SELECT + " where json_extract_string(source_json,'$.provider')='chiyoda2025-native'").fetchall():
        row = dict(zip(FIELDS, values, strict=True))
        registry[row['dataset_id']] = row
        if row['dataset_id'] not in seen:
            selected.append(row)
            datasets.append(row)
    for row in selected:
        if 'direction' not in row:
            row['direction'] = registry[row['dataset_id']]['direction']
    for row in selected:
        row['output_coverage'] = dict(complete=False, files=[], accounts={}, errors=[],
                                      original_rows=0, all_original_fields_preserved=False,
                                      recognition_status='unconfirmed', phase='unconfirmed',
                                      approval_status='unconfirmed',
                                      project_legal_setsu_correspondence='unconfirmed')
        row['_phase_lines'] = {}
    try:
        registered = {row['dataset_id']: row for row in selected}
        if len(entries) != 8 or len(registered) != 8:
            raise ValueError('Exact adopted8 chiyoda2025-native registrations missing or repeated')
        by_table = defaultdict(list)
        for entry in entries:
            provenance = json.loads(source_metadata_bytes(lock_path, entry))
            table_id = provenance['table_id']
            financial = provenance['direction'] == 'expenditure'
            token = 'expenditure' if financial else 'observation'
            kind = provenance.get('document_kind') or entry['documentKind']
            if kind != 'budget' or entry['documentKind'] != 'budget':
                raise ValueError('Provenance/lock document_kind differs from budget')
            dataset_id = (f"131016:{provenance['fiscal_year']}:{token}:{kind}"
                          f":{provenance['sha256']}:{table_id}")
            row = registered[dataset_id]
            if row['origin_sha256'] != provenance['sha256']:
                raise ValueError('Registered dataset/origin SHA differs from provenance')
            if entry['originEdition'] != provenance['sha256'] or entry['origin']['object']['sha256'] != provenance['sha256']:
                raise ValueError('Lock origin object differs from provenance')
            src = json.loads(row['source_json'])
            if (src.get('sha256'), src.get('tableId'), src.get('provider')) != (provenance['sha256'], table_id, 'chiyoda2025-native'):
                raise ValueError('Registry source_json differs from provenance/table')
            if row['fiscal_year'] != provenance['fiscal_year'] or provenance['fiscal_year'] != 2025:
                raise ValueError('Registered/provenance fiscal year differs')
            if financial and (provenance.get('source_amount_unit') != '千円' or provenance.get('unit_multiplier') != 1000):
                raise ValueError('Financial unit declaration differs')
            origin_path = OBJECTS / safe_relative(entry['origin']['object']['key'])
            verify_object(entry['origin']['object'], origin_path.read_bytes())
            if (row.get('direction') == 'expenditure') != financial:
                raise ValueError('Registered dataset direction differs from provenance')
            if json.loads(row['phases_json']) != []:
                raise ValueError('Registered dataset phases must be [] (phase unconfirmed)')
            if entry['direction'] != ('expenditure' if financial else None):
                raise ValueError('Lock entry direction differs from provenance')
            table_path = OBJECTS / safe_relative(entry['table']['key'])
            verify_object(entry['table'], table_path.read_bytes())
            by_table[table_id].append((entry, provenance, row, table_path, financial))
        if set(by_table) != set(EXPECTED_TABLES):
            raise ValueError('Table coverage differs from declared eight')
        for table_id, members in by_table.items():
            relative = f'fiscal/{JURISDICTION}/r7-native-{table_id.replace("native-", "").replace("_", "-")}.csv'
            if relative not in hashes:
                raise ValueError(f'chiyoda2025 CSV is not in verified artifacts: {relative}')
            if digest((candidate / relative).read_bytes()) != hashes[relative]:
                raise ValueError(f'chiyoda2025 CSV bytes differ: {relative}')
            for row in {m[2]['dataset_id']: m[2] for m in members}.values():
                row['output_coverage']['files'].append(relative)
            mart = f'csv_131016_r7_native_{table_id.replace("native-", "").replace("_", "-")}'
            all_types = {r[0]: r[1] for r in connection.execute(
                'describe select * from "' + mart + '"').fetchall()}
            for entry, provenance, row, table_path, financial in members:
                part_cols = [r[0] for r in connection.execute(
                    'describe select * from read_parquet(?)', [str(table_path)]).fetchall()]
                if not set(part_cols) <= set(all_types):
                    raise ValueError(f'{table_id}: provided CSV lost original columns')
                csv_args = [str(candidate / relative), all_types]  # CSV read covers mart's FULL column set
                csv_file = records(connection,
                    "select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')",
                    csv_args)
                col_list = ','.join('"' + c + '"' for c in part_cols)
                diff = connection.execute(f"""
                    select (select count(*) from (
                      select {col_list} from read_parquet(?)
                      except all
                      select {col_list} from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')))
                    + (select count(*) from (
                      select {col_list} from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')
                      except all
                      select {col_list} from read_parquet(?)))""",
                    [str(table_path), str(candidate / relative), all_types,
                     str(candidate / relative), all_types, str(table_path)]).fetchone()[0]
                key = compound_key(table_id)
                if len(csv_file) != provenance['rows'] or diff != 0:
                    raise ValueError(f'{table_id}: provided rows differ from fixed original partition')
                # raw ↔ stg/int/mart layers: typed bidirectional EXCEPT ALL on all original columns
                stg = 'stg_native__' + table_id.replace('native-', '')
                for layer in (stg, mart):
                    ldiff = connection.execute(f'''
                        select (select count(*) from (
                          select {col_list} from read_parquet(?) except all
                          select {col_list} from "{layer}"))
                        + (select count(*) from (
                          select {col_list} from "{layer}" except all
                          select {col_list} from read_parquet(?)))''',
                        [str(table_path), str(table_path)]).fetchone()[0]
                    if ldiff != 0:
                        raise ValueError(f'{table_id}: layer {layer} lost or changed original columns')
                if len({tuple(r[c] for c in key) for r in csv_file}) != len(csv_file):
                    raise ValueError(f'{table_id}: repeated original observation in provided CSV')
                if {r['origin_sha256'] for r in csv_file} != {row['origin_sha256']}:
                    raise ValueError(f'{table_id}: provided origin SHA differs')
                proof = row['output_coverage']
                proof['original_rows'] = len(csv_file)
                proof['all_original_fields_preserved'] = diff == 0
                if not financial:
                    if row.get('direction') is not None or json.loads(row['phases_json']):
                        raise ValueError('Nonfinancial observation gained direction or phase')
                if financial:
                    if any(r['phase'] is not None for r in csv_file):
                        raise ValueError(f'{table_id}: phase must stay NULL')
                    if table_id == 'native-moku_controls':
                        moku = [r for r in csv_file if r['role'] == 'moku-control']
                        by_account = defaultdict(int)
                        for r in moku:
                            by_account[r['account']] += int(r['observed_amount'])
                        if dict(by_account) != EXPECTED_MOKU_TOTALS:
                            raise ValueError('Independent printed moku controls differ')
                        proof['accounts'] = dict(by_account)
                    if table_id == 'native-unresolved_cells':
                        nulls = sum(1 for r in csv_file if r['observed_amount'] is None)
                        if nulls != EXPECTED_UNRESOLVED_ROWS:
                            raise ValueError('Unresolved phantom isolation differs')
                proof['complete'] = True
    except (ValueError, KeyError, TypeError, duckdb.Error) as error:
        for row in selected:
            if not row['output_coverage']['complete']:
                row['output_coverage']['errors'].append(str(error))
