"""Audit Mitaka independent project/setsu grains through exact typed CSV output."""

from importlib import import_module as _ingestion_module
from collections import defaultdict
import json, re, subprocess
from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, source_metadata
records = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.native_settlement_coverage').records
schema_of = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.settlement2019_coverage').schema_of
RAW_FIELDS = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_initial_native_coverage').RAW_FIELDS
_csv = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_initial_native_coverage')._csv
_equal_rows = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_initial_native_coverage')._equal_rows
_indexed = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_initial_native_coverage')._indexed
NAMESPACE = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_supplementary_registry').NAMESPACE
COLUMNS = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_supplementary_registry').COLUMNS
registered_specs = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_supplementary_registry').registered_specs
input_path = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_supplementary_registry').input_path
fields = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_supplementary_registry').fields
definition_files = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_supplementary_registry').definition_files
STAGING = 'stg_132047__supplementary_native'
INTERMEDIATE = 'int_132047__supplementary_native'

def output_coverage(connection, candidate, hashes, lock_path, datasets):
    entries = [e for e in read_lock(lock_path)['entries'] if e['path'].startswith(NAMESPACE + '/')]
    declared = records(
        connection,
        "select * from int_fiscal_datasets where json_extract_string(source_json,'$.namespace')=?",
        [NAMESPACE],
    )
    if not entries and (not declared):
        return
    expected = {(s['source']['id'], t['table_id']): (s, t) for s in registered_specs() for t in s['tables']}
    bound = set()
    raw = {}
    meta = {}
    selected = []
    definitions = definition_files()
    datasets_by_id = _indexed(datasets, 'dataset_id')
    registry = _indexed(declared, 'dataset_id')
    for row in declared:
        coverage_dataset = datasets_by_id.get(row['dataset_id'])
        if coverage_dataset is None:
            coverage_dataset = dict(row)
            datasets.append(coverage_dataset)
        else:
            coverage_dataset.update(row)
        coverage_dataset['output_coverage'] = {
            'complete': False,
            'files': [],
            'accounts': {},
            'errors': [],
            'original_rows': 0,
            'all_original_fields_preserved': False,
            'model': INTERMEDIATE,
        }
        coverage_dataset['_phase_lines'] = {}
        selected.append(coverage_dataset)
    try:
        schemas = {m: schema_of(connection, m) for m in (STAGING, INTERMEDIATE)}
        for entry in entries:
            original = source_metadata(lock_path, entry)
            key = (original['source_key'], original['table_id'])
            if key not in expected or key in bound:
                raise ValueError('Mitaka raw input repeated or undeclared')
            bound.add(key)
            spec, table = expected[key]
            table['edition_index'] = spec['edition_index']
            expected_fields = fields(spec, table, definitions)
            identity = f"132047:{spec['edition']['fiscal_year']}:expenditure:supplementary:{entry['originEdition']}:{table['table_id']}"
            if (
                identity not in registry
                or entry['path'] != input_path(spec['source'], table)
                or entry['originEdition'] != spec['source']['content_inspection']['sha256']
                or any((original.get(k) != v for k, v in expected_fields.items()))
            ):
                raise ValueError('Mitaka raw scope/approval/phase differs from SSOT')
            decl = json.loads(registry[identity]['source_json'])
            for k, v in {
                'rawRowCount': original['rows'],
                'rawTableSha256': entry['table']['sha256'],
                'rawTableBytes': entry['table']['bytes'],
                'approvalProof': spec['approval'],
                'phases': [],
                'financialPhase': None,
                'sourceAmountKind': 'supplementary',
                'canonicalChanges': table['observation_role'] == 'project_delta',
                'projectSetsuLinkage': 'independent_breakdowns',
                'firstArticleEvidence': original['first_article_evidence'],
                'printedTotal': original['printed_total'],
            }.items():
                if decl.get(k) != v:
                    raise ValueError('Mitaka declaration/raw contract differs: ' + k)
            path = OBJECTS / safe_relative(entry['table']['key'])
            body = path.read_bytes()
            if digest(body) != entry['table']['sha256'] or len(body) != entry['table']['bytes']:
                raise ValueError('Mitaka fixed raw bytes differ')
            query = 'select * from read_parquet(?,hive_partitioning=false)'
            schema = {r[0]: r[1] for r in connection.execute('describe ' + query, [str(path)]).fetchall()}
            if schema != COLUMNS or tuple(schema) != RAW_FIELDS:
                raise ValueError('Mitaka raw14 schema/order differs')
            values = records(connection, query + ' order by source_row', [str(path)])
            if len(values) != original['rows']:
                raise ValueError('Mitaka raw row count differs')
            for model in (STAGING, INTERMEDIATE):
                if any((schemas[model].get(k) != v for k, v in schema.items())):
                    raise ValueError('Mitaka staging/int typed raw differs')
                actual = records(
                    connection,
                    'select ' + ','.join(RAW_FIELDS) + ' from ' + model + ' where dataset_id=? order by source_row',
                    [identity],
                )
                if actual != values:
                    raise ValueError('Mitaka raw14 values/NULL/order/multiplicity differs')
            raw[identity] = values
            meta[identity] = original
        if bound != set(expected) or set(raw) != set(registry):
            raise ValueError('Mitaka four-role populations differ')
        for model in (STAGING, INTERMEDIATE):
            if {r['dataset_id'] for r in records(connection, 'select distinct dataset_id from ' + model)} != set(raw):
                raise ValueError('Mitaka model dataset population differs')
        _outputs(connection, candidate, hashes, raw, meta, selected, expected)
        for coverage_dataset in selected:
            coverage_dataset['output_coverage'].update(complete=True, all_original_fields_preserved=True)
    except Exception as error:
        for coverage_dataset in selected:
            coverage_dataset['output_coverage']['errors'].append(str(error))
        raise

