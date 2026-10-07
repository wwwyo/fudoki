"""Direct whole-field checks for the nine split-original Akishima FY2019 settlement resources.

Seven financial (expenditure) tables, eight nonadditive control tables (incl. summary-leaf
reprints), two 事業備考 tables, six nonadditive revenue observations and nine per-original
page inventories retain separate preserved grains. Recognition is NULL/unconfirmed;
revenue executes never enter canonical amounts; no project-to-setsu correspondence is claimed.

Every check is a value-level comparison, not a count. `complete` stays False until
all raw→staging→intermediate→mart→CSV whole-field and independent control-value
checks have actually run for all 32 tables.
"""
from __future__ import annotations
from ingestion.inputs import source_metadata_bytes

from collections import defaultdict
import hashlib
import json
from pathlib import Path

import duckdb

from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, verify_object
from ingestion.fiscal.native_settlement_coverage import records

NAMESPACE = 'akishima-settlement2019'
PACKAGE = Path(__file__).resolve().with_name('akishima_settlement2019')


def verify_implementation_bindings():
    manifest = json.loads((PACKAGE / 'evidence-manifest.json').read_bytes())
    if (manifest.get('namespace') != NAMESPACE
            or manifest.get('schema_version') != 1):
        raise ValueError('Settlement2019 evidence manifest differs')
    checked = {}
    for rel, digest in manifest['bindings'].items():
        body = (PACKAGE / rel).read_bytes()
        actual = hashlib.sha256(body).hexdigest()
        if actual != digest:
            raise ValueError(
                'Settlement2019 implementation binding differs: ' + rel)
        checked[rel] = actual
    return checked
EXPECTED_TOTALS = dict(rows={'financial': 1034, 'controls': 432, 'projects': 489,
                             'revenue': 771, 'page_inventory': 405},
                       executed_yen=71331451314)
EXPECTED_ACCOUNT_YEN = {'general': 45182987385, 'kokuho': 11865363067, 'kaigo': 8995201160,
                        'kouki': 2510249700, 'kukaku': 227799811, 'gesui': 2549850191}
DIR_TOKEN = {'expenditure': 'expenditure', 'revenue': 'revenue', None: 'observation'}
STG_ADDED = {'dataset_id', 'fiscal_line_id', 'document_kind', 'source_role',
             'original_table_id', 'source_json'}
INT_ADDED = {'amount', 'currency', 'mapped_expenditure_setsu_id', 'legal_mapping_status',
             'project_setsu_linkage', 'recognition_bill', 'recognition_date',
             'recognition_status', 'account_path_json', 'dimensions_json',
             'original_raw_and_staging_json', 'reference_amount_yen',
             'canonical_phase', 'canonical_financial_amount'}


def indexed(rows: list[dict]) -> dict:
    result = {row['source_row_id']: row for row in rows}
    if len(result) != len(rows):
        raise ValueError('Repeated settlement2019 original observation')
    return result


def typed_csv(connection, candidate: Path, relative: str, relation: str,
              hashes: dict) -> list[dict]:
    if relative not in hashes:
        raise ValueError('Settlement2019 typed CSV absent from verified artifacts: ' + relative)
    types = {row[0]: row[1] for row in connection.execute(
        'describe select * from ' + relation).fetchall()}
    return records(connection,
        "select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')",
        [str(candidate / relative), types])


def schema_of(connection, relation: str) -> dict:
    return {row[0]: row[1] for row in connection.execute(
        'describe select * from ' + relation).fetchall()}


def fieldmap(rows: list[dict]) -> dict:
    return {row['source_row_id']: row for row in rows}


def row_equal(a: dict, b: dict, fields) -> bool:
    return all(a.get(f) == b.get(f) for f in fields)


