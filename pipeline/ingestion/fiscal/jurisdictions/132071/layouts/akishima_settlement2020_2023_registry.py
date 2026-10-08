"""Exact recognized Akishima FY2020-2023 settlement resource registry; no generic PDF routing."""
import hashlib,json
from pathlib import Path
CONFIG=Path(__file__).with_name('sources-akishima-settlement2020-2023.json')
NAMESPACE='akishima-settlement2020-2023'
FINANCIAL='financial';ROLES={'financial','controls','projects','page_inventory'}
EXPECTED={2020:5,2021:5,2022:5,2023:6}
BILL={'general':'認定第1号','health':'認定第2号','care':'認定第3号','elderly':'認定第4号','land':'認定第5号','north':'認定第6号'}

def specs(config=CONFIG):
 data=json.loads(Path(config).read_bytes());editions=data['editions']
 if data['schema_version']!=1 or data['namespace']!=NAMESPACE or len(editions)!=4:raise ValueError('Exact four-edition FY2020-2023 settlement scope required')
 for e in editions:
  y=e['fiscal_year']
  if (e['jurisdiction_code'],e['document_kind'])!=('132071','settlement'):raise ValueError('Settlement edition scope differs')
  if y not in EXPECTED or len(e['accounts'])!=EXPECTED[y]:raise ValueError('Ordinary-account roster differs: '+str(y))
  for a in e['accounts']:
   if y>2020 and a['bill']!=BILL[a['id']]:raise ValueError('Recognition bill differs: '+str(y)+a['id'])
   if y==2020 and a['bill'] is not None:raise ValueError('FY2020 recognition is unlocated; bill must be NULL')
  if len(e['tables'])!=len(e['accounts'])*3+2:raise ValueError('Typed resource count differs: '+str(y))
  by_account={(t['account_slug'],t['raw_role']) for t in e['tables'] if t['raw_role']!='page_inventory'}
  expected={(a['id'],r) for a in e['accounts'] for r in ['financial','controls','projects']}|{('_all','controls')}
  if by_account!=expected:raise ValueError('Typed raw roles differ: '+str(y))
  if sum(1 for t in e['tables'] if t['raw_role']=='page_inventory')!=1:raise ValueError('Exactly one physical-page inventory per edition')
  for t in e['tables']:
   if t['additive_within_own_grain']!=(t['raw_role']==FINANCIAL):raise ValueError('Only moku x printed-legal-setsu financial rows are additive')
   if (t['raw_role']==FINANCIAL)!=(t['phase']=='executed'):raise ValueError('Executed phase belongs only to the financial grain')
 return editions

def settlement2020_2023_sources(config=CONFIG):
 from ingestion.fiscal.management.sources import Source, Resource
 out={}
 for e in specs(config):
  resources=tuple(Resource(direction=t['direction'],resource_name=e['document_title']+' '+t['table_id'],url=e['url'],url_basis=e['url_basis'],table_id=t['table_id']) for t in e['tables'])
  out[e['source_key']]=Source(key=e['source_key'],catalog=None,jurisdiction_code='132071',jurisdiction_name='昭島市',fiscal_year=e['fiscal_year'],fiscal_year_label=None,document_kind='settlement',document_label=e['document_label'],dataset_title=None,encoding='',redistribute=e['redistribute'],redistribute_basis=e['redistribute_basis'],license_id=e['license_id'],attribution=e['attribution'],landing_page=e['landing_page'],raw_form='extracted',resources=resources)
 return out

def dataset_id(e,t):
 token='expenditure' if t['direction']=='expenditure' else 'observation'
 return f"132071:{e['fiscal_year']}:{token}:settlement:{e['expected_sha256']}:{t['table_id']}"

def _definitions():
 base=Path(__file__).parent
 defs=[dict(path='pipeline/ingestion/fiscal/jurisdictions/132071/layouts/'+n,sha256=hashlib.sha256((base/n).read_bytes()).hexdigest(),bytes=(base/n).stat().st_size) for n in ['sources-akishima-settlement2020-2023.json','akishima_settlement2020_2023_registry.py']]
 defs+=[dict(path='pipeline/ingestion/fiscal/jurisdictions/132071/layouts/akishima_settlement2020_2023/'+n,sha256=hashlib.sha256((base/'akishima_settlement2020_2023'/n).read_bytes()).hexdigest(),bytes=(base/'akishima_settlement2020_2023'/n).stat().st_size) for n in ['__init__.py','__main__.py','provider.py','decoder.py','verify.py','materialize.py','config.json','evidence-manifest.json']]
 return defs

def data_manifest(config):
 return json.loads(Path(config).read_bytes())['source_manifest_sha256']

