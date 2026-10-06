"""Exact recognized Akishima FY2024 settlement resource registry; no generic PDF routing."""
import hashlib,json
from pathlib import Path
CONFIG=Path(__file__).with_name('sources-akishima-settlement2024.json')
NAMESPACE='akishima-settlement2024'
EXPECTED_ACCOUNTS={('general','認定第1号'),('health','認定第2号'),('care','認定第3号'),('elderly','認定第4号'),('land','認定第5号'),('north','認定第6号')}
FINANCIAL='financial';ROLES={'financial','controls','projects','page_inventory'}

def specs(config=CONFIG):
 data=json.loads(Path(config).read_bytes());editions=data['editions']
 if data['schema_version']!=1 or data['namespace']!=NAMESPACE or len(editions)!=1:raise ValueError('Exact one-edition FY2024 settlement scope required')
 e=editions[0]
 if (e['jurisdiction_code'],e['fiscal_year'],e['document_kind'])!=('132071',2024,'settlement'):raise ValueError('Settlement edition scope differs')
 if {(a['id'],a['bill']) for a in e['accounts']}!=EXPECTED_ACCOUNTS:raise ValueError('Ordinary-account recognition roster differs')
 if len(e['accounts'])!=6 or len(e['tables'])!=19:raise ValueError('Six accounts and nineteen typed resources required')
 by_account={(t['account_slug'],t['raw_role']) for t in e['tables'] if t['raw_role']!='page_inventory'}
 if by_account!={(a,r) for a,_ in EXPECTED_ACCOUNTS for r in ['financial','controls','projects']}:raise ValueError('Three typed raw roles required per account')
 if sum(1 for t in e['tables'] if t['raw_role']=='page_inventory')!=1:raise ValueError('Exactly one physical-page inventory required')
 for t in e['tables']:
  if t['additive_within_own_grain']!=(t['raw_role']==FINANCIAL):raise ValueError('Only moku x printed-legal-setsu financial rows are additive')
  if (t['raw_role']==FINANCIAL)!=(t['phase']=='executed'):raise ValueError('Executed phase belongs only to the financial grain')
 return editions

def settlement2024_sources(config=CONFIG):
 from ingestion.fiscal.sources import Source,Resource
 e=specs(config)[0]
 resources=tuple(Resource(direction=t['direction'],resource_name=e['document_title']+' '+t['table_id'],url=e['url'],url_basis=e['url_basis'],table_id=t['table_id']) for t in e['tables'])
 return {e['source_key']:Source(key=e['source_key'],catalog=None,jurisdiction_code='132071',jurisdiction_name='昭島市',fiscal_year=2024,fiscal_year_label=None,document_kind='settlement',document_label=e['document_label'],dataset_title=None,encoding='',redistribute=e['redistribute'],redistribute_basis=e['redistribute_basis'],license_id=e['license_id'],attribution=e['attribution'],landing_page=e['landing_page'],raw_form='extracted',resources=resources)}

def dataset_id(t):
 token='expenditure' if t['direction']=='expenditure' else 'observation'
 return f"132071:2024:{token}:settlement:{ORIGIN}:{t['table_id']}"

ORIGIN='20802834f53ef0a92ff9098bf05bd162cc603de55a998529f041008addcaaf71'

