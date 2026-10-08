"""Whole-field checks for the 5 FY2021 Chiyoda settlement native observation datasets.

Level rows (kan/kou/moku/total) and moku-setsu rows keep separate grains. Phase and
approval remain 'unconfirmed'; printed controls are verified: per-row
total=executed+carryforward+unused and hierarchy sums moku→kou→kan→歳出合計.
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

NAMESPACE = 'chiyoda2021-settlement-native'
JURISDICTION = '131016'
EXPECTED_TABLES = ['native-pages', 'native-observations', 'native-levels', 'native-setsu', 'native-notes']
EXPECTED_TOTAL_ROW = {'initial': 62778760000, 'amended': 11338142000, 'carryover': 1313752000,
                      'reserve': 0, 'total': 75430654000, 'executed': 63476217688,
                      'carryforward_next': 1007005000, 'unused': 10947431312}
EXPECTED_LEVEL_ROWS = 127
EXPECTED_SETSU_ROWS = 562
FIELDS = ['dataset_id', 'jurisdiction_code', 'fiscal_year', 'document_kind',
          'origin_sha256', 'structure_json', 'source_json', 'phases_json',
          'line_count', 'direction']
DATASET_SELECT = ('select ' + ', '.join(FIELDS) + ' from int_fiscal_datasets')


def compound_key(table_id: str) -> list[str]:
    return ['seq'] if table_id in ('native-levels', 'native-setsu') else ['physical_page']


def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path,
                    datasets: list[dict]) -> None:
    entries = [entry for entry in read_lock(lock_path)['entries']
               if entry['path'].startswith(NAMESPACE + '/')]
    if not entries:
        return
    selected = [row for row in datasets
                if json.loads(row['source_json']).get('provider') == NAMESPACE]
    seen = {row['dataset_id'] for row in selected}
    registry = {}
    for values in connection.execute(
            DATASET_SELECT + f" where json_extract_string(source_json,'$.provider')='{NAMESPACE}'").fetchall():
        row = dict(zip(FIELDS, values, strict=True))
        registry[row['dataset_id']] = row
        if row['dataset_id'] not in seen:
            selected.append(row)
            datasets.append(row)
    for row in selected:
        if 'direction' not in row:
            row['direction'] = registry[row['dataset_id']]['direction']
        row['output_coverage'] = dict(complete=False, files=[], accounts={}, errors=[],
                                      original_rows=0, all_original_fields_preserved=False,
                                      recognition_status='unconfirmed', phase='unconfirmed',
                                      approval_status='unconfirmed',
                                      project_legal_setsu_correspondence='unconfirmed')
    try:
        registered = {row['dataset_id']: row for row in selected}
        if len(entries) != 5 or len(registered) != 5:
            raise ValueError('Exact adopted5 chiyoda2021-settlement-native registrations missing or repeated')
        by_table = defaultdict(list)
        for entry in entries:
            provenance = json.loads(source_metadata_bytes(lock_path, entry))
            table_id = provenance['table_id']
            financial = provenance['direction'] == 'expenditure'
            token = 'expenditure' if financial else 'observation'
            kind = provenance.get('document_kind') or entry['documentKind']
            if kind != 'settlement' or entry['documentKind'] != 'settlement':
                raise ValueError('Provenance/lock document_kind differs from settlement')
            dataset_id = (f"131016:{provenance['fiscal_year']}:{token}:{kind}"
                          f":{provenance['sha256']}:{table_id}")
            row = registered[dataset_id]
            if row['origin_sha256'] != provenance['sha256']:
                raise ValueError('Registered dataset/origin SHA differs from provenance')
            if entry['originEdition'] != provenance['sha256'] or entry['origin']['object']['sha256'] != provenance['sha256']:
                raise ValueError('Lock origin object differs from provenance')
            src = json.loads(row['source_json'])
            if (src.get('sha256'), src.get('tableId'), src.get('provider')) != (provenance['sha256'], table_id, NAMESPACE):
                raise ValueError('Registry source_json differs from provenance/table')
            if row['fiscal_year'] != provenance['fiscal_year'] or provenance['fiscal_year'] != 2021:
                raise ValueError('Registered/provenance fiscal year differs')
            if financial and (provenance.get('source_amount_unit') != '円' or provenance.get('unit_multiplier') != 1):
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
            raise ValueError('Table coverage differs from declared five')
        for table_id, members in by_table.items():
            relative = f'fiscal/{JURISDICTION}/r3-native-{table_id.replace("native-", "").replace("_", "-")}.csv'
            if relative not in hashes:
                raise ValueError(f'CSV is not in verified artifacts: {relative}')
            if digest((candidate / relative).read_bytes()) != hashes[relative]:
                raise ValueError(f'CSV bytes differ: {relative}')
            for row in {m[2]['dataset_id']: m[2] for m in members}.values():
                row['output_coverage']['files'].append(relative)
            mart = f'csv_131016_r3_native_{table_id.replace("native-", "").replace("_", "-")}'
            all_types = {r[0]: r[1] for r in connection.execute(
                'describe select * from "' + mart + '"').fetchall()}
            for entry, provenance, row, table_path, financial in members:
                part_cols = [r[0] for r in connection.execute(
                    'describe select * from read_parquet(?)', [str(table_path)]).fetchall()]
                if not set(part_cols) <= set(all_types):
                    raise ValueError(f'{table_id}: provided CSV lost original columns')
                csv_file = records(connection,
                    "select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')",
                    [str(candidate / relative), all_types])
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
                if diff:
                    raise ValueError(f'{table_id}: raw and provided CSV disagree on {diff} whole-field rows')
                row['output_coverage']['original_rows'] += len(csv_file)
                row['output_coverage']['all_original_fields_preserved'] = True
        # printed controls: whole-table arithmetic already verified at extraction; re-verify the 歳出合計 row
        levels_path = OBJECTS / safe_relative(
            by_table['native-levels'][0][0]['table']['key'])
        total_row = records(connection,
            "select * from read_parquet(?) where level='total'", [str(levels_path)])
        if len(total_row) != 1 or any(total_row[0].get(k) != v for k, v in EXPECTED_TOTAL_ROW.items()):
            raise ValueError('歳出合計 printed control row differs from expected')
        rollup = connection.execute(f"""
            select coalesce(sum(initial),0),coalesce(sum(amended),0),coalesce(sum(carryover),0),
                   coalesce(sum(reserve),0),coalesce(sum(total),0),coalesce(sum(executed),0),
                   coalesce(sum(carryforward_next),0),coalesce(sum(unused),0)
            from read_parquet('{levels_path}') where level='kan'""").fetchone()
        if tuple(EXPECTED_TOTAL_ROW.values()) != tuple(rollup):
            raise ValueError('kan→歳出合計 roll-up differs from printed total')
        rowcount = connection.execute(
            f"select count(*) from read_parquet('{levels_path}')").fetchone()[0]
        if rowcount != EXPECTED_LEVEL_ROWS:
            raise ValueError('native-levels row count differs')
        setsu_path = OBJECTS / safe_relative(
            by_table['native-setsu'][0][0]['table']['key'])
        setu_count = connection.execute(
            f"select count(*) from read_parquet('{setsu_path}')").fetchone()[0]
        if setu_count != EXPECTED_SETSU_ROWS:
            raise ValueError('native-setsu row count differs')
        for row in selected:
            row['output_coverage']['complete'] = True
    except Exception as exc:
        for row in selected:
            row['output_coverage']['errors'].append(str(exc))
            row['output_coverage']['complete'] = False
