"""Direct whole-field checks for the six recognized Akishima FY2024 settlement editions.

Financial moku x printed-legal-setsu rows, independent project-remark totals,
nonadditive printed controls and the physical-page inventory retain separate
preserved grains. Preservation never establishes project-to-setsu correspondence.
"""
from __future__ import annotations
from ingestion.inputs import source_metadata_bytes

from collections import defaultdict
import json
from pathlib import Path

import duckdb

from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, verify_object
from ingestion.fiscal.native_settlement_coverage import records

NAMESPACE = 'akishima-settlement2024'
ROLE_TABLE = {'financial': 'financial', 'controls': 'controls', 'projects': 'projects', 'page_inventory': 'page_inventory'}
EXPECTED_FIELD_COUNTS = {'financial': 50, 'controls': 57, 'projects': 36, 'page_inventory': 20}
EXPECTED_TOTALS = dict(rows={'financial': 1026, 'controls': 754, 'projects': 555, 'page_inventory': 651},
                       executed_yen=77273862108, printed_zero=56, blank_reserve=6,
                       master_confirmed=1006, name_conflict=14)
EXPECTED_ACCOUNT_YEN = {'general': 51527072727, 'health': 11234501036, 'care': 10096329635,
                        'elderly': 3137428500, 'land': 266589429, 'north': 1011940781}


def indexed(rows: list[dict]) -> dict:
    result = {row['source_row_id']: row for row in rows}
    if len(result) != len(rows):
        raise ValueError('Repeated settlement2024 original observation')
    return result


def typed_csv(connection, candidate: Path, relative: str, relation: str, where: str = '') -> list[dict]:
    types = {row[0]: row[1] for row in connection.execute('describe select * from ' + relation).fetchall()}
    return records(connection,
                   "select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='') " + where,
                   [str(candidate / relative), types])


def schema_of(connection, relation: str) -> dict:
    return {row[0]: row[1] for row in connection.execute('describe select * from ' + relation).fetchall()}


