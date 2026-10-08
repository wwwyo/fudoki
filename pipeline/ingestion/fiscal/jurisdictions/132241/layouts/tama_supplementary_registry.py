"""Register Tama supplementary observations and approved signed changes."""
from __future__ import annotations

from importlib import import_module as _ingestion_module

import argparse
from collections import defaultdict
import json
from pathlib import Path
import shutil

from ingestion.fiscal.management.source_registry import INVENTORY, load_registry
from ingestion.inputs import OBJECTS, digest, encode, read_lock, record_input, save_object
from ingestion.paths import RAW, REPO

NAMESPACE = 'tama-supplementary-native'
PROVIDER = 'ingestion.fiscal.jurisdictions.132241.layouts.tama_supplementary_registry'
COLUMNS = {
    'source_row': 'BIGINT', 'source_observation_row': 'BIGINT',
    'record_kind': 'VARCHAR', 'code': 'VARCHAR', 'label': 'VARCHAR',
    'amount': 'BIGINT', 'amount_text': 'VARCHAR', 'physical_page': 'INTEGER',
    'bbox_json': 'VARCHAR', 'printed_text': 'VARCHAR', 'words_json': 'VARCHAR',
    'context_json': 'VARCHAR', 'source_grain': 'VARCHAR', 'printed_setsu_code': 'VARCHAR',
}
DEFINITION_PATHS = (
    'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_supplementary_registry.py',
    'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_budget_changes.py',
    'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_budget_amendment.py',
    'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_budget_detail.py',
    'pipeline/ingestion/fiscal/jurisdictions/131016/layouts/chiyoda_budget_changes.py',
    'pipeline/ingestion/fiscal/management/canonical_sources.py',
    'pipeline/ingestion/lib/pdf.py', 'pipeline/ingestion/inputs.py',
    'pipeline/ingestion/paths.py', 'pipeline/ingestion/fiscal/management/source_registry.py',
    'pipeline/ingestion/fiscal/management/sources.schema.json',
    'pipeline/ingestion/fiscal/management/sources.json', 'pipeline/ingestion/fiscal/management/sources.py',
    'pipeline/ingestion/declarations.py', 'pipeline/ingestion/acquire.py',
    'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_supplementary_native_coverage.py',
    'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_initial_native_coverage.py',
    'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/native_settlement_coverage.py',
    'pipeline/ingestion/fiscal/jurisdictions/132071/layouts/settlement2019_coverage.py',
    'pipeline/ingestion/fiscal/management/coverage_audit.py',
    'pipeline/dbt/models/staging/fiscal/_tama_supplementary_native_sources.yml',
    'pipeline/dbt/models/staging/fiscal/stg_132241__supplementary_native.sql',
    'pipeline/dbt/models/intermediate/fiscal/records/int_132241__supplementary_native.sql',
    'pipeline/dbt/models/intermediate/fiscal/records/int_132241__supplementary_native_datasets.sql',
    'pipeline/dbt/models/marts/records/fiscal_132241_supplementary_native_observations.sql',
    'pipeline/dbt/models/marts/records/fiscal_132241_supplementary_native_changes.sql',
    'pipeline/dbt/models/marts/records/fiscal_132241_supplementary_native_items.sql',
    'pipeline/dbt/models/marts/csv/csv_132241_supplementary_native_observations.sql',
    'pipeline/dbt/models/intermediate/fiscal/records/int_fiscal_datasets.sql',
    'pipeline/dbt/models/marts/records/fiscal_datasets.sql',
    'pipeline/dbt/models/marts/records/fiscal_expenditure_budget_changes.sql',
    'pipeline/dbt/models/marts/records/fiscal_expenditure_budget_items.sql',
    'pipeline/dbt/tests/expenditure_setsu.sql', 'uv.lock',
)


def definition_files() -> dict:
    return {relative: dict(sha256=digest(body), bytes=len(body))
            for relative in DEFINITION_PATHS for body in [(REPO / relative).read_bytes()]}


