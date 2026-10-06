"""公開資料の一覧を現在の固定入力・検査済みmartsと読み取り専用で照合する。"""
from __future__ import annotations
from ingestion.inputs import source_metadata_bytes

import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unicodedata

import duckdb
import jsonschema
import yaml

from ingestion.inputs import LOCK, OBJECTS, digest, encode, read_lock, safe_relative, verify_object
from ingestion.paths import PIPELINE, REPO
from ingestion.fiscal import canonical_sources

HERE = Path(__file__).resolve().parent
PHASE_KIND = {'initial': 'budget', 'supplementary': 'supplementary', 'settlement': 'settlement'}
PROJECT_LEVELS = frozenset({'project', 'jikou', 'saimoku', 'jigyo', 'daijigyo', 'chujigyo', 'shojigyo'})
SIDE_NAMESPACE = 'statement-moku-setsu/'
SIDE_RESOURCE = 'fiscal/131016/initial_expenditure_moku_setsu.csv'
SETTLEMENT_NAMESPACE = 'tama-settlement-pdf/'
INITIAL_NAMESPACE = 'initial-detail/'
COUNCIL_NAMESPACE = 'council-approved-detail/'
NATIVE_COUNCIL_NAMESPACE = 'native-council-approved-detail/'
SETTLEMENT_ROLES = {
    'legal-setsu': ('legal_setsu', 'printed-moku-by-legal-setsu'),
    'project-funding': ('project_funding', 'printed-project-by-funding-source'),
    'moku-controls': ('moku_controls', 'nonadditive-printed-moku-control'),
    'account-controls': ('account_controls', 'nonadditive-printed-account-control'),
    'project-controls': ('project_controls', 'nonadditive-printed-project-control'),
    'source-words': ('source_words', 'nonadditive-positioned-source-word'),
}


def label(value: str) -> str:
    return ''.join(unicodedata.normalize('NFKC', value).split())


def source_account_identities(source: dict, styles: dict) -> set[tuple[str | None, str]]:
    """会計コードの分離はdbtの当該団体の宣言に限定し、名称内の数字を残す。"""
    identities = set()
    for raw in source['account_labels']:
        value = label(raw)
        if (source['format'] == 'csv' and styles.get(source['jurisdiction']) == 'prefix2'
                and len(value) > 2 and all('0' <= c <= '9' for c in value[:2])):
            identities.add((value[:2], value[2:]))
        else:
            identities.add((None, value))
    return identities


def edition_account_identity(edition: dict, identities: set[tuple]) -> tuple | None:
    matching = [i for i in identities if i[1] == label(edition['account_label'])]
    return matching[0] if len(matching) == 1 else None


def path_levels(row: dict, absent: set[str]) -> set[str]:
    """原典の値がある提供経路だけを見る。空の宣言ノードを観測と数えない。"""
    def populated(code, name) -> bool:
        return any(label(str(v)) and label(str(v)) not in absent for v in [code, name] if v is not None)

    levels = {p['level'] for p in json.loads(row.get('account_path_json') or '[]')
              if populated(p.get('code'), p.get('label'))}
    for key in row:
        if key.endswith('_label') or key.endswith('_code'):
            level = key.rsplit('_', 1)[0]
            if populated(row.get(level + '_code'), row.get(level + '_label')):
                levels.add(level)
    if row.get('expenditure_setsu_id'):
        levels.add('setsu')
    return levels


def output_coverage(connection, candidate: Path, hashes: dict, datasets: list[dict]) -> None:
    """固定版CSVの行・内訳を、当該金額段階の原典行集合と1対1で照合する。"""
    cache: dict[str, list[dict]] = {}
    absent_by_code = yaml.safe_load((PIPELINE / 'dbt/dbt_project.yml').read_text())['vars']['fiscal_absent_level_markers']

    def rows(code: str, resource: str) -> tuple[str, list[dict]]:
        relative = f'fiscal/{code}/{resource}.csv'
        if relative not in hashes:
            raise ValueError(f'Phase output is not in verified artifacts: {relative}')
        if relative not in cache:
            with (candidate / relative).open(newline='') as stream:
                cache[relative] = list(csv.DictReader(stream))
        return relative, cache[relative]

    for dataset in datasets:
        dataset_id = dataset['dataset_id']
        code = dataset['jurisdiction_code']
        kind = dataset['document_kind']
        absent = {label(v) for v in absent_by_code[code]}
        proof = {'complete': False, 'files': [], 'accounts': {}, 'errors': []}
        dataset['output_coverage'] = proof
        dataset['_phase_lines'] = {}
        try:
            metadata = json.loads(dataset['source_json'])
            if metadata.get('namespace') in ('tama-initial-native', 'chiyoda-supplementary-native', 'tama-supplementary-native'):
                continue
            if metadata.get('independentBreakdown') and metadata.get('observationRole') in SETTLEMENT_ROLES:
                # 独立決算表は採用Parquetを直接照合する。共通財政明細へ混ぜない。
                continue
            if metadata.get('observationRole') == 'authoritative-initial-detail-candidate':
                continue  # whole-namespace adapter called below
            if metadata.get('observationRole') == 'nonadditive-initial-moku-reference':
                initial_reference_output_coverage(connection, candidate, hashes, dataset)
                continue
            if kind == 'supplementary':
                source = json.loads(dataset['source_json'])
                if source.get('observationRole') == 'nonadditive-supplementary-reference':
                    reference_output_coverage(connection, candidate, hashes, dataset)
                    continue
                if source.get('observationRole') in {
                        'authoritative-council-supplementary-detail',
                        'authoritative-native-council-supplementary-detail',
                        'authoritative-held5-council-supplementary-detail'}:
                    if not source.get('canonicalChanges'):
                        raise ValueError('Authoritative council detail lacks its canonical declaration')
                    model = {
                        'authoritative-council-supplementary-detail': 'int_132195_council_expenditure_changes',
                        'authoritative-native-council-supplementary-detail': 'int_132195_native_council_expenditure_changes',
                        'authoritative-held5-council-supplementary-detail': 'int_132195_held5_council_expenditure_changes',
                    }[source['observationRole']]
                    expected_rows = connection.execute(f'''select fiscal_line_id, source_row, delta_yen, fund_label, amendment_number
                        from {model} where dataset_id=?''', [dataset_id]).fetchall()
                elif source.get('tableId') == 'supplementary-expenditure-project-setsu':
                    expected_rows = connection.execute('''select fiscal_line_id, source_row, delta_yen, fund_label, amendment_number
                        from int_supplementary_expenditure_changes where dataset_id=?''', [dataset_id]).fetchall()
                else:
                    expected_rows = connection.execute('''select fiscal_line_id, source_row, delta_yen, fund_label, amendment_number
                        from int_fiscal_budget_history where dataset_id=? and record_kind='change' ''', [dataset_id]).fetchall()
                resources = ['expenditure_budget_changes']
            else:
                phase = 'approved' if kind == 'budget' else 'executed'
                if kind == 'budget' and metadata.get('observationRole') == 'authoritative-initial-detail':
                    if not metadata.get('canonicalInitial'):
                        raise ValueError('Authoritative initial detail lacks its canonical declaration')
                    expected_rows = connection.execute('''select fiscal_line_id, source_row, initial_yen, fund_label
                        from int_132195_initial_detail where dataset_id=?''', [dataset_id]).fetchall()
                else:
                    expected_rows = connection.execute('''select l.fiscal_line_id, l.source_row, a.value, l.fund_label
                        from int_fiscal_lines l join int_fiscal_amounts a using (fiscal_line_id)
                        where l.dataset_id=? and a.phase=?''', [dataset_id, phase]).fetchall()
                    if kind == 'budget':
                        expected_rows += connection.execute('''select fiscal_line_id, source_row, initial_yen, fund_label
                            from int_fiscal_budget_history where dataset_id=? and record_kind='initial' ''', [dataset_id]).fetchall()
                resources = (['initial_expenditure_budget'] if kind == 'budget'
                             else ['settlement_expenditure', 'settlement_expenditure_setsu'])
            expected = {r[0]: (int(r[1]), Decimal(str(r[2])), label(r[3])) for r in expected_rows}
            if (not expected or len(expected) != len(expected_rows)
                    or len(expected) != dataset['line_count']):
                raise ValueError('Required phase does not cover each dataset original row exactly once')
            sequences = {r[0]: int(r[4]) for r in expected_rows} if kind == 'supplementary' else {}
            items = {}
            if kind in ['budget', 'supplementary']:
                relative, item_rows = rows(code, 'expenditure_budget_items')
                proof['files'].append(relative)
                for item in item_rows:
                    key = item['budget_item_id']
                    if key in items:
                        raise ValueError('Duplicate budget item in provided CSV')
                    items[key] = item
            for resource in resources:
                relative, all_rows = rows(code, resource)
                proof['files'].append(relative)
                provided = [r for r in all_rows if r.get('dataset_id') == dataset_id]
                covered = Counter()
                output_ids = [r['change_id'] if kind == 'supplementary' else r['fiscal_line_id']
                              for r in provided]
                if len(set(output_ids)) != len(output_ids):
                    raise ValueError('Duplicate provided-line identities')
                for row in provided:
                    if 'fiscal_year' in row and int(row['fiscal_year']) != dataset['fiscal_year']:
                        raise ValueError('Provided row fiscal year differs from dataset')
                    item = items[row['budget_item_id']] if items else row
                    if (item.get('fiscal_year') and int(item['fiscal_year']) != dataset['fiscal_year']
                            or item.get('jurisdiction_code') and item['jurisdiction_code'] != code):
                        raise ValueError('Provided budget item belongs to another year or jurisdiction')
                    fund = label(item.get('fund_label', ''))
                    levels = path_levels(item, absent) | path_levels(row, absent)
                    account = proof['accounts'].setdefault(fund, {
                        'original_rows': 0, 'explicit_moku_setsu': True, 'explicit_project_setsu': True,
                        'project_outputs': [], 'setsu_outputs': [], 'amendment_numbers': []})
                    if kind == 'supplementary':
                        account['amendment_numbers'].append(int(row['sequence']))
                    has_project = bool(levels & PROJECT_LEVELS)
                    has_moku = 'moku' in levels
                    has_setsu = 'setsu' in levels
                    # 原典行表は参照用。組合せ/独立内訳の提供粒度は集約表で判定する。
                    if resource != 'settlement_expenditure':
                        account['explicit_moku_setsu'] &= has_moku and has_setsu
                        account['explicit_project_setsu'] &= has_moku and has_project and has_setsu
                        if has_moku and has_project and not has_setsu:
                            account['project_outputs'].append(relative)
                        if has_moku and has_setsu and not has_project:
                            account['setsu_outputs'].append(relative)
                    if resource == 'settlement_expenditure':
                        details = [{'fiscalLineId': row['fiscal_line_id'],
                                    'sourceRow': int(row['source_row']), 'amount': Decimal(row['amount'])}]
                    else:
                        details = json.loads(row['details_json'], parse_float=Decimal)
                        if not details:
                            raise ValueError('Provided row has no original-line details')
                    amount = Decimal(row['amount_delta'] if kind == 'supplementary' else row['amount'])
                    if amount != sum((Decimal(str(d['amount'])) for d in details), Decimal(0)):
                        raise ValueError('Provided amount differs from its original-line details')
                    for detail in details:
                        identity = detail['fiscalLineId']
                        actual = (int(detail['sourceRow']), Decimal(str(detail['amount'])), fund)
                        if kind == 'supplementary' and sequences.get(identity) != int(row['sequence']):
                            raise ValueError('Provided supplementary edition differs from original change')
                        if expected.get(identity) != actual:
                            raise ValueError('Provided original identity, row, amount or account differs')
                        covered[identity] += 1
                        if resource != 'settlement_expenditure':
                            dataset['_phase_lines'][int(detail['sourceRow'])] = {
                                'amount': str(detail['amount']), 'fund': fund,
                                'levels': sorted(levels),
                                'expenditure_setsu_id': item.get('expenditure_setsu_id') or row.get('expenditure_setsu_id')}
                        if resource != 'settlement_expenditure':
                            account['original_rows'] += 1
                if covered != Counter({identity: 1 for identity in expected}):
                    raise ValueError(f'Missing or repeated original rows in {resource}')
            # datasetごとに取得した実ファイルと行を持つ。int登録のみでは到達しない。
            for account in proof['accounts'].values():
                for key in ['project_outputs', 'setsu_outputs', 'amendment_numbers']:
                    account[key] = sorted(set(account[key]))
            proof['complete'] = True
        except (ValueError, KeyError, TypeError, InvalidOperation, duckdb.Error) as error:
            proof['errors'].append(str(error))