def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path,
                    datasets: list[dict]) -> None:
    entries = [entry for entry in read_lock(lock_path)['entries']
               if entry['path'].startswith(NAMESPACE + '/')]
    if not entries:
        return
    from ingestion.fiscal.akishima_settlement2019_registry import specs
    from ingestion.fiscal.extract_akishima_settlement2019 import MANIFEST, PKG
    selected = [row for row in datasets
                if json.loads(row['source_json']).get('namespace') == NAMESPACE]
    for row in selected:
        row['output_coverage'] = dict(complete=False, files=[], accounts={}, errors=[],
                                      original_rows=0, all_original_fields_preserved=False,
                                      project_legal_setsu_correspondence='unconfirmed')
        row['_phase_lines'] = {}
    try:
        spec = specs()[0]
        expected = {table['logical_path']: table for table in spec['tables']}
        origins = {o['file']: o for o in spec['originals']}
        registered = {row['dataset_id']: row for row in selected}
        if len(entries) != 32:
            raise ValueError('Exact adopted32 settlement2019 lock entries missing or repeated')
        # the normal audit passes only direction='expenditure' registrations
        # (17 = 7 financial + 8 controls + 2 projects); revenue/page_inventory
        # entries are still fully checked at raw/object/provenance level.
        expected_selected = {t['logical_path'] for t in spec['tables']
                             if t['direction'] == 'expenditure'}
        passed = {row['dataset_id'] for row in selected}
        if len(selected) != len(expected_selected) or passed != {
                ':'.join(('132071', '2019', DIR_TOKEN[t['direction']], 'settlement',
                          t['origin_sha256'], t['table_id']))
                for t in spec['tables'] if t['direction'] == 'expenditure'}:
            raise ValueError('Settlement2019 expenditure registrations missing or repeated')
        manifest = json.loads(MANIFEST.read_bytes())
        bound = verify_implementation_bindings()
        if digest((PKG / 'config.json').read_bytes()) != bound['config.json']:
            raise ValueError('Git source declaration differs from immutable accepted input')
        # Append the registrations the normal caller did not pass (revenue and
        # page_inventory). Rows come from the actual int_datasets relation —
        # spec-derived stand-ins are never used — so all 32 datasets leave a
        # persisted output_coverage record in the audit result.
        actual_datasets = records(connection, 'select * from int_132071_settlement2019_datasets')
        for row in actual_datasets:
            if row['dataset_id'] in registered:
                continue
            source = json.loads(row['source_json'])
            added = dict(dataset_id=row['dataset_id'], jurisdiction_code=row['jurisdiction_code'],
                         fiscal_year=row['fiscal_year'], direction=row['direction'],
                         document_kind=row['document_kind'], origin_sha256=row['origin_sha256'],
                         structure_json=row['structure_json'], source_json=row['source_json'],
                         phases_json=row['phases_json'], line_count=row['line_count'])
            added['output_coverage'] = dict(complete=False, files=[], accounts={}, errors=[],
                                            original_rows=0, all_original_fields_preserved=False,
                                            project_legal_setsu_correspondence='unconfirmed')
            added['_phase_lines'] = {}
            datasets.append(added)
            registered[added['dataset_id']] = added
        roles = defaultdict(list)
        raw_by_table = {}
        for entry in entries:
            table = expected[entry['path']]
            provenance = json.loads(source_metadata_bytes(lock_path, entry))
            if provenance['sha256'] != entry['originEdition']:
                raise ValueError('Settlement2019 provenance/origin edition differs')
            if entry['originEdition'] != table['origin_sha256']:
                raise ValueError('Settlement2019 entry/table origin edition differs')
            role = table['raw_role']
            did = ':'.join(('132071', '2019', DIR_TOKEN[table['direction']],
                            'settlement', table['origin_sha256'], table['table_id']))
            dataset = registered.get(did)
            if dataset is None:
                raise ValueError('Adopted settlement2019 dataset missing: ' + table['table_id'])
            source = json.loads(dataset['source_json']) if dataset is not None else None
            if dataset is not None and (entry['jurisdiction'] != '132071' or entry['fiscalYear'] != 2019
                    or entry['documentKind'] != 'settlement' or entry['direction'] != table['direction']
                    or source['url'] != table['origin_url'] or source['sha256'] != table['origin_sha256']
                    or source['originalBytes'] != table['origin_bytes']
                    
                    or source['rawTableSha256'] != entry['table']['sha256']
                    or source['rawTableBytes'] != entry['table']['bytes']
                    or source['rawRowCount'] != table['expected_rows']
                    or dataset['line_count'] != table['expected_rows']
                    or source['sourceAmountUnit'] != '円' or source['unitMultiplier'] != 1
                    or source['observationRole'] != role
                    or source['canonicalExecuted'] != (role == 'financial')
                    or source['nonadditive'] != (role != 'financial')
                    or source['recognitionStatus'] != 'unconfirmed'
                    or json.loads(dataset['phases_json']) != (['executed'] if role == 'financial' else [])):
                raise ValueError('Settlement2019 original/recognition/phase/unit/role identity differs')
            for reference in (entry['origin']['object'], entry['table']):
                verify_object(reference, (OBJECTS / safe_relative(reference['key'])).read_bytes())
            raw_path = str(OBJECTS / safe_relative(entry['table']['key']))
            raw = records(connection,
                          'select * from read_parquet(?,hive_partitioning=false)', [raw_path])
            declared = {c['name']: c['type'] for c in table['schema']}
            raw_schema = {row[0]: row[1] for row in connection.execute(
                'describe select * from read_parquet(?,hive_partitioning=false)', [raw_path]).fetchall()}
            if raw_schema != declared:
                raise ValueError('Settlement2019 raw schema differs from declaration: ' + table['table_id'])
            indexed(raw)
            if (len(raw) != table['expected_rows']
                    or any(not row['source_row_id'].startswith(table['table_id'] + ':')
                           or row['source_table_id'] != table['table_id']
                           or row['source_row_ordinal'] != int(row['source_row_id'].split(':')[-1])
                           for row in raw)):
                raise ValueError('Settlement2019 raw row/ordinal/table identity differs')
            for row in raw:
                if (row['original_sha256'] != table['origin_sha256'] or row['fiscal_year'] != 2019
                        or row['original_url'] != table['origin_url']
                        or row['original_file'] != table['origin_file']
                        or row['original_bytes'] != table['origin_bytes']):
                    raise ValueError('Settlement2019 original row identity differs')
                if role == 'financial' and row['executed'] is None:
                    raise ValueError('Settlement2019 financial row missing executed amount')
            roles[role].extend(raw)
            raw_by_table[table['table_id']] = raw
            if dataset is not None:
                dataset['output_coverage']['files'].append(
                    {'raw': raw_path,
                     'logical_path': entry['path']})
        totals = {role: len(rows) for role, rows in roles.items()}
        if totals != EXPECTED_TOTALS['rows']:
            raise ValueError('Settlement2019 role totals differ')
        if sum(row['executed'] for row in roles['financial']) != EXPECTED_TOTALS['executed_yen']:
            raise ValueError('Settlement2019 executed total differs')
        accounts = defaultdict(int)
        for row in roles['financial']:
            accounts[row['account_id']] += row['executed']
        if dict(accounts) != EXPECTED_ACCOUNT_YEN:
            raise ValueError('Settlement2019 per-account executed totals differ')
        # raw→staging whole-field value compare per role (1:1 by source_row_id)
        for role, rows in roles.items():
            relation = 'stg_132071__settlement2019_' + role
            staged = records(connection, 'select * from ' + relation)
            if len(staged) != len(rows):
                raise ValueError('Settlement2019 staged rows not 1:1: ' + relation)
            stg_map = fieldmap(staged)
            if set(stg_map) != {row['source_row_id'] for row in rows}:
                raise ValueError('Settlement2019 staged row identity differs: ' + relation)
            stg_schema = schema_of(connection, relation)
            original_fields = list(rows[0])
            if any(f not in stg_schema for f in original_fields):
                raise ValueError('Settlement2019 staging drops original fields: ' + relation)
            for row in rows:
                st = stg_map[row['source_row_id']]
                if not row_equal(row, st, original_fields):
                    raise ValueError('Settlement2019 staged values differ: ' + row['source_row_id'])
                if (st['fiscal_line_id'] != st['dataset_id'] + ':' + str(row['source_row_ordinal'])
                        or st['document_kind'] != 'settlement' or st['source_role'] != role
                        or st['original_table_id'] != row['source_table_id']):
                    raise ValueError('Settlement2019 staged lineage differs')
        # intermediate whole-value checks
        fin_map = {row['source_row_id']: row for row in roles['financial']}
        executed = records(connection, 'select * from int_132071_settlement2019_executed')
        if len(executed) != len(fin_map):
            raise ValueError('Settlement2019 int_executed not 1:1')
        def _orig_eq(raw: dict, snapshot: dict) -> bool:
            return all(snapshot.get(f) == raw[f] for f in raw)
        for row in executed:
            snapshot = json.loads(row['original_raw_and_staging_json'])
            if not _orig_eq(fin_map[row['source_row_id']], snapshot):
                raise ValueError('Settlement2019 int original JSON does not restore raw fields 1:1')
            fr = fin_map[row['source_row_id']]
            if (row['amount'] != fr['executed'] or row['currency'] != 'JPY'
                    or row['recognition_bill'] is not None or row['recognition_date'] is not None
                    or row['recognition_status'] != 'unconfirmed'
                    or row['project_setsu_linkage'] != 'unconfirmed'
                    or row['legal_mapping_status'] not in (
                        'confirmed-printed-code-name-active-year',
                        'unconfirmed-blank-reserve-row',
                        'unconfirmed-printed-name-master-conflict')):
                raise ValueError('Settlement2019 int_executed value/phase differs')
        for role, relation, ref_col in (
                ('controls', 'int_132071_settlement2019_controls', 'executed'),
                ('projects', 'int_132071_settlement2019_projects', 'amount'),
                ('page_inventory', 'int_132071_settlement2019_page_inventory', None),
                ('revenue', 'int_132071_settlement2019_revenue_observations', 'executed')):
            rmap = {row['source_row_id']: row for row in roles[role]}
            inter = records(connection, 'select * from ' + relation)
            if len(inter) != len(rmap):
                raise ValueError('Settlement2019 ' + relation + ' not 1:1')
            for row in inter:
                rr = rmap[row['source_row_id']]
                if (row['canonical_phase'] is not None
                        or row['canonical_financial_amount'] is not None
                        or row['project_setsu_linkage'] != 'unconfirmed'):
                    raise ValueError('Settlement2019 nonadditive int canonical fields not NULL')
                if ref_col is not None and row['reference_amount_yen'] != rr[ref_col]:
                    raise ValueError('Settlement2019 int reference amount differs')
                snapshot = json.loads(row['original_raw_and_staging_json'])
                if not _orig_eq(rr, snapshot):
                    raise ValueError('Settlement2019 int original JSON does not restore raw fields 1:1')
        # canonical executed mart: reshaped canonical output columns
        executed = records(connection, 'select * from int_132071_settlement2019_executed')
        mart = records(connection, 'select * from fiscal_132071_settlement2019_executed')
        mm = {row['fiscal_line_id']: row for row in mart}
        if len(mart) != len(executed):
            raise ValueError('Settlement2019 executed mart row set differs')
        for row in executed:
            m = mm[row['fiscal_line_id']]
            if (m['dataset_id'] != row['dataset_id'] or m['source_row'] != row['source_row_ordinal']
                    or m['amount'] != row['amount'] or m['fund_label'] != row['account_name']
                    or m['fund_code'] != '' or m['consolidation'] is not None
                    or m['counterpart_fund'] is not None or m['cofog_code'] is not None
                    or m['cofog_status'] != 'unclassified'):
                raise ValueError('Settlement2019 executed mart canonical fields differ')
            details = json.loads(m['details_json'])
            if (len(details) != 1 or details[0]['amount'] != row['amount']
                    or details[0]['fiscalLineId'] != row['fiscal_line_id']
                    or details[0]['originalSourceRowIdentity'] != row['source_row_id']
                    or details[0]['rawOriginal'] != json.loads(row['original_raw_and_staging_json'])):
                raise ValueError('Settlement2019 executed mart detail lost original identity')
        # passthrough marts = int whole-row compare
        for n in ('controls', 'projects', 'page_inventory',
                  'revenue_observations', 'datasets'):
            inter = records(connection, 'select * from int_132071_settlement2019_' + n)
            mart = records(connection, 'select * from fiscal_132071_settlement2019_' + n)
            key = 'fiscal_line_id' if n != 'datasets' else 'dataset_id'
            mm = {row[key]: row for row in mart}
            if len(mart) != len(inter):
                raise ValueError('Settlement2019 mart/int row set differs: ' + n)
            for row in inter:
                if row != mm[row[key]]:
                    raise ValueError('Settlement2019 mart value differs: ' + n)
        ds_rows = records(connection, 'select * from int_132071_settlement2019_datasets')
        if len(ds_rows) != 32:
            raise ValueError('Settlement2019 int datasets not 32')
        expected_ids = {':'.join(('132071', '2019', DIR_TOKEN[t['direction']],
                                  'settlement', t['origin_sha256'], t['table_id']))
                        for t in spec['tables']}
        for row in ds_rows:
            source = json.loads(row['source_json'])
            if (row['dataset_id'] not in expected_ids
                    or source['provider'] != 'akishima-settlement2019'
                    or json.loads(row['phases_json']) != (['executed'] if source['canonicalExecuted'] else [])):
                raise ValueError('Settlement2019 int dataset identity differs')
        # typed CSV compares at the canonical artifact relative paths
        for role in roles:
            rel = 'csv_132071_settlement2019_raw_' + role
            csv_rows = typed_csv(connection, candidate,
                                 'fiscal/132071/settlement2019_raw_' + role + '.csv',
                                 rel, hashes)
            if {row['source_row_id']: row for row in csv_rows} != {
                    row['source_row_id']: row for row in records(
                        connection, 'select * from ' + rel)}:
                raise ValueError('Settlement2019 raw typed CSV original NULL/value differs: ' + role)
        for n in ('executed', 'controls', 'projects', 'page_inventory',
                  'revenue_observations', 'datasets'):
            mart = records(connection, 'select * from fiscal_132071_settlement2019_' + n)
            rel = 'csv_132071_settlement2019_' + n
            csv_rows = typed_csv(connection, candidate,
                                 'fiscal/132071/settlement2019_' + n + '.csv',
                                 rel, hashes)
            if len(csv_rows) != len(mart):
                raise ValueError('Settlement2019 CSV row count differs: ' + n)
            key = 'fiscal_line_id' if n != 'datasets' else 'dataset_id'
            mm = {row[key]: row for row in mart}
            for row in csv_rows:
                if row != mm[row[key]]:
                    raise ValueError('Settlement2019 CSV typed value differs: ' + n)
        # independent printed controls: recompute kan/kou/moku executed sums from
        # the financial detail and compare to the printed control values
        detail = defaultdict(int)
        for row in roles['financial']:
            for grain, key in (
                    ('kan', (row['account_id'], row['kan_code'])),
                    ('kou', (row['account_id'], row['kan_code'], row['kou_code'])),
                    ('moku', (row['account_id'], row['kan_code'], row['kou_code'], row['moku_code']))):
                detail[(grain, key)] += row['executed'] or 0
        # a printed control with a code that does not join detail is acceptable
        # only when a sibling printed control for the same
        # (account,kan,kou,name,executed) DOES reconcile (summary-leaf reprint
        # ordinals are preserved as independent observations, not errors)
        printed_siblings = defaultdict(list)
        for row in roles['controls']:
            printed_siblings[(row['account_id'], row['kan_code'], row['kou_code'],
                            row['row_name'], row['executed'])].append(row)
        mismatches = []
        for row in roles['controls']:
            if row['grain'] == 'moku' and row['executed'] is not None:
                key = ('moku', (row['account_id'], row['kan_code'], row['kou_code'], row['moku_code']))
                if detail.get(key, 0) != row['executed']:
                    sib = printed_siblings[(row['account_id'], row['kan_code'], row['kou_code'],
                                            row['row_name'], row['executed'])]
                    def _k(other):
                        g = other['grain']
                        base = (other['account_id'], other['kan_code'])
                        if g == 'kou': base += (other['kou_code'],)
                        if g == 'moku': base += (other['kou_code'], other['moku_code'])
                        return (g, base)
                    if not any(other is not row and detail.get(_k(other), 0) == row['executed']
                               for other in sib):
                        mismatches.append((key, row['executed'], detail.get(key, 0)))
            elif row['grain'] == 'kou' and row['executed'] is not None:
                key = ('kou', (row['account_id'], row['kan_code'], row['kou_code']))
                if detail.get(key, 0) != row['executed']:
                    sib = printed_siblings[(row['account_id'], row['kan_code'], row['kou_code'],
                                            row['row_name'], row['executed'])]
                    def _k(other):
                        g = other['grain']
                        base = (other['account_id'], other['kan_code'])
                        if g == 'kou': base += (other['kou_code'],)
                        if g == 'moku': base += (other['kou_code'], other['moku_code'])
                        return (g, base)
                    if not any(other is not row and detail.get(_k(other), 0) == row['executed']
                               for other in sib):
                        mismatches.append((key, row['executed'], detail.get(key, 0)))
            elif row['grain'] == 'kan' and row['executed'] is not None:
                key = ('kan', (row['account_id'], row['kan_code']))
                if detail.get(key, 0) != row['executed']:
                    sib = printed_siblings[(row['account_id'], row['kan_code'], row['kou_code'],
                                            row['row_name'], row['executed'])]
                    def _k(other):
                        g = other['grain']
                        base = (other['account_id'], other['kan_code'])
                        if g == 'kou': base += (other['kou_code'],)
                        if g == 'moku': base += (other['kou_code'], other['moku_code'])
                        return (g, base)
                    if not any(other is not row and detail.get(_k(other), 0) == row['executed']
                               for other in sib):
                        mismatches.append((key, row['executed'], detail.get(key, 0)))
        if mismatches:
            raise ValueError('Settlement2019 printed control values differ: ' + str(mismatches[:5]))
        for entry in entries:
            table = expected[entry['path']]
            did = ':'.join(('132071', '2019', DIR_TOKEN[table['direction']],
                            'settlement', table['origin_sha256'], table['table_id']))
            dataset = registered.get(did)
            if dataset is None:
                continue
            dataset['output_coverage'].update(
                complete=True,
                original_rows=len(raw_by_table[table['table_id']]),
                all_original_fields_preserved=True,
                accounts={table['account_slug']: len(raw_by_table[table['table_id']])}
                if table['account_slug'] else {})
    except Exception as exc:
        for row in selected:
            row['output_coverage']['errors'].append(str(exc))
        raise
