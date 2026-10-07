"""Verify signed printed Tama amendments through their actual typed CSVs."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, source_metadata
from ingestion.fiscal.native_settlement_coverage import records
from ingestion.fiscal.settlement2019_coverage import schema_of
from ingestion.fiscal.tama_initial_native_coverage import RAW_FIELDS, _csv, _equal_rows, _indexed, _token

NAMESPACE = 'tama-supplementary-native'
STAGING = 'stg_132241__supplementary_native'
INTERMEDIATE = 'int_132241__supplementary_native'
CHANGES = 'fiscal_132241_supplementary_native_changes'
ITEMS = 'fiscal_132241_supplementary_native_items'


def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path,
                    datasets: list[dict]) -> None:
    from ingestion.fiscal.tama_supplementary_registry import registered_specs, input_path, _registered_fields
    from ingestion.fiscal.canonical_sources import require_inspected_scopes
    lock = read_lock(lock_path)
    require_inspected_scopes(lock, jurisdiction='132241')
    entries = [e for e in lock['entries'] if e['path'].startswith(NAMESPACE + '/')]
    registered = _indexed(records(connection, "select * from int_fiscal_datasets where "
        "json_extract_string(source_json, '$.namespace')=?", [NAMESPACE]), 'dataset_id')
    if not entries and not registered:
        return
    expected = {(s['source']['id'], t['table_id']): (s, t)
                for s in registered_specs() for t in s['tables']}
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
        bound, raw, metadata = set(), {}, {}
        fields = ','.join(RAW_FIELDS)
        model_schemas = {m: schema_of(connection, m) for m in (STAGING, INTERMEDIATE)}
        for entry in entries:
            original = source_metadata(lock_path, entry)
            key = original['source_key'], original['table_id']
            if key in bound or key not in expected:
                raise ValueError('Tama supplementary repeated or undeclared account table')
            bound.add(key)
            spec, table = expected[key]
            source, edition, approval = spec['source'], spec['edition'], spec['approval']
            financial = table['observation_role'] == 'expenditure'
            expected_fields = _registered_fields(spec, table, original['definition_files'])
            approved = expected_fields['canonical_changes']
            identity = ':'.join([entry['jurisdiction'], str(entry['fiscalYear']), 'expenditure',
                                 'supplementary', entry['originEdition'], table['table_id']])
            if (entry['path'] != input_path(source, table) or identity not in registered or identity in raw
                or entry['jurisdiction'] != '132241' or entry['fiscalYear'] != edition['fiscal_year']
                or entry['documentKind'] != 'supplementary' or entry['direction'] != 'expenditure'
                or entry['originEdition'] != source['content_inspection']['sha256']
                or original['fund_label'] != edition['account_label'] or original['pages'] != table['pages']
                or original['amendment_number'] != edition['amendment_number']
                or original['request_url'] != source['download_url'] or original['namespace'] != NAMESPACE
                or original['approval_proof'] != approval or original['canonical_changes'] is not approved
                or original['nonadditive'] is not (not financial)
                or original['phases'] != expected_fields['phases']
                or original.get('composition') != expected_fields.get('composition')
                or original.get('composed_canonical_changes') != expected_fields.get('composed_canonical_changes')
                or original['source_amount_unit'] != '千円' or original['unit_multiplier'] != 1000):
                raise ValueError('Tama supplementary fixed scope/approval differs from registry')
            declaration = json.loads(registered[identity]['source_json'])
            binds = dict(namespace=NAMESPACE, sourceKey=source['id'], tableId=table['table_id'],
                fundLabel=edition['account_label'], pages=table['pages'], rawRowCount=original['rows'],
                rawTableSha256=entry['table']['sha256'], rawTableBytes=entry['table']['bytes'],
                rawSchema=original['raw_schema'], sourceAmountUnit='千円', unitMultiplier=1000,
                observationRole=table['observation_role'], approvalProof=approval,
                canonicalChanges=approved, nonadditive=not financial,
                amendmentNumber=edition['amendment_number'])
            if any(declaration.get(k) != v for k, v in binds.items()):
                raise ValueError('Tama supplementary declaration differs from fixed raw input')
            if json.loads(registered[identity]['phases_json']) != expected_fields['phases']:
                raise ValueError('Unapproved Tama supplementary acquired an approved phase')
            table_path = OBJECTS / safe_relative(entry['table']['key'])
            if digest(table_path.read_bytes()) != entry['table']['sha256']:
                raise ValueError('Tama supplementary fixed Parquet differs')
            query = 'select * from read_parquet(?, hive_partitioning=false)'
            raw_schema = {r[0]:r[1] for r in connection.execute('describe ' + query, [str(table_path)]).fetchall()}
            if tuple(raw_schema) != RAW_FIELDS:
                raise ValueError('Tama supplementary raw column order differs')
            values = records(connection, query + ' order by source_row', [str(table_path)])
            if len(values) != original['rows'] or [r['source_row'] for r in values] != list(range(1, len(values)+1)):
                raise ValueError('Tama supplementary raw count/order differs')
            for model in (STAGING, INTERMEDIATE):
                if any(model_schemas[model].get(f) != t for f, t in raw_schema.items()):
                    raise ValueError('Tama supplementary raw field types differ: ' + model)
                observed = records(connection, f'select {fields} from {model} where dataset_id=? order by source_row', [identity])
                if observed != values:
                    raise ValueError('Tama supplementary ordered raw/NULL differs: ' + model)
            raw[identity], metadata[identity] = values, original
            dataset = next(d for d in selected if d['dataset_id'] == identity)
            dataset['output_coverage'].update(original_rows=len(values), files=[entry['path']+'/data.parquet'])
        if bound != set(expected) or set(raw) != set(registered):
            raise ValueError('Tama supplementary declaration/lock/dataset populations differ')
        for model in (STAGING, INTERMEDIATE):
            if {r['dataset_id'] for r in records(connection, f'select distinct dataset_id from {model}')} != set(raw):
                raise ValueError('Tama supplementary model contains omitted or extra datasets')
        _verify_outputs(connection, candidate, hashes, selected, raw, metadata)
        for dataset in selected:
            dataset['output_coverage'].update(complete=True, all_original_fields_preserved=True)
    except Exception as error:
        for dataset in selected:
            dataset['output_coverage']['errors'].append(str(error))
        raise


def _verify_outputs(connection, candidate, hashes, selected, raw, metadata):
    from ingestion.fiscal.tama_budget_detail import reconcile
    controls, left = {}, defaultdict(list)
    for identity, original in metadata.items():
        if original['observation_role'] != 'observations':
            continue
        if original['extractor'] == 'ingestion.fiscal.tama_budget_amendment':
            continue
        observations = [dict(r, **json.loads(r['context_json']), location=dict(
            page=r['physical_page'], bbox=json.loads(r['bbox_json']))) for r in raw[identity]]
        leaves, checks = reconcile(observations, [])
        financial_id = identity.removesuffix('-observations')+'-expenditure'
        if not checks['complete_observed_grain'] or checks['amount'] != original['printed_total']:
            raise ValueError('Tama supplementary independent moku/project/setsu controls differ')
        for row in raw[identity]:
            if row['record_kind'] == 'moku':
                context = json.loads(row['context_json'])['moku']
                if context['amount_before']+context['amount_delta'] != context['amount_after'] or context['amount_delta'] != row['amount']:
                    raise ValueError('Tama supplementary printed moku operands differ')
            if row['record_kind'] == 'left-setsu' and row['code'] is not None:
                left[(financial_id, _token(json.loads(row['context_json'])['moku']['key']), int(row['code']))].append(row)
        by_row = _indexed(raw[identity], 'source_row')
        expected = [dict(by_row[r['source_row']], source_row=n, source_grain=r['source_grain'],
                         printed_setsu_code=r['printed_setsu_code']) for n, r in enumerate(leaves, 1)]
        if expected != raw[financial_id]:
            raise ValueError('Tama supplementary leaves differ from reconciled observations')
        controls[financial_id] = checks
    master = records(connection, 'select * from fiscal_expenditure_setsu_master')
    replacements = _composition_replacements(raw, metadata)
    intermediate = records(connection, 'select * from '+INTERMEDIATE+' order by dataset_id, source_row')
    provided = _indexed(records(connection, 'select * from fiscal_datasets'), 'dataset_id')
    for identity, original in metadata.items():
        expected_kind = 'supplementary' if original['canonical_changes'] else None
        if provided[identity]['source_amount_kind'] != expected_kind:
            raise ValueError('Tama supplementary dataset amount kind differs from approved financial role')
    groups = defaultdict(list)
    for leaf in intermediate:
        identity = leaf['dataset_id']
        original = metadata[identity]
        value = raw[identity][leaf['source_row']-1]
        financial = original['observation_role'] == 'expenditure'
        approved = financial and original['canonical_changes']
        replacement = replacements.get((identity, leaf['source_row']))
        effective = replacement[1] if replacement else value
        expected_delta = effective['amount']*1000 if effective['amount'] is not None else None
        if json.loads(leaf['raw_original_json']) != value or leaf['delta_yen'] != expected_delta:
            raise ValueError('Tama supplementary rawOriginal or signed unit conversion differs')
        if replacement:
            if (leaf['replacement_dataset_id'] != replacement[0]
                or leaf['replacement_source_row'] != effective['source_row']
                or json.loads(leaf['replacement_raw_json']) != effective
                or json.loads(leaf['effective_context_json']) != json.loads(effective['context_json'])
                or leaf['effective_physical_page'] != effective['physical_page']
                or leaf['effective_bbox_json'] != effective['bbox_json']):
                raise ValueError('Tama supplementary explicit replacement lost motion raw/position')
        elif leaf['replacement_dataset_id'] is not None:
            raise ValueError('Tama supplementary replaced an undeclared target')
        if not financial:
            continue
        context = json.loads(effective['context_json'])
        hierarchy = [dict(level=k, code=context[k][0], label=context[k][1], nameSource='origin') for k in ('kan','kou')]
        hierarchy += [dict(level=k, code=context[k]['code'], label=context[k]['label'], nameSource='origin') for k in ('moku','project')]
        dimensions = [dict(dimension='department', code=None, label=context['department'])]
        if json.loads(leaf['account_path_json']) != hierarchy or json.loads(leaf['dimensions_json']) != dimensions:
            raise ValueError('Tama supplementary printed hierarchy/dimensions differ')
        choices = left[(identity, _token(context['moku']['key']), int(value['printed_setsu_code']))] if value['printed_setsu_code'] is not None else []
        labels = {r['label'] for r in choices}
        matches = [m for m in master if len(labels) == 1 and int(m['code']) == int(value['printed_setsu_code'])
                   and m['label'].replace('、','').replace('・','') == next(iter(labels)).replace('、','').replace('・','')
                   and (m['valid_from_fiscal_year'] is None or m['valid_from_fiscal_year'] <= leaf['fiscal_year'])
                   and (m['valid_to_fiscal_year'] is None or m['valid_to_fiscal_year'] >= leaf['fiscal_year'])]
        expected_setsu = matches[0]['expenditure_setsu_id'] if len(matches) == 1 else None
        expected_left_code = int(value['printed_setsu_code']) if len(labels) == 1 else None
        expected_left_label = next(iter(labels)) if len(labels) == 1 else None
        if replacement and context['setsu'] is not None and (
            context['setsu']['code'] != value['printed_setsu_code']
            or context['setsu']['label'].replace('、','').replace('・','') !=
               (expected_left_label or '').replace('、','').replace('・','')):
            raise ValueError('Tama replacement printed setsu differs from original legal correspondence')
        if (leaf['expenditure_setsu_id'] != expected_setsu or leaf['left_setsu_code'] != expected_left_code
            or leaf['left_setsu_label'] != expected_left_label
            or leaf['line_granularity'] != ('expenditure_setsu' if expected_setsu is not None else 'origin_line')):
            raise ValueError('Tama supplementary legal setsu code/name/year or unprinted reserve differs')
        target = dict(identityNamespace='tama-supplementary-printed-target', datasetId=identity,
            hierarchy=hierarchy, dimensions=dimensions, legalSetsuId=expected_setsu,
            originLine=leaf['fiscal_line_id'] if expected_setsu is None else None)
        if json.loads(leaf['target_identity_json']) != target or leaf['budget_item_id'] != 'b-'+digest(leaf['target_identity_json'].encode()):
            raise ValueError('Tama supplementary target identity differs')
        if approved:
            approval = original['approval_proof']
            effective = (approval['date'] if not original.get('composed_canonical_changes')
                         and approval.get('kind','budget_bill') == 'budget_bill' else None)
            if (str(leaf['effective_at']) if leaf['effective_at'] is not None else None) != effective:
                raise ValueError('Tama supplementary approval/effective date differs')
            groups[(identity, leaf['budget_item_id'])].append(leaf)
    changes = records(connection, 'select * from '+CHANGES)
    indexed = {(r['dataset_id'], r['budget_item_id']):r for r in changes}
    if len(indexed) != len(changes) or set(indexed) != set(groups):
        raise ValueError('Tama supplementary approved change groups differ; unknown must be excluded')
    for key, members in groups.items():
        change = indexed[key]
        details = json.loads(change['details_json'])
        if change['amount_delta'] != sum(r['delta_yen'] for r in members) or change['change_id'] != 'c-'+digest((key[0]+':'+key[1]).encode()):
            raise ValueError('Tama supplementary grouped signed delta or identity differs')
        if [d['sourceRow'] for d in details] != [r['source_row'] for r in members]:
            raise ValueError('Tama supplementary detail order/multiplicity differs')
        for detail, leaf in zip(details, members, strict=True):
            if (detail['rawOriginal'] != raw[key[0]][leaf['source_row']-1]
                or detail['amount'] != leaf['delta_yen'] or detail['physicalPage'] != leaf['effective_physical_page']
                or detail['bbox'] != json.loads(leaf['effective_bbox_json'])
                or detail['targetIdentity'] != json.loads(leaf['target_identity_json'])
                or detail['approvalProof'] != metadata[key[0]]['approval_proof']):
                raise ValueError('Tama supplementary actual financial detail lost raw values/meaning/position')
            replacement = replacements.get((key[0], leaf['source_row']))
            if replacement and (detail.get('replacementDatasetId') != replacement[0]
                or detail.get('positionDatasetId') != replacement[0]
                or detail.get('replacementRaw') != replacement[1]
                or detail.get('sameEventReplacement') is not True
                or detail.get('effectiveContext') != json.loads(replacement[1]['context_json'])):
                raise ValueError('Tama supplementary financial detail lost its same-event replacement relation')
    items = _indexed(records(connection, 'select * from '+ITEMS), 'budget_item_id')
    if set(items) != {k[1] for k in groups} or any(r['initial_state'] != 'unconfirmed' for r in items.values()):
        raise ValueError('Tama supplementary item set or unknown initial baseline differs')
    for members in groups.values():
        for leaf in members:
            item = items[leaf['budget_item_id']]
            if any(item[f] != leaf[f] for f in ('jurisdiction_code','fiscal_year','fund_code','fund_label',
                'expenditure_setsu_id','line_granularity','account_path_json','dimensions_json')):
                raise ValueError('Tama supplementary item differs from original printed target')
    csv_changes = _csv(connection,candidate,hashes,'fiscal/132241/expenditure_budget_changes.csv','csv_132241_expenditure_budget_changes')
    _equal_rows([r for r in csv_changes if r['dataset_id'] in metadata],changes,'Tama supplementary actual change CSV')
    csv_items = _csv(connection,candidate,hashes,'fiscal/132241/expenditure_budget_items.csv','csv_132241_expenditure_budget_items')
    _equal_rows([r for r in csv_items if r['budget_item_id'] in items],list(items.values()),'Tama supplementary actual item CSV')
    csv_observations = _csv(connection,candidate,hashes,'fiscal/132241/supplementary_native_observations.csv','csv_132241_supplementary_native_observations')
    observation_ids = {i for i,o in metadata.items() if o['observation_role'] == 'observations'}
    if ({r['dataset_id'] for r in csv_observations} != observation_ids
        or len(csv_observations) != sum(len(raw[i]) for i in observation_ids)
        or any(r['nonadditive'] is not True for r in csv_observations)):
        raise ValueError('Tama supplementary observation CSV dataset population/nonadditive differs')
    observations_by_id = defaultdict(list)
    for row in csv_observations:
        observations_by_id[row['dataset_id']].append({f:row[f] for f in RAW_FIELDS})
    for identity, original in metadata.items():
        if original['observation_role'] == 'observations':
            _equal_rows(observations_by_id[identity], raw[identity], 'Tama supplementary actual typed observation CSV')
    for dataset in selected:
        identity = dataset['dataset_id']
        financial = metadata[identity]['observation_role'] == 'expenditure'
        dataset['output_coverage']['accounts'][metadata[identity]['fund_label']] = dict(
            original_rows=len(raw[identity]), explicit_moku_setsu=False, explicit_project_setsu=financial,
            amendment_numbers=[metadata[identity]['amendment_number']]
                if financial and metadata[identity]['canonical_changes'] else [],
            financial_change_rows=sum(key[0] == identity for key in groups),
            printed_code_correspondence_verified=financial, initial_baseline_status='unconfirmed',
            approval_status=metadata[identity]['approval_status'])
        if financial:
            dataset['output_coverage']['independent_printed_controls'] = controls[identity]
            dataset['output_coverage']['files'].extend(['fiscal/132241/expenditure_budget_changes.csv','fiscal/132241/expenditure_budget_items.csv'])
        else:
            dataset['output_coverage']['files'].append('fiscal/132241/supplementary_native_observations.csv')


def _composition_replacements(raw: dict, metadata: dict) -> dict:
    """Validate motion-to-proposal keys without rewriting either raw table."""
    replaced = {}
    for identity, original in metadata.items():
        if not original.get('composed_canonical_changes'):
            continue
        binding = original['composition']
        motion_id = binding['motion_dataset_id']
        if (motion_id not in raw or metadata[motion_id].get('canonical_changes')
            or metadata[motion_id].get('composition') != binding
            or original['phases'] != [] or original['financial_phase'] is not None):
            raise ValueError('Tama composed event dependencies or signed-delta phase differ')
        motion = raw[motion_id]
        roots = [r for r in motion if r['record_kind'] == 'motion-replacement']
        if len(motion) != 55 or len(roots) != 2 or any(r['amount'] is not None for r in motion if r not in roots):
            raise ValueError('Tama partial motion observation/root population differs')
        net = 0
        for root in roots:
            context = json.loads(root['context_json'])
            relation = context['composition']
            row = relation['proposal_financial_row']
            proposal = raw[identity][row-1]
            old = json.loads(proposal['context_json'])
            if ((identity, row) in replaced
                or relation['proposal_origin_sha256'] != binding['proposal_origin_sha256']
                or relation['proposal_table_id'] != binding['proposal_table_id']
                or relation['proposal_source_id'] != binding['proposal_source_id']
                or relation['proposal_observation_row'] != proposal['source_observation_row']
                or relation['replaced_proposal']['amount'] != proposal['amount']
                or relation['replaced_proposal']['context'] != old
                or context['moku']['key'] != old['moku']['key']
                or context['project']['code'] != old['project']['code']
                or root['printed_setsu_code'] != proposal['printed_setsu_code']
                or context['department'] is not None
                or context['moku']['operand_words'] is not None
                or context['moku']['amount_delta'] != old['moku']['amount_delta']+root['amount']-proposal['amount']
                or context['moku']['amount_before']+context['moku']['amount_delta'] != context['moku']['amount_after']
                or relation['same_event_replacement'] is not True):
                raise ValueError('Tama motion target/unknown department/original reference differs')
            replaced[(identity, row)] = (motion_id, root)
            net += root['amount']-proposal['amount']
        effective_total = sum(replaced[(identity,r['source_row'])][1]['amount']
            if (identity,r['source_row']) in replaced else r['amount'] for r in raw[identity])
        if net != 0 or effective_total != original['printed_total']:
            raise ValueError('Tama same-event replacement adds another change or alters total')
    return replaced
