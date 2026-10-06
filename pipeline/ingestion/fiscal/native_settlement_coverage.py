"""Direct preservation checks for the fixed FY2020 Tama native observations.

This checks independent source grains. Successful preservation does not establish
project correspondence, legal applicability, recognition, or all-public coverage.
"""
from __future__ import annotations
from ingestion.inputs import source_metadata_bytes

from collections import defaultdict
import json
from pathlib import Path

import duckdb

from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, verify_object

NAMESPACE = 'tama-native-settlement/'
PROVIDER = 'tama-native-settlement'
FINANCIAL = {'legal-observations', 'hierarchy-controls', 'independent-account-controls'}


def records(connection, query: str, parameters=()) -> list[dict]:
    return [json.loads(row[0]) for row in connection.execute(
        'select to_json(observation) from (' + query + ') observation', parameters).fetchall()]


def indexed(rows: list[dict]) -> dict:
    result = {row['observed_id']: row for row in rows}
    if len(result) != len(rows):
        raise ValueError('Repeated original observation within an independent role')
    return result


def hierarchy_path(row: dict) -> tuple:
    path = json.loads(row['path_json'])
    return (row['account'], *(path.get(level, {}).get('code') for level in ('kan', 'kou', 'moku')))


def control_readback(roles: dict[str, list[dict]]) -> dict:
    """Compare independently printed controls, keeping reserve-only observations."""
    legal, hierarchy, accounts = (roles[key] for key in
                                  ('legal-observations', 'hierarchy-controls', 'independent-account-controls'))
    fields = ['initial_budget', 'supplementary_delta', 'carried_budget',
              'reserve_and_transfer_delta', 'current_budget', 'executed', 'carryover', 'unused']
    legal_fields = ['budget_current', 'executed', 'carryover', 'unused']
    children = defaultdict(list)
    for row in legal + hierarchy:
        observed = legal_fields if 'printed_setsu_code' in row else fields
        if any(row[field] is None or row[field + '_status'] not in
               ('observed-agreement', 'visually-read-original-cell') for field in observed):
            raise ValueError('Missing or unreviewed printed monetary cell')
        current = 'budget_current' if 'printed_setsu_code' in row else 'current_budget'
        if row[current] != sum(row[field] for field in ('executed', 'carryover', 'unused')):
            raise ValueError('Printed current/executed/carryover/unused controls differ')
        if current == 'current_budget' and row[current] != sum(row[field] for field in fields[:4]):
            raise ValueError('Printed hierarchy budget decomposition differs')
    for row in legal:
        children[hierarchy_path(row)].append(row)
    if len({hierarchy_path(row) + (row['printed_setsu_code'],) for row in legal}) != len(legal):
        raise ValueError('Repeated printed hierarchy/setsu occurrence')
    moku = [row for row in hierarchy if row['control_level'] == 'moku']
    reserves = []
    for row in moku:
        child = children[hierarchy_path(row)]
        if '予備費' in row['printed_label_observed']:
            if child or row['executed'] != 0 or row['carryover'] != 0:
                raise ValueError('Reserve-only moku acquired children or executed expenditure')
            reserves.append(row['observed_id'])
        elif any(sum(item[left] for item in child) != row[right] for left, right in
                 zip(legal_fields, ('current_budget', 'executed', 'carryover', 'unused'), strict=True)):
            raise ValueError('Printed moku controls differ from printed legal children')
    for row in hierarchy:
        if row['control_level'] == 'moku':
            continue
        if row['control_level'] not in ('kan', 'kou'):
            raise ValueError('Unknown hierarchy control level')
        size = 2 if row['control_level'] == 'kan' else 3
        child = [item for item in moku if hierarchy_path(item)[:size] == hierarchy_path(row)[:size]]
        if not child or any(sum(item[field] for item in child) != row[field] for field in fields):
            raise ValueError('Printed kan/kou controls differ from printed moku')
    if len({row['account'] for row in accounts}) != 4:
        raise ValueError('Missing or repeated independent printed account summary')
    for row in accounts:
        child = [item for item in moku if item['account'] == row['account']]
        leaves = [item for item in legal if item['account'] == row['account']]
        if (not child or not leaves
                or any(sum(item[field] for item in child) != row[field]
                       for field in ('current_budget', 'executed', 'carryover', 'unused'))
                or sum(item['executed'] for item in leaves) != row['executed']
                or row['current_budget'] - row['executed'] != row['current_minus_executed_printed']):
            raise ValueError('Independent printed account summary differs')
    if (len(legal), len(hierarchy), len(moku), len(accounts), len(reserves)) != (889, 275, 161, 4, 3):
        raise ValueError('Fixed FY2020 control scope differs')
    return dict(legal_rows=len(legal), hierarchy_rows=len(hierarchy), moku_rows=len(moku),
                independent_accounts=len(accounts), reserve_control_only_rows=reserves,
                executed_total=sum(row['executed'] for row in legal), errors=[])