def registered_specs() -> list[dict]:
    """Derive each account and its two tables from the origin registry."""
    result = []
    identities = set()
    sources = load_registry(INVENTORY)['sources']
    motions = []
    for source in sources:
        if source['jurisdiction'] != '132241':
            continue
        for ingestion in source.get('ingestions', []):
            if ingestion['section'] == 'native_supplementary_amendment' and ingestion['enabled']:
                motions.append((source, ingestion))
                continue
            if ingestion['section'] != 'native_supplementary_detail' or not ingestion['enabled']:
                continue
            profile = ingestion['profile']
            index = profile.get('edition_index', 0)
            edition = source['editions'][index]
            first, last = profile['physical_pages']
            if first > last or (last - first + 1) % 2 or last > source['content_inspection']['pages']:
                raise ValueError('Native Tama supplementary pages must contain complete account pairs')
            tables = []
            for role in ('observations', 'expenditure'):
                table = dict(table_id=f'supplementary-{edition["amendment_number"]}-pages-{first}-{last}-{role}',
                             account=edition['account_label'], pages=[first, last],
                             observation_role=role, amendment_number=edition['amendment_number'])
                identity = (source['id'], table['table_id'])
                if identity in identities:
                    raise ValueError('Duplicate native Tama supplementary table registration')
                identities.add(identity)
                tables.append(table)
            result.append(dict(source=source, edition=edition, edition_index=index,
                               approval=ingestion['options'].get('approval'), tables=tables,
                               composition_reference=ingestion['options'].get('composition')))
    for source, ingestion in motions:
        relation = ingestion['options']['replaces']
        index = relation['options']['edition_index']
        proposals = [s for s in result if s['source']['id'] == relation['source_id'] and s['edition_index'] == index]
        if len(proposals) != 1:
            raise ValueError('Motion requires one enabled proposal edition')
        proposal = proposals[0]
        edition = source['editions'][ingestion['profile'].get('edition_index', 0)]
        if (proposal['composition_reference'] != {'source_id': source['id']}
            or ingestion['profile']['physical_pages'] != [1, 3]
            or source['content_inspection']['pages'] != 3
            or tuple(proposal['edition'][k] for k in ('fiscal_year','account_label','amendment_number')) !=
               tuple(edition[k] for k in ('fiscal_year','account_label','amendment_number'))
            or proposal['approval'] is None):
            raise ValueError('Motion/proposal reciprocal event scope or approval differs')
        table = dict(table_id=f'supplementary-{edition["amendment_number"]}-amendment-observations',
            account=edition['account_label'], pages=[1,3], observation_role='observations',
            amendment_number=edition['amendment_number'])
        binding = dict(proposal_source_id=proposal['source']['id'],
            proposal_origin_sha256=proposal['source']['content_inspection']['sha256'],
            proposal_table_id=proposal['tables'][1]['table_id'], motion_source_id=source['id'],
            motion_origin_sha256=source['content_inspection']['sha256'], motion_table_id=table['table_id'],
            motion_dataset_id=':'.join([source['jurisdiction'], str(source['fiscal_year']),
                'expenditure', 'supplementary', source['content_inspection']['sha256'], table['table_id']]))
        proposal['composition'] = binding
        result.append(dict(source=source, edition=edition, edition_index=0,
            approval=proposal['approval'], tables=[table], motion=True,
            proposal=proposal, composition=binding))
    if any(s.get('composition_reference') and not s.get('composition') for s in result):
        raise ValueError('Enabled composition has no reciprocal motion ingestion')
    return result


def registered_sources():
    from ingestion.fiscal.management.sources import Resource, Source
    from ingestion.shared.jurisdictions import jurisdiction_name
    grouped = defaultdict(list)
    for spec in registered_specs():
        grouped[spec['source']['id']].append(spec)
    return {source['id']: Source(key=source['id'], catalog=None,
        jurisdiction_code=source['jurisdiction'], jurisdiction_name=jurisdiction_name(source['jurisdiction']),
        fiscal_year=source['fiscal_year'], fiscal_year_label=None, document_kind='supplementary',
        document_label=source['document_title'], dataset_title=None, encoding='',
        redistribute='review', redistribute_basis='当該PDFの再配布条件は未確認。別の資料の条件を適用しない。',
        license_id='NOASSERTION', attribution='多摩市', landing_page=source['landing_url'],
        raw_form='extracted', resources=tuple(Resource(direction='expenditure',
            resource_name=source['document_title'] + ' ' + table['account'] + ' ' + table['observation_role'],
            url=source['download_url'], url_basis='自治体の公式予算ページが補正号付きPDFを掲載。',
            table_id=table['table_id']) for spec in specs for table in spec['tables']))
        for specs in grouped.values() for source in [specs[0]['source']]}


