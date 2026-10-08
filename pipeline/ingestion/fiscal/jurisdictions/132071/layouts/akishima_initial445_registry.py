"""Exact approved Akishima initial445 resource registry; no generic PDF routing."""
import hashlib,json
from pathlib import Path
CONFIG=Path(__file__).with_name('sources-akishima-initial445.json')
NAMESPACE='akishima-initial445'
def specs(config=CONFIG):
 data=json.loads(Path(config).read_bytes());editions=data['editions']
 if data['schema_version']!=1 or data['namespace']!=NAMESPACE or len(editions)!=8:raise ValueError('Exact eight-edition initial445 scope required')
 expected={(2023,'land'),(2023,'north'),(2025,'health'),(2025,'elderly'),(2025,'land'),(2025,'north'),(2026,'land'),(2026,'north')}
 if {(e['fiscal_year'],e['account_slug']) for e in editions}!=expected:raise ValueError('Ordinary-account initial edition roster differs')
 if any(len(e['tables'])!=3 for e in editions):raise ValueError('Three separately typed raw roles required per edition')
 return editions

def initial445_sources(config=CONFIG):
 from ingestion.fiscal.management.sources import Source, Resource
 return {e['source_key']:Source(key=e['source_key'],catalog=None,jurisdiction_code='132071',jurisdiction_name='昭島市',fiscal_year=e['fiscal_year'],fiscal_year_label=None,document_kind='budget',document_label=e['document_title'],dataset_title=None,encoding='',redistribute=e['redistribute'],redistribute_basis=e['redistribute_basis'],license_id=e['license_id'],attribution=e['attribution'],landing_page=e['landing_page'],raw_form='extracted',resources=tuple(Resource(direction='expenditure',resource_name=e['document_title']+' '+t['raw_role'],url=e['url'],url_basis='Whole immutable original and exact approved council bill; finite cached native/cell extraction',table_id=t['table_id']) for t in e['tables'])) for e in specs(config)}

def register_initial445_declarations(rows,history,entries,config=CONFIG,lock_path=None):
 from ingestion.inputs import source_metadata_bytes
 from ingestion.paths import INPUT_LOCK
 lock_path=lock_path or INPUT_LOCK;lookup={t['logical_path']:(e,t) for e in specs(config) for t in e['tables']};seen=set()
 for entry in entries:
  if not entry['path'].startswith(NAMESPACE+'/'):continue
  if entry['path'] not in lookup or entry['path'] in seen:raise ValueError('Unknown or repeated initial445 resource')
  seen.add(entry['path']);e,t=lookup[entry['path']];p=json.loads(source_metadata_bytes(lock_path,entry))
  if (entry['jurisdiction']!='132071' or entry['fiscalYear']!=e['fiscal_year'] or entry['originEdition']!=e['expected_sha256'] or entry['documentKind']!='budget' or entry['direction']!='expenditure' or entry['table']['sha256']!=t['expected_table_sha256'] or entry['table']['bytes']!=t['expected_table_bytes'] or p['rows']!=t['expected_rows'] or p['source_key']!=e['source_key'] or p['table_id']!=t['table_id'] or p['approval_proof']!=e['approval']):raise ValueError('Approved initial445 fixed original/table/row/approval identity differs')
  financial=t['raw_role']=='explanation';dataset=f"132071:{e['fiscal_year']}:expenditure:budget:{e['expected_sha256']}:{t['table_id']}"
  structure=dict(hierarchy=['kan','kou','moku','project','setsu','detail'] if financial else ['kan','kou','moku'],dimensions=['department'] if financial else [],funds=[dict(code='',label=e['account'])],scope=dict(granularity=p['grain'],observationRole=t['raw_role'],authoritativeInitial=financial,financialLeaf=financial,nonadditive=not financial,sourceAmountUnit='千円',unitMultiplier=1000,explanationLegalCorrespondence='unconfirmed-no-printed-explanation-code',leftLegalTransferToExplanation=False))
  source=dict(documentKind='budget',documentLabel=e['document_title'],landingPage=e['landing_page'],url=e['url'],sha256=e['expected_sha256'],licenseId=e['license_id'],attribution=e['attribution'],rawForm='extracted',namespace=NAMESPACE,tableId=t['table_id'],originalSourceTableId=p['original_source_table_id'],pages=p['pages'],fundLabel=e['account'],observationRole=t['raw_role'],grain=p['grain'],canonicalInitial=financial,canonicalChanges=False,nonadditive=not financial,sourceAmountUnit='千円',unitMultiplier=1000,financialPhase='approved' if financial else None,approvedInitialObservation=True,approvalDate=e['approval_date'],printedSubmissionDate=e['submitted_date'],approvalStatus=p['approval_status'],approvalProof=e['approval'],documentDirectEvidence=e['document_direct_evidence'],rawTableSha256=entry['table']['sha256'],rawRowCount=p['rows'],structure=structure,reserveExceptionRows=p['reserve_rows'],immutableInputManifestSha256=p['source_manifest_sha256'],initialTargetCorrespondence='observed-origin-row; no equivalence to other namespace asserted',cofogStatus='unclassified',gfsm=None)
  rows.append(dict(dataset_id=dataset,jurisdiction_code='132071',fiscal_year=e['fiscal_year'],direction='expenditure',document_kind='budget',source_json=json.dumps(source,ensure_ascii=False,sort_keys=True)))
 # Initial445 declarations deliberately do not add references to the budget history route.
 return rows,history
