"""Verify adopted Tama native initial-budget rows through typed public CSVs."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path

from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, source_metadata_bytes
from ingestion.fiscal.native_settlement_coverage import records
from ingestion.fiscal.settlement2019_coverage import schema_of, typed_csv

from ingestion.fiscal.tama_budget_detail import NAMESPACE, PROVIDER
RAW_FIELDS = ('source_row', 'source_observation_row', 'record_kind', 'code', 'label',
              'amount', 'amount_text', 'physical_page', 'bbox_json', 'printed_text',
              'words_json', 'context_json', 'source_grain', 'printed_setsu_code')
STAGING = 'stg_132241__initial_native'
INTERMEDIATE = 'int_132241__initial_native'
LINES = 'fiscal_132241_initial_native_lines'
ITEMS = 'fiscal_132241_initial_native_items'
OBSERVATIONS = 'fiscal_132241_initial_native_observations'


def _token(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _equal_rows(actual: list[dict], expected: list[dict], label: str) -> None:
    if Counter(map(_token, actual)) != Counter(map(_token, expected)):
        raise ValueError(label + ': typed rows/NULL/multiplicity differ')


def _indexed(rows: list[dict], key: str) -> dict:
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError('Repeated ' + key)
    return result


def _csv(connection, candidate: Path, hashes: dict, relative: str, relation: str) -> list[dict]:
    if relative not in hashes or digest((candidate / relative).read_bytes()) != hashes[relative]:
        raise ValueError('CSV differs from verified artifacts: ' + relative)
    rows = typed_csv(connection, candidate, relative, relation, hashes)
    _equal_rows(rows, records(connection, 'select * from ' + relation), relative)
    return rows


def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path,
                    datasets: list[dict]) -> None:
    entries = [e for e in read_lock(lock_path)['entries'] if e['path'].startswith(NAMESPACE + '/')]
    registry = records(connection, "select * from int_fiscal_datasets where "
                       "json_extract_string(source_json,'$.namespace')=?", [NAMESPACE])
    if not entries and not registry:
        return
    registered = _indexed(registry, 'dataset_id')
    existing = _indexed(datasets, 'dataset_id')
    selected = []
    for identity, row in registered.items():
        if identity in existing:
            dataset = existing[identity]
            dataset.update(row)
        else:
            dataset = row
            datasets.append(dataset)
        dataset['output_coverage'] = dict(complete=False, files=[], errors=[], accounts={},
            original_rows=0, all_original_fields_preserved=False, model=INTERMEDIATE)
        dataset['_phase_lines'] = {}
        selected.append(dataset)
    try:
        from ingestion.fiscal.tama_budget_detail import registered_specs
        expected_tables = {}
        for spec in registered_specs():
            for table in spec['tables']:
                key = (spec['source']['id'], table['table_id'])
                if key in expected_tables:
                    raise ValueError('Repeated native initial ingestion declaration')
                expected_tables[key] = (spec, table)
        bound_tables = set()
        staging_schema = schema_of(connection, STAGING)
        expected_ids = set()
        raw_by_dataset = {}
        metadata = {}
        for entry in entries:
            original = json.loads(source_metadata_bytes(lock_path, entry))
            table_id = original['table_id']
            table_key = (original['source_key'], table_id)
            if table_key not in expected_tables or table_key in bound_tables:
                raise ValueError('Native fixed input differs from registered ingestion tables')
            bound_tables.add(table_key)
            spec, table = expected_tables[table_key]
            source = spec['source']
            if (entry['jurisdiction'] != source['jurisdiction'] or entry['fiscalYear'] != source['fiscal_year'] or
                entry['direction'] != 'expenditure' or entry['documentKind'] != 'budget' or
                entry['originEdition'] != source['content_inspection']['sha256'] or
                original['fund_label'] != table['account'] or original['pages'] != table['pages'] or
                original['observation_role'] != table['observation_role'] or
                original['request_url'] != source['download_url'] or
                original['landing_page'] != source['landing_url']):
                raise ValueError('Native lock origin/account/year/pages differ from source registry')
            identity = ':'.join([entry['jurisdiction'], str(entry['fiscalYear']),
                                entry['direction'], entry['documentKind'], entry['originEdition'], table_id])
            if identity in expected_ids:
                raise ValueError('Repeated native initial lock dataset')
            expected_ids.add(identity)
            if identity not in registered:
                raise ValueError('Native initial lock dataset absent from registry: ' + identity)
            dataset = existing.get(identity, registered[identity])
            sj = json.loads(dataset['source_json'])
            financial = original['observation_role'] == 'expenditure'
            expected_phase = ['approved'] if financial else []
            binds = {'namespace': NAMESPACE, 'provider': PROVIDER, 'tableId': table_id,
                     'fundLabel': original['fund_label'], 'sha256': entry['originEdition'],
                     'rawRowCount': original['rows'], 'pages': original['pages'],
                     'financialPhase': original['financial_phase'],
                     'canonicalInitial': original['canonical_initial'],
                     'approvalProof': original['approval_proof'], 'nonadditive': original['nonadditive']}
            for key, value in binds.items():
                if sj.get(key) != value:
                    raise ValueError(f'{identity}: {key} differs from fixed input')
            if (dataset['jurisdiction_code'] != entry['jurisdiction'] or
                dataset['fiscal_year'] != entry['fiscalYear'] or dataset['direction'] != entry['direction'] or
                dataset['document_kind'] != entry['documentKind'] or
                dataset['origin_sha256'] != entry['originEdition'] or
                dataset['line_count'] != original['rows'] or
                json.loads(dataset['phases_json']) != expected_phase):
                raise ValueError('Native initial dataset scope/phase differs from lock')
            if financial and (sj.get('financialPhase') != 'approved' or
                              sj.get('canonicalInitial') is not True or not sj.get('approvalProof')):
                raise ValueError('Native initial financial approval declaration absent')
            if not financial and (sj.get('financialPhase') is not None or
                                  sj.get('canonicalInitial') is True or sj.get('nonadditive') is not True):
                raise ValueError('Native observations acquired additive financial meaning')
            path = OBJECTS / safe_relative(entry['table']['key'])
            raw_query = 'select * from read_parquet(?,hive_partitioning=false)'
            raw = records(connection, raw_query + ' order by source_row', [str(path)])
            raw_schema = {r[0]: r[1] for r in connection.execute('describe ' + raw_query, [str(path)]).fetchall()}
            if tuple(raw_schema) != RAW_FIELDS:
                raise ValueError('Native raw column order/schema changed')
            if [r['source_row'] for r in raw] != list(range(1, len(raw) + 1)):
                raise ValueError('Native raw row order is not contiguous')
            first, last = original['pages']
            if any(not first <= r['physical_page'] <= last for r in raw):
                raise ValueError('Native row escaped declared physical pages')
            fields = ','.join(RAW_FIELDS)
            stg = records(connection, f'select {fields} from {STAGING} where dataset_id=? order by source_row', [identity])
            if any(staging_schema.get(f) != t for f, t in raw_schema.items()):
                raise ValueError('Native staging raw types changed')
            if raw != stg:
                raise ValueError('Native staging row order/values/NULL differ')
            raw_by_dataset[identity] = raw
            metadata[identity] = original
            dataset['output_coverage'].update(original_rows=len(raw), files=[entry['path'] + '/data.parquet'])
        if bound_tables != set(expected_tables) or expected_ids != set(registered):
            raise ValueError('Native registry/lock dataset sets differ')
        staged = records(connection, f'select distinct dataset_id from {STAGING}')
        if {r['dataset_id'] for r in staged} != expected_ids:
            raise ValueError('Native staging dataset set differs')
        _verify_outputs(connection, candidate, hashes, selected, raw_by_dataset, metadata)
        for dataset in selected:
            dataset['output_coverage'].update(complete=True, all_original_fields_preserved=True)
    except Exception as error:
        for dataset in selected:
            dataset['output_coverage']['errors'].append(str(error))
        raise


def _verify_outputs(connection, candidate, hashes, selected, raw_by_dataset, metadata) -> None:
    from ingestion.fiscal.coverage_audit import label
    from ingestion.fiscal.tama_budget_detail import reconcile
    provided_datasets = {r['dataset_id']:r for r in records(connection,'select * from fiscal_datasets')}
    for identity, original in metadata.items():
        expected_kind = 'initial' if original['observation_role'] == 'expenditure' else None
        if identity not in provided_datasets or provided_datasets[identity]['source_amount_kind'] != expected_kind:
            raise ValueError('Native dataset amount kind differs from its financial/observation role')
    controls = {}
    for identity, original in metadata.items():
        if original['observation_role'] != 'observations':
            continue
        observations = [dict(r, **json.loads(r['context_json']),
                             location=dict(page=r['physical_page'], bbox=json.loads(r['bbox_json'])))
                        for r in raw_by_dataset[identity]]
        expected, control = reconcile(observations, [])
        financial_id = identity.removesuffix('-observations') + '-expenditure'
        if not control['complete_observed_grain'] or control['amount'] != original['printed_total']:
            raise ValueError('Native independently printed project/moku/left-setsu controls differ')
        if [r['source_row'] for r in expected] != [r['source_observation_row'] for r in raw_by_dataset[financial_id]]:
            raise ValueError('Native financial rows do not preserve reconciled original leaves')
        by_observation = {r['source_row']:r for r in raw_by_dataset[identity]}
        expected_financial = [dict(by_observation[r['source_row']],source_row=n,
            source_grain=r['source_grain'],printed_setsu_code=r['printed_setsu_code'])
            for n,r in enumerate(expected,1)]
        if expected_financial != raw_by_dataset[financial_id]:
            raise ValueError('Native financial fields differ from independently reconciled observations')
        controls[financial_id] = control
    leaves = records(connection, 'select * from ' + INTERMEDIATE + ' order by dataset_id,source_row')
    financial_ids = {identity for identity, original in metadata.items()
                     if original['observation_role'] == 'expenditure'}
    raw_leaves = {(identity, r['source_row']): r for identity in financial_ids for r in raw_by_dataset[identity]}
    actual_leaves = {(r['dataset_id'], r['source_row']): r for r in leaves}
    if len(actual_leaves) != len(leaves) or set(actual_leaves) != set(raw_leaves):
        raise ValueError('Native financial leaves missing/repeated/extra')
    left = defaultdict(list)
    for identity, rows in raw_by_dataset.items():
        if metadata[identity]['observation_role'] != 'observations':
            continue
        financial_id = identity.removesuffix('-observations') + '-expenditure'
        for row in rows:
            if row['record_kind'] == 'left-setsu' and row['code'] is not None:
                context = json.loads(row['context_json'])
                left[(financial_id, _token(context['moku']['key']), int(row['code']))].append(row)
    master = records(connection, 'select * from fiscal_expenditure_setsu_master')
    groups = defaultdict(list)
    intermediate_schema = schema_of(connection, INTERMEDIATE)
    staging_schema = schema_of(connection, STAGING)
    if any(intermediate_schema[f] != staging_schema[f] for f in RAW_FIELDS):
        raise ValueError('Native intermediate changed original types')
    for key, leaf in actual_leaves.items():
        raw = raw_leaves[key]
        original = metadata[key[0]]
        if leaf['fiscal_line_id'] != key[0] + ':' + str(key[1]):
            raise ValueError('Native financial original line ID changed')
        if (leaf['jurisdiction_code'], leaf['fiscal_year'], leaf['fund_label'], leaf['fund_code']) != (
                original['jurisdiction_code'], original['fiscal_year'], original['fund_label'], None):
            raise ValueError('Native financial leaf account/year/jurisdiction changed')
        if {f: leaf[f] for f in RAW_FIELDS} != raw:
            raise ValueError('Native intermediate changed original fields/types')
        if leaf['initial_yen'] != raw['amount'] * metadata[key[0]]['unit_multiplier']:
            raise ValueError('Native financial unit multiplier/amount differs')
        if any(json.loads(leaf['raw_original_json'])[f] != raw[f] for f in RAW_FIELDS):
            raise ValueError('Native rawOriginal changed original fields')
        context = json.loads(raw['context_json'])
        hierarchy = [dict(level=level, code=context[level][0], label=context[level][1], nameSource='origin')
                     for level in ('kan', 'kou')]
        hierarchy += [dict(level=level, code=context[level]['code'], label=context[level]['label'], nameSource='origin')
                      for level in ('moku', 'project')]
        dimensions = [dict(dimension='department', code=None, label=context['department'])]
        if json.loads(leaf['account_path_json']) != hierarchy or json.loads(leaf['dimensions_json']) != dimensions:
            raise ValueError('Native financial hierarchy/dimensions differ from original')
        observation_id = key[0].removesuffix('-expenditure') + '-observations'
        observation = raw_by_dataset[observation_id][raw['source_observation_row'] - 1]
        if any(raw[f] != observation[f] for f in RAW_FIELDS
               if f not in ('source_row','source_grain','printed_setsu_code')):
            raise ValueError('Native financial leaf does not match its original observation')
        code = raw['printed_setsu_code']
        if code is None:
            if any(leaf[f] is not None for f in ('left_setsu_code', 'left_setsu_label', 'expenditure_setsu_id')):
                raise ValueError('Unprinted reserve acquired statutory setsu')
        else:
            choices = left[(key[0], _token(context['moku']['key']), int(code))]
            if len(choices) != 1:
                raise ValueError('Printed right code lacks unique same-moku left setsu')
            left_row = choices[0]
            normalize = lambda label: label.replace('、', '').replace('・', '')
            matches = [r for r in master if int(r['code']) == int(code) and
                       normalize(r['label']) == normalize(left_row['label']) and
                       (r['valid_from_fiscal_year'] is None or r['valid_from_fiscal_year'] <= leaf['fiscal_year']) and
                       (r['valid_to_fiscal_year'] is None or r['valid_to_fiscal_year'] >= leaf['fiscal_year'])]
            if len(matches) != 1 or (leaf['left_setsu_code'], leaf['left_setsu_label'], leaf['expenditure_setsu_id']) != (
                    int(code), left_row['label'], matches[0]['expenditure_setsu_id']):
                raise ValueError('Native statutory setsu code/name/year differs')
        target = dict(identityNamespace='tama-initial-printed-target', datasetId=key[0],
                      hierarchy=hierarchy, dimensions=dimensions, legalSetsuId=leaf['expenditure_setsu_id'],
                      originLine=leaf['fiscal_line_id'] if leaf['expenditure_setsu_id'] is None else None)
        if json.loads(leaf['target_identity_json']) != target:
            raise ValueError('Native grouped target identity differs from original')
        if leaf['budget_item_id'] != 'b-' + digest(leaf['target_identity_json'].encode()):
            raise ValueError('Native budget item ID differs from its target identity')
        groups[(leaf['dataset_id'], leaf['budget_item_id'])].append(leaf)
    lines = records(connection, 'select * from ' + LINES)
    by_group = {(r['dataset_id'], r['budget_item_id']): r for r in lines}
    if len(by_group) != len(lines) or set(by_group) != set(groups):
        raise ValueError('Native grouped financial line set differs')
    for key, members in groups.items():
        line = by_group[key]
        if line['fiscal_line_id'] != 'tama-' + key[1]:
            raise ValueError('Native grouped financial line ID changed')
        details = json.loads(line['details_json'])
        if line['amount'] != sum(r['initial_yen'] for r in members):
            raise ValueError('Native grouped amount differs')
        if [d['sourceRow'] for d in details] != sorted(r['source_row'] for r in members):
            raise ValueError('Native detail order/multiplicity differs')
        by_row = _indexed(details, 'sourceRow')
        if line['source_row'] != min(r['source_row'] for r in members):
            raise ValueError('Native grouped representative original row differs')
        for leaf in members:
            detail = by_row[leaf['source_row']]
            expected = dict(fiscalLineId=leaf['fiscal_line_id'], sourceObservationRow=leaf['source_observation_row'],
                amount=leaf['initial_yen'], physicalPage=leaf['physical_page'], bbox=json.loads(leaf['bbox_json']),
                leftSetsuCode=leaf['left_setsu_code'], leftSetsuName=leaf['left_setsu_label'],
                statutorySetsuId=leaf['expenditure_setsu_id'], targetIdentity=json.loads(leaf['target_identity_json']))
            expected['path'] = json.loads(leaf['account_path_json'])
            if any(detail[k] != v for k, v in expected.items()) or any(
                    detail['rawOriginal'][f] != leaf[f] for f in RAW_FIELDS):
                raise ValueError('Native financial detail lost original leaf/target/position')
    items = _indexed(records(connection, 'select * from ' + ITEMS), 'budget_item_id')
    if set(items) != {key[1] for key in groups}:
        raise ValueError('Native item/group set differs')
    for leaf in leaves:
        item = items[leaf['budget_item_id']]
        for field in ('jurisdiction_code', 'fiscal_year', 'fund_code', 'fund_label', 'expenditure_setsu_id',
                      'line_granularity', 'account_path_json', 'dimensions_json'):
            if item[field] != leaf[field]:
                raise ValueError('Native budget item identity differs: ' + field)
    line_csv = _csv(connection, candidate, hashes, 'fiscal/132241/initial_expenditure_budget.csv', 'csv_132241_initial_expenditure_budget')
    csv_lines = _indexed([r for r in line_csv if r['dataset_id'] in financial_ids], 'fiscal_line_id')
    if set(csv_lines) != {r['fiscal_line_id'] for r in lines}:
        raise ValueError('Native canonical CSV line set differs')
    for line in lines:
        if any(csv_lines[line['fiscal_line_id']][f] != v for f, v in line.items()):
            raise ValueError('Native canonical CSV changed financial line')
    item_csv = _csv(connection, candidate, hashes, 'fiscal/132241/expenditure_budget_items.csv', 'csv_132241_expenditure_budget_items')
    csv_items = _indexed([r for r in item_csv if r['budget_item_id'] in items], 'budget_item_id')
    _equal_rows(list(csv_items.values()), list(items.values()), 'Native canonical item CSV')
    observation_csv = _csv(connection, candidate, hashes, 'fiscal/132241/initial_native_observations.csv', OBSERVATIONS)
    expected_observations = []
    for identity, rows in raw_by_dataset.items():
        if identity in financial_ids:
            continue
        for raw in rows:
            expected_observations.append(dict(raw, table_id=metadata[identity]['table_id'], dataset_id=identity,
                fiscal_line_id=identity + ':' + str(raw['source_row']), nonadditive=True))
    _equal_rows(observation_csv, expected_observations, 'Native nonadditive observation CSV')
    for dataset in selected:
        identity = dataset['dataset_id']
        if identity in financial_ids:
            dataset['output_coverage']['independent_printed_controls'] = controls[identity]
        dataset['output_coverage']['accounts'][label(metadata[identity]['fund_label'])] = dict(
            original_rows=len(raw_by_dataset[identity]),
            explicit_moku_setsu=False, explicit_project_setsu=False,
            printed_code_correspondence_verified=identity in financial_ids,
            statutory_setsu_null_rows=sum(r['printed_setsu_code'] is None for r in raw_by_dataset[identity])
                if identity in financial_ids else None)
        dataset['output_coverage']['files'].extend(
            ['fiscal/132241/initial_expenditure_budget.csv', 'fiscal/132241/expenditure_budget_items.csv']
            if dataset['dataset_id'] in financial_ids else ['fiscal/132241/initial_native_observations.csv'])