def reference_output_coverage(connection, candidate: Path, hashes: dict, dataset: dict) -> None:
    """旧補正の全原典行を参照CSVで照合し、正本の変更への二重収録を拒否する。"""
    proof = dataset['output_coverage']
    relative = f'fiscal/{dataset["jurisdiction_code"]}/supplementary_moku_reference_observations.csv'
    proof['files'].append(relative)
    proof['observation_role'] = 'nonadditive-supplementary-reference'
    if relative not in hashes:
        raise ValueError('Nonadditive reference CSV is not a verified artifact')
    with (candidate / relative).open(newline='') as stream:
        provided = [r for r in csv.DictReader(stream) if r['dataset_id'] == dataset['dataset_id']]
    cursor = connection.execute("select * from stg_132195__budget_history where dataset_id=? and record_kind='change'", [dataset['dataset_id']])
    columns = [c[0] for c in cursor.description]
    # DuckDBのCSV書き出しと同じ型の文字列表現で、全原典列を直接比較する。
    projection = ','.join('cast("' + c.replace('"', '""') + '" as varchar)' for c in columns)
    expected = connection.execute(f"select {projection} from stg_132195__budget_history where dataset_id=? and record_kind='change'", [dataset['dataset_id']]).fetchall()
    original = {r[columns.index('fiscal_line_id')]: dict(zip(columns, r, strict=True)) for r in expected}
    if (len(original) != len(expected) or len(expected) != dataset['line_count']
            or len(provided) != len(expected)
            or len({r['fiscal_line_id'] for r in provided}) != len(provided)):
        raise ValueError('Nonadditive reference does not preserve every original row once')
    declarations = connection.execute('select effective_at,amendment_number from fiscal_datasets where dataset_id=?', [dataset['dataset_id']]).fetchall()
    if len(declarations) != 1:
        raise ValueError('Nonadditive reference edition is ambiguous')
    effective_at, amendment = declarations[0]
    for row in provided:
        raw = original.get(row['fiscal_line_id'])
        if raw is None or any(row.get(c) != (raw[c] or '') for c in columns):
            raise ValueError('Nonadditive reference original cells differ')
        if (row['observation_role'] != 'nonadditive-moku-reference'
                or row['superseded_by_detail'] != 'true'
                or Decimal(row['amount_delta']) != Decimal(raw['delta_amount']) * 1000
                or row['effective_at'] != str(effective_at)
                or int(row['amendment_number']) != int(amendment)):
            raise ValueError('Nonadditive reference amount, role or edition differs')
    if connection.execute('select count(*) from fiscal_expenditure_budget_changes where dataset_id=?', [dataset['dataset_id']]).fetchone()[0]:
        raise ValueError('Superseded reference is also included in canonical changes')
    proof['complete'] = True


def initial_reference_output_coverage(connection, candidate: Path, hashes: dict, dataset: dict) -> None:
    """旧当初二目を全列で保存し、同じ原典行の正本への重複収録を拒否する。"""
    proof = dataset['output_coverage']
    relative = f'fiscal/{dataset["jurisdiction_code"]}/initial_moku_reference.csv'
    proof['files'].append(relative)
    proof['observation_role'] = 'nonadditive-initial-moku-reference'
    if relative not in hashes:
        raise ValueError('Initial reference CSV is not a verified artifact')
    with (candidate / relative).open(newline='') as stream:
        provided = [r for r in csv.DictReader(stream) if r['dataset_id'] == dataset['dataset_id']]
    cursor = connection.execute("select * from stg_132195__budget_history where dataset_id=? and record_kind='initial'", [dataset['dataset_id']])
    columns = [c[0] for c in cursor.description]
    expected = connection.execute("select to_json(s) from stg_132195__budget_history s where dataset_id=? and record_kind='initial'", [dataset['dataset_id']]).fetchall()
    original = {r['fiscal_line_id']: r for value in expected for r in [json.loads(value[0])]}
    if (not original or len(original) != len(expected) or len(expected) != dataset['line_count']
            or len(provided) != len(expected) or len({r['fiscal_line_id'] for r in provided}) != len(provided)):
        raise ValueError('Initial reference does not preserve every original row once')
    source = json.loads(dataset['source_json'])
    if source.get('canonicalInitial') is not False or not source.get('supersededByInitialDetail'):
        raise ValueError('Initial reference declaration does not identify superseded amounts')
    for row in provided:
        raw = original.get(row['fiscal_line_id'])
        observation = json.loads(row['source_observation_json'])
        if raw is None or any(observation.get(c) != raw[c] for c in columns):
            raise ValueError('Initial reference original fields differ')
        if (row['observation_role'] != 'nonadditive-initial-moku-reference'
                or row['superseded_by_full_initial_detail'] != 'true'
                or Decimal(row['amount']) != Decimal(str(raw['initial_amount'])) * 1000
                or observation['budget_item_id'] != row['budget_item_id']
                or Decimal(str(observation['amount_initial'])) != Decimal(row['amount'])):
            raise ValueError('Initial reference amount or nonadditive disposition differs')
        if connection.execute('select count(*) from fiscal_initial_expenditure_budget_lines where fiscal_line_id=?', [row['fiscal_line_id']]).fetchone()[0]:
            raise ValueError('Superseded initial reference is included in authoritative initial lines')
        if connection.execute('''select count(*) from int_132195_initial_detail
            where jurisdiction_code=? and fiscal_year=? and fund_label=?''',
            [dataset['jurisdiction_code'], dataset['fiscal_year'], raw['fund_label']]).fetchone()[0] == 0:
            raise ValueError('Initial reference has no adopted authoritative account detail')
    proof['complete'] = True


def initial_detail_output_coverage(connection, candidate: Path, hashes: dict,
                                   lock_path: Path, datasets: list[dict]) -> None:
    """新しい当初の全原典列・行と、詳細CSVの原典証拠を直接照合する。"""
    registered = {d['dataset_id']: d for d in datasets}
    relative = 'fiscal/132195/initial_expenditure_budget.csv'
    provided = None
    for entry in read_lock(lock_path)['entries']:
        if not entry['path'].startswith(INITIAL_NAMESPACE):
            continue
        identity = ':'.join([entry['jurisdiction'], str(entry['fiscalYear']), 'expenditure',
                             entry['documentKind'], entry['originEdition'], entry_table_id(entry) or ''])
        dataset = registered.get(identity)
        if dataset is None:
            dataset = dict(dataset_id=identity, jurisdiction_code=entry['jurisdiction'], fiscal_year=entry['fiscalYear'],
                           document_kind=entry['documentKind'], origin_sha256=entry['originEdition'],
                           source_json='{}', structure_json='{"funds":[]}', line_count=0, phases_json='[]',
                           output_coverage=dict(complete=False, files=[], accounts={}, errors=[]), _phase_lines={})
            datasets.append(dataset)
        proof = dataset['output_coverage']
        try:
            if identity not in registered or not proof['complete']:
                raise ValueError('Authoritative initial table has no verified registered phase output')
            source = json.loads(dataset['source_json'])
            provenance = json.loads(source_metadata_bytes(lock_path, entry))
            expected_metadata = dict(observationRole='authoritative-initial-detail', canonicalInitial=True,
                url=provenance['request_url'], sha256=entry['originEdition'], tableId=entry_table_id(entry),
                grain=provenance['grain'], fundLabel=provenance['fund_label'], sourceAmountUnit='千円',
                unitMultiplier=1000, 
                 rawTableSha256=entry['table']['sha256'])
            if (entry['jurisdiction'] != '132195' or entry['documentKind'] != 'budget'
                    or entry['direction'] != 'expenditure'
                    or any(source.get(k) != v for k, v in expected_metadata.items())):
                raise ValueError('Authoritative initial registered original identity or grain differs')
            for ref in (entry['origin']['object'], entry['table']):
                verify_object(ref, (OBJECTS / safe_relative(ref['key'])).read_bytes())
            raw_path = OBJECTS / safe_relative(entry['table']['key'])
            cursor = connection.execute('select * from read_parquet(?,hive_partitioning=false)', [str(raw_path)])
            columns = [c[0] for c in cursor.description]
            projection = ','.join('cast("' + c.replace('"', '""') + '" as varchar)' for c in columns)
            raw_rows = connection.execute(f'select {projection} from read_parquet(?,hive_partitioning=false)', [str(raw_path)]).fetchall()
            original = {int(r[columns.index('source_row')]): dict(zip(columns, r, strict=True)) for r in raw_rows}
            actual_rows = connection.execute(f'select {projection} from int_132195_initial_detail where dataset_id=?', [identity]).fetchall()
            actual = {int(r[columns.index('source_row')]): dict(zip(columns, r, strict=True)) for r in actual_rows}
            if (not original or len(original) != len(raw_rows) or len(actual) != len(actual_rows)
                    or original != actual or len(original) != dataset['line_count'] or len(original) != provenance['rows']):
                raise ValueError('Authoritative initial raw columns or original row population differ in intermediate')
            if relative not in hashes:
                raise ValueError('Authoritative initial detail CSV is not a verified artifact')
            if provided is None:
                with (candidate / relative).open(newline='') as stream:
                    provided = list(csv.DictReader(stream))
            selected = [r for r in provided if r['dataset_id'] == identity]
            cursor = connection.execute('select * from csv_132195_initial_expenditure_budget where dataset_id=?', [identity])
            names = [c[0] for c in cursor.description]
            selects = ','.join('cast("' + c.replace('"', '""') + '" as varchar)' for c in names)
            values = connection.execute(f'select {selects} from csv_132195_initial_expenditure_budget where dataset_id=?', [identity]).fetchall()
            expected_csv = {int(r[names.index('source_row')]): dict(zip(names, r, strict=True)) for r in values}
            rows = {int(r['source_row']): r for r in selected}
            if (len(rows) != len(selected) or len(expected_csv) != len(values)
                    or rows.keys() != original.keys() or expected_csv.keys() != original.keys()):
                raise ValueError('Authoritative initial detail CSV repeats or omits original rows')
            scalar_fields = dict(printedSetsuCode='setsu_code', printedSetsuLabel='setsu_label',
                printedDepartment='department_text', printedValue='printed_amount_text', sourceAmountUnit='source_amount_unit',
                printedText='printed_text', approvalDate='approval_date', observedSourceGrain='source_grain',
                observedGrainValidationStatus='observed_grain_validation_status', setsuCorrespondenceStatus='setsu_correspondence_status')
            json_fields = dict(originalMokuControl='control_moku_json', projectEvidence='project_evidence_json',
                sourceLocations='source_locations_json', bbox='bbox_json', leftSetsuEvidence='left_setsu_evidence_json',
                unitEvidence='unit_evidence_json', approvalEvidence='approval_evidence_json')
            for number, raw in original.items():
                row = rows[number]
                if any(row.get(c) != (expected_csv[number][c] or '') for c in names):
                    raise ValueError('Authoritative initial detail CSV field differs from its materialized model')
                details = json.loads(row['details_json'], parse_float=Decimal)
                if (number < 1 or row['fiscal_line_id'] != f'{identity}:{number}' or len(details) != 1
                        or raw['source_amount_unit'] != '千円' or raw['source_url'] != source['url']
                        or raw['origin_sha256'] != entry['originEdition'] or int(raw['fiscal_year']) != entry['fiscalYear']
                        or raw['fund_label'] != provenance['fund_label']
                        or Decimal(row['amount']) != Decimal(raw['amount_initial']) * 1000):
                    raise ValueError('Authoritative initial detail amount, original identity or grain differs')
                detail = details[0]
                if (detail['fiscalLineId'] != row['fiscal_line_id'] or detail['sourceRow'] != number
                        or Decimal(str(detail['amount'])) != Decimal(row['amount'])
                        or detail['page'] != int(raw['page_number'])
                        or detail['projectSourceRow'] != int(raw['project_source_row'])
                        or detail['printedProjectInitial'] != int(raw['project_printed_initial'])
                        or any(detail.get(k) != raw[c] for k, c in scalar_fields.items())
                        or any(detail.get(k) != json.loads(raw[c], parse_float=Decimal) for k, c in json_fields.items())):
                    raise ValueError('Authoritative initial provided original value or positioned evidence differs')
                path = detail['originalPrintedHierarchy']
                for level in ('kan', 'kou', 'moku', 'project'):
                    nodes = [n for n in path if n['level'] == level]
                    if len(nodes) != 1 or nodes[0]['code'] != raw[level + '_code'] or nodes[0]['label'] != raw[level + '_label']:
                        raise ValueError('Authoritative initial printed hierarchy differs in provided evidence')
            proof['files'].append(relative)
            proof['raw_fields_model'] = 'int_132195_initial_detail'
            proof['raw_original_rows'] = len(original)
            proof['fixed_input'] = entry['path']
        except (OSError, ValueError, KeyError, TypeError, InvalidOperation, duckdb.Error) as error:
            proof['complete'] = False
            proof['errors'].append(str(error))


