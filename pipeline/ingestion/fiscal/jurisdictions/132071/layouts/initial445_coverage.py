"""Direct whole-field checks for eight fixed Akishima initial editions.

Explanation leaves, independently printed controls and left legal observations
retain separate grains. Preservation never establishes their correspondence.
"""
from __future__ import annotations

from importlib import import_module as _ingestion_module
from ingestion.inputs import source_metadata_bytes

from collections import defaultdict
import json
from pathlib import Path

import duckdb

from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, verify_object
records = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.native_settlement_coverage').records

NAMESPACE = 'akishima-initial445'
ROLES = {'explanation': 'explanation', 'controls': 'controls', 'left-legal': 'left_legal'}


def indexed(rows: list[dict]) -> dict:
    result = {row['source_row_id']: row for row in rows}
    if len(result) != len(rows):
        raise ValueError('Repeated initial445 original observation')
    return result


def printed_controls(roles: dict, configs: dict) -> dict:
    results = []
    for sha, config in configs.items():
        leaves, controls, left = (roles[role][sha] for role in ROLES)
        path = lambda row: tuple(row[level + '_code'] for level in ('kan', 'kou', 'moku'))
        by_path = defaultdict(list)
        for row in leaves:
            by_path[path(row)].append(row)
        article = config['first_article']['amount']
        if sum(row['amount'] for row in leaves) != article:
            raise ValueError('Explanation sum differs from independent first article')
        counts = defaultdict(int)
        left_controls = []
        for row in controls:
            kind = row['control_kind']
            counts[kind] += 1
            extra = json.loads(row['extra_evidence'])
            codes = json.loads(row['path_codes'])
            children = None
            if kind in ('first-article', 'account-total', 'first-budget-summary-account-total'):
                children = leaves
            elif kind == 'coded-moku':
                children = by_path[tuple(codes)]
                reserve = all(child['source_grain'] == 'printed-moku-reserve' for child in children)
                if not reserve and sum(child['amount'] for child in left if path(child) == tuple(codes)) != row['amount']:
                    raise ValueError('Independent left legal sum differs from coded moku')
            elif kind in ('printed-project', 'printed-setsu'):
                field = 'project_control_node_id' if kind == 'printed-project' else 'setsu_control_node_id'
                children = [child for child in leaves if child[field] == extra['node_id']]
            elif kind in ('first-budget-summary-kan', 'first-budget-summary-kou') and all(codes):
                children = [child for child in leaves if path(child)[:len(codes)] == tuple(codes)]
            elif kind == 'printed-left-setsu':
                left_controls.append((tuple(codes), extra['printed_code'], row['amount']))
            if children is not None and sum(child['amount'] for child in children) != row['amount']:
                raise ValueError('Independent printed hierarchy/project/setsu control differs')
            if 'printed_previous' in extra and row['amount'] - extra['printed_previous'] != extra['printed_comparison']:
                raise ValueError('Independently printed previous/comparison arithmetic differs')
        if sorted(left_controls) != sorted((path(row), row['printed_code'], row['amount']) for row in left):
            raise ValueError('Independent left observations/control occurrences differ')
        expected = config['expected_counts']
        if (len(leaves) != expected['leaf_rows'] or len(left) != expected['left_legal_setsu_controls']
                or sum(row['source_grain'] == 'printed-moku-reserve' for row in leaves) != expected['reserve_rows']
                or counts['coded-moku'] != expected['coded_moku_controls']
                or counts['printed-project'] != expected['project_controls']
                or counts['printed-setsu'] != expected['setsu_controls']
                or counts['printed-current-prior-comparison'] != expected['printed_comparison_controls']
                or sum(count for kind, count in counts.items() if kind.startswith('first-budget-summary-')) != expected['first_budget_summary_controls']
                or counts['first-article'] != 1 or counts['account-total'] != 1):
            raise ValueError('Fixed independent printed control census differs')
        results.append(dict(origin_sha256=sha, explanation_rows=len(leaves), control_rows=len(controls),
                            left_rows=len(left), approved_initial_thousand_yen=article, errors=[]))
    if (sum(r['explanation_rows'] for r in results), sum(r['control_rows'] for r in results),
            sum(r['left_rows'] for r in results)) != (445, 786, 183):
        raise ValueError('Fixed eight-edition source-row scope differs')
    return dict(editions=results, errors=[])


