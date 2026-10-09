"""Exact Akishima FY2025 supplementary No.1 registry; private proposal, not yet installed.

Scope: the three printed 款別集計表 tables of the published 概要 PDF only
(歳入 summary, 目的別歳出 summary, 性質別歳出 summary). The 概要 detail rows,
fund/debt annexes and the whole-document observation table are deliberately
excluded from this finite integration — they remain nonadditive candidates.
amount_change is a printed 増減 amount (amount_kind='change'), never a phase;
budget_before / budget_after are the printed 補正前額 / 計 columns, NULL-preserved.
"""

from importlib import import_module as _ingestion_module
import hashlib,json
from pathlib import Path
CONFIG=Path(__file__).with_name('sources-akishima-supplementary-fy2025-01.json')
NAMESPACE='akishima-supplementary2020-2025'
TABLE_IDS={'kan-summary-revenue','kan-summary-expenditure-purpose','kan-summary-expenditure-nature'}

def specs(config=CONFIG):
    data=json.loads(Path(config).read_bytes());editions=data['editions']
    if data['schema_version']!=1 or data['namespace']!=NAMESPACE or len(editions)!=1:
        raise ValueError('Exact single FY2025 supplementary No.1 scope required')
    for e in editions:
        if e['fiscal_year']!=2025 or (e['jurisdiction_code'],e['document_kind'],e['amendment_number'])!=('132071','supplementary',1):
            raise ValueError('Edition scope differs')
        if len(e['tables'])!=3 or {t['table_id'] for t in e['tables']}!=TABLE_IDS:
            raise ValueError('Exactly the three printed kan-summary tables required')
        for t in e['tables']:
            if t['amount_kind']!='change' or t['phase'] is not None:
                raise ValueError('Delta is amount_kind=change, never a phase')
            if t['delta_sum']!=t['printed_total'] or t['printed_total']!=86300:
                raise ValueError('Printed section total does not match decoded kan delta sum')
            if t['additive_within_own_grain'] is not True:
                raise ValueError('Kan rows are additive only within their own printed table')
    return editions

def supplementary_fy2025_01_sources(config=CONFIG):
    from ingestion.fiscal.management.sources import Source, Resource
    out={}
    for e in specs(config):
        resources=tuple(Resource(direction=t['direction'],resource_name=e['document_title']+' '+t['table_id'],
                                 url=e['url'],url_basis=e['url_basis'],table_id=t['table_id']) for t in e['tables'])
        out[e['source_key']]=Source(key=e['source_key'],catalog=None,jurisdiction_code='132071',
            jurisdiction_name='昭島市',fiscal_year=e['fiscal_year'],fiscal_year_label=None,
            document_kind='supplementary',document_label=e['document_label'],dataset_title=None,
            encoding='',redistribute=e['redistribute'],redistribute_basis=e['redistribute_basis'],
            license_id=e['license_id'],attribution=e['attribution'],landing_page=e['landing_page'],
            raw_form='extracted',resources=resources)
    return out

def dataset_id(e,t):
    return f"132071:{e['fiscal_year']}:{t['direction']}:supplementary:{e['expected_sha256']}:{t['table_id']}"