def council_detail_output_coverage(connection, candidate: Path, hashes: dict,
                                   lock_path: Path, datasets: list[dict], *, native: bool = False) -> None:
    """番号付き承認原典の全列・増減・日付・承認証跡を提供CSVまで照合する。"""
    from ingestion.fiscal.council_approved_provider import load_council_approved

    namespace = NATIVE_COUNCIL_NAMESPACE if native else COUNCIL_NAMESPACE
    entries = [e for e in read_lock(lock_path)['entries'] if e['path'].startswith(namespace)]
    if not entries:
        return
    runtime = None
    if native:
        from ingestion.fiscal.native_council_provider import Runtime
        runtime = Runtime()
        runtime.verify_all_objects()
        specs = {s['source_key'].removeprefix(namespace.rstrip('/') + ':'): s for s in runtime.candidates}
    else:
        specs = load_council_approved()
    model = ('int_132195_native_council_expenditure_changes' if native
             else 'int_132195_council_expenditure_changes')
    mart = ('fiscal_132195_native_council_expenditure_budget_changes' if native
            else 'fiscal_132195_council_expenditure_budget_changes')
    registered = {d['dataset_id']: d for d in datasets}
    relative = 'fiscal/132195/expenditure_budget_changes.csv'
    provided = None
    for entry in entries:
        identity = ':'.join([entry['jurisdiction'], str(entry['fiscalYear']), 'expenditure',
                             entry['documentKind'], entry['originEdition'], entry_table_id(entry) or ''])
        dataset = registered.get(identity)
        if dataset is None:
            dataset = dict(dataset_id=identity, jurisdiction_code=entry['jurisdiction'], fiscal_year=entry['fiscalYear'],
                           document_kind=entry['documentKind'], origin_sha256=entry['originEdition'],
                           source_json='{}', structure_json='{"funds":[]}', line_count=0, phases_json='[]',
                           output_coverage=dict(complete=False, files=[], accounts={}, errors=[]), _phase_lines={})
            datasets.append(dataset)
        proof = dataset['output_coverage']
        try:
            if identity not in registered or not proof['complete']:
                raise ValueError('Authoritative council table has no verified registered phase output')
            p = json.loads(source_metadata_bytes(lock_path, entry))
            spec = specs[p['source_key'].removeprefix(namespace.rstrip('/') + ':')]
            source = json.loads(dataset['source_json'])
            reserve_count = spec.get('reserve_exception_rows', 0) if native else spec['reserve_exception_rows']
            approval_proof = spec['approval_proof']
            if native:
                approval_proof = {**approval_proof, 'original_identity_evidence': [
                    e for e in approval_proof['original_identity_evidence']
                    if '上記の議案' in e['observed_text'] or '地方自治法' in e['observed_text']]}
                if not approval_proof['original_identity_evidence'] or not approval_proof['resolution_evidence']:
                    raise ValueError('Native numbered proposal or indexed resolution proof is empty')
            expected_metadata = dict(observationRole=('authoritative-native-council-supplementary-detail' if native
                                                     else 'authoritative-council-supplementary-detail'), canonicalChanges=True,
                url=spec['url'], sha256=entry['originEdition'], tableId=spec['table_id'],
                pages=p['pages'], grain=p['grain'], fundLabel=spec['fund_label'], amendmentNumber=spec['amendment_number'],
                approvalStatus=spec['approval_status'], approvalDate=p['council_resolution_date'],
                councilResolutionDate=p['council_resolution_date'], printedSubmissionDate=p['printed_submission_date'],
                executiveDispositionDate=p['executive_disposition_date'], effectiveDate=p['effective_date'],
                effectiveDateBasis=p['effective_date_basis'], approvalProof=approval_proof,
                sourceAmountUnit='千円', unitMultiplier=1000, reserveExceptionRows=reserve_count,
                  rawTableSha256=entry['table']['sha256'])
            if (entry['jurisdiction'] != '132195' or entry['documentKind'] != 'supplementary'
                    or entry['direction'] != 'expenditure' or entry['fiscalYear'] != spec['fiscal_year']
                    or entry['originEdition'] != spec['expected_sha256']
                    or entry['table']['sha256'] != spec['expected_table_sha256']
                    or p['approval_proof'] != approval_proof
                    or any(source.get(k) != v for k, v in expected_metadata.items())):
                raise ValueError('Authoritative council registered identity, approval or date basis differs')
            if native and (p['frozen_native_page_refs'] != spec['native_page_refs']
                           or p['date_anomaly'] != spec['date_anomaly']
                           or p['visual_ledger_file'] != runtime.data['visual_ledger_file']
                           or p['configured_attachment_pages'] != [spec['first_page'], spec['last_page']]
                           or p['effective_date'] is not None):
                raise ValueError('Native council frozen observations, direct readings or date conflict differ')
            replay = None
            if native:
                from ingestion.fiscal.decode_komae_native_observations import parse
                replay = parse(spec, runtime)
                if (not replay['fully_complete_observed_grain'] or not replay['fully_complete']
                        or replay['parser_problems']):
                    raise ValueError('Native original replay failed whole attachment checks')
                runtime.verify_rows(spec, replay['rows'])
            objects = [entry['origin']['object'], entry['table']]
            for evidence in spec['approval_proof']['original_identity_evidence'] + spec['approval_proof']['resolution_evidence']:
                objects.append(dict(key=evidence['object_key'], sha256=evidence['sha256'], bytes=evidence['bytes']))
            for obj in objects:
                verify_object(obj, (OBJECTS / safe_relative(obj['key'])).read_bytes())
            raw_path = OBJECTS / safe_relative(entry['table']['key'])
            cursor = connection.execute('select * from read_parquet(?,hive_partitioning=false)', [str(raw_path)])
            columns = [c[0] for c in cursor.description]
            projection = ','.join('cast("' + c.replace('"', '""') + '" as varchar)' for c in columns)
            raw_rows = connection.execute(f'select {projection} from read_parquet(?,hive_partitioning=false)', [str(raw_path)]).fetchall()
            original = {int(r[columns.index('source_row')]): dict(zip(columns, r, strict=True)) for r in raw_rows}
            if replay is not None:
                frozen_rows = {int(row['source_row']): {
                    column: None if row[column] is None else str(row[column]) for column in columns
                } for row in replay['rows']}
                if frozen_rows != original:
                    raise ValueError('Native original replay differs from adopted raw fields')
            actual_rows = connection.execute(f'select {projection} from {model} where dataset_id=?', [identity]).fetchall()
            actual = {int(r[columns.index('source_row')]): dict(zip(columns, r, strict=True)) for r in actual_rows}
            if (not original or original != actual or len(original) != len(raw_rows) or len(actual) != len(actual_rows)
                    or len(original) != dataset['line_count'] or len(original) != p['rows']
                    or len(original) != spec['expected_rows']):
                raise ValueError('Authoritative council original columns or row population differ in intermediate')
            invalid_setsu = connection.execute(f'''select count(*) from {model} c
                left join fiscal_expenditure_setsu_master m on c.expenditure_setsu_id=m.expenditure_setsu_id
                where c.dataset_id=? and ((c.setsu_code is not null and
                  (m.expenditure_setsu_id is null or try_cast(m.code as integer)<>try_cast(c.setsu_code as integer)
                   or m.label<>c.full_legal_setsu_label
                   or c.fiscal_year<coalesce(m.valid_from_fiscal_year,-9999)
                   or c.fiscal_year>coalesce(m.valid_to_fiscal_year,9999)))
                  or (c.setsu_code is null and (c.expenditure_setsu_id is not null or c.moku_label<>'予備費')))''',
                [identity]).fetchone()[0]
            reserve_rows = sum(r['setsu_code'] is None for r in original.values())
            if invalid_setsu or reserve_rows != reserve_count:
                raise ValueError('Authoritative council statutory code/name/year or printed reserve exception differs')
            if native:
                invalid_baseline = connection.execute(f'''select count(*) from {model} c
                    left join int_132195_initial_detail i
                      on c.target_identity_json=i.supplementary_compatibility_identity_json
                    left join (
                      select distinct target_identity_json,budget_item_id from int_supplementary_expenditure_changes
                      union select distinct target_identity_json,budget_item_id from int_132195_council_expenditure_changes
                    ) e on c.target_identity_json=e.target_identity_json
                    where c.dataset_id=? and
                    ((i.fiscal_line_id is not null and (c.budget_item_id<>i.budget_item_id
                        or c.exact_initial_fiscal_line_id is distinct from i.fiscal_line_id
                        or c.exact_initial_compatibility_identity_json is distinct from i.supplementary_compatibility_identity_json
                        or c.initial_state<>'recorded'))
                     or (i.fiscal_line_id is null and (c.exact_initial_fiscal_line_id is not null
                        or c.initial_state<>'unconfirmed'
                        or (e.budget_item_id is not null and (c.budget_item_id<>e.budget_item_id
                          or c.exact_existing_target_identity_json is distinct from e.target_identity_json
                          or c.exact_existing_fiscal_line_id is null))
                        or (e.budget_item_id is null and (c.budget_item_id<>c.native_namespace_budget_item_id
                          or c.exact_existing_target_identity_json is not null
                          or c.exact_existing_fiscal_line_id is not null)))))''', [identity]).fetchone()[0]
                invalid_existing = connection.execute(f'''select count(*) from {model} c
                    left join (
                      select target_identity_json,budget_item_id,fiscal_line_id from int_supplementary_expenditure_changes
                      union all select target_identity_json,budget_item_id,fiscal_line_id from int_132195_council_expenditure_changes
                    ) e on c.exact_existing_fiscal_line_id=e.fiscal_line_id
                    where c.dataset_id=? and c.exact_existing_fiscal_line_id is not null and
                      (e.fiscal_line_id is null or c.target_identity_json<>e.target_identity_json
                       or c.budget_item_id<>e.budget_item_id)''', [identity]).fetchone()[0]
                invalid_baseline += invalid_existing
            else:
                invalid_baseline = connection.execute('''select count(*) from int_132195_council_expenditure_changes c
                left join int_132195_initial_detail i
                  on c.target_identity_json=i.supplementary_compatibility_identity_json
                where c.dataset_id=? and
                ((i.fiscal_line_id is not null and (c.budget_item_id<>i.budget_item_id
                    or c.exact_initial_fiscal_line_id is distinct from i.fiscal_line_id or c.initial_state<>'recorded'))
                 or (i.fiscal_line_id is null and (c.budget_item_id<>c.council_namespace_budget_item_id
                    or c.exact_initial_fiscal_line_id is not null or c.initial_state<>'unconfirmed')))''',
                [identity]).fetchone()[0]
            if invalid_baseline:
                raise ValueError('Authoritative council baseline identity is not the exact initial correspondence')
            typed = connection.execute('select to_json(r) from read_parquet(?,hive_partitioning=false) r', [str(raw_path)]).fetchall()
            original_json = {r['source_row']: r for value in typed for r in [json.loads(value[0], parse_float=Decimal)]}
            if runtime is not None:
                runtime.verify_rows(spec, list(original_json.values()))
            if relative not in hashes:
                raise ValueError('Authoritative council change CSV is not a verified artifact')
            if provided is None:
                with (candidate / relative).open(newline='') as stream:
                    provided = list(csv.DictReader(stream))
            selected = [r for r in provided if r['dataset_id'] == identity]
            cursor = connection.execute(f'select * from {mart} where dataset_id=?', [identity])
            names = [c[0] for c in cursor.description]
            selects = ','.join('cast("' + c.replace('"', '""') + '" as varchar)' for c in names)
            values = connection.execute(f'select {selects} from {mart} where dataset_id=?', [identity]).fetchall()
            expected_csv = {int(r[names.index('source_row')]): dict(zip(names, r, strict=True)) for r in values}
            rows = {int(r['source_row']): r for r in selected}
            if (len(rows) != len(selected) or len(expected_csv) != len(values)
                    or rows.keys() != original.keys() or expected_csv.keys() != original.keys()):
                raise ValueError('Authoritative council change CSV repeats or omits original rows')
            for number, raw in original.items():
                row = rows[number]
                details = json.loads(row['details_json'], parse_float=Decimal)
                if (number < 1 or any(row.get(c) != (expected_csv[number][c] or '') for c in names)
                        or len(details) != 1 or details[0].get('rawSource') != original_json[number]
                        or details[0]['fiscalLineId'] != f'{identity}:{number}'
                        or row['change_id'] != 'c-' + digest(f'{identity}:{number}'.encode())
                        or Decimal(row['amount_delta']) != Decimal(raw['amount_delta']) * 1000
                        or row['effective_at'] != (raw['effective_date'] or '')
                        or int(row['sequence']) != spec['amendment_number']
                        or raw['source_url'] != spec['url'] or raw['origin_sha256'] != entry['originEdition']
                        or int(raw['fiscal_year']) != spec['fiscal_year'] or raw['fund_label'] != spec['fund_label']
                        or raw['source_amount_unit'] != '千円'
                        or json.loads(raw['approval_proof_json']) != approval_proof):
                    raise ValueError('Authoritative council provided original fields, signed amount or dates differ')
            proof['raw_fields_model'] = model
            proof['raw_original_rows'] = len(original)
            proof['fixed_input'] = entry['path']
        except (OSError, ValueError, KeyError, TypeError, InvalidOperation, duckdb.Error) as error:
            proof['complete'] = False
            proof['errors'].append(str(error))


