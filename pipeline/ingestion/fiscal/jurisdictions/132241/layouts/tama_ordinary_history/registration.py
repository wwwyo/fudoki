"""Explicit recovered Tama FY2019/FY2020 ordinary-account namespace and fixed-input registration."""
from __future__ import annotations

from importlib import import_module as _ingestion_module
import hashlib, json, re, tomllib
from pathlib import Path

DIRECTORY = Path(__file__).absolute().parent
CONFIG = DIRECTORY / 'sources.toml'
NAMESPACE = 'tama-ordinary-history'
FINANCIAL = {'project-expenditure-original-rows'}
ROLES = FINANCIAL | {'positioned-original-text-layer-observation',
                     'whole-physical-page-observation'}


def identity(path):
    b = Path(path).read_bytes()
    return dict(path='pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history/' + Path(path).name,
                sha256=hashlib.sha256(b).hexdigest(), bytes=len(b))


def specifications():
    bounded_read = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').bounded_read
    validate_specs = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').validate_specs
    specs = tomllib.loads(bounded_read(CONFIG).decode())['ordinary_history']
    manifest = json.loads(bounded_read(DIRECTORY / 'evidence-manifest.json'))
    if len(manifest['originals'])!=20 or len({x['sha256'] for x in manifest['originals']})!=20:
        raise ValueError('Duplicate or missing original evidence occurrence')
    originals = {x['sha256']: x for x in manifest['originals']}
    if len(specs) != 15 or sum(len(x['tables']) for x in specs.values()) != 38:
        raise ValueError('Exact fifteen-document/38-table scope required')
    seen = set()
    for key, s in specs.items():
        o = originals[s['origin_sha256']]
        if s['jurisdiction_code'] != '132241' or s['raw_form'] != 'extracted':
            raise ValueError('Ordinary-history source scope changed')
        if s['document_kind'] != 'settlement':
            raise ValueError('Ordinary-history document kind must be settlement')
        if s['url'] != o['url'] or s['origin_bytes'] != o['bytes'] or s['recognition_status'] != 'unconfirmed':
            raise ValueError('Ordinary-history original identity changed')
        if not o['complete_capture']:
            raise ValueError('Adopted doc must be a complete capture')
        for t in s['tables']:
            if (key, t['table_id']) in seen or t['role'] not in ROLES:
                raise ValueError('Duplicate or unknown ordinary-history role')
            seen.add((key, t['table_id']))
            financial = t['role'] in FINANCIAL
            if financial:
                if t.get('direction') != 'expenditure' or t.get('phase') != 'executed':
                    raise ValueError('Financial row direction/phase changed')
                if t.get('source_amount_unit') is not None and \
                        (t.get('source_amount_unit'), t.get('unit_multiplier')) != ('千円', 1000):
                    raise ValueError('Only printed 千円 may declare a unit')
            else:
                if t.get('phase') is not None or t.get('source_amount_unit') is not None:
                    raise ValueError('Observation table cannot carry a money phase/unit')
            if t['additive_within_own_grain'] is not False or t['rows'] < 1 \
                    or not re.fullmatch('[a-f0-9]{64}', t['candidate_table_sha256']):
                raise ValueError('Ordinary-history count/hash/additivity changed')
    validate_specs(specs, manifest, json.loads(bounded_read(DIRECTORY / 'raw-schema.json')),
                   json.loads(bounded_read(DIRECTORY / 'replay-manifest.json')))
    for key,s in specs.items():s['source_spec_key']=key
    return specs


def input_path(spec, table):
    direction = 'expenditure' if table['role'] in FINANCIAL else table['direction']
    return (f"{NAMESPACE}/jurisdiction=132241/year={spec['financial_year']}"
            f"/document_kind={spec['document_kind']}/edition={spec['origin_sha256']}"
            f"/direction={direction}/table={table['table_id']}")


def dataset_id(spec, table):
    direction = 'expenditure' if table['role'] in FINANCIAL else table['direction']
    return (f"132241:{spec['financial_year']}:{direction}:{spec['document_kind']}"
            f":{spec['origin_sha256']}:{table['table_id']}")


def ordinary_history_sources():
    from ingestion.fiscal.management.sources import Source, Resource
    from ingestion.shared.jurisdictions import jurisdiction_name
    out = {}
    for key, s in specifications().items():
        out[f'ordinary-history:{key}'] = Source(
            key=f'ordinary-history:{key}', catalog=None, jurisdiction_code='132241',
            jurisdiction_name=jurisdiction_name('132241'), fiscal_year=s['financial_year'],
            fiscal_year_label=None, document_kind=s['document_kind'],
            document_label=s['document_label'], dataset_title=None, encoding='',
            redistribute=s['redistribute'], redistribute_basis=s['redistribute_basis'],
            license_id=s['license_id'], attribution=s['attribution'],
            landing_page=s['landing_page'], raw_form='extracted',
            resources=tuple(Resource(direction=t.get('direction'),
                                     resource_name=s['document_title'] + ' ' + t['table_id'],
                                     url=s['url'], url_basis=s['url_basis'], table_id=t['table_id'])
                            for t in s['tables']))
    return out


def reviewed_definitions() -> dict:
    read_reviewed_definitions = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').read_reviewed_definitions
    return read_reviewed_definitions(DIRECTORY)


