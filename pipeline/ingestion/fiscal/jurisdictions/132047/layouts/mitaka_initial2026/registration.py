"""Schema3 one-book observation adapter; runtime facts come from source_metadata.

The adopted lock binds Git definitions by installed canonical paths. No run
report, provenance sidecar, R2 evidence-code object or global build fingerprint
is an input declaration. Imports needed by the normal provider are lazy.
"""
from __future__ import annotations
import hashlib, json, tomllib
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[7]
PREFIX = 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026'
NAMESPACE = 'mitaka-initial2026'
SOURCE_KEY = '132047-initial-2026-book-226190ff2413'
ORIGIN_SHA = '226190ff24132abd4e372f5977226d8cb61c4015f372a8d1ee90ba5416e0a3af'
RAW_SHA = 'cddbb9966996b3de873c6a461bc88981e413cd2e18314433f172bb44d5d2eea2'
TABLE_ID = 'initial-observation'
ROWS = 1495
DATASET_ID = '132047:2026:observation:budget:' + ORIGIN_SHA + ':' + TABLE_ID
INPUT_PATH = NAMESPACE + '/jurisdiction=132047/year=2026/document_kind=budget/edition=' + ORIGIN_SHA + '/direction=observation/table=' + TABLE_ID
F25 = ['source_key','fiscal_year','document_kind','account','amendment','direction',
       'row_type','grain','name','printed_text','printed_amounts','amount_semantics','phase',
       'page','line','indent','col_context','table_index','section','sec_i','ordinal',
       'kan_amount','row_label','cells','extra']