def input_path(source: dict, table: dict) -> str:
    return (f'{NAMESPACE}/jurisdiction={source["jurisdiction"]}/year={source["fiscal_year"]}/'
            f'document_kind=supplementary/edition={source["content_inspection"]["sha256"]}/'
            f'direction=expenditure/table={table["table_id"]}')


def _registered_fields(spec: dict, table: dict, definitions: dict) -> dict:
    source, approval = spec['source'], spec['approval']
    financial = table['observation_role'] == 'expenditure'
    canonical = financial and approval is not None
    composed = financial and 'composition' in spec
    effective_at = (approval['date'] if canonical and not composed and approval.get('kind', 'budget_bill') == 'budget_bill'
                    else None)
    fields = dict(namespace=NAMESPACE, source_key=source['id'],
        jurisdiction_code=source['jurisdiction'], fiscal_year=source['fiscal_year'],
        document_kind='supplementary', direction='expenditure',
        origin_sha256=source['content_inspection']['sha256'],
        request_url=source['download_url'], final_url=source['content_inspection']['final_url'],
        landing_page=source['landing_url'], document_title=source['document_title'],
        account=table['account'], fund_label=table['account'],
        amendment_number=table['amendment_number'], table_id=table['table_id'], pages=table['pages'],
        source_amount_unit='千円', unit_multiplier=1000, observation_role=table['observation_role'],
        nonadditive=not financial, phases=['adjusted'] if canonical and not composed else [],
        financial_phase='adjusted' if canonical and not composed else None, canonical_changes=canonical,
        approval_status='approved_with_amendment' if 'composition' in spec else 'approved' if approval else 'unconfirmed',
        approval_date=approval['date'] if approval else None, approval_proof=approval,
        effective_at=effective_at, baseline_status='unconfirmed',
        phase_semantics='signed supplementary change; not adjusted total',
        project_setsu_linkage='printed-right-code; legal correspondence unassigned',
        grain=('printed-project-setsu-detail-or-unprinted-setsu-reserve' if financial
               else 'nonadditive-supplementary-printed-operands-and-explanation'),
        extractor='ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_changes', definition_files=definitions)
    if 'composition' in spec:
        fields.update(composition=spec['composition'], composed_canonical_changes=composed)
    if composed:
        fields['source_amount_kind'] = 'supplementary'
    if spec.get('motion'):
        fields.update(extractor='ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_amendment',
            grain='nonadditive-partial-motion-native-rows-and-explicit-replacement-roots')
    return fields