def register_supplementary_fy2025_01_declarations(rows, history, entries, config=CONFIG, lock_path=None):
    """Validate lock entries against the sealed spec and emit dataset declarations."""
    from ingestion.inputs import source_metadata_bytes
    from ingestion.paths import INPUT_LOCK
    lock_path = lock_path or INPUT_LOCK
    for e in specs(config):
        lookup = {t['logical_path']: t for t in e['tables']}
        seen = set()
        for entry in entries:
            if not entry['path'].startswith(NAMESPACE + '/') or f"year={e['fiscal_year']}" not in entry['path']:
                continue
            if entry['path'] not in lookup or entry['path'] in seen:
                raise ValueError('Unknown or repeated supplementary FY2025-01 resource')
            seen.add(entry['path'])
            t = lookup[entry['path']]
            p = json.loads(source_metadata_bytes(lock_path, entry))
            expected_origin = dict(key='inputs/origin/sha256/' + e['expected_sha256'],
                                   sha256=e['expected_sha256'], bytes=e['expected_bytes'])
            expected_table = dict(key='inputs/table/sha256/' + t['expected_table_sha256'],
                                  sha256=t['expected_table_sha256'], bytes=t['expected_table_bytes'])
            if (entry['jurisdiction'] != '132071' or entry['fiscalYear'] != e['fiscal_year']
                    or entry['documentKind'] != 'supplementary' or entry['direction'] != t['direction']
                    or entry['originEdition'] != e['expected_sha256']
                    or entry['origin']['object'] != expected_origin or entry['table'] != expected_table
                    or p['source_key'] != e['source_key'] or p['table_id'] != t['table_id']
                    or p['rows'] != t['expected_rows'] or p['request_url'] != e['url']
                    or p['source_amount_unit'] != t['source_amount_unit']
                    or p['unit_multiplier'] != t['unit_multiplier']
                    or p['additive_within_own_grain'] != t['additive_within_own_grain']
                    or p['amount_kind'] != 'change'
                    or p['delta_sum'] != t['delta_sum'] or p['printed_total'] != t['printed_total']):
                raise ValueError('Approved supplementary FY2025-01 original/table/row identity differs: ' + entry['path'])
            validate_provenance(e,t,p,entry)
            structure = dict(
                hierarchy=['kan'], dimensions=[], funds=[dict(code='', label='一般会計')],
                scope=dict(granularity=t['grain'], observationRole=t['raw_role'],
                           additiveWithinOwnGrain=True, financialLeaf=False, nonadditiveAcrossTables=True,
                           printedTotalsAdditiveBoundary='section',
                           amountKind='change', budgetBeforeField='budget_before',
                           budgetAfterField='budget_after', sourceAmountUnit='千円', unitMultiplier=1000))
            source = dict(provider=NAMESPACE, sourceKey=e['source_key'], documentKind='supplementary',
                          documentLabel=e['document_label'], landingPage=e['landing_page'], url=e['url'],
                          sha256=e['expected_sha256'], originalBytes=e['expected_bytes'],
                          licenseId=e['license_id'], attribution=e['attribution'], rawForm='extracted',
                          namespace=NAMESPACE, tableId=t['table_id'], accountPartition='general',
                          observationRole=t['raw_role'], grain=t['grain'], direction=t['direction'],
                          phases=[], sourceAmountUnit='千円', unitMultiplier=1000,
                          additiveWithinOwnGrain=True, canonicalExecuted=False, canonicalChanges=False,
                          nonadditive=True, additiveScope='section', amendmentNumber=1, approval=e['approval'],
                          
                          
                          
                          rawTableSha256=entry['table']['sha256'], rawTableBytes=entry['table']['bytes'],
                          rawRowCount=p['rows'], rawSchema=p['raw_schema'],
                          immutableInputManifestSha256=p['source_manifest_sha256'],
                          structure=structure)
            rows.append(dict(dataset_id=dataset_id(e, t), jurisdiction_code='132071',
                             fiscal_year=e['fiscal_year'], direction=t['direction'],
                             document_kind='supplementary',
                             source_json=json.dumps(source, ensure_ascii=False, sort_keys=True)))
        if seen != set(lookup):
            raise ValueError('Missing finite supplementary resource declaration')
    return rows, history


def validate_provenance(e,t,p,entry):
    verify_local_evidence = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_supplementary_fy2025_01.evidence').verify_local_evidence
    manifest=verify_local_evidence()
    root=Path(__file__).resolve().parents[5]
    # Exact all26 field names/types, code definitions and archived evidence bindings.
    if (p['source_spec_sha256']!=hashlib.sha256(CONFIG.read_bytes()).hexdigest()
            or p['source_spec_bytes']!=CONFIG.stat().st_size
            or p['raw_schema']!=t['raw_schema'] or len(p['raw_schema'])!=26
            or p['raw_table_sha256']!=entry['table']['sha256']
            or p['raw_table_bytes']!=entry['table']['bytes']
            or p['origin_sha256']!=e['expected_sha256'] or p['origin_bytes']!=e['expected_bytes']
            or p['approval']!=e['approval'] or p['canonical_changes'] or p['canonical_executed']
            or p['definition_files']!=e['definition_files']
            or p['source_manifest_sha256']!=manifest['evidence/source-census.json']['sha256']):
        raise ValueError('Finite typed provenance identity differs')
    for ref in p['definition_files']:
        path=Path(ref['path'])
        if path.parts[0]!='pipeline' or '..' in path.parts:raise ValueError('Unsafe definition path')
        body=(root/Path(*path.parts[1:])).read_bytes()
        if hashlib.sha256(body).hexdigest()!=ref['sha256'] or len(body)!=ref['bytes']:
            raise ValueError('Definition bytes differ: '+ref['path'])
