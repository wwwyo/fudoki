"""Explicit Tama pre-FY2020 recovered-observation namespace and fixed-input registration."""
from __future__ import annotations
import hashlib, json, re, tomllib
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
CONFIG = DIRECTORY / 'sources.toml'
NAMESPACE = 'tama-pre2020'
FINANCIAL = {'health-expenditure-original-rows'}
MONETARY_CONTROL = {'nonadditive-account-reference-control'}
ROLES = FINANCIAL | MONETARY_CONTROL | {'csv-lexical-original-rows',
        'positioned-original-text-layer-observation', 'whole-physical-page-observation'}


def identity(path):
    b = Path(path).read_bytes()
    return dict(path='pipeline/ingestion/fiscal/tama_pre2020/' + Path(path).name,
                sha256=hashlib.sha256(b).hexdigest(), bytes=len(b))


def specifications():
    specs = tomllib.loads(CONFIG.read_text())['pre2020_observation']
    manifest = json.loads((DIRECTORY / 'evidence-manifest.json').read_text())
    originals = {x['sha256']: x for x in manifest['originals']}
    if len(specs) != 30 or sum(len(x['tables']) for x in specs.values()) != 49:
        raise ValueError('Exact thirty-original/49-role scope required')
    seen = set()
    for key, s in specs.items():
        o = originals[s['origin_sha256']]
        if s['jurisdiction_code'] != '132241' or s['raw_form'] != 'extracted':
            raise ValueError('Pre2020 source scope changed')
        if s['document_kind'] not in ('budget', 'supplementary', 'settlement'):
            raise ValueError('Pre2020 document kind outside the fixed enum')
        if s['url'] != o['url'] or s['origin_bytes'] != o['bytes'] or s['recognition_status'] != 'unconfirmed':
            raise ValueError('Pre2020 original identity changed')
        for t in s['tables']:
            if (key, t['table_id']) in seen or t['role'] not in ROLES:
                raise ValueError('Duplicate or unknown pre2020 role')
            seen.add((key, t['table_id']))
            financial = t['role'] in FINANCIAL
            control = t['role'] in MONETARY_CONTROL
            if financial and (t['direction'], t['phase'], t['source_amount_unit'], t['unit_multiplier'],
                              t['legal_correspondence_status']) != ('expenditure', 'executed', '円', 1, 'unconfirmed'):
                raise ValueError('Printed health unit/phase/correspondence changed')
            if control and (t.get('direction') is not None or t.get('phase') is not None
                            or (t['source_amount_unit'], t['unit_multiplier'],
                                t['legal_correspondence_status']) != ('千円', 1000, 'unconfirmed')):
                raise ValueError('Account reference control unit/direction changed')
            if not (financial or control) and any(t.get(x) is not None for x in
                    ['direction', 'phase', 'source_amount_unit', 'unit_multiplier', 'legal_correspondence_status']):
                raise ValueError('Nonmonetary observation cannot acquire a direction, phase or unit')
            if t['additive_within_own_grain'] is not False or t['rows'] < 1 \
                    or not re.fullmatch('[a-f0-9]{64}', t['candidate_table_sha256']):
                raise ValueError('Pre2020 count/hash/additivity changed')
    return specs


def input_path(spec, table):
    token = 'expenditure' if table['role'] in FINANCIAL else 'observation'
    return (f"{NAMESPACE}/jurisdiction=132241/year={spec['financial_year']}"
            f"/document_kind={spec['document_kind']}/edition={spec['origin_sha256']}"
            f"/direction={token}/table={table['table_id']}")


def dataset_id(spec, table):
    token = 'expenditure' if table['role'] in FINANCIAL else 'observation'
    return (f"132241:{spec['financial_year']}:{token}:{spec['document_kind']}"
            f":{spec['origin_sha256']}:{table['table_id']}")


def pre2020_sources():
    from ingestion.fiscal.sources import Source, Resource
    from ingestion.shared.jurisdictions import jurisdiction_name
    out = {}
    for key, s in specifications().items():
        out[f'pre2020-observation:{key}'] = Source(
            key=f'pre2020-observation:{key}', catalog=None, jurisdiction_code='132241',
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


def register_pre2020_declarations(rows, history, entries, lock_path):
    from ingestion.inputs import source_metadata_bytes
    specs = specifications()
    sources = pre2020_sources()
    by_key = {f'pre2020-observation:{k}': v for k, v in specs.items()}
    originals = {x['sha256']: x for x in json.loads((DIRECTORY / 'evidence-manifest.json').read_text())['originals']}
    definitions = {n: identity(DIRECTORY / n) for n in
                   ['sources.toml', 'evidence-manifest.json', 'raw-schema.json', 'health-grid-declarations.json',
                    'registration.py', 'reconstruct.py']}
    seen = set()
    for e in entries:
        if not e['path'].startswith(NAMESPACE + '/'):
            continue
        p = json.loads(source_metadata_bytes(lock_path, e))
        s = by_key[p['source_key']]
        ts = [t for t in s['tables'] if t['table_id'] == p['table_id']]
        if len(ts) != 1:
            raise ValueError('Pre2020 declaration has ambiguous source-key/table tuple')
        t = ts[0]
        source = sources[p['source_key']]
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
                or p['definition_files'] != definitions):
            raise ValueError('Adopted pre2020 source/SHA/year/table/row/definition identity differs')
        matches = [r for r in source.resources
                   if (r.direction, r.url, r.table_id) == (e['direction'], p['request_url'], p['table_id'])]
        if len(matches) != 1:
            raise ValueError('Pre2020 exact source-key/URL/table/direction registration differs')
        seen.add(e['path'])
        structure = dict(hierarchy=['fund', 'kan', 'kou', 'moku'] if financial else [],
                         dimensions=[], funds=[], scope=dict(
            granularity=t['grain'], observationRole=t['role'], independentBreakdown=True,
            additiveWithinOwnGrain=False, financialLeaf=False, nonadditive=True,
            mixedPrintedGrains=t['role'] in FINANCIAL,
            sourceAmountUnit=t.get('source_amount_unit'), unitMultiplier=t.get('unit_multiplier'),
            expenditureSetsuStatus='unconfirmed', projectSetsuLinkage='unconfirmed',
            recognitionStatus='unconfirmed',
            observedSetsuScheme='tama-pre2020-printed-legacy-code-applicability-unconfirmed'))
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
                    
                   
                   rawTableSha256=e['table']['sha256'], rawTableBytes=e['table']['bytes'],
                   rawSchema=p['raw_schema'], pages=p['pages'], definitionFiles=definitions,
                   comparisonOnlyInputsExcludedFromExtraction=True, structure=structure)
        rows.append(dict(dataset_id=dataset_id(s, t), jurisdiction_code='132241',
                         fiscal_year=s['financial_year'], direction=t.get('direction'),
                         document_kind=s['document_kind'],
                         source_json=json.dumps(src, ensure_ascii=False, sort_keys=True)))
    return rows, history