def register_declarations(rows, history, entries, lock_path):
    """Bind adopted raw tables and approval to the current registry and support files."""
    restore_approval_evidence = _ingestion_module('ingestion.fiscal.jurisdictions.131016.layouts.chiyoda_budget_changes').restore_approval_evidence
    from ingestion.inputs import source_metadata
    restore_approval_evidence(entries, OBJECTS, namespace=NAMESPACE)
    specs = {(spec['source']['id'], table['table_id']): (spec, table)
             for spec in registered_specs() for table in spec['tables']}
    adopted = [entry for entry in entries if entry['path'].startswith(NAMESPACE + '/')]
    if not adopted:
        return rows, history
    definitions = definition_files()
    seen = set()
    for entry in adopted:
        metadata = source_metadata(lock_path, entry)
        identity = (metadata['source_key'], metadata['table_id'])
        if identity not in specs:
            raise ValueError('Native Tama supplementary adopted table has no enabled declaration')
        spec, table = specs[identity]
        source = spec['source']
        expected = _registered_fields(spec, table, definitions)
        sha = source['content_inspection']['sha256']
        if (entry['path'] != input_path(source, table) or entry['path'] in seen
            or entry['originEdition'] != sha or entry['jurisdiction'] != source['jurisdiction']
            or entry['fiscalYear'] != source['fiscal_year'] or entry['documentKind'] != 'supplementary'
            or entry['direction'] != 'expenditure'
            or entry['origin']['object']['bytes'] != source['content_inspection']['bytes']
            or metadata['raw_schema'] != [dict(name=name, type=kind) for name, kind in COLUMNS.items()]
            or any(metadata.get(name) != value for name, value in expected.items())):
            raise ValueError('Native Tama supplementary adopted scope/approval/definitions differ')
        seen.add(entry['path'])
        financial = table['observation_role'] == 'expenditure'
        structure = dict(hierarchy=['kan', 'kou', 'moku', 'project'], dimensions=['department'],
            funds=[dict(code='', label=table['account'])], scope=dict(granularity=metadata['grain'],
                nonadditive=not financial, sourceAmountUnit='千円', unitMultiplier=1000,
                initialState='unconfirmed', authoritativeSupplementaryChanges=expected['canonical_changes'],
                expenditureSetsuStatus='same-moku-printed-left-code-name-and-active-year-master; blank-reserve-unconfirmed'))
        declaration = dict(namespace=NAMESPACE, provider=PROVIDER, sourceKey=source['id'],
            documentKind='supplementary', documentLabel=source['document_title'],
            landingPage=source['landing_url'], url=source['download_url'], sha256=sha,
            licenseId='NOASSERTION', attribution='多摩市', redistributionStatus='unconfirmed',
            rawForm='extracted', tableId=table['table_id'], fundLabel=table['account'], pages=table['pages'],
            rawRowCount=metadata['rows'], rawSchema=metadata['raw_schema'],
            rawTableSha256=entry['table']['sha256'], rawTableBytes=entry['table']['bytes'],
            sourceAmountUnit='千円', unitMultiplier=1000, observationRole=table['observation_role'],
            nonadditive=not financial, phases=expected['phases'], financialPhase=expected['financial_phase'],
            canonicalChanges=expected['canonical_changes'], approvalStatus=expected['approval_status'],
            approvalDate=expected['approval_date'], approvalProof=spec['approval'],
            amendmentNumber=table['amendment_number'], phaseSemantics=metadata['phase_semantics'],
            projectSetsuLinkage=metadata['project_setsu_linkage'], grain=metadata['grain'], structure=structure)
        if 'composition' in spec:
            declaration.update(composition=spec['composition'],
                composedCanonicalChanges=expected['composed_canonical_changes'])
        if expected.get('source_amount_kind'):
            declaration['sourceAmountKind'] = expected['source_amount_kind']
        row = dict(dataset_id=':'.join([source['jurisdiction'], str(source['fiscal_year']),
            'expenditure', 'supplementary', sha, table['table_id']]),
            jurisdiction_code=source['jurisdiction'], fiscal_year=source['fiscal_year'],
            direction='expenditure', document_kind='supplementary',
            source_json=json.dumps(declaration, ensure_ascii=False, sort_keys=True))
        rows.append(row)
        history.append(dict(**row, origin_sha256=sha, effective_at=expected['effective_at'],
            amendment_number=table['amendment_number'], fund_label=table['account'],
            line_count=metadata['rows'], structure_json=json.dumps(structure, ensure_ascii=False)))
    if seen != {input_path(spec['source'], table) for spec, table in specs.values()}:
        raise ValueError('Native Tama supplementary adopted tables differ from enabled account ranges')
    return rows, history