def entry_table_id(entry: dict) -> str | None:
    parts = [part.split('=', 1)[1] for part in entry['path'].split('/')
             if part.startswith('table=')
             or (entry['path'].startswith(INITIAL_NAMESPACE) and part.startswith('resource='))]
    if len(parts) > 1:
        raise ValueError('Adopted table/resource identity is ambiguous')
    return parts[0] if parts else None


def side_output_coverage(connection, candidate: Path, hashes: dict,
                         lock_path: Path, datasets: list[dict]) -> None:
    """独立した目×節はint_fiscal_linesへ結合せず、採用Parquetと提供CSVを直接照合する。"""
    entries = [e for e in read_lock(lock_path)['entries'] if e['path'].startswith(SIDE_NAMESPACE)]
    if not entries and SIDE_RESOURCE not in hashes:
        return
    provided = []
    if SIDE_RESOURCE in hashes:
        with (candidate / SIDE_RESOURCE).open(newline='') as stream:
            provided = list(csv.DictReader(stream))
    adopted_ids = {':'.join([e['jurisdiction'], str(e['fiscalYear']), 'expenditure',
                            e['documentKind'], e['originEdition'], entry_table_id(e) or ''])
                   for e in entries}
    unexpected = {r.get('dataset_id') for r in provided} - adopted_ids
    if not entries and unexpected:
        raise ValueError('Provided independent moku/setsu CSV contains no adopted side inputs')
    explanation = {d['dataset_id']: d for d in datasets}
    checked_objects = set()

    def checked_object(ref: dict) -> Path:
        path = OBJECTS / safe_relative(ref['key'])
        identity = (ref['key'], ref['sha256'], ref['bytes'])
        if identity not in checked_objects:
            verify_object(ref, path.read_bytes())
            checked_objects.add(identity)
        return path

    def bbox(value: str) -> list:
        parsed = json.loads(value, parse_float=Decimal)
        if (not isinstance(parsed, list) or len(parsed) != 4
                or any(not Decimal(str(v)).is_finite() for v in parsed)):
            raise ValueError('Independent row has no finite original bounding box')
        return parsed

    for entry in entries:
        provenance = json.loads(source_metadata_bytes(lock_path, entry))
        table = entry_table_id(entry)
        dataset_id = ':'.join([entry['jurisdiction'], str(entry['fiscalYear']), 'expenditure',
                               entry['documentKind'], entry['originEdition'], table or ''])
        fund = provenance.get('fund_label', '')
        proof = {'complete': False, 'files': [SIDE_RESOURCE], 'accounts': {}, 'errors': [],
                 'fixed_input': entry['path'], 'table_sha256': entry['table']['sha256'],
                 
                 'origin_sha256': entry['originEdition']}
        source = {'url': provenance['request_url'], 'sha256': entry['originEdition'],
                  'tableId': table, 'observationRole': provenance.get('observation_role'),
                  'grain': provenance.get('grain'), 'pages': provenance.get('pages'),
                  'explanationDatasetId': provenance.get('explanation_dataset_id')}
        side = {'dataset_id': dataset_id, 'jurisdiction_code': entry['jurisdiction'],
                'fiscal_year': entry['fiscalYear'], 'document_kind': entry['documentKind'],
                'origin_sha256': entry['originEdition'], 'source_json': json.dumps(source),
                'structure_json': json.dumps({'funds': [{'code': '', 'label': fund}],
                                              'hierarchy': ['fund', 'kan', 'kou', 'moku', 'setsu']}),
                'line_count': provenance.get('rows'), 'phases_json': '["approved"]',
                'output_coverage': proof}
        datasets.append(side)
        try:
            if (entry['jurisdiction'] != '131016' or entry['documentKind'] != 'budget'
                    or entry['direction'] != 'expenditure' or not table
                    or provenance.get('table_id') != table
                    or provenance.get('observation_role') != 'independent-moku-setsu'
                    or provenance.get('grain') != 'document-fund-moku-printed-setsu-row'
                    or provenance.get('project_setsu_linkage') != 'unconfirmed'
                    or not fund):
                raise ValueError('Adopted independent input identity or original grain is not confirmed')
            parent = explanation.get(source['explanationDatasetId'])
            if (not parent or parent['jurisdiction_code'] != entry['jurisdiction']
                    or parent['fiscal_year'] != entry['fiscalYear']
                    or parent['document_kind'] != entry['documentKind']
                    or parent['origin_sha256'] != entry['originEdition']
                    or json.loads(parent['source_json'])['url'] != provenance['request_url']
                    or label(fund) not in parent['output_coverage']['accounts']):
                raise ValueError('Independent row explanation dataset does not match the same original/account/edition')
            if SIDE_RESOURCE not in hashes:
                raise ValueError('Independent moku/setsu CSV is not a verified artifact')
            if unexpected:
                raise ValueError('Provided independent CSV contains unadopted datasets')
            checked_object(entry['origin']['object'])
            table_path = checked_object(entry['table'])
            cursor = connection.execute('select * from read_parquet(?, hive_partitioning=false)', [str(table_path)])
            fields = [c[0] for c in cursor.description]
            raw_rows = [dict(zip(fields, values, strict=True)) for values in cursor.fetchall()]
            actual_rows = [r for r in provided if r['dataset_id'] == dataset_id]
            raw = {int(r['source_row']): r for r in raw_rows}
            actual = {int(r['source_row']): r for r in actual_rows}
            if (not raw or len(raw) != len(raw_rows) or len(actual) != len(actual_rows)
                    or set(raw) != set(actual) or len(raw) != provenance['rows']):
                raise ValueError('Independent original rows are missing, repeated or differ from adopted count')
            if any(row['reconciled'] is not True for row in raw_rows):
                raise ValueError('Independent original rows contain an unreconciled printed moku total')
            mappings = {'会計名称': 'fund_label', '款': 'kan_code', '款名称': 'kan_label',
                        '項': 'kou_code', '項名称': 'kou_label', '目': 'moku_code', '目名称': 'moku_label',
                        '節': 'setsu_code', '節名称': 'setsu_label', 'source_table_id': 'source_table_id',
                        'source_amount_unit': 'source_amount_unit'}
            for number, original in raw.items():
                row = actual[number]
                if (number < 1 or row['observation_id'] != f'{dataset_id}:{number}'
                        or row['explanation_dataset_id'] != source['explanationDatasetId']
                        or row['jurisdiction_code'] != entry['jurisdiction']
                        or int(row['fiscal_year']) != entry['fiscalYear']
                        or int(original['source_fiscal_year']) != entry['fiscalYear']
                        or row['document_kind'] != 'budget' or row['phase'] != 'approved'
                        or row['origin_sha256'] != entry['originEdition']
                        or row['line_granularity'] != 'independent-moku-setsu'
                        or row['project_setsu_linkage'] != 'unconfirmed'
                        or original['事業名'] or original['内訳名称']):
                    raise ValueError('Independent observation identity/phase/linkage differs or invents a project association')
                if any(str(original[k]) != row[v] for k, v in mappings.items()):
                    raise ValueError('Independent hierarchy labels/codes or original amount unit differ')
                if (original['会計名称'] != fund or original['source_table_id'] != table
                        or original['source_amount_unit'] != provenance['source_amount_unit']
                        or original['source_amount_unit'] != '千円' or not original['目']
                        or not original['節'] or not original['節名称']):
                    raise ValueError('Independent original account/table/unit/moku/printed setsu is not confirmed')
                amount = Decimal(str(original['本年度予算額']))
                if Decimal(row['source_amount']) != amount or Decimal(row['amount']) != amount * 1000:
                    raise ValueError('Independent original amount or declared unit conversion differs')
                if (int(original['source_page']) < 1 or int(row['source_page']) != int(original['source_page'])
                        or bbox(row['source_bbox']) != bbox(original['source_bbox'])
                        or original['reconciled'] is not True or row['reconciled'].lower() != 'true'):
                    raise ValueError('Independent original location/reconciliation differs')
                metadata = json.loads(row['source_json'])
                if any(metadata.get(k) != v for k, v in source.items()):
                    raise ValueError('Independent provided provenance metadata differs')
            proof['accounts'][label(fund)] = {
                'original_rows': len(raw), 'explicit_moku_setsu': True,
                'explicit_project_setsu': False, 'project_outputs': [],
                'setsu_outputs': [SIDE_RESOURCE], 'amendment_numbers': []}
            proof['moku_without_printed_setsu'] = provenance.get('moku_without_printed_setsu', [])
            proof['complete'] = True
        except (OSError, ValueError, KeyError, TypeError, InvalidOperation, duckdb.Error) as error:
            proof['errors'].append(str(error))