def register_settlement2024_declarations(rows,history,entries,config=CONFIG,lock_path=None):
 from ingestion.inputs import source_metadata_bytes
 from ingestion.paths import INPUT_LOCK
 lock_path=lock_path or INPUT_LOCK;e=specs(config)[0]
 lookup={t['logical_path']:t for t in e['tables']};seen=set()
 definitions=[dict(path='pipeline/ingestion/fiscal/'+n,sha256=hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest(),bytes=Path(__file__).with_name(n).stat().st_size) for n in ['sources-akishima-settlement2024.json','akishima_settlement2024_registry.py']]
 definitions+= [dict(path='pipeline/ingestion/fiscal/akishima_settlement2024/'+n,sha256=hashlib.sha256((Path(__file__).parent/'akishima_settlement2024'/n).read_bytes()).hexdigest(),bytes=(Path(__file__).parent/'akishima_settlement2024'/n).stat().st_size) for n in ['__init__.py','__main__.py','provider.py','decoder.py','materialize.py','config.json']]
 for entry in entries:
  if not entry['path'].startswith(NAMESPACE+'/'):continue
  if entry['path'] not in lookup or entry['path'] in seen:raise ValueError('Unknown or repeated settlement2024 resource')
  seen.add(entry['path']);t=lookup[entry['path']];p=json.loads(source_metadata_bytes(lock_path,entry))
  expected_origin=dict(key='inputs/origin/sha256/'+e['expected_sha256'],sha256=e['expected_sha256'],bytes=e['expected_bytes'])
  expected_table=dict(key='inputs/table/sha256/'+t['expected_table_sha256'],sha256=t['expected_table_sha256'],bytes=t['expected_table_bytes'])
  financial=t['raw_role']==FINANCIAL
  if (entry['jurisdiction']!='132071' or entry['fiscalYear']!=2024 or entry['documentKind']!='settlement'
      or entry['direction']!=t['direction'] or entry['originEdition']!=e['expected_sha256']
      or entry['origin']['object']!=expected_origin or entry['table']!=expected_table
      or p['source_key']!=e['source_key'] or p['table_id']!=t['table_id'] or p['rows']!=t['expected_rows']
      or p['observation_role']!=t['raw_role'] or p['request_url']!=e['url']
      or p['source_amount_unit']!=t.get('source_amount_unit') or p['unit_multiplier']!=t.get('unit_multiplier')
      or p['additive_within_own_grain']!=t['additive_within_own_grain']
      or p['recognition_status']!='recognized-2025-10-02' or p['definition_files']!=definitions
      or p['source_manifest_sha256']!=data_manifest(config)):raise ValueError('Approved settlement2024 fixed original/table/row/recognition identity differs')
  financial_role=t['raw_role']
  structure=dict(
   hierarchy=['kan','kou','moku','setsu'] if financial_role==FINANCIAL else ['kan','kou','moku'] if financial_role=='controls' else ['kan','kou','moku','project-remark'] if financial_role=='projects' else [],
   dimensions=[],funds=[dict(code='',label=next(a['name'] for a in e['accounts'] if a['id']==t['account_slug']))] if t['account_slug'] else [],
   scope=dict(granularity=t['grain'],observationRole=financial_role,authoritativeExecuted=financial,
    financialLeaf=financial,nonadditive=not financial,sourceAmountUnit=t.get('source_amount_unit'),
    unitMultiplier=t.get('unit_multiplier'),projectSetsuLinkage='unconfirmed-independent-remark-totals',
    printedLeftCodesTransferToProjects=False,statutorySetsuStatus='printed-code-name-active-year-assessed',
    budgetColumnsAreNonadditiveReferences=True))
  source=dict(provider=NAMESPACE,sourceKey=e['source_key'],documentKind='settlement',documentLabel=e['document_label'],
   landingPage=e['landing_page'],url=e['url'],sha256=e['expected_sha256'],originalBytes=e['expected_bytes'],
   licenseId=e['license_id'],attribution=e['attribution'],rawForm='extracted',namespace=NAMESPACE,
   tableId=t['table_id'],accountPartition=t['account_slug'],observationRole=financial_role,grain=t['grain'],
   direction=t['direction'],phases=['executed'] if financial else [],sourceAmountUnit=t.get('source_amount_unit'),
   unitMultiplier=t.get('unit_multiplier'),additiveWithinOwnGrain=t['additive_within_own_grain'],
   canonicalExecuted=financial,canonicalChanges=False,nonadditive=not financial,
   recognitionStatus='recognized-2025-10-02',recognitionDate=e['recognition_date'],
   recognitionProof=p['recognition_proof'],printedSubmissionDate=None,
   expenditureSetsuStatus=p['statutory_correspondence_status'],projectSetsuLinkage='unconfirmed',
   cofogStatus='unclassified',gfsm=None,
   
   rawTableSha256=entry['table']['sha256'],rawTableBytes=entry['table']['bytes'],rawRowCount=p['rows'],rawSchema=p['raw_schema'],
   pages=p['pages'],originalSourceTableId=p['original_source_table_id'],reserveRows=p['reserve_rows'],
   printedZeroRows=p['printed_zero_rows'],immutableInputManifestSha256=p['source_manifest_sha256'],
   definitionFiles=definitions,structure=structure)
  rows.append(dict(dataset_id=dataset_id(t),jurisdiction_code='132071',fiscal_year=2024,direction=t['direction'],document_kind='settlement',source_json=json.dumps(source,ensure_ascii=False,sort_keys=True)))
 return rows,history

def data_manifest(config):
 return json.loads(Path(config).read_bytes())['source_manifest_sha256']