def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path,
                    datasets: list[dict]) -> None:
    entries = [entry for entry in read_lock(lock_path)['entries'] if entry['path'].startswith(NAMESPACE)]
    if not entries:
        return
    from ingestion.fiscal.tama_native_settlement.registration import DIRECTORY, dataset_id, specifications
    from ingestion.fiscal.tama_native_settlement.native_scan_provider import FrozenNativeProvider

    actual_registry = records(connection, "select * from int_fiscal_datasets "
                              "where json_extract_string(source_json,'$.provider')=?", [PROVIDER])
    registered = {row['dataset_id']: row for row in actual_registry}
    existing = {row['dataset_id']: row for row in datasets}
    for identity, row in registered.items():
        if identity not in existing:
            datasets.append(row)
            existing[identity] = row
    selected = []
    try:
        specs = specifications()
        expected = {dataset_id(spec, table): (spec, table)
                    for spec in specs.values() for table in spec['tables']}
        for identity, (spec, table) in expected.items():
            if identity not in existing:
                # A missing registration is an explicit gap, never an inferred success.
                row = dict(dataset_id=identity, jurisdiction_code='132241', fiscal_year=2020,
                           document_kind='settlement', origin_sha256=spec['origin_sha256'],
                           source_json=json.dumps(dict(provider=PROVIDER, observationRole=table['role'])),
                           structure_json='{"funds":[]}', phases_json='[]', line_count=0)
                datasets.append(row)
                existing[identity] = row
            selected.append(existing[identity])
            existing[identity]['output_coverage'] = dict(
                complete=False, files=[], accounts={}, errors=[], observation_role=table['role'],
                original_rows=0, recognition_status='unconfirmed',
                legal_correspondence_status='unconfirmed', project_setsu_confirmed=False)
            existing[identity]['_phase_lines'] = {}
        if len(entries) != 51 or len(registered) != 51 or set(registered) != set(expected):
            raise ValueError('Exact adopted51 native-role registrations are missing or repeated')
        provider = FrozenNativeProvider(DIRECTORY / 'evidence-manifest.json', OBJECTS)
        assets = provider.verify_all()
        transcription = json.loads((DIRECTORY / 'frozen-transcription.json').read_text())
        ledger = provider.validate_source_ledgers(transcription)
        schema = json.loads((DIRECTORY / 'raw-schema.json').read_text())
        references = {item['role']: item for item in transcription['expected']}
        declarations = {}
        role_rows = defaultdict(list)
        for entry in entries:
            provenance = json.loads(source_metadata_bytes(lock_path, entry))
            identity = ':'.join((entry['jurisdiction'], str(entry['fiscalYear']),
                                  'expenditure' if entry['direction'] is not None else 'observation',
                                  entry['documentKind'], entry['originEdition'], provenance['table_id']))
            if identity not in expected or identity in declarations:
                raise ValueError('Native source/role identity is missing or repeated')
            spec, table = expected[identity]
            source = json.loads(registered[identity]['source_json'])
            financial = table['role'] in FINANCIAL
            if (entry['jurisdiction'] != '132241' or entry['fiscalYear'] != 2020
                    or entry['documentKind'] != 'settlement' or entry['originEdition'] != spec['origin_sha256']
                    or entry['direction'] != table.get('direction')
                    or provenance['request_url'] != spec['url'] or provenance['rows'] != table['rows']
                    or provenance['observation_role'] != table['role']
                    or registered[identity]['source_json'] != existing[identity]['source_json']
                    or registered[identity]['line_count'] != table['rows']
                    or source.get('provider') != PROVIDER or source.get('url') != spec['url']
                    or source.get('tableId') != table['table_id']
                    or source.get('rawTableSha256') != entry['table']['sha256']
                    
                    or source.get('sourceAmountUnit') != table.get('source_amount_unit')
                    or source.get('unitMultiplier') != table.get('unit_multiplier')
                    or json.loads(registered[identity]['phases_json']) != (['executed'] if financial else [])
                    or source.get('recognitionStatus') != 'unconfirmed'
                    or source.get('expenditureSetsuStatus') != 'unconfirmed'
                    or source.get('projectSetsuLinkage') != 'unconfirmed'):
                raise ValueError('Native registered source/phase/unit/provenance identity differs')
            for definition in provenance['definition_files'].values():
                data = (DIRECTORY / Path(definition['path']).name).read_bytes()
                if digest(data) != definition['sha256'] or len(data) != definition['bytes']:
                    raise ValueError('Native adopted definition identity differs')
            for object_ref in (entry['origin']['object'], entry['table']):
                verify_object(object_ref, (OBJECTS / safe_relative(object_ref['key'])).read_bytes())
            raw = records(connection, 'select * from read_parquet(?,hive_partitioning=false)',
                          [str(OBJECTS / safe_relative(entry['table']['key']))])
            if len(raw) != table['rows'] or set(raw[0]) != {column['name'] for column in schema[table['role']]}:
                raise ValueError('Native adopted raw schema or row count differs')
            indexed(raw)
            declarations[identity] = (source, table, raw, entry)
            role_rows[table['role']].extend(raw)
        for role, rows in role_rows.items():
            original = indexed(rows)
            if role in references:
                reference = references[role]['reference']
                if provider.assets[reference['logical_path']]['sha256'] != reference['sha256']:
                    raise ValueError('Frozen reference identity differs')
                frozen = indexed([json.loads(line) for line in
                                  provider.path(reference['logical_path']).read_text().splitlines()])
                if original != frozen:
                    raise ValueError('Adopted original fields differ from independently frozen observations')
            if role == 'page-observations':
                if len(rows) != 230 or {row['printed_page'] for row in rows} != set(range(1, 231)):
                    raise ValueError('Native full230 physical-page observations differ')
                for row in rows:
                    ref = dict(key=row['page_observation_object_key'], sha256=row['page_observation_sha256'])
                    page = json.loads((OBJECTS / safe_relative(ref['key'])).read_text())
                    if (digest((OBJECTS / safe_relative(ref['key'])).read_bytes()) != ref['sha256']
                            or json.loads(row['native_page_observations_json']) != page
                            or row['physical_page'] != page['physical_page']
                            or row['origin_sha256'] != page['origin_sha256']):
                        raise ValueError('Native page evidence identity differs')
            suffix = role.replace('-', '_')
            relative = 'fiscal/132241/tama_native_settlement_' + suffix + '.csv'
            if relative not in hashes:
                raise ValueError('Native role CSV is not a verified artifact')
            fields = [column['name'] for column in schema[role]]
            for prefix in ('stg_132241__', 'int_132241__', 'fiscal_132241_', 'csv_132241_'):
                relation = prefix + 'tama_native_settlement_' + suffix
                provided = indexed(records(connection, 'select * from ' + relation))
                if provided.keys() != original.keys():
                    raise ValueError('Native original occurrences are missing or repeated in ' + relation)
                for observed, raw in original.items():
                    row = provided[observed]
                    source, table, _, _ = declarations[row['dataset_id']]
                    if ({field: row[field] for field in fields} != raw
                            or row['source_json'] != registered[row['dataset_id']]['source_json']
                            or row['fiscal_line_id'] != row['dataset_id'] + ':' + observed):
                        raise ValueError('Native original field/source JSON/occurrence differs in ' + relation)
                    if prefix == 'stg_132241__':
                        continue
                    if role == 'legal-observations' and (
                            row['expenditure_setsu_id'] is not None or row['amount'] != raw['executed']
                            or row['setsu_correspondence_status'] != 'unconfirmed' or row['currency'] != 'JPY'):
                        raise ValueError('Native executed amount or unknown legal mapping changed')
                    if role not in FINANCIAL and any(row.get(field) is not None for field in
                                                    ('phase', 'direction', 'amount_unit', 'amount_multiplier')):
                        raise ValueError('Native word/page proof acquired monetary metadata')
            types = {row[0]: row[1] for row in connection.execute('describe select * from ' + relation).fetchall()}
            csv_rows = indexed(records(connection,
                "select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')",
                [str(candidate / relative), types]))
            if csv_rows != provided:
                raise ValueError('Native CSV changed a typed original/derived field or NULL')
            for identity, (source, table, raw, entry) in declarations.items():
                if table['role'] != role:
                    continue
                proof = existing[identity]['output_coverage']
                proof.update(files=[relative], original_rows=len(raw), fixed_input=entry['path'],
                             origin_sha256=entry['originEdition'], table_sha256=entry['table']['sha256'],
                             
                             all_original_fields_and_source_json_preserved=True,
                             immutable_proof_objects=len(assets), whole_physical_pages=ledger['pages'])
        controls = control_readback(role_rows)
        for dataset in selected:
            dataset['output_coverage'].update(complete=True, independent_control_readback=controls)
    except (OSError, ValueError, KeyError, TypeError, duckdb.Error) as error:
        for dataset in selected:
            dataset['output_coverage']['complete'] = False
            dataset['output_coverage']['errors'].append(str(error))