def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path,
                    datasets: list[dict]) -> None:
    entries = [entry for entry in read_lock(lock_path)['entries']
               if entry['path'].startswith(NAMESPACE + '/')]
    if not entries:
        return
    from ingestion.fiscal.akishima_settlement2024_registry import specs
    from ingestion.fiscal.extract_akishima_settlement2024 import PACKAGE, MANIFEST, RepoBundle
    selected = [row for row in datasets if json.loads(row['source_json']).get('namespace') == NAMESPACE]
    for row in selected:
        row['output_coverage'] = dict(complete=False, files=[], accounts={}, errors=[],
                                      original_rows=0, all_original_fields_preserved=False,
                                      project_legal_setsu_correspondence='unconfirmed')
        row['_phase_lines'] = {}
    try:
        spec = specs()[0]
        expected = {table['logical_path']: table for table in spec['tables']}
        registered = {row['dataset_id']: row for row in selected}
        if len(entries) != 19 or len(selected) != 18 or len(registered) != 18:
            raise ValueError('Exact adopted19 settlement2024 registrations missing or repeated')
        manifest = json.loads(MANIFEST.read_bytes())
        bundle = RepoBundle(OBJECTS, manifest)
        assets = bundle.validate_all()
        if digest((PACKAGE / 'config.json').read_bytes()) != manifest['bindings']['config/config.json']:
            raise ValueError('Git source declaration differs from immutable accepted input')
        roles = defaultdict(list)
        raw_schemas = {}
        declarations = {}
        for entry in entries:
            table = expected[entry['path']]
            provenance = json.loads(source_metadata_bytes(lock_path, entry))
            source_key = table['raw_role']
            dataset = registered.get(
                ':'.join(('132071', '2024', 'expenditure', 'settlement', spec['expected_sha256'], table['table_id'])))
            if table['raw_role'] != 'page_inventory' and dataset is None:
                raise ValueError('Adopted settlement2024 dataset missing')
            if dataset is not None:
                source = json.loads(dataset['source_json'])
                if (entry['jurisdiction'] != '132071' or entry['fiscalYear'] != 2024
                        or entry['documentKind'] != 'settlement' or entry['direction'] != 'expenditure'
                        or entry['originEdition'] != spec['expected_sha256']
                        or source['url'] != spec['url'] or source['sha256'] != spec['expected_sha256']
                        
                        or source['rawTableSha256'] != entry['table']['sha256']
                        or source['rawRowCount'] != table['expected_rows']
                        or dataset['line_count'] != table['expected_rows']
                        or source['sourceAmountUnit'] != '円' or source['unitMultiplier'] != 1
                        or source['observationRole'] != source_key
                        or source['canonicalExecuted'] != (source_key == 'financial')
                        or source['nonadditive'] != (source_key != 'financial')
                        or json.loads(dataset['phases_json']) != (['executed'] if source_key == 'financial' else [])):
                    raise ValueError('Settlement2024 original/recognition/phase/unit/role identity differs')
            for reference in (entry['origin']['object'], entry['table']):
                verify_object(reference, (OBJECTS / safe_relative(reference['key'])).read_bytes())
            raw_path = str(OBJECTS / safe_relative(entry['table']['key']))
            raw = records(connection, 'select * from read_parquet(?,hive_partitioning=false)', [raw_path])
            raw_schemas[table['table_id']] = {row[0]: row[1] for row in connection.execute(
                'describe select * from read_parquet(?,hive_partitioning=false)', [raw_path]).fetchall()}
            indexed(raw)
            if (len(raw) != table['expected_rows']
                    or len(list(raw[0])) != EXPECTED_FIELD_COUNTS[source_key]
                    or any(not row['source_row_id'].startswith(spec['expected_sha256'] + ':') for row in raw)):
                raise ValueError('Settlement2024 raw row count/fields/original occurrence differs')
            for row in raw:
                if row['original_sha256'] != spec['expected_sha256'] or row['fiscal_year'] != 2024:
                    raise ValueError('Settlement2024 original row edition/year differs')
                if source_key != 'page_inventory' and (row['original_url'] != spec['url'] or row['unit'] != '円'):
                    raise ValueError('Settlement2024 original row url/unit differs')
                if table['raw_role'] != 'page_inventory':
                    if (row['account_id'] != table['account_slug'] or row['recognition_date'] != '2025-10-02'
                            or row['statutory_setsu_id'] is not None):
                        raise ValueError('Settlement2024 original row account/recognition/statutory differs')
                    if source_key == 'financial' and row['phase'] != 'executed':
                        raise ValueError('Settlement2024 financial row phase differs')
                    if source_key != 'financial' and row['phase'] not in ('executed', None):
                        raise ValueError('Settlement2024 nonadditive row printed phase differs')
            roles[source_key].extend(raw)
            if dataset is not None:
                declarations[dataset['dataset_id']] = (dataset, table, raw)
        # typed staging + raw CSVs preserve every original field exactly once per role
        for role, raw in roles.items():
            suffix = ROLE_TABLE[role]
            original = indexed(raw)
            fields = list(raw[0])
            table_schema = next(s for tid, s in raw_schemas.items() if tid.endswith('-' + suffix)
                                or tid == 'fy2024-page-inventory')
            for relation in ('stg_132071__settlement2024_' + suffix,
                             'csv_132071_settlement2024_raw_' + suffix):
                provided_schema = schema_of(connection, relation)
                if any(field not in provided_schema or provided_schema[field] != table_schema[field]
                       for field in fields):
                    raise ValueError('Settlement2024 original field TYPES differ in ' + relation)
                provided = indexed(records(connection, 'select * from ' + relation))
                if provided.keys() != original.keys() or any(
                        {field: provided[key][field] for field in fields} != row
                        for key, row in original.items()):
                    raise ValueError('Settlement2024 original field/occurrence differs in ' + relation)
            relative = 'fiscal/132071/settlement2024_raw_' + suffix + '.csv'
            if relative not in hashes:
                raise ValueError('Settlement2024 raw typed CSV absent from verified artifacts')
            relation = 'csv_132071_settlement2024_raw_' + suffix
            csv_rows = typed_csv(connection, candidate, relative, relation)
            if indexed(csv_rows) != indexed(records(connection, 'select * from ' + relation)):
                raise ValueError('Settlement2024 raw typed CSV original NULL/value differs')
        # financial: executed amount identity, separate legal judgment columns, exact censuses
        financial = indexed(records(connection, 'select * from int_132071_settlement2024_executed'))
        if len(financial) != EXPECTED_TOTALS['rows']['financial']:
            raise ValueError('Settlement2024 financial occurrences differ')
        original_fin = indexed(roles['financial'])
        for key, row in financial.items():
            if (row['amount'] != row['amount_executed'] or row['currency'] != 'JPY'
                    or row['statutory_setsu_id'] is not None):
                raise ValueError('Settlement2024 executed amount/statutory identity differs')
            fields = list(original_fin[key])
            if {f: row[f] for f in fields} != original_fin[key]:
                raise ValueError('Settlement2024 financial original fields lost in intermediate')
        status = {row['legal_mapping_status'] for row in financial.values()}
        counts = {s: sum(1 for row in financial.values() if row['legal_mapping_status'] == s) for s in status}
        if (counts.get('confirmed-printed-code-name-active-year', 0) != EXPECTED_TOTALS['master_confirmed']
                or counts.get('unconfirmed-printed-name-master-conflict', 0) != EXPECTED_TOTALS['name_conflict']
                or counts.get('unconfirmed-blank-reserve-row', 0) != EXPECTED_TOTALS['blank_reserve']
                or sum(1 for row in financial.values() if row['amount_executed'] == 0) != EXPECTED_TOTALS['printed_zero']
                or sum(row['amount'] for row in financial.values()) != EXPECTED_TOTALS['executed_yen']):
            raise ValueError('Settlement2024 executed/legal-judgment census differs')
        per_account = defaultdict(int)
        for row in financial.values():
            per_account[row['account_id']] += row['amount']
        if dict(per_account) != EXPECTED_ACCOUNT_YEN:
            raise ValueError('Settlement2024 per-account executed totals differ')
        # canonical executed CSV: every line carries exactly one original row
        fin_by_line = {row['fiscal_line_id']: row for row in financial.values()}
        executed_rows = records(connection, 'select * from fiscal_132071_settlement2024_executed')
        if len(executed_rows) != len(financial) or len(fin_by_line) != len(financial):
            raise ValueError('Settlement2024 canonical executed occurrences differ')
        provided_ids = [row['fiscal_line_id'] for row in executed_rows]
        if len(set(provided_ids)) != len(provided_ids) or set(provided_ids) != set(fin_by_line):
            raise ValueError('Settlement2024 canonical line identities duplicated or differ')
        for row in executed_rows:
            details = json.loads(row['details_json'])
            if (len(details) != 1 or details[0]['amount'] != row['amount']
                    or details[0]['fiscalLineId'] != row['fiscal_line_id']
                    or details[0]['rawOriginal'] != json.loads(fin_by_line[row['fiscal_line_id']]['original_raw_and_staging_json'])):
                raise ValueError('Settlement2024 canonical detail lost original fields or monetary identity')
        relative = 'fiscal/132071/settlement2024_executed.csv'
        if relative not in hashes:
            raise ValueError('Settlement2024 executed CSV absent from verified artifacts')
        csv_rows = typed_csv(connection, candidate, relative, 'csv_132071_settlement2024_executed')
        if {row['fiscal_line_id']: row for row in csv_rows} != {row['fiscal_line_id']: row for row in
                records(connection, 'select * from csv_132071_settlement2024_executed')}:
            raise ValueError('Settlement2024 executed typed CSV row/NULL differs')
        # controls/projects stay independent nonadditive: canonical contribution stays NULL
        for role, relation in (('controls', 'int_132071_settlement2024_controls'),
                               ('projects', 'int_132071_settlement2024_projects')):
            rows = records(connection, 'select * from ' + relation)
            if len(rows) != EXPECTED_TOTALS['rows'][role]:
                raise ValueError('Settlement2024 ' + role + ' occurrences differ')
            original = indexed(roles[role])
            fields = list(roles[role][0])
            for row in rows:
                if row['canonical_phase'] is not None or row['canonical_financial_amount'] is not None:
                    raise ValueError('Settlement2024 ' + role + ' acquired a financial contribution')
                if {f: row[f] for f in fields} != original[row['source_row_id']]:
                    raise ValueError('Settlement2024 ' + role + ' lost original fields')
                if role == 'projects' and row['project_setsu_linkage'] != 'unconfirmed':
                    raise ValueError('Settlement2024 project acquired an unproven setsu linkage')
            int_by_id = {row['source_row_id']: row for row in rows}
            for mart in ('fiscal', 'csv'):
                rel = f'{mart}_132071_settlement2024_{role}' if mart == 'fiscal' else f'csv_132071_settlement2024_{role}'
                provided = indexed(records(connection, 'select * from ' + rel))
                if provided.keys() != set(int_by_id):
                    raise ValueError('Settlement2024 ' + role + ' mart occurrences differ')
                all_fields = list(rows[0])
                if any({f: provided[key][f] for f in all_fields} != int_by_id[key] for key in provided):
                    raise ValueError('Settlement2024 ' + role + ' mart carried values differ')
            relative = f'fiscal/132071/settlement2024_{role}.csv'
            if relative not in hashes:
                raise ValueError('Settlement2024 ' + role + ' CSV absent from verified artifacts')
            rel = 'csv_132071_settlement2024_' + role
            if indexed(typed_csv(connection, candidate, relative, rel)) != indexed(
                    records(connection, 'select * from ' + rel)):
                raise ValueError('Settlement2024 ' + role + ' typed CSV row/NULL differs')
        # page inventory: every physical page exactly once, metadata-only
        pages = records(connection, 'select * from int_132071_settlement2024_page_inventory')
        if (len(pages) != 651 or {row['physical_page'] for row in pages} != set(range(1, 652))
                or any(row['canonical_financial_amount'] is not None or row['canonical_phase'] is not None for row in pages)):
            raise ValueError('Settlement2024 page inventory acquired amounts or lost pages')
        original_pages = indexed(roles['page_inventory'])
        page_fields = list(roles['page_inventory'][0])
        for row in pages:
            if {f: row[f] for f in page_fields} != original_pages[row['source_row_id']]:
                raise ValueError('Settlement2024 page inventory lost original fields')
        relative = 'fiscal/132071/settlement2024_page_inventory.csv'
        if relative not in hashes:
            raise ValueError('Settlement2024 page inventory CSV absent from verified artifacts')
        if indexed(typed_csv(connection, candidate, relative, 'csv_132071_settlement2024_page_inventory')) != indexed(
                records(connection, 'select * from csv_132071_settlement2024_page_inventory')):
            raise ValueError('Settlement2024 page inventory typed CSV row/NULL differs')
        # independent printed controls: sums recomputed from preserved grains only
        control_proof = printed_controls(roles, records)
        # dataset registry: phases/nonadditive never enter fiscal amounts
        refs = records(connection, "select m.*, i.phases_json from fiscal_datasets m "
                       "join int_fiscal_datasets i using(dataset_id) where json_extract_string(m.source_json,'$.namespace')=?",
                       [NAMESPACE])
        if (len(refs) != 19 or sum(row['source_amount_kind'] is None and row['phases_json'] == '[]' for row in refs) != 13
                or sum(row['source_amount_kind'] == 'executed' for row in refs) != 6):
            raise ValueError('Settlement2024 datasets acquired phase/amount kind')
        relative = 'fiscal/132071/settlement2024_datasets.csv'
        if relative not in hashes:
            raise ValueError('Settlement2024 datasets CSV absent from verified artifacts')
        csv_registry = {row['dataset_id']: row for row in typed_csv(
            connection, candidate, relative, 'csv_132071_settlement2024_datasets')}
        actual_registry = {row['dataset_id']: row for row in records(
            connection, 'select * from csv_132071_settlement2024_datasets')}
        original_registry = {row['dataset_id']: row for row in records(
            connection, 'select * from int_132071_settlement2024_datasets')}
        if len(csv_registry) != 19 or csv_registry != actual_registry or actual_registry != original_registry:
            raise ValueError('Settlement2024 dataset CSV changed original registered metadata')
        for dataset, table, raw in declarations.values():
            role = table['raw_role']
            proof = dataset['output_coverage']
            files = ['fiscal/132071/settlement2024_raw_' + ROLE_TABLE[role] + '.csv', relative]
            if role == 'financial':
                files = ['fiscal/132071/settlement2024_executed.csv'] + files
            elif role in ('controls', 'projects'):
                files = [f'fiscal/132071/settlement2024_{role}.csv'] + files
            proof.update(complete=True, all_original_fields_preserved=True,
                         original_rows=len(raw),
                         immutable_proof_objects=assets['objects_verified'],
                         independent_printed_controls=control_proof)
            proof['files'].extend(files)
            proof['accounts'][next(a['name'] for a in spec['accounts'] if a['id'] == table['account_slug'])] = {
                'original_rows': len(raw)}
    except (ValueError, KeyError, TypeError, OSError, duckdb.Error) as error:
        for row in selected:
            row['output_coverage']['complete'] = False
            row['output_coverage']['errors'].append(str(error))