def register_settlement2020_2023_declarations(rows,history,entries,config=CONFIG,lock_path=None):
 from ingestion.inputs import source_metadata_bytes
 from ingestion.paths import INPUT_LOCK
 lock_path=lock_path or INPUT_LOCK
 definitions=_definitions()
 for e in specs(config):
  lookup={t['logical_path']:t for t in e['tables']};seen=set()
  for entry in entries:
   if not entry['path'].startswith(NAMESPACE+'/') or f"year={e['fiscal_year']}" not in entry['path']:continue
   if entry['path'] not in lookup or entry['path'] in seen:raise ValueError('Unknown or repeated settlement2020-2023 resource')
   seen.add(entry['path']);t=lookup[entry['path']];p=json.loads(source_metadata_bytes(lock_path,entry))
   fund_label=next((a['name'] for a in e['accounts'] if a['id']==t['account_slug']),None)
   expected_origin=dict(key='inputs/origin/sha256/'+e['expected_sha256'],sha256=e['expected_sha256'],bytes=e['expected_bytes'])
   expected_table=dict(key='inputs/table/sha256/'+t['expected_table_sha256'],sha256=t['expected_table_sha256'],bytes=t['expected_table_bytes'])
   financial=t['raw_role']==FINANCIAL
   if (entry['jurisdiction']!='132071' or entry['fiscalYear']!=e['fiscal_year'] or entry['documentKind']!='settlement'
       or entry['direction']!=t['direction'] or entry['originEdition']!=e['expected_sha256']
       or entry['origin']['object']!=expected_origin or entry['table']!=expected_table
       or p['source_key']!=e['source_key'] or p['table_id']!=t['table_id'] or p['rows']!=t['expected_rows']
       or p['observation_role']!=t['raw_role'] or p['request_url']!=e['url']
       or p.get('fund_label')!=fund_label
       or p['source_amount_unit']!=t.get('source_amount_unit') or p['unit_multiplier']!=t.get('unit_multiplier')
       or p['additive_within_own_grain']!=t['additive_within_own_grain']
       or p['recognition_status']!=e['recognition_status'] or p['definition_files']!=definitions
       or p['source_manifest_sha256']!=data_manifest(config)):raise ValueError('Approved settlement2020-2023 fixed original/table/row/recognition identity differs: '+entry['path'])
   structure=dict(
    hierarchy=['kan','kou','moku','setsu'] if financial else ['kan','kou','moku'] if t['raw_role']=='controls' else ['kan','kou','moku','project-remark'] if t['raw_role']=='projects' else [],
    dimensions=[],funds=[dict(code='',label=fund_label)] if fund_label is not None else ([dict(code='',label='全会計合計')] if t['account_slug']=='_all' else []),
    scope=dict(granularity=t['grain'],observationRole=t['raw_role'],authoritativeExecuted=financial,
     financialLeaf=financial,nonadditive=not financial,sourceAmountUnit=t.get('source_amount_unit'),
     unitMultiplier=t.get('unit_multiplier'),projectSetsuLinkage='unconfirmed-independent-remark-totals',
     printedLeftCodesTransferToProjects=False,statutorySetsuStatus='printed-code-name-active-year-assessed',
     budgetColumnsAreNonadditiveReferences=True))
   source=dict(provider=NAMESPACE,sourceKey=e['source_key'],documentKind='settlement',documentLabel=e['document_label'],
    landingPage=e['landing_page'],url=e['url'],sha256=e['expected_sha256'],originalBytes=e['expected_bytes'],
    licenseId=e['license_id'],attribution=e['attribution'],rawForm='extracted',namespace=NAMESPACE,
    tableId=t['table_id'],accountPartition=t['account_slug'],observationRole=t['raw_role'],grain=t['grain'],
    direction=t['direction'],phases=['executed'] if financial else [],sourceAmountUnit=t.get('source_amount_unit'),
    unitMultiplier=t.get('unit_multiplier'),additiveWithinOwnGrain=t['additive_within_own_grain'],
    canonicalExecuted=financial,canonicalChanges=False,nonadditive=not financial,
    recognitionStatus=e['recognition_status'],recognitionDate=e['recognition_date'],
    recognitionProof=p.get('recognition_proof'),printedSubmissionDate=None,
    expenditureSetsuStatus=p['statutory_correspondence_status'],projectSetsuLinkage='unconfirmed',
    cofogStatus='unclassified',gfsm=None,
    
    rawTableSha256=entry['table']['sha256'],rawTableBytes=entry['table']['bytes'],rawRowCount=p['rows'],rawSchema=p['raw_schema'],
    pages=p['pages'],originalSourceTableId=p['original_source_table_id'],reserveRows=p['reserve_rows'],
    printedZeroRows=p['printed_zero_rows'],immutableInputManifestSha256=p['source_manifest_sha256'],
    definitionFiles=definitions,structure=structure)
   rows.append(dict(dataset_id=dataset_id(e,t),jurisdiction_code='132071',fiscal_year=e['fiscal_year'],direction=t['direction'],document_kind='settlement',source_json=json.dumps(source,ensure_ascii=False,sort_keys=True)))
 return rows,history
