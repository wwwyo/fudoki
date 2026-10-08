"""Six explicitly numbered, approved Komae original expenditure editions.

Git declarations bind every original and approval object to immutable bytes.
Native/manual recovery candidates are outside this supported provider.
"""
from __future__ import annotations
import json
from pathlib import Path
import re

CONFIG = Path(__file__).with_name('sources-council-approved.json')
FAMILY = 'supplementary-expenditure-project-setsu-council-original'
NAMESPACE = 'council-approved-detail'
ACCOUNT_SLUGS = {'一般会計':'general','介護保険特別会計':'care'}
SUPPORTED = {(2024,'一般会計',2),(2024,'一般会計',4),(2025,'一般会計',6),
             (2022,'一般会計',4),(2022,'一般会計',6),(2022,'介護保険特別会計',2)}

def load_council_approved(path: Path = CONFIG) -> dict[str, dict]:
    data=json.loads(path.read_text())
    if data['schema_version']!=1:raise ValueError('Unsupported council declaration schema')
    specs=data['council_approved'];identities=set()
    for key,spec in specs.items():
        identity=(spec['fiscal_year'],spec['fund_label'],spec['amendment_number'])
        identities.add(identity)
        expected=f'132195:{identity[0]}:{ACCOUNT_SLUGS[identity[1]]}:{identity[2]}'
        resource=FAMILY+'-'+ACCOUNT_SLUGS[identity[1]]+'-'+str(identity[2])
        if key!=expected or spec['table_id']!=resource or identity not in SUPPORTED:
            raise ValueError('Unsupported or colliding council original account/issue identity')
        if not re.fullmatch('[a-f0-9]{64}',spec['expected_table_sha256']) or spec['expected_rows']<=0:
            raise ValueError('Canonical table byte/count contract missing')
        if spec['approval_status']!='council-approved-original' or spec['edition_status']!='published':
            raise ValueError('A proposal listing is not adopted approval proof')
        proof=spec['approval_proof']
        if [proof[k] for k in ('fiscal_year','account','amendment_number')]!=list(identity):
            raise ValueError('Exact approval identity differs')
        for ref in proof['original_identity_evidence']+proof['resolution_evidence']:
            if ref.get('object_key')!='inputs/origin/sha256/'+ref['sha256'] or type(ref['bytes']) is not int:
                raise ValueError('Approval object needs immutable byte identity')
            if any(k in ref for k in ['local_path','object_path']):
                raise ValueError('Canonical approval proof cannot depend on exploratory paths')
    if identities!=SUPPORTED or len(specs)!=len(SUPPORTED):raise ValueError('Finite six-edition provider scope differs')
    return specs

def council_approved_sources(path: Path = CONFIG):
    from ingestion.fiscal.management.sources import Source, Resource
    from ingestion.shared.jurisdictions import jurisdiction_name
    return {NAMESPACE+':'+key:Source(key=NAMESPACE+':'+key,catalog=None,
        jurisdiction_code='132195',jurisdiction_name=jurisdiction_name('132195'),
        fiscal_year=s['fiscal_year'],fiscal_year_label=None,document_kind='supplementary',
        document_label=s['document_title'],dataset_title=None,encoding='',redistribute=s['redistribute'],
        redistribute_basis=s['redistribute_basis'],license_id=s['license_id'],attribution=s['attribution'],
        landing_page=s['landing_page'],raw_form='extracted',
        resources=(Resource(direction='expenditure',resource_name=s['document_title'],url=s['url'],
            url_basis=s['url_basis'],table_id=s['table_id']),)) for key,s in load_council_approved(path).items()}

def canonical_candidates():
    from ingestion.inputs import origin_path
    return [dict(s,source_key=NAMESPACE+':'+k,pdf_path=str(origin_path(s['expected_sha256'])))
            for k,s in load_council_approved().items()]

def evidence_objects():
    refs={}
    for spec in load_council_approved().values():
        for e in spec['approval_proof']['original_identity_evidence']+spec['approval_proof']['resolution_evidence']:
            ref=dict(key=e['object_key'],sha256=e['sha256'],bytes=e['bytes'])
            if ref['key'] in refs and refs[ref['key']]!=ref:raise ValueError('Conflicting approval byte identity')
            refs[ref['key']]=ref
    return list(refs.values())