def settlement_pdf_output_coverage(connection, candidate: Path, hashes: dict,
                                   lock_path: Path, datasets: list[dict]) -> None:
    """決算の独立明細と非加算観測を、採用表の全列・全行と直接照合する。"""
    entries = [e for e in read_lock(lock_path)['entries'] if e['path'].startswith(SETTLEMENT_NAMESPACE)]
    registered = {d['dataset_id']: d for d in datasets}
    by_role = {}
    for entry in entries:
        provenance = json.loads(source_metadata_bytes(lock_path, entry))
        identity = ':'.join([entry['jurisdiction'], str(entry['fiscalYear']), 'expenditure',
                             entry['documentKind'], entry['originEdition'], entry_table_id(entry) or ''])
        by_role.setdefault(provenance['observation_role'], set()).add(identity)
    provided_cache = {}
    for entry in entries:
        provenance = json.loads(source_metadata_bytes(lock_path, entry))
        table = entry_table_id(entry)
        identity = ':'.join([entry['jurisdiction'], str(entry['fiscalYear']), 'expenditure',
                             entry['documentKind'], entry['originEdition'], table or ''])
        role = provenance['observation_role']
        dataset = registered.get(identity)
        if dataset is None:
            # 未登録の採用入力も欠落として出す。監査内で登録済みへ昇格させない。
            dataset = dict(dataset_id=identity, jurisdiction_code=entry['jurisdiction'], fiscal_year=entry['fiscalYear'],
                           document_kind=entry['documentKind'], origin_sha256=entry['originEdition'],
                           source_json=json.dumps(dict(url=provenance['request_url'], tableId=table, observationRole=role)),
                           structure_json=json.dumps(dict(funds=[])), line_count=provenance['rows'], phases_json='[]')
            datasets.append(dataset)
        proof = {'complete': False, 'files': [], 'accounts': {}, 'errors': [],
                 'fixed_input': entry['path'], 'observation_role': role,
                 'table_sha256': entry['table']['sha256'], 'origin_sha256': entry['originEdition'],
                 }
        dataset['output_coverage'] = proof
        dataset['_phase_lines'] = {}
        try:
            if identity not in registered:
                raise ValueError('Adopted settlement table is missing from the actual dataset registry')
            if (entry['jurisdiction'] != '132241' or entry['documentKind'] != 'settlement'
                    or entry['direction'] != 'expenditure' or table != provenance['table_id']
                    or role not in SETTLEMENT_ROLES):
                raise ValueError('Independent settlement input identity or role differs')
            suffix, grain = SETTLEMENT_ROLES[role]
            financial = role in ('legal-setsu', 'project-funding')
            source = json.loads(dataset['source_json'])
            expected_source = dict(url=provenance['request_url'], sha256=entry['originEdition'], tableId=table,
                                   observationRole=role, grain=grain, independentBreakdown=True,
                                   additiveWithinOwnGrain=financial, rawTableSha256=entry['table']['sha256'],
                                   )
            if role != 'source-words':
                expected_source.update(sourceAmountUnit=provenance['source_amount_unit'], unitMultiplier=provenance['unit_multiplier'])
            if any(source.get(k) != value for k, value in expected_source.items()):
                raise ValueError('Independent settlement registered provenance or grain differs')
            for ref in (entry['origin']['object'], entry['table']):
                verify_object(ref, (OBJECTS / safe_relative(ref['key'])).read_bytes())
            table_path = OBJECTS / safe_relative(entry['table']['key'])
            cursor = connection.execute('select * from read_parquet(?,hive_partitioning=false)', [str(table_path)])
            columns = [c[0] for c in cursor.description]
            projection = ','.join('cast("' + c.replace('"', '""') + '" as varchar)' for c in columns)
            raw_rows = connection.execute(f'select {projection} from read_parquet(?,hive_partitioning=false)', [str(table_path)]).fetchall()
            original = {int(r[columns.index('source_row')]): dict(zip(columns, r, strict=True)) for r in raw_rows}
            if not original or len(original) != len(raw_rows) or len(original) != provenance['rows'] or len(original) != dataset['line_count']:
                raise ValueError('Independent settlement original row identities or registered count differ')
            relative = f'fiscal/132241/settlement_expenditure_pdf_{suffix}.csv'
            if role == 'source-words':
                # 原典の位置付き単語は内部marts。金額段階の提供CSVとは区別する。
                model = 'fiscal_132241_settlement_pdf_source_words'
                cursor = connection.execute(f'select * from {model} where dataset_id=?', [identity])
                names = [c[0] for c in cursor.description]
                selects = ','.join('cast("' + c.replace('"', '""') + '" as varchar)' for c in names)
                values = connection.execute(f'select {selects} from {model} where dataset_id=?', [identity]).fetchall()
                provided = [dict(zip(names, r, strict=True)) for r in values]
                proof['warehouse_model'] = model
            else:
                if relative not in hashes:
                    raise ValueError('Independent settlement CSV is not a verified artifact')
                if relative not in provided_cache:
                    with (candidate / relative).open(newline='') as stream:
                        provided_cache[relative] = list(csv.DictReader(stream))
                all_rows = provided_cache[relative]
                if {r['dataset_id'] for r in all_rows} - by_role[role]:
                    raise ValueError('Independent settlement CSV contains unadopted datasets')
                provided = [r for r in all_rows if r['dataset_id'] == identity]
                proof['files'].append(relative)
            actual = {int(r['source_row']): r for r in provided}
            if len(actual) != len(provided) or set(actual) != set(original):
                raise ValueError('Independent settlement original rows are missing or repeated in marts')
            for number, raw in original.items():
                row = actual[number]
                if any((row.get(c) or '') != (raw[c] or '') for c in columns):
                    raise ValueError('Independent settlement original field, value or position differs')
                if (number < 1 or row['dataset_id'] != identity or row['fiscal_line_id'] != f'{identity}:{number}'
                        or raw['jurisdiction_code'] != '132241' or int(raw['fiscal_year']) != entry['fiscalYear']
                        or raw['origin_sha256'] != entry['originEdition'] or raw['table_id'] != table
                        or raw['observation_role'] != role or raw['grain'] != grain
                        or row['line_granularity'] != grain or row['project_setsu_linkage'] != 'unconfirmed'
                        or row['additive_within_own_grain'] != str(financial).lower()):
                    raise ValueError('Independent settlement identity, grain or additivity differs')
                if json.loads(row['source_json']) != source:
                    raise ValueError('Independent settlement provided metadata differs from registry')
                if role == 'source-words':
                    if raw['source_amount'] is not None or raw['source_amount_unit'] is not None or raw['unit_multiplier'] is not None:
                        raise ValueError('Positioned source words acquired synthetic monetary values')
                    continue
                amount, multiplier = Decimal(raw['source_amount']), Decimal(raw['unit_multiplier'])
                if (raw['phase'] != 'executed' or row['currency'] != 'JPY'
                        or raw['source_amount_unit'] != provenance['source_amount_unit']
                        or multiplier != Decimal(str(provenance['unit_multiplier']))
                        or (raw['source_amount_unit'], multiplier) not in (('円', Decimal(1)), ('千円', Decimal(1000)))
                        or Decimal(row['amount']) != amount * multiplier):
                    raise ValueError('Independent settlement phase, original unit or converted amount differs')
                if not financial:
                    continue
                fund = label(raw['fund_label'])
                has_moku = all(raw[c] for c in ('kan', 'kou', 'moku'))
                if role == 'legal-setsu' and (not has_moku or not raw['setsu_code'] or not raw['setsu_label'] or raw['funding_code']):
                    raise ValueError('Legal settlement row lacks its printed hierarchy/setsu or acquired funding grain')
                if role == 'project-funding' and (not has_moku or not raw['project_code'] or raw['funding_code'] not in ('1', '2', '3', '4', '5') or raw['setsu_code']):
                    raise ValueError('Funding settlement row lacks project/funding or acquired synthetic legal setsu')
                account = proof['accounts'].setdefault(fund, dict(original_rows=0, explicit_moku_setsu=role == 'legal-setsu',
                    explicit_project_setsu=False, project_outputs=[relative] if role == 'project-funding' else [],
                    setsu_outputs=[relative] if role == 'legal-setsu' else [], amendment_numbers=[]))
                account['original_rows'] += 1
                levels = ['kan', 'kou', 'moku', 'setsu' if role == 'legal-setsu' else 'project']
                dataset['_phase_lines'][number] = dict(amount=str(amount * multiplier), fund=fund, levels=levels,
                                                      expenditure_setsu_id=row.get('expenditure_setsu_id'))
            proof['original_rows'] = len(original)
            proof['complete'] = True
        except (OSError, ValueError, KeyError, TypeError, InvalidOperation, duckdb.Error) as error:
            proof['errors'].append(str(error))


def checked_datasets(lock_path: Path, warehouse: Path) -> tuple[list[dict], str]:
    """全量buildの証明と現行コード・入力の一致がある場合だけDBを読む。"""
    if not warehouse.exists():
        return [], 'warehouse_missing'
    latest_path = warehouse.parent / 'latest.json'
    marker_path = warehouse.parent / 'warehouse.json'
    if not latest_path.exists() or not marker_path.exists():
        return [], 'build_evidence_missing'
    latest = json.loads(latest_path.read_text())
    marker = json.loads(marker_path.read_text())
    if latest['buildId'] != marker['buildId']:
        return [], 'warehouse_build_mismatch'
    current = subprocess.run(
        ['bun', '-e', 'import {buildIdentity} from "./pipeline/identity.ts"; console.log(JSON.stringify(await buildIdentity()))'],
        cwd=REPO, env={**os.environ, 'FUDOKI_INPUT_LOCK': str(lock_path.resolve())},
        check=True, capture_output=True, text=True)
    identity = json.loads(current.stdout)
    if latest['buildId'] != identity['buildId']:
        return [], 'build_is_stale'
    candidate = warehouse.parent / 'builds' / safe_relative(identity['buildId'])
    verification_path = candidate / 'verification.json'
    if not verification_path.exists():
        return [], 'artifact_verification_missing'
    verification = json.loads(verification_path.read_text())
    if any(verification.get(k) != v for k, v in identity.items()):
        return [], 'artifact_identity_mismatch'
    expected = verification['files']
    actual = {str(p.relative_to(candidate)) for p in candidate.rglob('*.csv')}
    if actual != set(expected):
        return [], 'artifact_inventory_mismatch'
    for relative, sha256 in expected.items():
        if digest((candidate / safe_relative(relative)).read_bytes()) != sha256:
            return [], 'artifact_hash_mismatch'
    connection = duckdb.connect(str(warehouse), read_only=True)
    try:
        cursor = connection.execute('''select dataset_id, jurisdiction_code, fiscal_year,
            document_kind, origin_sha256, structure_json, source_json, phases_json, line_count
            from int_fiscal_datasets where direction='expenditure'
            and coalesce(json_extract_string(source_json, '$.observationRole'), '') != 'independent-moku-setsu'
            order by dataset_id''')
        fields = [c[0] for c in cursor.description]
        datasets = [dict(zip(fields, values, strict=True)) for values in cursor.fetchall()]
        output_coverage(connection, candidate, expected, datasets)
        initial_detail_output_coverage(connection, candidate, expected, lock_path, datasets)
        council_detail_output_coverage(connection, candidate, expected, lock_path, datasets)
        council_detail_output_coverage(connection, candidate, expected, lock_path, datasets, native=True)
        side_output_coverage(connection, candidate, expected, lock_path, datasets)
        settlement_pdf_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.native_settlement_coverage import output_coverage as native_settlement_output_coverage
        native_settlement_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.initial445_coverage import output_coverage as initial445_output_coverage
        initial445_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.tama_initial_native_coverage import output_coverage as tama_initial_native_output_coverage
        tama_initial_native_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.chiyoda_supplementary_native_coverage import output_coverage as chiyoda_supplementary_native_output_coverage
        chiyoda_supplementary_native_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.tama_supplementary_native_coverage import output_coverage as tama_supplementary_native_output_coverage
        tama_supplementary_native_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.held5_coverage import output_coverage as held5_output_coverage
        held5_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.settlement2024_coverage import output_coverage as settlement2024_output_coverage
        settlement2024_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.settlement2019_coverage import output_coverage as settlement2019_output_coverage
        settlement2019_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.settlement2020_2023_coverage import output_coverage as settlement2020_2023_output_coverage
        settlement2020_2023_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.supplementary_fy2025_01_coverage import output_coverage as supplementary_fy2025_01_output_coverage
        supplementary_fy2025_01_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.tama_pre2020_coverage import output_coverage as pre2020_output_coverage
        pre2020_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.komae_recovered_coverage import output_coverage as komae_recovered_output_coverage
        komae_recovered_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.komae_supplementary_2020_1_coverage import output_coverage as supplementary1_output_coverage
        supplementary1_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.chiyoda2025_native_coverage import output_coverage as chiyoda2025_output_coverage
        chiyoda2025_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.chiyoda2021_settlement_coverage import output_coverage as chiyoda2021_settle_coverage
        chiyoda2021_settle_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.mitaka_initial2026.coverage import output_coverage as mitaka_output_coverage
        mitaka_output_coverage(connection, candidate, expected, lock_path, datasets)
        from ingestion.fiscal.tama_ordinary_history_coverage import output_coverage as ordinary_output_coverage
        ordinary_output_coverage(connection,candidate,expected,lock_path,datasets)
    finally:
        connection.close()
    return datasets, 'verified_current_build'


def scope_key(edition: dict) -> tuple:
    return (edition['fiscal_year'], label(edition['account_label']),
            edition['document_phase'], edition['amendment_number'])


def evidence_backed(scope: dict) -> bool:
    return bool(scope.get('basis', '').strip() and scope.get('evidence_urls'))


def grain_reasons(source: dict, matching: list[dict], account_label: str) -> list[str]:
    grain = source['content_grain']
    reasons = []
    if grain['status'] != 'observed' or not grain['observed_levels']:
        reasons.append('content_grain_not_observed')
    if not any(v == 'setsu' or '節' in v for v in grain['observed_levels']):
        reasons.append('setsu_grain_not_observed')
    if not any(v == 'moku' or '目' in v for v in grain['observed_levels']):
        reasons.append('moku_grain_not_observed')
    relation = grain['project_setsu_relation']
    if relation == 'unconfirmed' or not grain['relation_evidence']:
        reasons.append('project_setsu_relation_without_evidence')
    accounts = [d['output_coverage']['accounts'].get(label(account_label), {}) for d in matching]
    if relation == 'confirmed_explicit':
        project_observed = any('事業' in v or v in PROJECT_LEVELS or v == 'project' or '事項' in v or '細目' in v
                               for v in grain['observed_levels'])
        field = 'explicit_project_setsu' if project_observed else 'explicit_moku_setsu'
        if not accounts or not all(a.get(field, False) for a in accounts):
            reasons.append('explicit_relation_not_preserved_in_phase_output')
    elif relation == 'independent_breakdowns':
        # 一つの原典の別datasetとして両独立表を提供できる。CSV内でもdatasetを混ぜない。
        projects = {d['dataset_id'] for d, a in zip(matching, accounts, strict=True)
                    if a.get('project_outputs')}
        setsu = {d['dataset_id'] for d, a in zip(matching, accounts, strict=True)
                 if a.get('setsu_outputs')}
        side_sets = [d for d in matching if d['dataset_id'] in setsu
                     and json.loads(d['source_json']).get('observationRole') == 'independent-moku-setsu']
        if any(json.loads(d['source_json']).get('explanationDatasetId') not in projects for d in side_sets):
            reasons.append('independent_side_table_explanation_reference_not_verified')
        if not projects or not setsu or projects & setsu:
            reasons.append('independent_project_and_setsu_outputs_not_both_preserved')
    return reasons