def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path,
                    datasets: list[dict]) -> None:
    entries = [entry for entry in read_lock(lock_path)['entries']
               if entry['path'].startswith(NAMESPACE + '/')]
    if not entries:
        return
    specs = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_initial445_registry').specs
    PACKAGE = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.extract_akishima_initial445').PACKAGE
    MANIFEST = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.extract_akishima_initial445').MANIFEST
    RepoBundle = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.extract_akishima_initial445').RepoBundle

    selected = [row for row in datasets if json.loads(row['source_json']).get('namespace') == NAMESPACE]
    for row in selected:
        row['output_coverage'] = dict(complete=False, files=[], accounts={}, errors=[],
            original_rows=0, all_original_fields_preserved=False,
            project_legal_setsu_correspondence='unconfirmed')
        row['_phase_lines'] = {}
    try:
        specifications = specs()
        expected = {table['logical_path']: (spec, table) for spec in specifications for table in spec['tables']}
        registered = {row['dataset_id']: row for row in selected}
        if len(entries) != 24 or len(selected) != 24 or len(registered) != 24:
            raise ValueError('Exact adopted24 initial445 registrations missing or repeated')
        manifest = json.loads(MANIFEST.read_bytes())
        bundle = RepoBundle(OBJECTS, manifest)
        assets = bundle.validate_all()
        configs_list = bundle.json('config/editions.json')
        if digest((PACKAGE / 'editions.json').read_bytes()) != manifest['bindings']['config/editions.json']:
            raise ValueError('Git source declaration differs from immutable accepted input')
        bundle.observed_scope(configs_list)
        configs = {config['identity']['prior_sha256']: config for config in configs_list}
        roles = {role: defaultdict(list) for role in ROLES}
        raw_by_role = defaultdict(list)
        declarations = {}
        for entry in entries:
            spec, table = expected[entry['path']]
            provenance = json.loads(source_metadata_bytes(lock_path, entry))
            identity = ':'.join(('132071', str(spec['fiscal_year']), 'expenditure', 'budget',
                                  spec['expected_sha256'], table['table_id']))
            dataset = registered[identity]
            source = json.loads(dataset['source_json'])
            financial = table['raw_role'] == 'explanation'
            if (entry['jurisdiction'] != '132071' or entry['fiscalYear'] != spec['fiscal_year']
                    or entry['documentKind'] != 'budget' or entry['direction'] != 'expenditure'
                    or entry['originEdition'] != spec['expected_sha256']
                    or source['url'] != spec['url'] or source['sha256'] != spec['expected_sha256']
                     or source['rawTableSha256'] != entry['table']['sha256']
                    or source['rawRowCount'] != table['expected_rows'] or dataset['line_count'] != table['expected_rows']
                    or source['approvalProof'] != spec['approval'] or source['approvalDate'] != spec['approval_date']
                    or source['printedSubmissionDate'] != spec['submitted_date']
                    or source['sourceAmountUnit'] != '千円' or source['unitMultiplier'] != 1000
                    or source['canonicalInitial'] != financial or source['nonadditive'] == financial
                    or json.loads(dataset['phases_json']) != (['approved'] if financial else [])
                    or provenance['request_url'] != spec['url'] or provenance['table_id'] != table['table_id']
                    or provenance['rows'] != table['expected_rows'] or provenance['approval_proof'] != spec['approval']
                    or entry['table']['sha256'] != table['expected_table_sha256']):
                raise ValueError('Initial445 original/approval/phase/unit/role identity differs')
            for reference in (entry['origin']['object'], entry['table']):
                verify_object(reference, (OBJECTS / safe_relative(reference['key'])).read_bytes())
            raw = records(connection, 'select * from read_parquet(?,hive_partitioning=false)',
                          [str(OBJECTS / safe_relative(entry['table']['key']))])
            indexed(raw)
            if len(raw) != table['expected_rows'] or any(
                    not row['source_row_id'].startswith(spec['expected_sha256'] + ':') for row in raw):
                raise ValueError('Initial445 raw row count/whole-original occurrence differs')
            if {row['source_row'] for row in raw} != set(range(1, len(raw) + 1)):
                raise ValueError('Initial445 original ordinals missing or repeated')
            for row in raw:
                if (row['origin_sha256'] != spec['expected_sha256'] or row['source_url'] != spec['url']
                        or row['fiscal_year'] != spec['fiscal_year'] or row['account_name'] != spec['account']
                        or row['amount_unit'] != '千円' or row['approval_date'] != spec['approval_date']
                        or row['submitted_date'] != spec['submitted_date']):
                    raise ValueError('Initial445 original row edition/unit/approval differs')
            roles[table['raw_role']][spec['expected_sha256']].extend(raw)
            raw_by_role[table['raw_role']].extend(raw)
            declarations[identity] = (dataset, table, raw)
        for role, raw in raw_by_role.items():
            suffix = ROLES[role]
            original = indexed(raw)
            fields = list(raw[0])
            for relation in ('stg_132071__initial445_' + suffix,
                             'int_132071_initial445' + ('' if role == 'explanation' else '_' + suffix),
                             'csv_132071_initial445_raw_' + suffix):
                provided = indexed(records(connection, 'select * from ' + relation))
                if provided.keys() != original.keys() or any(
                        {field: provided[key][field] for field in fields} != row for key, row in original.items()):
                    raise ValueError('Initial445 original field/occurrence differs in ' + relation)
            intermediate = 'int_132071_initial445' + ('' if role == 'explanation' else '_' + suffix)
            processed = indexed(records(connection, 'select * from ' + intermediate))
            for key, row in processed.items():
                if role == 'explanation':
                    if (row['printed_setsu_code'] is not None or row['statutory_setsu_id'] is not None
                            or row['expenditure_setsu_id'] is not None or row['initial_yen'] != row['amount'] * 1000):
                        raise ValueError('Explanation acquired an unsupported code or changed unit')
                elif row['canonical_phase'] is not None or row['canonical_financial_amount'] is not None:
                    raise ValueError('Independent initial control acquired a financial contribution')
                if role == 'left-legal' and row['independently_validated_statutory_setsu_id'] != row['statutory_setsu_id']:
                    raise ValueError('Independent left code/full-name/year mapping changed')
            resources = [('initial445_raw_' + suffix, 'csv_132071_initial445_raw_' + suffix)]
            if role != 'explanation':
                resources.append(('initial445_reference_' + suffix, 'csv_132071_initial445_reference_' + suffix))
            for resource, relation in resources:
                relative = 'fiscal/132071/' + resource + '.csv'
                if relative not in hashes:
                    raise ValueError('Initial445 typed CSV absent from verified artifacts')
                types = {row[0]: row[1] for row in connection.execute('describe select * from ' + relation).fetchall()}
                provided = indexed(records(connection, 'select * from ' + relation))
                csv = indexed(records(connection,
                    "select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')",
                    [str(candidate / relative), types]))
                if csv != provided:
                    raise ValueError('Initial445 typed CSV original NULL/value differs')
            for dataset, table, raw in declarations.values():
                if table['raw_role'] == role:
                    dataset['output_coverage']['files'] = ['fiscal/132071/' + name + '.csv' for name, _ in resources]
                    dataset['output_coverage']['original_rows'] = len(raw)
        financial = records(connection, 'select l.*, i.source_row_id, i.original_raw_and_staging_json, i.initial_yen '
                            'from fiscal_132071_initial445_lines l join int_132071_initial445 i using(fiscal_line_id)')
        if len(financial) != 445:
            raise ValueError('Initial445 canonical financial occurrences differ')
        for row in financial:
            details = json.loads(row['details_json'])
            if (len(details) != 1 or details[0]['rawOriginal'] != json.loads(row['original_raw_and_staging_json'])
                    or row['amount'] != row['initial_yen'] or details[0]['amount'] != row['amount']
                    or details[0]['fiscalLineId'] != row['fiscal_line_id']):
                raise ValueError('Initial445 canonical detail lost original fields or monetary identity')
        for resource, key, condition in (
                ('initial_expenditure_budget', 'fiscal_line_id',
                 'dataset_id in (select dataset_id from int_132071_initial445_datasets)'),
                ('expenditure_budget_items', 'budget_item_id',
                 'budget_item_id in (select budget_item_id from int_132071_initial445)')):
            relation = 'csv_132071_' + resource
            relative = 'fiscal/132071/' + resource + '.csv'
            if relative not in hashes:
                raise ValueError('Initial445 canonical CSV absent from verified artifacts')
            types = {row[0]: row[1] for row in connection.execute('describe select * from ' + relation).fetchall()}
            actual = records(connection, 'select * from ' + relation + ' where ' + condition)
            csv = records(connection,
                "select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='') where " + condition,
                [str(candidate / relative), types])
            by_identity = lambda rows: {row[key]: row for row in rows}
            if len(actual) != 445 or len(csv) != 445 or len(by_identity(actual)) != 445 or by_identity(actual) != by_identity(csv):
                raise ValueError('Initial445 canonical typed CSV row/NULL/target differs')
            original = {row[key]: row for row in records(connection,
                        'select * from ' + ('fiscal_132071_initial445_lines' if key == 'fiscal_line_id'
                                             else 'int_132071_initial445_budget_items'))}
            for row in actual:
                if any(row[field] != value for field, value in original[row[key]].items()):
                    raise ValueError('Initial445 canonical CSV lost original detail/target/amount')
        refs = records(connection, "select m.*, i.phases_json from fiscal_datasets m "
                       "join int_fiscal_datasets i using(dataset_id) where json_extract_string(m.source_json,'$.namespace')=?", [NAMESPACE])
        if len(refs) != 24 or sum(row['source_amount_kind'] is None and row['phases_json'] == '[]' for row in refs) != 16:
            raise ValueError('Initial445 independent datasets acquired phase/amount kind')
        relative = 'fiscal/132071/initial445_datasets.csv'
        relation = 'csv_132071_initial445_datasets'
        if relative not in hashes:
            raise ValueError('Initial445 dataset CSV absent from verified artifacts')
        types = {row[0]: row[1] for row in connection.execute('describe select * from ' + relation).fetchall()}
        csv = records(connection,
            "select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')",
            [str(candidate / relative), types])
        csv_registry = {row['dataset_id']: row for row in csv}
        actual = records(connection, 'select * from ' + relation)
        actual_registry = {row['dataset_id']: row for row in actual}
        if len(csv) != 24 or len(actual) != 24 or csv_registry != actual_registry:
            raise ValueError('Initial445 dataset CSV source/phase/unit/NULL differs')
        original_registry = {row['dataset_id']: row for row in records(connection,
                             'select * from int_132071_initial445_datasets')}
        if actual_registry != original_registry:
            raise ValueError('Initial445 dataset CSV changed original registered metadata')
        control_proof = printed_controls(roles, configs)
        for dataset, table, raw in declarations.values():
            proof = dataset['output_coverage']
            proof.update(complete=True, all_original_fields_preserved=True,
                         immutable_proof_objects=assets['objects_verified'],
                         independent_printed_controls=control_proof)
            proof['files'].append(relative)
            if table['raw_role'] == 'explanation':
                proof['files'].extend(['fiscal/132071/initial_expenditure_budget.csv',
                                       'fiscal/132071/expenditure_budget_items.csv'])
    except (ValueError, KeyError, TypeError, OSError, duckdb.Error) as error:
        for row in selected:
            row['output_coverage']['complete'] = False
            row['output_coverage']['errors'].append(str(error))
