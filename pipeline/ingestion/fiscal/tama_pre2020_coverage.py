"""Direct whole-field checks for the 49 recognized pre-FY2020 Tama observation datasets.

Lexical CSV cells, positioned words/pages, nonadditive account-reference controls and the
health expenditure grids retain separate preserved grains. Recognition and
project-to-legal-setsu correspondence always remain 'unconfirmed'.
"""
from __future__ import annotations
from ingestion.inputs import source_metadata_bytes

import json
from collections import defaultdict
from pathlib import Path

import duckdb

from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, verify_object
from ingestion.fiscal.native_settlement_coverage import records

NAMESPACE = 'tama-pre2020'
JURISDICTION = '132241'
FINANCIAL_TABLE = 'health-expenditure-rows'
EXPECTED_2019_CONTROLS = dict(executed_yen=15472775811,
                              budget_current_thousand_yen=15704921,
                              initial_budget_thousand_yen=15583149)
EXPECTED_2018_REF_NULLS = 27
FIELDS = ['dataset_id', 'jurisdiction_code', 'fiscal_year', 'document_kind',
          'origin_sha256', 'structure_json', 'source_json', 'phases_json',
          'line_count', 'direction']
DATASET_SELECT = ('select ' + ', '.join(FIELDS) + ' from int_fiscal_datasets')


def compound_key(table_id: str) -> list[str]:
    if table_id == FINANCIAL_TABLE:
        return ['observed_id']
    if table_id == 'account-reference-controls':
        return ['source_ordinal', 'source_column_ordinal']
    if table_id == 'pdf-word-observations':
        return ['physical_page', 'source_ordinal']
    if table_id == 'pdf-page-observations':
        return ['physical_page']
    return ['source_ordinal']


def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path,
                    datasets: list[dict]) -> None:
    entries = [entry for entry in read_lock(lock_path)['entries']
               if entry['path'].startswith(NAMESPACE + '/')]
    if not entries:
        return
    selected = [row for row in datasets
                if json.loads(row['source_json']).get('provider') == 'tama-pre2020']
    seen = {row['dataset_id'] for row in selected}
    registry = {}
    for values in connection.execute(
            DATASET_SELECT + " where json_extract_string(source_json,'$.provider')='tama-pre2020'").fetchall():
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
                                      recognition_status='unconfirmed',
                                      project_legal_setsu_correspondence='unconfirmed')
        row['_phase_lines'] = {}
    try:
        registered = {row['dataset_id']: row for row in selected}
        if len(entries) != 49 or len(registered) != 49:
            raise ValueError('Exact adopted49 pre2020 registrations missing or repeated')
        by_table = defaultdict(list)
        for entry in entries:
            provenance = json.loads(source_metadata_bytes(lock_path, entry))
            table_id = provenance['table_id']
            financial = provenance.get('phase') == 'executed'
            token = 'expenditure' if financial else 'observation'
            dataset_id = (f"132241:{provenance['fiscal_year']}:{token}:{provenance['document_kind']}"
                          f":{provenance['sha256']}:{table_id}")
            row = registered[dataset_id]
            if row['origin_sha256'] != provenance['sha256']:
                raise ValueError('Registered dataset/origin SHA differs from provenance')
            if (row.get('direction') == 'expenditure') != financial:
                raise ValueError('Registered dataset direction differs from provenance phase')
            if json.loads(row['phases_json']) != (['executed'] if financial else []):
                raise ValueError('Registered dataset phases differ from provenance phase')
            if entry['direction'] != ('expenditure' if financial else None):
                raise ValueError('Lock entry direction differs from provenance phase')
            table_path = OBJECTS / safe_relative(entry['table']['key'])
            verify_object(entry['table'], table_path.read_bytes())
            by_table[table_id].append((entry, provenance, row, table_path, financial))
        for table_id, members in by_table.items():
            relative = f'fiscal/{JURISDICTION}/tama_pre2020_{table_id.replace("-", "_")}.csv'
            if relative not in hashes:
                raise ValueError(f'Pre2020 CSV is not in verified artifacts: {relative}')
            if digest((candidate / relative).read_bytes()) != hashes[relative]:
                raise ValueError(f'Pre2020 CSV bytes differ: {relative}')
            for row in {m[2]['dataset_id']: m[2] for m in members}.values():
                row['output_coverage']['files'].append(relative)
            mart = f'fiscal_{JURISDICTION}_tama_pre2020_{table_id.replace("-", "_")}'
            all_types = {r[0]: r[1] for r in connection.execute(
                'describe select * from ' + mart).fetchall()}
            for entry, provenance, row, table_path, financial in members:
                part_cols = [r[0] for r in connection.execute(
                    'describe select * from read_parquet(?)', [str(table_path)]).fetchall()]
                if not set(part_cols) <= set(all_types):
                    raise ValueError(f'{table_id}: provided CSV lost original columns')
                csv_args = [str(candidate / relative), all_types, row['dataset_id']]
                csv_file = records(connection,
                    "select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')"
                    ' where dataset_id=?', csv_args)
                col_list = ','.join('"' + c + '"' for c in part_cols)
                diff = connection.execute(f"""
                    select (select count(*) from (
                      select {col_list} from read_parquet(?)
                      except all
                      select {col_list} from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='') where dataset_id=?))
                    + (select count(*) from (
                      select {col_list} from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='') where dataset_id=?
                      except all
                      select {col_list} from read_parquet(?)))""",
                    [str(table_path), str(candidate / relative), all_types, row['dataset_id'],
                     str(candidate / relative), all_types, row['dataset_id'], str(table_path)]).fetchone()[0]
                key = compound_key(table_id)
                if len(csv_file) != row['line_count'] or len(csv_file) != provenance['rows'] or diff != 0:
                    raise ValueError(f'{table_id}: provided rows differ from fixed original partition')
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
                if table_id == FINANCIAL_TABLE:
                    fy = provenance['fiscal_year']
                    nulls = sum(1 for r in csv_file if r['printed_executed_yen'] == '#REF!'
                                and r['executed_yen'] is None)
                    if fy == 2018 and nulls != EXPECTED_2018_REF_NULLS:
                        raise ValueError('FY2018 #REF! literals not preserved as numeric NULL')
                    if fy == 2019:
                        for grain in ('moku-observation', 'kou-control', 'kan-control'):
                            g = [r for r in csv_file if r['observed_grain'] == grain]
                            if sum(int(r['executed_yen']) for r in g) != EXPECTED_2019_CONTROLS['executed_yen']:
                                raise ValueError('FY2019 independent printed control differs')
                        for col, ref in [('budget_current_thousand_yen', 15704921),
                                         ('initial_budget_thousand_yen', 15583149)]:
                            m = [r for r in csv_file if r['observed_grain'] == 'moku-observation' and r[col] is not None]
                            if sum(int(r[col]) for r in m) != ref:
                                raise ValueError('FY2019 budget control differs')
                proof['complete'] = True
    except (ValueError, KeyError, TypeError, duckdb.Error) as error:
        for row in selected:
            if not row['output_coverage']['complete']:
                row['output_coverage']['errors'].append(str(error))