def source_input_fingerprint(entries: list[dict]) -> str:
    """同一原典の全固定入力と意味の宣言を、循環するコード参照を除いて固定する。"""
    inputs = [{**entry, 'source': {key: value for key, value in entry['source'].items()
                                  if key not in {'definition_files', 'source_manifest_sha256'}}}
              for entry in sorted(entries, key=lambda entry: entry['path'])]
    return digest(encode({'schema_version': 1, 'source_inputs': inputs}))


def proof_binding_matches(proof: dict, entries: list[dict], lock_sha: str) -> bool:
    if 'input_fingerprint' in proof:
        return bool(entries) and proof['input_fingerprint'] == source_input_fingerprint(entries)
    return proof.get('lock_sha256') == lock_sha


def published_grain_reasons(source: dict, edition: dict, matching: list[dict],
                            entries: list[dict], provenance: dict, lock_path: Path,
                            lock_sha: str, styles: dict) -> list[str]:
    """人が全原典で確認した欠如を、採用表全行と当該phaseの実CSVで限定して照合する。"""
    proof = edition['published_grain_exception']
    evidence = source['content_inspection']['evidence']
    row_scoped = any(p.get('row_exceptions') for p in proof['preservation'])
    # 全行を既に直接照合した当初明細では、印字節欄が空の予備費だけを例外にできる。
    # 独立内訳や参照表をこの行例外へ読み替えることは認めない。
    initial_row_scoped = (row_scoped and edition['document_phase'] == 'initial'
                          and bool(matching)
                          and all(d['document_kind'] == 'budget'
                                  and json.loads(d['source_json']).get('observationRole') == 'authoritative-initial-detail'
                                  and json.loads(d['source_json']).get('canonicalInitial') is True
                                  and d['output_coverage']['complete'] for d in matching))
    allowed_roles = ({'authoritative-initial-detail', 'nonadditive-initial-moku-reference', None, ''}
                     if initial_row_scoped else {None, ''})

    def backed(item: dict) -> bool:
        return bool(item['basis'].strip() and item['evidence_indices']
                    and all(0 <= i < len(evidence) and evidence[i]['text'].strip()
                            for i in item['evidence_indices']))

    reasons = []
    if (proof['origin_sha256'] != source['content_inspection'].get('sha256')
            or not proof_binding_matches(proof, entries, lock_sha)
            or any(proof[k] != edition[k] for k in
                   ['fiscal_year', 'account_label', 'document_phase', 'amendment_number'])
            or source['content_grain']['status'] != 'observed'
            or not backed(proof['whole_original_inspection'])):
        reasons.append('published_grain_original_identity_or_whole_inspection_missing')
    inspection = proof['whole_original_inspection']
    if source['format'] == 'pdf':
        pages = source['content_inspection'].get('pages')
        observed_pages = {evidence[i]['page'] for i in inspection['evidence_indices']
                          if 0 <= i < len(evidence)}
        if (inspection['method'] != 'pdf_all_pages' or not pages
                or inspection['page_count'] != pages or inspection['row_count'] is not None
                or observed_pages != set(range(1, pages + 1))):
            reasons.append('published_grain_all_pdf_pages_not_inspected')
    elif (source['format'] != 'csv' or inspection['method'] != 'csv_all_rows'
          or not inspection['row_count'] or inspection['page_count'] is not None):
        reasons.append('published_grain_all_csv_rows_not_inspected')
    absent = {a['dimension'] for a in proof['absent_dimensions']}
    if ('project_setsu_relation' not in absent
            or len(absent) != len(proof['absent_dimensions'])
            or not all(backed(a) for a in proof['absent_dimensions'])):
        reasons.append('published_grain_printed_absence_without_evidence')
    if (source['content_grain']['project_setsu_relation'] != 'unconfirmed'
            or any(json.loads(d['source_json']).get('observationRole') not in allowed_roles for d in matching)
            or any(provenance[e['path']].get('observation_role') not in allowed_roles
                   and label(provenance[e['path']].get('fund_label', edition['account_label'])) == label(edition['account_label'])
                   for e in entries)):
        reasons.append('published_grain_cannot_replace_explicit_or_independent_breakdowns')
    if edition['document_phase'] == 'supplementary':
        if not proof.get('approval') or not backed(proof['approval']):
            reasons.append('published_grain_supplementary_approval_not_confirmed')
    ids = {d['dataset_id'] for d in matching}
    rows_proofs = proof['preservation']
    if (not ids or set(proof['dataset_ids']) != ids
            or {p['dataset_id'] for p in rows_proofs} != ids
            or len(rows_proofs) != len(ids)):
        reasons.append('published_grain_verified_dataset_set_mismatch')
    if reasons:
        return reasons
    by_id = {d['dataset_id']: d for d in matching}
    connection = duckdb.connect()
    try:
        for row_proof in rows_proofs:
            dataset = by_id[row_proof['dataset_id']]
            selected = [e for e in entries if e['path'] == row_proof['fixed_input_path']]
            if len(selected) != 1:
                raise ValueError('Published-grain input is not uniquely in the current lock')
            entry = selected[0]
            p = provenance[entry['path']]
            authoritative_initial = (initial_row_scoped and entry['path'].startswith(INITIAL_NAMESPACE)
                                     and entry['documentKind'] == 'budget'
                                     and p.get('observation_role') == 'authoritative-initial-detail'
                                     and p.get('approval_status') == 'cover-approved'
                                     and bool(p.get('approval_date'))
                                     and bool(row_proof.get('row_exceptions')))
            identity = ':'.join([entry['jurisdiction'], str(entry['fiscalYear']), 'expenditure',
                                  entry['documentKind'], entry['originEdition'],
                                  *([entry_table_id(entry)] if entry_table_id(entry) else [])])
            if (identity != dataset['dataset_id'] or entry['direction'] != 'expenditure'
                    or entry['originEdition'] != proof['origin_sha256']
                    or row_proof['phase'] != {'budget': 'approved', 'supplementary': 'delta', 'settlement': 'executed'}[entry['documentKind']]
                    or entry['path'].startswith(SIDE_NAMESPACE)
                    or (p.get('observation_role') and not authoritative_initial)
                    or p.get('scope', {}).get('targets')
                    or not backed(row_proof)):
                raise ValueError('Published-grain input identity, whole-table scope or evidence differs')
            # 固定入力の検査済みParquetだけでは原典の全量を証明しない。全原典の人の証拠も上で要求する。
            if entry['origin']['availability'] != 'stored':
                raise ValueError('Published-grain original bytes are unavailable')
            original = entry['origin']['object']
            original_bytes = (OBJECTS / safe_relative(original['key'])).read_bytes()
            verify_object(original, original_bytes)
            table = OBJECTS / safe_relative(entry['table']['key'])
            verify_object(entry['table'], table.read_bytes())
            cursor = connection.execute('select * from read_parquet(?)', [str(table)])
            columns = [c[0] for c in cursor.description]
            original_rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
            if source['format'] == 'csv':
                if p.get('raw_form') != 'verbatim':
                    raise ValueError('Published-grain CSV has no adopted verbatim restoration proof')
                decoded = original_bytes.decode(p['encoding'])
                if decoded.encode(p['encoding']) != original_bytes:
                    raise ValueError('Published-grain original CSV decoding is not reversible')
                records = list(csv.reader(io.StringIO(decoded, newline='')))
                while records and not any(c.strip() for c in records[-1]):
                    records.pop()
                header, data = records[0], records[1:]
                if (header != p['header'] or len(set(header)) != len(header)
                        or len(data) != inspection['row_count'] or len(data) != len(original_rows)
                        or row_proof['source_row_column'] != 'source_row'):
                    raise ValueError('Published-grain full original CSV header/row scope differs')
                original_rows.sort(key=lambda row: int(row['source_row']))
                if any(int(row['source_row']) != i or [row[c] for c in header] != cells
                       for i, (row, cells) in enumerate(zip(original_rows, data, strict=True), 2)):
                    raise ValueError('Published-grain adopted cells differ from whole original CSV')
            if (len(original_rows) != row_proof['row_count']
                    or len(original_rows) != dataset['line_count']
                    or len(original_rows) != p.get('rows')):
                raise ValueError('Published-grain whole original row population differs')
            dimension_columns = {k: row_proof[k + '_columns'] for k in ['moku', 'project', 'setsu']}
            required_columns = [row_proof['account_column'], row_proof['amount_column'],
                                *(c for cs in dimension_columns.values() for c in cs)]
            if row_proof['source_row_column']:
                required_columns.append(row_proof['source_row_column'])
            exceptions = {e['source_row']: e for e in row_proof.get('row_exceptions', [])}
            statutory_column = row_proof.get('statutory_setsu_code_column')
            if row_scoped:
                if (not statutory_column or statutory_column not in dimension_columns['setsu']
                        or len(exceptions) != len(row_proof.get('row_exceptions', []))):
                    raise ValueError('Published-grain row scope has no unique rows or printed statutory column')
                required_columns.append(statutory_column)
                for exception in exceptions.values():
                    required_columns.append(exception['role_column'])
                    if (exception['role_column'] not in dimension_columns['moku']
                            or not backed(exception)
                            or not all(0 <= i < len(evidence) and evidence[i]['text'].strip()
                                       for i in exception['printed_setsu_evidence_indices'])):
                        raise ValueError('Published-grain reserve role/printed blank column lacks original evidence')
            if any(c not in columns for c in required_columns):
                raise ValueError('Published-grain declared original columns are missing')
            # 印字された節列を宣言から落として分類の失敗を欠如に見せない。
            recognized_setsu = {c for c in columns if c in ['setsu', 'setsu_code', 'setsu_label', '節', '節名称']
                                or c.lstrip('0123456789') in ['節', '節名称']}
            if not recognized_setsu <= set(dimension_columns['setsu']):
                raise ValueError('Published-grain printed setsu columns are omitted')
            recognized_project = {c for c in columns if c in ['project_name', 'project_code', 'project_label', '事業名', '細目名称']
                                  or c.lstrip('0123456789') in ['事項', '事業', '細目']}
            if not recognized_project <= set(dimension_columns['project']):
                raise ValueError('Published-grain printed project columns are omitted')
            expected = {}
            for ordinal, row in enumerate(original_rows, 2):
                number = int(row[row_proof['source_row_column']]) if row_proof['source_row_column'] else ordinal
                if number < 1 or number in expected:
                    raise ValueError('Published-grain original row numbers repeat')
                account = source_account_identities({**source, 'account_labels': [str(row[row_proof['account_column']])]}, styles)
                fund = next(iter(account))[1]
                populated = {k: any(row[c] is not None and label(str(row[c]))
                                    for c in cs) for k, cs in dimension_columns.items()}
                exception = exceptions.get(number)
                if not populated['moku']:
                    raise ValueError('Published-grain original moku is missing')
                if row_scoped:
                    code = label(str(row[statutory_column])) if row[statutory_column] is not None else ''
                    if exception:
                        if (code or label(str(row[exception['role_column']])) != '予備費'
                                or 'setsu' not in absent):
                            raise ValueError('Published-grain reserve exception contradicts the printed role/code')
                    elif (not populated['project'] or not populated['setsu']
                          or not code or not code.isascii() or not code.isdecimal()):
                        raise ValueError('Published-grain remaining row lacks explicit project and printed statutory setsu')
                elif ((populated['setsu'] and 'setsu' in absent)
                        or (populated['project'] and populated['setsu'])):
                    raise ValueError('Published-grain absence contradicts original cells or moku is missing')
                amount = Decimal(str(row[row_proof['amount_column']]))
                if not amount.is_finite():
                    raise ValueError('Published-grain original amount is not finite')
                amount *= 1000 if row_proof['amount_unit'] == '千円' else 1
                expected[number] = (str(amount), fund, populated)
            if not set(exceptions) <= set(expected):
                raise ValueError('Published-grain exception row is not in the whole original')
            provided = dataset.get('_phase_lines', {})
            if set(expected) != set(provided):
                raise ValueError('Published-grain phase output does not preserve the whole original row set')
            for number, (amount, fund, populated) in expected.items():
                output = provided[number]
                levels = set(output['levels'])
                if (Decimal(output['amount']) != Decimal(amount) or output['fund'] != fund
                        or 'moku' not in levels
                        or (populated['project'] and not levels & PROJECT_LEVELS)
                        or (not populated['project'] and levels & PROJECT_LEVELS)
                        or (number not in exceptions and populated['setsu'] and 'setsu' not in levels)
                        or (number not in exceptions and populated['setsu'] and not output['expenditure_setsu_id'])
                        or (number in exceptions and output['expenditure_setsu_id'])
                        or (not row_scoped and 'setsu' in absent and 'setsu' in levels)):
                    raise ValueError('Published-grain original value/account/dimensions differ in phase output')
            observed_setsu = any(v == 'setsu' or '節' in v for v in source['content_grain']['observed_levels'])
            if (not row_scoped and ('setsu' in absent and observed_setsu
                    or 'setsu' not in absent and not any(v[2]['setsu'] for v in expected.values()))):
                raise ValueError('Published-grain setsu absence and observed grain disagree')
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation, duckdb.Error) as error:
        reasons.append('published_grain_preservation_failed:' + str(error))
    finally:
        connection.close()
    return reasons