NULL_FIELDS = ['amendment','phase','table_index','section','kan_amount','row_label','cells']
RAW_SCHEMA = [(name, 'INTEGER' if name in NULL_FIELDS else 'VARCHAR') for name in F25]
CSV_SCHEMA = [('jurisdiction_code', 'VARCHAR'), *RAW_SCHEMA]
DECLARATION_CONSTANTS = {
    'namespace': 'mitaka-initial2026', 'source_key': '132047-initial-2026-book-226190ff2413',
    'table_id': 'initial-observation', 'original_source_table_id': 'initial-observation',
    'observation_role': 'initial-budget-observation', 'grain': 'printed-row-observation',
    'source_grain': 'mixed printed rows; not an additive fiscal expenditure leaf',
    'raw_form': 'extracted', 'account': None, 'source_amount_unit': None,
    'unit_multiplier': None, 'source_amount_kind': None, 'amount_kind': None,
    'phase': None, 'phases': [], 'financial_phase': None,
    'approval_status': 'unconfirmed', 'approval_date': None, 'approval_proof': None,
    'recognition_status': 'unconfirmed', 'legal_correspondence_status': 'unconfirmed',
    'project_setsu_linkage': 'unconfirmed', 'additive_within_own_grain': False,
    'nonadditive': True, 'independent_breakdown': True,
    'canonical_initial': False, 'canonical_changes': False, 'canonical_executed': False,
    'source_page_range': [3, 187],
    'fiscal_year_basis': 'Printed edition cover FY2026; individual numeric-cell year remains unconfirmed',
    'year_basis': 'edition-cover-only; cell/year/role linkage unconfirmed',
    'source_position_method': 'original layout line and native WORD union; unresolved positions retained',
    'original_observation_identity': ['source_key','page','line','row_type'],
    'phase_note': 'No approval/financial phase inferred from initial-budget document label',
    'nonadditive_reason': 'Mixed ordinance totals, kan/kou controls and auxiliary numeric observations; overlapping quantities retained',
    'extractor': 'ingestion.fiscal.jurisdictions.132047.layouts.mitaka_initial2026 explicit --objects CLI; saved 25-field serializer',
}
# Filled by the stdlib-only proposal builder; installed paths, no lock/report hash.
DEFINITION_PATHS = ['pipeline/dbt/models/intermediate/fiscal/records/int_132047__mitaka_initial2026_datasets.sql', 'pipeline/dbt/models/intermediate/fiscal/records/int_fiscal_datasets.sql', 'pipeline/dbt/models/intermediate/fiscal/records/int_mitaka_initial2026.sql', 'pipeline/dbt/models/marts/csv/csv_132047_mitaka_initial2026_observation.sql', 'pipeline/dbt/models/marts/records/fiscal_datasets.sql', 'pipeline/dbt/models/marts/records/mart_mitaka_initial2026.sql', 'pipeline/dbt/models/staging/fiscal/_mitaka_initial2026_sources.yml', 'pipeline/dbt/models/staging/fiscal/stg_mitaka_initial2026.sql', 'pipeline/ingestion/declarations.py', 'pipeline/ingestion/fiscal/management/coverage_audit.py', 'pipeline/ingestion/fiscal/jurisdictions/132195/layouts/held5-runtime-manifest.json', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/__init__.py', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/__main__.py', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/config.json', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/coverage.py', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/decoder.py', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/raw-schema.json', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/reconstruct.py', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/registration.py', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/runtime-manifest.json', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/runtime.py', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/serialize.py', 'pipeline/ingestion/fiscal/jurisdictions/132047/layouts/mitaka_initial2026/sources.toml', 'pipeline/ingestion/fiscal/management/source_registry.py', 'pipeline/ingestion/fiscal/management/sources.json', 'pipeline/ingestion/fiscal/management/sources.py', 'pipeline/ingestion/fiscal/management/sources.schema.json']


def identity(relative):
    from ingestion.inputs import safe_relative
    path = REPO / safe_relative(relative)
    if not path.is_file() or path.is_symlink():
        raise ValueError('Missing or symbolic installed definition: ' + relative)
    body = path.read_bytes()
    return {'path': relative, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}


def definitions():
    if not DEFINITION_PATHS or len(set(DEFINITION_PATHS)) != len(DEFINITION_PATHS):
        raise ValueError('Definition path set is empty or ambiguous')
    return {path: identity(path) for path in DEFINITION_PATHS}


def specifications():
    specfile = DIRECTORY / 'sources.toml'
    all_specs = tomllib.loads(specfile.read_text())['mitaka_initial2026']
    cfg = json.loads((DIRECTORY / 'config.json').read_bytes())
    if len(all_specs) != 1 or cfg['source_key'] != SOURCE_KEY:
        raise ValueError('Exact one-original/source-key scope required')
    spec = next(iter(all_specs.values()))
    if (spec['jurisdiction_code'], spec['financial_year'], spec['document_kind'], spec['raw_form'],
        spec['origin_sha256'], spec['origin_bytes']) != ('132047', 2026, 'budget', 'extracted', ORIGIN_SHA, 2838828):
        raise ValueError('Original scope/spec changed')
    if (cfg['edition']['sha256'], cfg['edition']['bytes'], cfg['edition']['fiscal_year'], cfg['edition']['url']) != (ORIGIN_SHA, 2838828, 2026, spec['url']):
        raise ValueError('Extraction config and normal source specification differ')
    if len(spec['tables']) != 1:
        raise ValueError('One observed table required')
    table = spec['tables'][0]
    if (table['table_id'], table['role'], table['grain'], table['rows'], table['candidate_table_sha256'], table['candidate_table_bytes']) != (TABLE_ID, 'initial-budget-observation', 'printed-row-observation', ROWS, RAW_SHA, 386402):
        raise ValueError('Table identity or expected shape changed')
    if (table.get('direction') is not None or table.get('phase') is not None
            or table.get('source_amount_unit') is not None or table.get('unit_multiplier') is not None
            or table['additive_within_own_grain'] is not False
            or spec['recognition_status'] != 'unconfirmed'
            or table['legal_correspondence_status'] != 'unconfirmed'):
        raise ValueError('Observation acquired phase/unit/direction/recognition/additivity')
    if json.loads((DIRECTORY / 'raw-schema.json').read_text())['columns'] != F25:
        raise ValueError('Required physical raw fields changed')
    return spec, table


def expected_source():
    from ingestion.inputs import source_declaration
    spec, _ = specifications()
    declaration = dict(DECLARATION_CONSTANTS,
        request_url=spec['url'], original_url=spec['url'], source_url=spec['url'],
        landing_page=spec['landing_page'], document_title=spec['document_title'],
        document_label=spec['document_label'], url_basis=spec['url_basis'],
        redistribute=spec['redistribute'], redistribute_basis=spec['redistribute_basis'],
        license_id=spec['license_id'], attribution=spec['attribution'],
        definition_files=definitions(), source_manifest_sha256=identity(PREFIX + '/runtime-manifest.json')['sha256'],
        source_spec_sha256=identity(PREFIX + '/sources.toml')['sha256'],
        source_spec_bytes=identity(PREFIX + '/sources.toml')['bytes'])
    if source_declaration(declaration) != declaration:
        raise ValueError('Source declaration contains execution-only fields')
    return declaration


def input_entry():
    return dict(path=INPUT_PATH, jurisdiction='132047', fiscalYear=2026, documentKind='budget',
        direction=None, originEdition=ORIGIN_SHA,
        origin=dict(availability='stored', sha256=ORIGIN_SHA,
            object=dict(key='inputs/origin/sha256/' + ORIGIN_SHA, sha256=ORIGIN_SHA, bytes=2838828)),
        table=dict(key='inputs/table/sha256/' + RAW_SHA, sha256=RAW_SHA, bytes=386402),
        source=expected_source())


def get_sources():
    from ingestion.fiscal.management.sources import Source, Resource
    from ingestion.shared.jurisdictions import jurisdiction_name
    spec, table = specifications()
    return {SOURCE_KEY: Source(key=SOURCE_KEY, catalog=None, jurisdiction_code='132047',
        jurisdiction_name=jurisdiction_name('132047'), fiscal_year=2026, fiscal_year_label=None,
        document_kind='budget', document_label=spec['document_label'], dataset_title=None, encoding='',
        redistribute=spec['redistribute'], redistribute_basis=spec['redistribute_basis'],
        license_id=spec['license_id'], attribution=spec['attribution'], landing_page=spec['landing_page'],
        raw_form='extracted', resources=(Resource(direction=None, resource_name=spec['document_title'] + ' ' + TABLE_ID,
            url=spec['url'], url_basis=spec['url_basis'], table_id=table['table_id']),))}


def metadata(lock_path, entry):
    from ingestion.inputs import source_metadata_bytes
    if entry != input_entry():
        raise ValueError('Schema3 entry/source/object/installed-definition binding differs')
    value = json.loads(source_metadata_bytes(lock_path, entry))
    if (type(value['rows']) is not int or value['rows'] != ROWS or value['header'] != F25
            or value['raw_schema'] != [dict(name=n, type=t) for n, t in RAW_SCHEMA]
            or value['input_hashes_verified'] is not True
            or (value['jurisdiction_code'], value['fiscal_year'], value['document_kind'], value['direction']) != ('132047', 2026, 'budget', None)
            or (value['origin_sha256'], value['origin_bytes'], value['raw_table_sha256'], value['raw_table_bytes']) != (ORIGIN_SHA, 2838828, RAW_SHA, 386402)):
        raise ValueError('Regenerated source_metadata shape or identities differ')
    return value


def dataset_record(value):
    spec, table = specifications()
    structure = dict(hierarchy=[], dimensions=[], funds=[], scope=dict(
        granularity=table['grain'], observationRole=table['role'], independentBreakdown=True,
        additiveWithinOwnGrain=False, financialLeaf=False, nonadditive=True,
        mixedPrintedGrains=True, sourceAmountUnit=None, unitMultiplier=None,
        phase=None, approvalStatus='unconfirmed', recognitionStatus='unconfirmed',
        expenditureSetsuStatus='unconfirmed', projectSetsuLinkage='unconfirmed',
        cellYearRoleLinkage='unconfirmed'))
    source = dict(provider=NAMESPACE, namespace=NAMESPACE, sourceKey=SOURCE_KEY,
        originalSourceTableId=TABLE_ID, documentKind='budget', documentLabel=spec['document_label'],
        landingPage=spec['landing_page'], url=value['request_url'], sha256=ORIGIN_SHA, originalBytes=2838828,
        licenseId=spec['license_id'], attribution=spec['attribution'], rawForm='extracted', tableId=TABLE_ID,
        observationRole=table['role'], grain=table['grain'], direction=None, fiscalYear=2026,
        phases=[], phase=None, approvalStatus='unconfirmed', approvalDate=None, approvalProof=None,
        recognitionStatus='unconfirmed', legalCorrespondenceStatus='unconfirmed',
        sourceAmountUnit=None, sourceAmountKind=None, unitMultiplier=None,
        canonicalInitial=False, canonicalChanges=False, canonicalExecuted=False,
        independentBreakdown=True, additiveWithinOwnGrain=False, nonadditive=True,
        cellYearRoleLinkage='unconfirmed', expenditureSetsuStatus='unconfirmed', projectSetsuLinkage='unconfirmed',
        rawTableSha256=RAW_SHA, rawTableBytes=386402, rawSchema=value['raw_schema'],
        sourcePageRange=value['source_page_range'], yearBasis=value['year_basis'],
        definitionFiles=value['definition_files'], structure=structure)
    return dict(dataset_id=DATASET_ID, jurisdiction_code='132047', fiscal_year=2026, direction=None,
        document_kind='budget', origin_sha256=ORIGIN_SHA, phases_json='[]', line_count=value['rows'],
        source_json=json.dumps(source, ensure_ascii=False, sort_keys=True),
        structure_json=json.dumps(structure, ensure_ascii=False, sort_keys=True))


def register_declarations(rows, history, entries, lock_path):
    matching = [entry for entry in entries if entry['path'].startswith(NAMESPACE + '/')]
    if not matching:
        return rows, history
    if len(matching) != 1:
        raise ValueError('One exact Mitaka input required')
    if any(row['dataset_id'] == DATASET_ID for row in [*rows, *history]):
        raise ValueError('Mitaka dataset already registered or in fiscal history')
    value = metadata(lock_path, matching[0])
    source = get_sources()[SOURCE_KEY]
    if len(source.resources) != 1 or (source.resources[0].direction, source.resources[0].url, source.resources[0].table_id) != (None, value['request_url'], TABLE_ID):
        raise ValueError('Source/Resource/source declaration tuple differs')
    rows.append(dataset_record(value))
    # Observation is not approved/adjusted history; existing history is untouched.
    return rows, history
