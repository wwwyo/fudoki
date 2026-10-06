"""Verify separate printed amendment observations and finite approved project deltas.

Passing this adapter does not establish project/setsu or initial-target correspondence.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, source_metadata_bytes
from ingestion.fiscal.chiyoda_budget_changes import COLUMNS, NAMESPACE, input_path
from ingestion.fiscal.native_settlement_coverage import records
from ingestion.fiscal.settlement2019_coverage import schema_of, typed_csv
from ingestion.fiscal.tama_initial_native_coverage import _equal_rows, _indexed

STAGING = 'stg_131016__supplementary_native'
INTERMEDIATE = 'int_131016__supplementary_native'
OBSERVATIONS = 'fiscal_131016_supplementary_native_observations'
CHANGES = 'fiscal_131016_supplementary_native_changes'
ITEMS = 'fiscal_131016_supplementary_native_items'


def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path,
                    datasets: list[dict]) -> None:
    entries = [e for e in read_lock(lock_path)['entries'] if e['path'].startswith(NAMESPACE + '/')]
    registered = _indexed(records(connection, "select * from int_fiscal_datasets where "
        "json_extract_string(source_json,'$.namespace')=?", [NAMESPACE]), 'dataset_id')
    if not entries and not registered:
        return
    existing = _indexed(datasets, 'dataset_id')
    selected = []
    for identity, row in registered.items():
        dataset = existing.get(identity)
        if dataset is None:
            dataset = dict(row)
            datasets.append(dataset)
        else:
            dataset.update(row)
        dataset['output_coverage'] = dict(complete=False, files=[], accounts={}, errors=[],
            original_rows=0, all_original_fields_preserved=False, model=INTERMEDIATE)
        dataset['_phase_lines'] = {}
        selected.append(dataset)
    try:
        from ingestion.fiscal.chiyoda_budget_changes import registered_specs
        specs = {s['source']['id']: s for s in registered_specs()}
        fields = ','.join(COLUMNS)
        schemas = {model: schema_of(connection, model)
                   for model in (STAGING, INTERMEDIATE, OBSERVATIONS)}
        for model, schema in schemas.items():
            if any(schema.get(f) != t for f, t in COLUMNS.items()):
                raise ValueError('Native supplementary raw types differ: ' + model)
        raw_by_id, metadata, expected_changes, intermediate_rows = {}, {}, {}, {}
        for entry in entries:
            original = json.loads(source_metadata_bytes(lock_path, entry))
            spec = specs[original['source_key']]
            source, approval = spec['source'], spec['approval']
            table = spec['table']['table_id']
            identity = ':'.join([entry['jurisdiction'], str(entry['fiscalYear']),
                entry['direction'], entry['documentKind'], entry['originEdition'], table])
            if identity in raw_by_id or identity not in registered:
                raise ValueError('Native supplementary dataset repeated or absent')
            dataset = next(d for d in selected if d['dataset_id'] == identity)
            declaration = json.loads(dataset['source_json'])
            approved = approval is not None
            phase = ['adjusted'] if approved else []
            number = source['amendment_numbers'][0]
            expected_path = input_path(source)
            if (entry['path'] != expected_path or entry['jurisdiction'] != source['jurisdiction'] or
                entry['fiscalYear'] != source['fiscal_year'] or entry['direction'] != 'expenditure' or
                entry['documentKind'] != 'supplementary' or
                entry['originEdition'] != source['content_inspection']['sha256'] or
                original['table_id'] != table or original['request_url'] != source['download_url'] or
                original['amendment_number'] != number or original['fund_label'] != '一般会計' or
                original['source_amount_unit'] != '千円' or original['unit_multiplier'] != 1000 or
                original['pages'] != [1, source['content_inspection']['pages']] or
                original['approval_status'] != ('approved' if approved else 'unconfirmed') or
                original['project_setsu_linkage'] != 'unconfirmed' or
                original['approval_proof'] != approval or
                original['approval_date'] != (approval['date'] if approved else None) or
                original['canonical_changes'] is not approved or original['phases'] != phase or
                original['nonadditive'] is not True):
                raise ValueError('Native supplementary input scope/approval differs from registry')
            binds = dict(namespace=NAMESPACE, tableId=table, sha256=entry['originEdition'],
                rawRowCount=original['rows'], rawSchema=original['raw_schema'],
                rawTableSha256=entry['table']['sha256'], rawTableBytes=entry['table']['bytes'],
                canonicalChanges=approved, approvalStatus=original['approval_status'],
                approvalDate=original['approval_date'], approvalProof=approval, amendmentNumber=number,
                phaseSemantics=original['phase_semantics'], nonadditive=True,
                sourceAmountUnit='千円', unitMultiplier=1000)
            if any(declaration.get(k) != v for k, v in binds.items()):
                raise ValueError('Native supplementary declaration differs from fixed input')
            if (json.loads(dataset['phases_json']) != phase or dataset['line_count'] != original['rows'] or
                dataset['jurisdiction_code'] != '131016' or dataset['fiscal_year'] != 2026 or
                dataset['direction'] != 'expenditure' or dataset['document_kind'] != 'supplementary' or
                dataset['origin_sha256'] != entry['originEdition']):
                raise ValueError('Native supplementary dataset phase/scope differs')
            path = OBJECTS / safe_relative(entry['table']['key'])
            body = path.read_bytes()
            if digest(body) != entry['table']['sha256'] or len(body) != entry['table']['bytes']:
                raise ValueError('Native supplementary fixed table bytes differ')
            query = 'select * from read_parquet(?,hive_partitioning=false)'
            raw_schema = {r[0]: r[1] for r in connection.execute('describe ' + query, [str(path)]).fetchall()}
            if raw_schema != COLUMNS or list(raw_schema) != list(COLUMNS):
                raise ValueError('Native supplementary fixed raw schema/order differs')
            raw = records(connection, query + ' order by source_row', [str(path)])
            if len(raw) != original['rows'] or [r['source_row'] for r in raw] != list(range(1, len(raw)+1)):
                raise ValueError('Native supplementary raw count/order differs')
            for model in (STAGING, INTERMEDIATE, OBSERVATIONS):
                observed = records(connection, f'select {fields} from {model} where dataset_id=? order by source_row', [identity])
                if observed != raw:
                    raise ValueError('Native supplementary ordered raw/NULL rows differ: ' + model)
            intermediate_rows[identity] = _indexed(records(connection,
                f'select * from {INTERMEDIATE} where dataset_id=?', [identity]), 'source_row')
            moku, setsu, projects = {}, defaultdict(int), defaultdict(int)
            for row in raw:
                context = json.loads(row['context_json'])
                leaf = intermediate_rows[identity][row['source_row']]
                if (json.loads(leaf['raw_original_json']) != row or
                    leaf['delta_yen'] != (row['amount_delta']*1000 if row['amount_delta'] is not None else None) or
                    leaf['before_yen'] != (row['amount_before']*1000 if row['amount_before'] is not None else None) or
                    leaf['after_yen'] != (row['amount_after']*1000 if row['amount_after'] is not None else None) or
                    leaf['expenditure_setsu_id'] is not None or leaf['canonical_changes'] is not approved):
                    raise ValueError('Native supplementary intermediate transformation/NULL differs')
                if row['record_kind'] == 'moku_control':
                    if row['amount_before'] + row['amount_delta'] != row['amount_after']:
                        raise ValueError('Native supplementary printed moku arithmetic differs')
                    moku[row['source_row']] = row['amount_delta']
                elif row['record_kind'] in ('setsu_delta', 'project_delta'):
                    target = setsu if row['record_kind'] == 'setsu_delta' else projects
                    target[context['moku']['row']] += row['amount_delta']
                if row['record_kind'] == 'project_delta' and approved:
                    expected_changes[(identity, row['source_row'])] = row
                if len(json.loads(row['bbox_json'])) != 4 or not json.loads(row['words_json']):
                    raise ValueError('Native supplementary original source position absent')
            if set(setsu) - set(moku) or set(projects) - set(moku) or any(
                    setsu.get(key, 0) != amount or projects.get(key, 0) != amount for key, amount in moku.items()):
                raise ValueError('Native supplementary separate printed decompositions differ')
            raw_by_id[identity], metadata[identity] = raw, original
            dataset['output_coverage'].update(original_rows=len(raw), files=[entry['path']+'/data.parquet'],
                independent_printed_controls=dict(moku_delta=sum(moku.values()),
                    setsu_delta=sum(setsu.values()), project_delta=sum(projects.values())))
        if set(raw_by_id) != set(registered) or len(raw_by_id) != 3 or sum(map(len, raw_by_id.values())) != 17:
            raise ValueError('Native supplementary expected three datasets/17 observations differ')
        for model in (STAGING, INTERMEDIATE, OBSERVATIONS):
            actual = records(connection, f'select distinct dataset_id from {model}')
            if {r['dataset_id'] for r in actual} != set(registered):
                raise ValueError('Native supplementary model dataset set differs: ' + model)
        csvs = {}
        for relative, relation in (
            ('fiscal/131016/supplementary_native_observations.csv', 'csv_131016_supplementary_native_observations'),
            ('fiscal/131016/expenditure_budget_changes.csv', 'csv_131016_expenditure_budget_changes'),
            ('fiscal/131016/expenditure_budget_items.csv', 'csv_131016_expenditure_budget_items')):
            if relative not in hashes or digest((candidate/relative).read_bytes()) != hashes[relative]:
                raise ValueError('Native supplementary CSV artifact hash differs: ' + relative)
            csvs[relative] = typed_csv(connection, candidate, relative, relation, hashes)
            _equal_rows(csvs[relative], records(connection, 'select * from '+relation), relative)
        observed_csv = csvs['fiscal/131016/supplementary_native_observations.csv']
        if len(observed_csv) != 17 or any(r['nonadditive'] is not True for r in observed_csv):
            raise ValueError('Native supplementary observation CSV count/nonadditive differs')
        for identity, raw in raw_by_id.items():
            observed = [{f:r[f] for f in COLUMNS} for r in observed_csv if r['dataset_id']==identity]
            _equal_rows(observed, raw, 'Native supplementary actual observation CSV')
        changes = records(connection, 'select * from '+CHANGES)
        actual_changes = {(r['dataset_id'],r['source_row']):r for r in changes}
        if len(actual_changes) != len(changes) or set(actual_changes) != set(expected_changes) or len(changes) != 2:
            raise ValueError('Native supplementary finite approved project changes differ; unknown must be excluded')
        items = _indexed(records(connection, 'select * from '+ITEMS), 'budget_item_id')
        if set(items) != {r['budget_item_id'] for r in changes}:
            raise ValueError('Native supplementary item/change sets differ')
        csv_changes = _indexed(csvs['fiscal/131016/expenditure_budget_changes.csv'], 'change_id')
        csv_items = _indexed(csvs['fiscal/131016/expenditure_budget_items.csv'], 'budget_item_id')
        native_csv_changes = [r for r in csv_changes.values() if r['dataset_id'] in registered]
        _equal_rows(native_csv_changes, changes, 'Native supplementary canonical change dataset set')
        for key, change in actual_changes.items():
            raw, original = expected_changes[key], metadata[key[0]]
            item = items[change['budget_item_id']]
            if (change['amount_delta'] != raw['amount_delta']*1000 or
                change['sequence'] != original['amendment_number'] or
                str(change['effective_at']) != original['approval_date'] or
                item['initial_state'] != 'unconfirmed' or item['line_granularity'] != 'origin_line' or
                item['expenditure_setsu_id'] is not None):
                raise ValueError('Native supplementary change value/approval or unconfirmed item differs')
            if csv_changes.get(change['change_id']) != change or csv_items.get(item['budget_item_id']) != item:
                raise ValueError('Native supplementary canonical CSV changed approved rows')
            leaf = intermediate_rows[key[0]][key[1]]
            for field in ('jurisdiction_code','fiscal_year','fund_code','fund_label',
                          'expenditure_setsu_id','line_granularity','account_path_json','dimensions_json'):
                if item[field] != leaf[field]:
                    raise ValueError('Native supplementary item differs from original identity: '+field)
            context = json.loads(raw['context_json'])
            hierarchy = [dict(level=level,code=context[level][0],label=context[level][1],nameSource='origin')
                         for level in ('kan','kou')]
            hierarchy += [dict(level=level,code=context[level]['code'],label=context[level]['label'],nameSource='origin')
                          for level in ('moku','project')]
            line_id = key[0]+':'+str(key[1])
            target = dict(identityNamespace='chiyoda-supplementary-native-origin-line',
                datasetId=key[0],originLine=line_id,hierarchy=hierarchy,dimensions=[],legalSetsuId=None)
            if (json.loads(item['account_path_json']) != hierarchy or json.loads(item['dimensions_json']) != [] or
                json.loads(leaf['target_identity_json']) != target or
                item['budget_item_id'] != 'b-'+digest(leaf['target_identity_json'].encode()) or
                change['change_id'] != 'c-'+digest(line_id.encode())):
                raise ValueError('Native supplementary printed hierarchy/target identity differs')
            detail = json.loads(change['details_json'])
            if len(detail) != 1 or detail[0]['rawOriginal'] != raw:
                raise ValueError('Native supplementary financial detail lost original raw observation')
            expected_detail = dict(path=hierarchy,dimensions=[],amount=raw['amount_delta']*1000,
                fiscalLineId=line_id,sourceRow=key[1],targetIdentity=target,physicalPage=raw['physical_page'],
                bbox=json.loads(raw['bbox_json']),sourceAmountUnit='千円',unitMultiplier=1000,
                approvalDate=original['approval_date'],approvalProof=original['approval_proof'],
                projectSetsuLinkage='unconfirmed',initialState='unconfirmed')
            if any(detail[0].get(f) != v for f,v in expected_detail.items()):
                raise ValueError('Native supplementary financial detail changed position/meaning/approval')
            children = [r for r in raw_by_id[key[0]] if r['record_kind']=='detail_delta' and
                        json.loads(r['context_json'])['project']['row']==key[1]]
            expected_children = [dict(fiscalLineId=key[0]+':'+str(r['source_row']),sourceRow=r['source_row'],
                amountDelta=r['amount_delta']*1000,rawOriginal=r,physicalPage=r['physical_page'],
                bbox=json.loads(r['bbox_json']),nonadditive=True) for r in children]
            if detail[0]['printedDetailRows'] != expected_children:
                raise ValueError('Native supplementary nested printed detail rows differ')
            dataset = next(d for d in selected if d['dataset_id']==key[0])
            dataset['_phase_lines'][key[1]] = dict(amount=str(change['amount_delta']),fund='一般会計',
                levels=['kan','kou','moku','project'],expenditure_setsu_id=None)
        for dataset in selected:
            identity = dataset['dataset_id']
            count = sum(k[0] == identity for k in expected_changes)
            dataset['output_coverage'].update(complete=True, all_original_fields_preserved=True,
                accounts={'一般会計':dict(original_rows=len(raw_by_id[identity]), financial_change_rows=count,
                    amendment_numbers=[metadata[identity]['amendment_number']],
                    explicit_moku_setsu=False, explicit_project_setsu=False,
                    target_relation_confirmed=False, project_setsu_linkage='unconfirmed',
                    initial_baseline_status='unconfirmed')})
            dataset['output_coverage']['files'].append('fiscal/131016/supplementary_native_observations.csv')
            if count:
                dataset['output_coverage']['files'].extend(['fiscal/131016/expenditure_budget_changes.csv',
                    'fiscal/131016/expenditure_budget_items.csv'])
    except Exception as error:
        for dataset in selected:
            dataset['output_coverage']['errors'].append(str(error))
        raise