def unresolved_reasons(source: dict, reasons: list[str], verified: list[str], lock_sha: str,
                       entries: list[dict]) -> list[str]:
    """各残件の解決証跡が現行の原典・全固定入力・全版出力に当たる場合だけ除く。"""
    remaining = []
    proofs = source.get('unresolved_resolutions', [])
    for item in source['unresolved']:
        matching = [p for p in proofs if p['item'] == item]
        resolved = (not reasons and bool(verified) and len(matching) == 1)
        if resolved:
            proof = matching[0]
            resolved = (bool(proof['basis'].strip())
                        and proof['origin_sha256'] == source['content_inspection'].get('sha256')
                        and proof_binding_matches(proof, entries, lock_sha)
                        and set(proof['dataset_ids']) == set(verified)
                        and bool(proof['evidence_indices'])
                        and all(i < len(source['content_inspection']['evidence'])
                                for i in proof['evidence_indices']))
        if not resolved:
            remaining.append(item)
    unknown = {p['item'] for p in proofs} - set(source['unresolved'])
    if unknown:
        remaining.append('resolution_does_not_match_census_item')
    return remaining


def target_key(scope: dict, source: dict | None = None) -> tuple:
    account = canonical_sources.account_label(scope['account_label'], scope['jurisdiction'],
                                               csv=bool(source and source['format'] == 'csv'))
    return (scope['jurisdiction'], scope['fiscal_year'], account,
            scope['document_phase'], scope['amendment_number'], 'expenditure')


def target_coverage(selection: dict, edition_results: dict) -> tuple[list, list]:
    verified, gaps = [], []
    pending: dict[tuple, set[str]] = {}
    for source in selection['content_unconfirmed_sources']:
        for scope in source['identified_scopes']:
            key = target_key({**scope, 'jurisdiction': source['jurisdiction']})
            pending.setdefault(key, set()).add(source['source_id'])
    for group in selection['groups']:
        result = {key: group[key] for key in (
            'source_key', 'jurisdiction', 'fiscal_year', 'account_label', 'document_phase',
            'amendment_number', 'direction', 'canonical_source_id', 'selection_status')}
        sid = group['canonical_source_id']
        key = target_key(group)
        if sid is None:
            reasons = [group['selection_status']]
            result['candidate_source_ids'] = [c['source_id'] for c in group['candidates']]
        else:
            editions = edition_results.get((sid, key), [])
            if len(editions) != 1:
                reasons = ['canonical_edition_missing_or_ambiguous']
            else:
                result['verified_datasets'] = editions[0]['verified_datasets']
                reasons = editions[0]['reasons']
        if key in pending:
            result['pending_candidate_source_ids'] = sorted(pending[key])
            reasons = [*reasons, 'alternative_content_not_confirmed']
        if reasons:
            gaps.append({**result, 'reasons': sorted(set(reasons))})
        else:
            verified.append(result)
    return verified, gaps


def search_coverage(inventory: dict, selection: dict, verified_targets: list[dict]) -> tuple[list, list, list]:
    boundaries, gaps, population = [], [], []
    sources = {s['id']: s for s in inventory['sources']}
    source_targets: dict[str, set[tuple]] = {}
    for group in selection['groups']:
        key = target_key(group)
        for candidate in group['candidates']:
            source_targets.setdefault(candidate['source_id'], set()).add(key)
    verified_keys = {target_key(t) for t in verified_targets}
    unidentified = {s['source_id'] for kind in ('unclassified_sources', 'content_unconfirmed_sources')
                    for s in selection[kind]}
    for jurisdiction in inventory['jurisdictions']:
        code = jurisdiction['code']
        unavailable = set()
        for gap in jurisdiction['gaps']:
            # URLなし・年度不明・全段階の曖昧な非公開宣言は探索の終端にならない。
            if (gap['status'] == 'publisher_declares_unavailable' and gap['detail'].strip() and gap['evidence_urls']
                    and gap['years'] and gap['phase'] in PHASE_KIND):
                unavailable.update((year, label(gap['account_scope']), gap['phase']) for year in gap['years'])
            else:
                gaps.append({'jurisdiction': code, **gap})
        complete_scopes = set()
        if not jurisdiction['search_boundaries']:
            boundaries.append({'jurisdiction': code, 'url': None, 'reasons': ['no_finite_search_boundaries']})
        for boundary in jurisdiction['search_boundaries']:
            reasons = []
            boundary_scopes = set()
            proof = boundary.get('completion_proof')
            if boundary['status'] != 'inspected':
                reasons.append('search_boundary_not_inspected')
            if not proof:
                reasons.append('search_boundary_completion_not_proven')
            else:
                if not evidence_backed(proof):
                    reasons.append('search_boundary_completion_without_evidence')
                chosen = proof['source_ids']
                if any(i not in sources or sources[i]['jurisdiction'] != code for i in chosen):
                    reasons.append('boundary_source_population_mismatch')
                # Alternative URLs witness discovery; only the selected target
                # needs verified outputs. Unknown identity/selection still blocks.
                discovered = set().union(*(source_targets.get(i, set()) for i in chosen))
                available = {key[1:5] for key in discovered & verified_keys if key[0] == code}
                for scope in proof['scopes']:
                    if not evidence_backed(scope):
                        reasons.append('search_scope_without_evidence')
                    key = (scope['fiscal_year'], label(scope['account_label']), scope['document_phase'])
                    numbers = scope['amendment_numbers']
                    if scope['document_phase'] == 'supplementary':
                        # 最終号を証明し、号の欠落を省略した列挙で隠さない。
                        last = scope['last_amendment_number']
                        if (last is None or last != len(numbers)
                                or sorted(numbers) != list(range(1, len(numbers) + 1))):
                            reasons.append('supplementary_sequence_not_closed')
                        needed = {(*key, n) for n in numbers}
                    else:
                        if numbers or scope['last_amendment_number'] is not None:
                            reasons.append('non_supplementary_scope_has_amendment')
                        needed = {(*key, None)}
                    if key not in unavailable and (not needed or not needed <= available):
                        reasons.append('boundary_scope_not_in_verified_phase_outputs:' + json.dumps(scope, ensure_ascii=False, sort_keys=True))
                    else:
                        boundary_scopes.add(key)
                # 探索で列挙した対象の未検証をscopesから外して隠さない。
                if any(sources.get(i, {}).get('role') == 'statement'
                       and sources[i]['in_scope']['status'] != 'excluded'
                       and sources[i]['directions'] != ['revenue']
                       and (i in unidentified or not source_targets.get(i)
                            or not source_targets[i] <= verified_keys)
                       for i in chosen if i in sources):
                    reasons.append('boundary_contains_unverified_target')
            if reasons:
                boundaries.append({'jurisdiction': code, 'url': boundary['url'], 'reasons': sorted(set(reasons))})
            else:
                complete_scopes.update(boundary_scopes)
        for phase in PHASE_KIND:
            if not any(k[2] == phase for k in complete_scopes):
                population.append({'jurisdiction': code, 'phase': phase,
                                   'reason': 'no_evidenced_year_account_phase_population'})
    return boundaries, gaps, population