def _outputs(c, candidate, hashes, raw, meta, selected, specs):
    models = {
        'project_observations': ('fiscal_132047_supplementary_native_observations', 'supplementary_native_observations'),
        'left_setsu_observations': (
            'fiscal_132047_supplementary_native_left_setsu_observations',
            'supplementary_native_left_setsu_observations',
        ),
        'left_setsu_delta': ('fiscal_132047_supplementary_native_left_setsu', 'supplementary_native_left_setsu'),
    }
    csvrows = {}
    master = records(c, 'select * from fiscal_expenditure_setsu_master')
    verified_originals = set()
    articles = {}
    for identity, metadata in meta.items():
        spec = specs[metadata['source_key'], metadata['table_id']][0]
        key = (metadata['origin_sha256'], spec['edition_index'])
        if key not in articles:
            original = OBJECTS / f"inputs/origin/sha256/{metadata['origin_sha256']}"
            if metadata['origin_sha256'] not in verified_originals:
                body = original.read_bytes()
                inspection = spec['source']['content_inspection']
                if digest(body) != inspection['sha256'] or len(body) != inspection['bytes']:
                    raise ValueError('Mitaka article original bytes differ')
                verified_originals.add(metadata['origin_sha256'])
            articles[key] = _article_evidence(original, spec)
        if (
            metadata.get('first_article_evidence') != articles[key]
            or metadata.get('printed_total') != articles[key]['amount_delta']
        ):
            raise ValueError('Mitaka article evidence differs from independently located original on a raw role')
    for role, (model, name) in models.items():
        csvmodel = 'csv_132047_' + name
        path = 'fiscal/132047/' + name + '.csv'
        data = _csv(c, candidate, hashes, path, csvmodel)
        _equal_rows(data, records(c, 'select * from ' + model), 'Mitaka mart/CSV ' + role)
        csvrows[role] = data
    changes = records(c, 'select * from fiscal_132047_supplementary_native_changes')
    items = _indexed(records(c, 'select * from fiscal_132047_supplementary_native_items'), 'budget_item_id')
    financial = {i for i, m in meta.items() if m['observation_role'] == 'project_delta'}
    if any((r['dataset_id'] not in financial for r in changes)):
        raise ValueError('Mitaka observation/left-root became project change')
    allcsv = _csv(
        c,
        candidate,
        hashes,
        'fiscal/132047/expenditure_budget_changes.csv',
        'csv_132047_expenditure_budget_changes',
    )
    _equal_rows([r for r in allcsv if r['dataset_id'] in raw], changes, 'Mitaka financial actual CSV')
    itemcsv = _csv(
        c,
        candidate,
        hashes,
        'fiscal/132047/expenditure_budget_items.csv',
        'csv_132047_expenditure_budget_items',
    )
    _equal_rows(
        [r for r in itemcsv if r['budget_item_id'] in items],
        list(items.values()),
        'Mitaka items actual CSV',
    )
    for identity, rows in raw.items():
        metadata = meta[identity]
        role = metadata['observation_role']
        intermediate_rows = records(c, 'select * from ' + INTERMEDIATE + ' where dataset_id=? order by source_row', [identity])
        coverage_dataset = next((d for d in selected if d['dataset_id'] == identity))
        accounts = {
            'original_rows': len(rows),
            'explicit_moku_setsu': role.startswith('left_setsu'),
            'explicit_project_setsu': False,
            'target_relation_confirmed': False,
            'project_setsu_linkage': 'independent_breakdowns',
            'financial_change_rows': 0,
            'approval_status': metadata['approval_status'],
            'initial_baseline_status': 'unconfirmed',
            'amendment_numbers': ([metadata['amendment_number']] if role in ('project_delta', 'left_setsu_delta') else []),
            'project_outputs': (['fiscal/132047/expenditure_budget_changes.csv'] if role == 'project_delta' else []),
            'setsu_outputs': (
                ['fiscal/132047/supplementary_native_left_setsu.csv']
                if role == 'left_setsu_delta'
                else []
            ),
        }
        if any(
            (
                (
                    json.loads(r['phases_json']) != []
                    or r['source_amount_kind'] != 'supplementary'
                    or r['effective_at'] is not None
                )
                for r in intermediate_rows
            ),
        ):
            raise ValueError('Mitaka signed delta phase/effective date semantics differ')
        if role in ('project_observations', 'left_setsu_observations'):
            exported = sorted([r for r in csvrows[role] if r['dataset_id'] == identity], key=lambda r: r['source_row'])
            if (
                [{k: r[k] for k in RAW_FIELDS} for r in exported] != rows
                or any((r['nonadditive'] is not True for r in exported))
            ):
                raise ValueError('Mitaka observation CSV raw/NULL/order differs')
        if role == 'project_delta':
            project_changes = sorted([r for r in changes if r['dataset_id'] == identity], key=lambda r: r['source_row'])
            if len(project_changes) != len(rows):
                raise ValueError('Mitaka project change rows differ')
            observation_dataset_id = identity.removesuffix('-project_delta') + '-project_observations'
            observations_by_row = _indexed(raw[observation_dataset_id], 'source_row')
            for source, intermediate_row, change in zip(rows, intermediate_rows, project_changes):
                original = observations_by_row[source['source_observation_row']]
                if any((source[k] != original[k] for k in RAW_FIELDS if k not in ('source_row', 'source_grain'))):
                    raise ValueError('Mitaka financial root source observation differs')
                item = items.get(change['budget_item_id'])
                detail = json.loads(change['details_json'])
                if (
                    change['amount_delta'] != source['amount'] * 1000
                    or intermediate_row['expenditure_setsu_id'] is not None
                    or item is None
                    or item['expenditure_setsu_id'] is not None
                    or item['initial_state'] != 'unconfirmed'
                    or len(detail) != 1
                    or detail[0]['rawOriginal'] != source
                    or detail[0]['statutorySetsuId'] is not None
                ):
                    raise ValueError('Mitaka project amount/raw/NULL target differs')
                if change['effective_at'] is not None:
                    raise ValueError('Mitaka effective date inferred from approval')
                context = json.loads(source['context_json'])
                project = context.get('project')
                project_row = project.get('row') if project else None
                expected_details = [
                    {
                        'sourceRow': r['source_row'],
                        'physicalPage': r['physical_page'],
                        'rawOriginal': r,
                        'nonadditive': True,
                    }
                    for r in raw[observation_dataset_id]
                    if (
                        project_row is not None
                        and (json.loads(r['context_json']).get('project') or {}).get('row') == project_row
                    )
                ]
                if detail[0]['printedDetailRows'] != expected_details:
                    raise ValueError('Mitaka nested original detail rows/NULL/order differ')
            accounts['financial_change_rows'] = len(project_changes)
        if role == 'left_setsu_delta':
            left_setsu_rows = sorted([r for r in csvrows[role] if r['dataset_id'] == identity], key=lambda r: r['source_row'])
            if len(left_setsu_rows) != len(rows):
                raise ValueError('Mitaka separate left root rows differ')
            for source, intermediate_row, row in zip(rows, intermediate_rows, left_setsu_rows):
                context = json.loads(source['context_json'])
                printed = context['setsu']
                year = intermediate_row['fiscal_year']
                clean = lambda value: re.sub('[、，,・･]', '', value)
                matches = [
                    v
                    for v in master
                    if (
                        v['code'] == printed['code'].zfill(2)
                        and clean(v['label']) == clean(printed['label'])
                        and (v['valid_from_fiscal_year'] is None or v['valid_from_fiscal_year'] <= year)
                        and (v['valid_to_fiscal_year'] is None or v['valid_to_fiscal_year'] >= year)
                    )
                ]
                expected = matches[0]['expenditure_setsu_id'] if len(matches) == 1 else None
                if expected != context['printed_record_context']['legal_setsu_master_id']:
                    raise ValueError('Mitaka raw judgment differs from independently recomputed active legal master')
                if (
                    row['amount_delta'] != source['amount'] * 1000
                    or json.loads(row['raw_original_json']) != source
                    or row['expenditure_setsu_id'] != expected
                    or row['nonadditive'] is not True
                ):
                    raise ValueError('Mitaka independent left root/master/NULL differs')
        if role == 'project_observations':
            spec = specs[metadata['source_key'], metadata['table_id']][0]
            total = articles[metadata['origin_sha256'], spec['edition_index']]['amount_delta']
            financial_rows = raw[identity.removesuffix('-project_observations') + '-project_delta']
            if (
                total != metadata['first_article_evidence']['amount_delta']
                or total != metadata['printed_total']
                or total != sum((r['amount'] for r in financial_rows))
            ):
                raise ValueError('Mitaka original article/project total differs')
            moku = {}
            project_sum = defaultdict(int)
            setsu_sum = defaultdict(int)
            for r in rows:
                row_context = json.loads(r['context_json'])
                moku_context = row_context.get('moku')
                key = tuple(moku_context['key']) if moku_context else None
                if r['record_kind'] == 'moku':
                    if (
                        moku_context['before'] + moku_context['delta'] != moku_context['after']
                        or r['amount'] != moku_context['delta']
                    ):
                        raise ValueError('Mitaka printed moku before/delta/after differs')
                    moku[key] = moku_context
                if r['record_kind'] == 'left-setsu' and r['amount'] is not None:
                    setsu_sum[key] += r['amount']
            for r in raw[identity.removesuffix('-project_observations') + '-project_delta']:
                project_sum[tuple(json.loads(r['context_json'])['moku']['key'])] += r['amount']
            for key, moku_context in moku.items():
                if (
                    project_sum[key] != moku_context['delta']
                    or (moku_context['label'] != '予備費' and setsu_sum[key] != moku_context['delta'])
                ):
                    raise ValueError('Mitaka independent moku/project/left-setsu controls differ')
        coverage_dataset['output_coverage'].update(
            original_rows=len(rows),
            all_original_fields_preserved=True,
            accounts={metadata['fund_label']: accounts},
            files=(
                [models[role][1] + '.csv']
                if role in models
                else [
                    'fiscal/132047/expenditure_budget_changes.csv',
                    'fiscal/132047/expenditure_budget_items.csv',
                ]
            ),
        )

def _article_evidence(original, spec):
    """Locate the article independently within this edition, not a supplied page."""
    normalize = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').normalize
    number = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').number
    first = spec['edition']['page']
    last = spec['tables'][0]['pages'][0] - 1
    if first > last:
        raise ValueError('Mitaka article range before expenditure detail is empty')
    pages = subprocess.check_output([
        'pdftotext', '-f', str(first), '-l', str(last), '-layout', str(original), '-',
    ]).decode().split('\f')
    if not pages[-1].strip():
        pages.pop()
    if len(pages) != last - first + 1:
        raise ValueError('Mitaka article range physical page count differs')
    articles = []
    for page, text in enumerate(pages, first):
        text = normalize(text)
        printed = re.search(r'歳入歳出それぞれ([△▲−\-\d,]+)千円を(追加|増額|減額)', text)
        if printed and '第1条' in text:
            articles.append({
                'page': page,
                'amount_delta': number(printed[1]) * (-1 if printed[2] == '減額' else 1),
            })
    if len(articles) != 1:
        raise ValueError('Mitaka original has no unique first-article page in the declared edition')
    return articles[0]