def register_ordinary_history_declarations(rows, history, entries, lock_path):
    from ingestion.inputs import source_metadata_bytes
    validate_source_metadata = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').validate_source_metadata
    specs = specifications()
    sources = ordinary_history_sources()
    by_key = {f'ordinary-history:{k}': v for k, v in specs.items()}
    originals = {x['sha256']: x for x in json.loads((DIRECTORY / 'evidence-manifest.json').read_text())['originals']}
    definitions = reviewed_definitions()
    DEFINITION_PATH = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').DEFINITION_PATH
    seal = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').seal
    def source_seal(value):return seal((json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode())
    caller_ids=[r['dataset_id'] for r in rows]
    if len(caller_ids)!=len(set(caller_ids)):
        raise ValueError('Existing declarations contain duplicate dataset occurrence')
    seen = set();added_ids=set()
    for e in entries:
        if not e['path'].startswith(NAMESPACE + '/'):
            continue
        p = json.loads(source_metadata_bytes(lock_path, e))
        s = by_key[p['source_key']]
        ts = [t for t in s['tables'] if t['table_id'] == p['table_id']]
        if len(ts) != 1:
            raise ValueError('Ordinary-history declaration has ambiguous source-key/table tuple')
        t = ts[0]
        source = sources[p['source_key']]
        validate_source_metadata(e, p, s, t, definitions)
        financial = t['role'] in FINANCIAL
        expected_origin = dict(key='inputs/origin/sha256/' + s['origin_sha256'],
                               sha256=s['origin_sha256'], bytes=s['origin_bytes'])
        expected_table = dict(key='inputs/table/sha256/' + t['candidate_table_sha256'],
                              sha256=t['candidate_table_sha256'], bytes=t['candidate_table_bytes'])
        if (e['path'] != input_path(s, t) or e['path'] in seen or e['jurisdiction'] != '132241'
                or e['fiscalYear'] != s['financial_year'] or e['documentKind'] != s['document_kind']
                or e['direction'] != t.get('direction') or e['originEdition'] != s['origin_sha256']
                or e['origin']['object'] != expected_origin or e['table'] != expected_table
                or p['request_url'] != s['url'] or p['rows'] != t['rows']
                or p['observation_role'] != t['role']
                or p['source_amount_unit'] != t.get('source_amount_unit')
                or p['unit_multiplier'] != t.get('unit_multiplier')
                or p['recognition_status'] != 'unconfirmed'
                or p['legal_correspondence_status'] != 'unconfirmed'
                or {k: {x: y for x, y in v.items() if x in ('sha256', 'bytes')}
                       for k, v in p['definition_files'].items()} != definitions):
            raise ValueError('Adopted ordinary-history source/SHA/year/table/row/definition identity differs')
        matches = [r for r in source.resources
                   if (r.direction, r.url, r.table_id) == (e['direction'], p['request_url'], p['table_id'])]
        if len(matches) != 1:
            raise ValueError('Ordinary-history exact source-key/URL/table/direction registration differs')
        seen.add(e['path'])
        structure = dict(hierarchy=['fund', 'kan', 'kou', 'moku'] if financial else [],
                         dimensions=[], funds=[], scope=dict(
            granularity=t['grain'], observationRole=t['role'], independentBreakdown=True,
            additiveWithinOwnGrain=False, financialLeaf=financial,
            nonadditive=True, mixedPrintedGrains=financial,
            sourceAmountUnit=t.get('source_amount_unit'), unitMultiplier=t.get('unit_multiplier'),
            expenditureSetsuStatus='unconfirmed', projectSetsuLinkage='unconfirmed',
            recognitionStatus='unconfirmed',
            observedSetsuScheme='tama-printed-legacy-code-applicability-unconfirmed'))
        src = dict(provider=NAMESPACE, sourceKey=p['source_key'], documentKind=s['document_kind'],
                   documentLabel=s['document_label'], landingPage=s['landing_page'], url=s['url'],
                   sha256=e['originEdition'], originalBytes=s['origin_bytes'],
                   originalFetch=originals[e['originEdition']], licenseId=s['license_id'],
                   attribution=s['attribution'], rawForm='extracted', tableId=t['table_id'],
                   observationRole=t['role'], grain=t['grain'],
                   direction=t.get('direction'),
                   fiscalYear=s['financial_year'],
                   phases=['executed'] if financial else [],
                   sourceAmountUnit=t.get('source_amount_unit'), unitMultiplier=t.get('unit_multiplier'),
                   recognitionStatus='unconfirmed', expenditureSetsuStatus='unconfirmed',
                   projectSetsuLinkage='unconfirmed', independentBreakdown=True,
                   additiveWithinOwnGrain=False,
                   sourceDeclaration={k:v for k,v in e['source'].items() if k!='definition_files'},
                   sourceDeclarationSeal=source_seal(e['source']), inputMetadataKind='inline-source-v3',
                   regeneratedInputHashesVerified=p['input_hashes_verified'],
                   rawTableSha256=e['table']['sha256'], rawTableBytes=e['table']['bytes'],
                   rawSchema=p['raw_schema'], pages=p['pages'], definitionFiles={DEFINITION_PATH:definitions[DEFINITION_PATH]},
                   comparisonOnlyInputsExcludedFromExtraction=True, structure=structure)
        did=dataset_id(s,t)
        if did in caller_ids or did in added_ids:
            raise ValueError('New dataset collides with an existing declaration occurrence')
        added_ids.add(did)
        rows.append(dict(dataset_id=did, jurisdiction_code='132241',
                         fiscal_year=s['financial_year'], direction=t.get('direction'),
                         document_kind=s['document_kind'],
                         source_json=json.dumps(src, ensure_ascii=False, sort_keys=True)))
    if len(seen) != 38:
        raise ValueError('Exact38 adopted ordinary-history declarations required')
    return rows, history