def audit(inventory_path: Path, schema_path: Path, lock_path: Path, warehouse: Path) -> dict:
    inventory = canonical_sources.load_inventory(inventory_path)
    schema = json.loads(schema_path.read_text())
    jsonschema.validators.validator_for(schema).check_schema(schema)
    jsonschema.validate(inventory, schema, format_checker=jsonschema.FormatChecker())
    ids = [s['id'] for s in inventory['sources']]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate source IDs in coverage inventory')
    codes = [j['code'] for j in inventory['jurisdictions']]
    if len(set(codes)) != len(codes) or set(codes) != {'131016', '132047', '132071', '132195', '132241'}:
        raise ValueError('Coverage population must contain the five managed jurisdictions exactly once')
    styles = yaml.safe_load((PIPELINE / 'dbt/dbt_project.yml').read_text())['vars']['fiscal_code_style']
    lock = read_lock(lock_path)
    entries = lock['entries']
    selection = canonical_sources.report(inventory, lock)
    by_url: dict[str, list[dict]] = {}
    provenance_by_path = {}
    for entry in entries:
        provenance = json.loads(source_metadata_bytes(lock_path, entry))
        provenance_by_path[entry['path']] = provenance
        for url in {provenance.get('request_url'), provenance.get('final_url')} - {None}:
            by_url.setdefault(url, []).append(entry)
        # Archived acquisitions retain the publisher URL separately from the
        # archive request. Only the same, hash-pinned edition is an alias.
        original_url = provenance.get('original_url')
        if original_url and provenance.get('sha256') == entry['originEdition']:
            if entry not in by_url.get(original_url, []):
                by_url.setdefault(original_url, []).append(entry)
    datasets, build_state = checked_datasets(lock_path, warehouse)
    gaps = []
    lock_sha = digest(lock_path.read_bytes())
    tally: Counter = Counter()
    published_exceptions = []
    edition_results: dict[tuple, list[dict]] = {}
    matched_paths: set[str] = set()
    for source in inventory['sources']:
        code = source['jurisdiction']
        if code not in codes:
            raise ValueError(f'Unmanaged jurisdiction in source: {source["id"]}')
        inspection = source['content_inspection']
        source_entries = [e for e in by_url.get(source['download_url'], [])
                          if e['jurisdiction'] == code]
        if inspection.get('sha256'):
            source_entries = [e for e in source_entries if e['originEdition'] == inspection['sha256']]
        matched_paths.update(e['path'] for e in source_entries)
        tally['listed'] += 1
        tally['adopted_origins'] += bool(source_entries)
        if source['in_scope']['status'] == 'excluded' and evidence_backed(source['in_scope']):
            tally['excluded_sources'] += 1
            continue
        revenue_only = (source.get('directions') == ['revenue']
                        and inspection['status'] in ['text_probed', 'csv_inspected']
                        and inspection.get('sha256')
                        and any('歳入' in e['text'] or 'revenue' in e['text'].lower()
                                for e in inspection['evidence']))
        if source['role'] != 'statement' or revenue_only:
            continue
        tally['statements'] += 1
        reasons = []
        if source['in_scope']['status'] != 'included' or not evidence_backed(source['in_scope']):
            reasons.append('account_regime_not_confirmed')
        if 'expenditure' not in source.get('directions', []):
            reasons.append('expenditure_scope_not_confirmed')
        if (inspection['status'] not in ['text_probed', 'csv_inspected']
                or not inspection['evidence'] or not inspection.get('sha256')):
            reasons.append('content_not_inspected')
        if source['account_scope_status'] != 'content_inspected':
            reasons.append('account_scope_not_confirmed')
        if source['edition_status'] != 'content_inspected':
            reasons.append('edition_scope_not_confirmed')
        if not source_entries:
            reasons.append('not_in_current_fixed_inputs')
        account_identities = source_account_identities(source, styles)
        editions = source['editions']
        if not editions:
            reasons.append('no_content_confirmed_editions')
        if {edition_account_identity(e, account_identities) for e in editions} != account_identities:
            reasons.append('listed_accounts_not_all_identified_in_editions')
        if {e['amendment_number'] for e in editions if e['document_phase'] == 'supplementary'} != set(source['amendment_numbers']):
            reasons.append('listed_amendments_not_all_identified_in_editions')
        verified = []
        source_exceptions = []
        source_reasons = list(reasons)
        inspected_editions = []
        for edition in editions:
            edition_reasons = list(source_reasons)
            account_identity = edition_account_identity(edition, account_identities)
            if edition['in_scope']['status'] == 'excluded' and evidence_backed(edition['in_scope']):
                continue
            if edition['in_scope']['status'] != 'included' or not evidence_backed(edition['in_scope']):
                edition_reasons.append('edition_account_regime_not_confirmed')
            if (edition['fiscal_year'] is None
                    or account_identity is None
                    or (source['document_phase'] != 'mixed'
                        and edition['document_phase'] != source['document_phase'])
                    or (source['fiscal_year'] is not None and edition['fiscal_year'] != source['fiscal_year'])
                    or (edition['document_phase'] == 'supplementary'
                        and (edition['amendment_number'] is None
                             or edition['amendment_number'] not in source['amendment_numbers']))
                    or (edition['document_phase'] != 'supplementary'
                        and edition['amendment_number'] is not None)):
                edition_reasons.append('edition_identity_not_confirmed')
            confirmation = edition.get('content_confirmation')
            if (not confirmation
                    or confirmation['direction'] != 'expenditure'
                    or confirmation['origin_sha256'] != inspection.get('sha256')
                    or any(i >= len(inspection['evidence'])
                           for key in ['account_evidence_indices', 'edition_evidence_indices', 'direction_evidence_indices']
                           for i in confirmation[key])):
                edition_reasons.append('edition_content_confirmation_missing_or_stale')
            matching = [d for d in datasets
                        if d.get('direction', 'expenditure') == 'expenditure'
                        and d['jurisdiction_code'] == code
                        and d['fiscal_year'] == edition['fiscal_year']
                        and d['document_kind'] == PHASE_KIND.get(edition['document_phase'])
                        and any(e['originEdition'] == d['origin_sha256']
                                and e['jurisdiction'] == code and e['fiscalYear'] == edition['fiscal_year']
                                and e['documentKind'] == PHASE_KIND.get(edition['document_phase'])
                                and e['direction'] == 'expenditure'
                                and json.loads(d['source_json'])['url'] == provenance_by_path[e['path']]['request_url']
                                and json.loads(d['source_json']).get('tableId') == entry_table_id(e)
                                and (edition['document_phase'] != 'supplementary'
                                     or provenance_by_path[e['path']].get('amendment_number') == edition['amendment_number'])
                                for e in source_entries)
                        and account_identity is not None
                        and any(label(f['label']) == account_identity[1]
                                and (account_identity[0] is None or str(f['code']) == account_identity[0])
                                for f in json.loads(d['structure_json'])['funds'])
                        and not json.loads(d['structure_json']).get('scope', {}).get('targets')
                        and not json.loads(d['source_json']).get('scope', {}).get('targets')
                        and d['output_coverage']['complete']
                        and label(edition['account_label']) in d['output_coverage']['accounts']
                        and (edition['document_phase'] != 'supplementary'
                             or edition['amendment_number'] in d['output_coverage']['accounts'][label(edition['account_label'])]['amendment_numbers'])]
            if not matching:
                edition_reasons.append('edition_not_in_verified_marts:' + json.dumps(edition, ensure_ascii=False, sort_keys=True))
            grain_source = {**source, 'content_grain': edition.get('content_grain', source['content_grain'])}
            grain_gaps = grain_reasons(grain_source, matching, edition['account_label'])
            if edition.get('published_grain_exception'):
                exception_gaps = published_grain_reasons(grain_source, edition, matching, source_entries,
                                                         provenance_by_path, lock_path, lock_sha, styles)
                edition_reasons.extend(exception_gaps)
                if exception_gaps:
                    edition_reasons.extend(grain_gaps)
                else:
                    edition_reasons.extend(r for r in grain_gaps if r in
                                   ['content_grain_not_observed', 'moku_grain_not_observed'])
                    source_exceptions.append({'source_id': source['id'], 'edition': scope_key(edition),
                                              'dataset_ids': sorted(d['dataset_id'] for d in matching),
                                              'absent_dimensions': sorted(a['dimension'] for a in edition['published_grain_exception']['absent_dimensions']),
                                              'row_exceptions': [{'dataset_id': p['dataset_id'], 'source_row': e['source_row'],
                                                                  'role': e['role']}
                                                                 for p in edition['published_grain_exception']['preservation']
                                                                 for e in p.get('row_exceptions', [])],
                                              'project_setsu_confirmed': False})
            else:
                edition_reasons.extend(grain_gaps)
            verified.extend(d['dataset_id'] for d in matching)
            result = {'reasons': sorted(set(edition_reasons)),
                      'verified_datasets': sorted(d['dataset_id'] for d in matching)}
            key = target_key({**edition, 'jurisdiction': code}, source)
            edition_results.setdefault((source['id'], key), []).append(result)
            inspected_editions.append(result)
            reasons.extend(edition_reasons)
        if source['document_phase'] == 'supplementary' and not source['amendment_numbers']:
            reasons.append('amendment_number_not_confirmed')
        unresolved = unresolved_reasons(source, reasons, verified, lock_sha, source_entries)
        reasons.extend(unresolved)
        for result in inspected_editions:
            result['reasons'] = sorted(set(result['reasons'] + unresolved))
        if not reasons and verified:
            tally['verified_statements'] += 1
            published_exceptions.extend(source_exceptions)
        else:
            gaps.append({'source_id': source['id'], 'jurisdiction': code,
                         'fiscal_year': source['fiscal_year'], 'phase': source['document_phase'],
                         'reasons': sorted(set(reasons)), 'verified_datasets': sorted(set(verified))})
    verified_targets, target_gaps = target_coverage(selection, edition_results)
    inventory_gaps = [{'source_id': item['source_id'], 'jurisdiction': item['jurisdiction'],
                       'kind': kind, 'reasons': item['reasons']}
                      for kind in ('unclassified_sources', 'content_unconfirmed_sources')
                      for item in selection[kind]]
    for source in inventory['sources']:
        if source['role'] != 'statement':
            continue
        if any(scope.get('in_scope', {}).get('status') == 'excluded'
               and not evidence_backed(scope['in_scope']) for scope in [source, *source['editions']]):
            inventory_gaps.append({'source_id': source['id'], 'jurisdiction': source['jurisdiction'],
                                   'kind': 'exclusion_unconfirmed', 'reasons': ['exclusion_without_evidence']})
    boundary_gaps, search_gaps, population_gaps = search_coverage(inventory, selection, verified_targets)
    unmatched = sorted(e['path'] for e in entries if e['path'] not in matched_paths)
    unmatched_expenditure = sorted(e['path'] for e in entries
                                   if e['path'] not in matched_paths and e['direction'] == 'expenditure')
    complete = (bool(selection['groups']) and not target_gaps and not inventory_gaps and not search_gaps
                and not boundary_gaps and not population_gaps
                and not unmatched_expenditure and build_state == 'verified_current_build'
                and all(d['output_coverage']['complete'] for d in datasets))
    return {'schema_version': 1, 'complete': complete, 'build_state': build_state,
            'inventory_lock_changed': inventory['lock_reconciliation']['lock_sha256'] != digest(lock_path.read_bytes()),
            'counts': dict(sorted(tally.items())), 'source_gap_count': len(gaps),
            'completion_unit': 'canonical_expenditure_target',
            'target_count': len(selection['groups']), 'verified_target_count': len(verified_targets),
            'target_gap_count': len(target_gaps), 'target_gaps': target_gaps,
            'verified_targets': verified_targets,
            'inventory_gap_count': len(inventory_gaps), 'inventory_gaps': inventory_gaps,
            'search_gap_count': len(search_gaps), 'source_gaps': gaps, 'search_gaps': search_gaps,
            'boundary_gap_count': len(boundary_gaps), 'boundary_gaps': boundary_gaps,
            'population_gap_count': len(population_gaps), 'population_gaps': population_gaps,
            'adopted_independent_side_table_count': sum(e['path'].startswith(SIDE_NAMESPACE) for e in entries),
            'independent_side_tables': [{'dataset_id': d['dataset_id'], **d['output_coverage']}
                                        for d in datasets
                                        if json.loads(d['source_json']).get('observationRole') == 'independent-moku-setsu'],
            'published_grain_exceptions': published_exceptions,
            'independent_settlement_tables': [{'dataset_id': d['dataset_id'], **d['output_coverage']}
                                              for d in datasets
                                              if json.loads(d['source_json']).get('observationRole') in SETTLEMENT_ROLES],
            'adopted_independent_settlement_table_count': sum(e['path'].startswith(SETTLEMENT_NAMESPACE) for e in entries),
            'adopted_native_settlement_table_count': sum(e['path'].startswith('tama-native-settlement/') for e in entries),
            'native_settlement_tables': [{'dataset_id': d['dataset_id'], **d['output_coverage']}
                                         for d in datasets
                                         if json.loads(d['source_json']).get('provider') == 'tama-native-settlement'],
            'nonadditive_reference_tables': [{'dataset_id': d['dataset_id'], **d['output_coverage']}
                                            for d in datasets
                                            if json.loads(d['source_json']).get('observationRole') in
                                            ('nonadditive-supplementary-reference', 'nonadditive-initial-moku-reference')],
            'adopted_initial445_table_count': sum(e['path'].startswith('akishima-initial445/') for e in entries),
            'initial445_tables': [{'dataset_id': d['dataset_id'], **d['output_coverage']}
                                  for d in datasets if json.loads(d['source_json']).get('namespace') == 'akishima-initial445'],
            'adopted_held5_table_count': sum(e['path'].startswith('held5-council-approved-detail/') for e in entries),
            'held5_tables': [{'dataset_id': d['dataset_id'], **d['output_coverage']}
                            for d in datasets if json.loads(d['source_json']).get('observationRole') == 'authoritative-held5-council-supplementary-detail'],
            'adopted_settlement2024_table_count': sum(e['path'].startswith('akishima-settlement2024/') for e in entries),
            'settlement2024_tables': [{'dataset_id': d['dataset_id'], **d['output_coverage']}
                                     for d in datasets
                                     if json.loads(d['source_json']).get('namespace') == 'akishima-settlement2024'],
            'adopted_settlement2020_2023_table_count': sum(e['path'].startswith('akishima-settlement2020-2023/') for e in entries),
            'settlement2020_2023_tables': [{'dataset_id': d['dataset_id'], **d['output_coverage']}
                                          for d in datasets
                                          if json.loads(d['source_json']).get('namespace') == 'akishima-settlement2020-2023'],
            'adopted_pre2020_table_count': sum(e['path'].startswith('tama-pre2020/') for e in entries),
            'pre2020_tables': [{'dataset_id': d['dataset_id'], **d['output_coverage']}
                               for d in datasets
                               if json.loads(d['source_json']).get('provider') == 'tama-pre2020'],
            'dataset_output_gaps': [{'dataset_id': d['dataset_id'], **d['output_coverage']}
                                    for d in datasets if not d['output_coverage']['complete']],
            'adopted_mitaka_initial_observation_count': sum(e['path'].startswith('mitaka-initial2026/') for e in entries),
            'mitaka_initial_observation_tables': [{'dataset_id': d['dataset_id'], **d['output_coverage']}
                                                for d in datasets if json.loads(d['source_json']).get('provider') == 'mitaka-initial2026'],
            'unmatched_fixed_inputs': unmatched,
            'unmatched_expenditure_inputs': unmatched_expenditure}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=HERE / 'sources.json')
    parser.add_argument('--schema', type=Path, default=HERE / 'sources.schema.json')
    parser.add_argument('--lock', type=Path, default=LOCK)
    parser.add_argument('--warehouse', type=Path, default=PIPELINE / '.build/warehouse.duckdb')
    parser.add_argument('--describe', action='store_true', help='Print the inventory schema and exit')
    parser.add_argument('--json', action='store_true', help='Print a machine-readable audit')
    parser.add_argument('--limit', type=int, default=25, help='Limit displayed source and target gaps (default 25)')
    parser.add_argument('--require-complete', action='store_true', help='Exit 2 if the full scope is incomplete')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('--limit must be nonnegative')
    try:
        if args.describe:
            print(args.schema.read_text())
            return 0
        report = audit(args.inventory, args.schema, args.lock, args.warehouse)
        report['source_gaps'] = report['source_gaps'][:args.limit]
        report['source_gaps_truncated'] = report['source_gap_count'] > args.limit
        report['target_gaps'] = report['target_gaps'][:args.limit]
        report['target_gaps_truncated'] = report['target_gap_count'] > args.limit
        if args.json or not sys.stdout.isatty():
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        else:
            print(f'complete={report["complete"]} build={report["build_state"]}')
            print(json.dumps(report['counts'], ensure_ascii=False))
            print(f'target gaps={report["target_gap_count"]}; inventory gaps={report["inventory_gap_count"]}; '
                  f'candidate source gaps={report["source_gap_count"]}; search gaps={report["search_gap_count"]}; '
                  f'boundary gaps={report["boundary_gap_count"]}; population gaps={report["population_gap_count"]}')
        return 2 if args.require_complete and not report['complete'] else 0
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, jsonschema.exceptions.ValidationError,
            jsonschema.exceptions.SchemaError, subprocess.CalledProcessError, duckdb.Error) as error:
        print(json.dumps({'error': type(error).__name__, 'message': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