def emit_registered(output: Path, original: dict, spec: dict, *, raw_root: Path | None = None,
                    definitions: dict | None = None) -> dict:
    """Reuse the candidate reader, assigning approval only to declared financial tables."""
    restore_approval_evidence = _ingestion_module('ingestion.fiscal.jurisdictions.131016.layouts.chiyoda_budget_changes').restore_approval_evidence
    emit_candidates = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_changes').emit_candidates
    if spec.get('motion'):
        return emit_motion_registered(output, spec, raw_root=raw_root, definitions=definitions)
    if original['source'] != spec['source'] or original['sha256'] != spec['source']['content_inspection']['sha256']:
        raise ValueError('Inspected native original differs from the registered original')
    scopes = [scope for scope in original['editions'] if scope['edition'] == spec['edition']]
    if len(scopes) != 1 or [scopes[0]['first'], scopes[0]['last']] != spec['tables'][0]['pages']:
        raise ValueError('Discovered native account pages differ from the registered range')
    if definitions is None:
        definitions = definition_files()
    if set(definitions) != set(DEFINITION_PATHS):
        raise ValueError('Native supplementary support snapshot omits required definitions')
    result = emit_candidates(output, original, spec['edition'])
    if not result['checks']['complete_observed_grain']:
        raise ValueError('Native supplementary candidate reconciliation failed')
    registered_entries = []
    candidate_inputs = []
    candidate_counts = {item['role']: item['rows'] for item in result['candidate_inputs']}
    for table in spec['tables']:
        directory = output / table['observation_role']
        metadata = dict(read_lock(directory / 'inputs.lock.json')['entries'][0]['source'])
        if metadata['table_id'] != table['table_id'] or metadata['pages'] != table['pages']:
            raise ValueError('Emitted native table differs from the registered account pages')
        metadata.update(_registered_fields(spec, table, definitions))
        logical = input_path(spec['source'], table)
        if raw_root is not None:
            destination = raw_root / logical
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(directory / 'data.parquet', destination / 'data.parquet')
            directory = destination
        entry = record_input(directory, metadata, logical_path=logical)
        registered_entries.append(entry)
        candidate_inputs.append(dict(role=table['observation_role'], path=entry['path'], table=entry['table'],
            rows=candidate_counts[table['observation_role']], phases=metadata['phases']))
    restore_approval_evidence(registered_entries, OBJECTS, namespace=NAMESPACE)
    result.update(status='registered_extracted', approval_phase_assigned=spec['approval'] is not None,
                  candidate_inputs=candidate_inputs)
    (output / 'inspection.json').write_bytes(encode(result))
    return result


def emit_motion_registered(output: Path, spec: dict, *, raw_root: Path | None = None,
                           definitions: dict | None = None) -> dict:
    cached_original = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_amendment').cached_original
    extract_motion = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_amendment').extract_motion
    write_motion = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_amendment').write_motion
    table = spec['tables'][0]
    records, checks = extract_motion(cached_original(spec['source']), spec)
    directory = output / table['observation_role'] if raw_root is None else raw_root / input_path(spec['source'], table)
    write_motion(directory, records)
    metadata = _registered_fields(spec, table, definitions if definitions is not None else definition_files())
    metadata['raw_form'] = 'extracted'
    entry = record_input(directory, metadata, logical_path=input_path(spec['source'], table))
    result = dict(status='registered_motion_extracted', adopted=False, checks=checks,
        candidate_inputs=[dict(role='observations', path=entry['path'], table=entry['table'], rows=len(records), phases=[])])
    output.mkdir(parents=True, exist_ok=True)
    (output / 'inspection.json').write_bytes(encode(result))
    return result


def acquire_registered():
    """Fetch each budget original once and fan out its declared account tables."""
    inspect_original = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_changes').inspect_original
    from ingestion.lib.http import http_get
    grouped = defaultdict(list)
    for spec in registered_specs():
        grouped[spec['source']['id']].append(spec)
    definitions = definition_files() if grouped else None
    fetched_evidence = set()
    for specs in grouped.values():
        source = specs[0]['source']
        body = http_get(source['download_url']).body
        inspected = source['content_inspection']
        if digest(body) != inspected['sha256'] or len(body) != inspected['bytes']:
            raise ValueError('Native supplementary original differs from the inspected bytes')
        origin = save_object('origin', body)
        original = (dict(source=source, sha256=inspected['sha256']) if specs[0].get('motion')
                    else inspect_original(OBJECTS / origin['key'], source))
        for spec in specs:
            for url, evidence in (spec['approval']['evidence'].items() if spec['approval'] else []):
                if url not in fetched_evidence:
                    body = http_get(url).body
                    if digest(body) != evidence['sha256'] or len(body) != evidence['bytes']:
                        raise ValueError('Council evidence differs from the registered approval')
                    save_object('origin', body)
                    fetched_evidence.add(url)
            output = RAW.parent / 'reports' / NAMESPACE / source['id'] / f'edition-{spec["edition_index"]}'
            emit_registered(output, original, spec, raw_root=RAW, definitions=definitions)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquire-registered', action='store_true')
    args = parser.parse_args(argv)
    if not args.acquire_registered:
        parser.error('--acquire-registered is required')
    return acquire_registered()


if __name__ == '__main__':
    raise SystemExit(main())