def printed_controls(roles: dict, records_fn) -> dict:
    """原典が独立に印刷した統制値を、保持された別粒度の行から再計算して一致させる。

    Numeric equality is enforced only where the printed grain is provably the same:
    kan/kou/moku/account totals, the kan summary's account total row, and per-moku
    project-remark sums. Summary-page breakdowns (formal settlement, setsu summary
    variants, real-surplus references) are census-verified printed observations.
    """
    accounts = defaultdict(lambda: defaultdict(list))
    for row in roles['financial']:
        accounts[row['account_id']]['financial'].append(row)
    for row in roles['controls']:
        accounts[row['account_id']]['controls'].append(row)
    for row in roles['projects']:
        accounts[row['account_id']]['projects'].append(row)
    results = []
    for account, grain in sorted(accounts.items()):
        comparisons = 0
        fin = grain['financial']
        if EXPECTED_ACCOUNT_YEN[account] != sum(row['amount_executed'] for row in fin):
            raise ValueError('Financial sum differs from fixed account scope')
        for row in fin + grain['controls']:
            cells = [row['budget_current'], row['amount_executed'], row['carry_continuing'],
                     row['carry_authorized'], row['carry_accident'], row['amount_unspent']]
            if all(cell is not None for cell in cells):
                comparisons += 1
                carry = row['carry_continuing'] + row['carry_authorized'] + row['carry_accident']
                if row['budget_current'] != row['amount_executed'] + carry + row['amount_unspent']:
                    raise ValueError('Printed budget-current arithmetic identity differs')
        kan = defaultdict(int)
        kou = defaultdict(int)
        moku = defaultdict(int)
        for row in fin:
            kan[row['kan_code']] += row['amount_executed']
            kou[(row['kan_code'], row['kou_code'])] += row['amount_executed']
            moku[(row['kan_code'], row['kou_code'], row['moku_code'])] += row['amount_executed']
        project_sums = defaultdict(int)
        for row in grain['projects']:
            project_sums[(row['kan_code'], row['kou_code'], row['moku_code'])] += row['amount_executed']
        project_moku = 0
        for key, amount in project_sums.items():
            if key not in moku:
                raise ValueError('Independent project-remark sum has no matching financial moku')
            comparisons += 1
            project_moku += 1
            if moku[key] != amount:
                raise ValueError('Independent project-remark sum differs from moku executed')
        grain_counts = defaultdict(int)
        equality_by_grain = defaultdict(int)
        for row in grain['controls']:
            grain_counts[row['source_grain']] += 1
            g = row['source_grain']
            if g == 'kan_control':
                if row['kan_code'] not in kan:
                    raise ValueError('Printed kan control has no matching financial kan')
                expected = kan[row['kan_code']]
            elif g == 'kou_control':
                if (row['kan_code'], row['kou_code']) not in kou:
                    raise ValueError('Printed kou control has no matching financial kou')
                expected = kou[(row['kan_code'], row['kou_code'])]
            elif g == 'moku_control':
                if (row['kan_code'], row['kou_code'], row['moku_code']) not in moku:
                    raise ValueError('Printed moku control has no matching financial moku')
                expected = moku[(row['kan_code'], row['kou_code'], row['moku_code'])]
            elif g == 'account_kan_summary_control':
                if row['kan_code'] is None:
                    expected = EXPECTED_ACCOUNT_YEN[account]
                else:
                    if row['kan_code'] not in kan:
                        raise ValueError('Printed kan summary row has no matching financial kan')
                    expected = kan[row['kan_code']]
            elif g in ('account_control', 'account_overview_control'):
                expected = EXPECTED_ACCOUNT_YEN[account]
            else:
                expected = None  # summary-page breakdown: preserved printed observation, census-only
            if expected is not None:
                comparisons += 1
                equality_by_grain[g] += 1
                if expected != row['amount_executed']:
                    raise ValueError('Independent printed ' + g + ' differs from financial sum')
        budget_identity = comparisons - project_moku - sum(equality_by_grain.values())
        results.append(dict(account=account, financial_rows=len(fin), control_rows=len(grain['controls']),
                            project_rows=len(grain['projects']), comparisons=comparisons,
                            budget_identity_checks=budget_identity, project_moku_checks=project_moku,
                            equality_checks_by_grain=dict(equality_by_grain),
                            census_only_control_rows={g: c for g, c in grain_counts.items()
                                                      if g not in ('kan_control', 'kou_control', 'moku_control',
                                                                   'account_control', 'account_overview_control',
                                                                   'account_kan_summary_control')},
                            control_grains=dict(grain_counts), errors=[]))
    totals = {g: sum(r['equality_checks_by_grain'].get(g, 0) for r in results)
              for g in ('kan_control', 'kou_control', 'moku_control',
                        'account_control', 'account_overview_control', 'account_kan_summary_control')}
    if (totals['kan_control'] != 44 or totals['kou_control'] != 89 or totals['moku_control'] != 186
            or totals['account_control'] + totals['account_overview_control'] != 12
            or totals['account_kan_summary_control'] != 50):
        raise ValueError('Documented independent control census differs')
    return dict(accounts=results, equality_checks_by_grain=totals,
                project_moku_checks=sum(r['project_moku_checks'] for r in results),
                budget_identity_checks=sum(r['budget_identity_checks'] for r in results),
                errors=[])