def main():
    import argparse
    from ingestion.inputs import OBJECTS,verify_object,remote_object
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--describe',action='store_true')
    parser.add_argument('--restore-evidence',action='store_true')
    parser.add_argument('--remote',action='store_true',help='Retrieve only missing immutable declared bytes through cf R2')
    args=parser.parse_args();refs=evidence_objects()
    if args.describe:
        print(json.dumps(dict(schema_version=1,config=str(CONFIG),editions=len(SUPPORTED),objects=refs,
            restoration='Hash/size verified immutable cf R2 objects, never current replacement URLs'),ensure_ascii=False));return
    if not args.restore_evidence:parser.error('--restore-evidence or --describe is required')
    for ref in refs:
        p=OBJECTS/ref['key']
        if not p.exists():
            if not args.remote:raise FileNotFoundError('Missing approval/original object; restore-evidence --remote: '+ref['key'])
            remote_object(ref,'get')
        verify_object(ref,p.read_bytes())
    print(json.dumps(dict(status='verified-fixed-evidence',objects=len(refs))))

if __name__=='__main__':main()

def register_council_declarations(rows,history,entries):
    from ingestion.inputs import source_metadata_bytes
    from ingestion.paths import INPUT_LOCK
    specs=load_council_approved();seen=set()
    for entry in entries:
        if not entry['path'].startswith(NAMESPACE+'/'):continue
        p=json.loads(source_metadata_bytes(INPUT_LOCK,entry));s=specs[p['source_key'].removeprefix(NAMESPACE+':')]
        expected_path=(f"{NAMESPACE}/jurisdiction=132195/year={s['fiscal_year']}/document_kind=supplementary/"
                       f"edition={s['expected_sha256']}/direction=expenditure/table={s['table_id']}")
        if entry['path'] in seen:raise ValueError('Duplicate council original occurrence')
        seen.add(entry['path'])
        if (entry['path']!=expected_path or entry['jurisdiction']!='132195'
            or entry['fiscalYear']!=s['fiscal_year'] or entry['direction']!='expenditure'
            or entry['documentKind']!='supplementary' or p['fund_label']!=s['fund_label']
            or p['amendment_number']!=s['amendment_number']
            or entry['originEdition']!=s['expected_sha256'] or p['table_id']!=s['table_id']
            or entry['table']['sha256']!=s['expected_table_sha256'] or p['rows']!=s['expected_rows']
            or p['approval_proof']!=s['approval_proof']):
            raise ValueError('Adopted council bytes/count/whole-grain/approval contract differs')
        dataset=f"132195:{s['fiscal_year']}:expenditure:supplementary:{entry['originEdition']}:{s['table_id']}"
        source=dict(documentKind='supplementary',documentLabel=s['document_title'],landingPage=s['landing_page'],
            url=s['url'],sha256=entry['originEdition'],licenseId=s['license_id'],attribution=s['attribution'],
            rawForm='extracted',tableId=s['table_id'],pages=p['pages'],grain=p['grain'],
            observationRole='authoritative-council-supplementary-detail',canonicalChanges=True,
            approvalStatus=s['approval_status'],approvalDate=p['council_resolution_date'],
            councilResolutionDate=p['council_resolution_date'],printedSubmissionDate=p['printed_submission_date'],
            executiveDispositionDate=p['executive_disposition_date'],effectiveDate=p['effective_date'],
            effectiveDateBasis=p['effective_date_basis'],approvalProof=s['approval_proof'],
            amendmentNumber=s['amendment_number'],fundLabel=s['fund_label'],sourceAmountUnit='千円',unitMultiplier=1000,
            
            rawTableSha256=entry['table']['sha256'],reserveExceptionRows=s['reserve_exception_rows'],
            initialState='unconfirmed')
        row=dict(dataset_id=dataset,jurisdiction_code='132195',fiscal_year=s['fiscal_year'],direction='expenditure',
            document_kind='supplementary',source_json=json.dumps(source,ensure_ascii=False,sort_keys=True))
        rows.append(row)
        structure=dict(hierarchy=['kan','kou','moku','project','setsu'],dimensions=['department'],
            funds=[dict(code='',label=s['fund_label'])],scope=dict(granularity=p['grain'],
            authoritativeSupplementaryChanges=True,sourceAmountUnit='千円',initialState='unconfirmed',
            reserveExceptionRows=s['reserve_exception_rows'],expenditureSetsuStatus='printed-code-full-name-active-year-master-required'))
        history.append(dict(**row,origin_sha256=entry['originEdition'],effective_at=p['effective_date'],
            amendment_number=s['amendment_number'],fund_label=s['fund_label'],line_count=p['rows'],
            structure_json=json.dumps(structure,ensure_ascii=False,sort_keys=True)))
    return rows,history
