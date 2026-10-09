"""Proposed exact Akishima FY2019 settlement resource registry; no generic PDF routing.

Recognition is NULL/unconfirmed (no FY2019 results page on the official council
index). Phase 'executed' applies only to printed 支出済額/収入済額 cells.
Revenue rows are nonadditive until leaf grain is proved.
"""
import hashlib,json
from pathlib import Path
CONFIG=Path(__file__).with_name('sources-akishima-settlement2019.json')
NAMESPACE='akishima-settlement2019'
EDITION='per-origin-sha256'
EXPECTED_ACCOUNTS={'general','kokuho','kaigo','kouki','gesui','kukaku'}
ROLES={'financial','controls','projects','revenue','page_inventory'}

def specs(config=CONFIG):
 data=json.loads(Path(config).read_bytes());editions=data['editions']
 if data['schema_version']!=1 or data['namespace']!=NAMESPACE or len(editions)!=1:raise ValueError('Exact one-edition FY2019 settlement scope required')
 e=editions[0]
 if (e['jurisdiction_code'],e['fiscal_year'],e['document_kind'])!=('132071',2019,'settlement'):raise ValueError('Settlement edition scope differs')
 if {a['id'] for a in e['accounts']}!=EXPECTED_ACCOUNTS:raise ValueError('Ordinary-account roster differs')
 if len(e['originals'])!=9:raise ValueError('Nine intact split originals required')
 if len(e['tables'])!=32:raise ValueError('Thirty-two typed raw resources required')
 if e['recognition_date'] is not None:raise ValueError('Recognition must stay NULL/unconfirmed')
 origins={o['file']:o for o in e['originals']}
 for t in e['tables']:
  if t['raw_role'] not in ROLES:raise ValueError('Unknown raw role')
  if t['additive_within_own_grain']!=(t['raw_role']=='financial'):raise ValueError('Only moku x printed-setsu financial rows are additive')
  if (t['phase']=='executed')!=(t['raw_role'] in ('financial','revenue')):raise ValueError('Executed phase belongs only to printed 支出済額/収入済額 rows')
  if t['recognition_status']!='unconfirmed' or t['recognition_bill'] is not None:raise ValueError('Recognition must be unconfirmed')
  if t['origin_file'] not in origins:raise ValueError('Every table needs exactly one origin')
  o=origins[t['origin_file']]
  if t['origin_sha256']!=o['sha256'] or t['origin_url']!=o['url'] or t['origin_bytes']!=o['bytes']:raise ValueError('Table origin identity differs')
 return editions

def settlement2019_sources(config=CONFIG):
 from ingestion.fiscal.management.sources import Source, Resource
 e=specs(config)[0]
 resources=tuple(Resource(direction=t['direction'],resource_name=e['document_title']+' '+t['table_id'],url=t['origin_url'] or e['url'],url_basis=e['url_basis'],table_id=t['table_id']) for t in e['tables'])
 return {e['source_key']:Source(key=e['source_key'],catalog=None,jurisdiction_code='132071',jurisdiction_name='昭島市',fiscal_year=2019,fiscal_year_label='令和元年度',document_kind='settlement',document_label=e['document_label'],dataset_title=None,encoding='',redistribute=e['redistribute'],redistribute_basis=e['redistribute_basis'],license_id=e['license_id'],attribution=e['attribution'],landing_page=e['landing_page'],raw_form='extracted',resources=resources)}

def dataset_id(t):
 token={'expenditure':'expenditure','revenue':'revenue',None:'observation'}[t['direction']]
 return f"132071:2019:{token}:settlement:{t['origin_sha256']}:{t['table_id']}"

def register_settlement2019_declarations(rows,history,entries,config=CONFIG,lock_path=None):
 from ingestion.inputs import source_metadata_bytes
 from ingestion.paths import INPUT_LOCK
 lock_path=lock_path or INPUT_LOCK;e=specs(config)[0]
 lookup={t['logical_path']:t for t in e['tables']};seen=set()
 for entry in entries:
  if not entry['path'].startswith(NAMESPACE+'/'):continue
  if entry['path'] not in lookup or entry['path'] in seen:raise ValueError('Unknown or repeated settlement2019 resource')
  seen.add(entry['path']);t=lookup[entry['path']];p=json.loads(source_metadata_bytes(lock_path,entry))
  financial=t['raw_role']=='financial'
  expected_origin=dict(key='inputs/origin/sha256/'+t['origin_sha256'],sha256=t['origin_sha256'],bytes=t['origin_bytes']) if t['origin_sha256'] else None
  expected_table=dict(key='inputs/table/sha256/'+t['expected_table_sha256'],sha256=t['expected_table_sha256'],bytes=t['expected_table_bytes'])
  if (entry['jurisdiction']!='132071' or entry['fiscalYear']!=2019 or entry['documentKind']!='settlement'
      or entry['direction']!=t['direction'] or entry['table']!=expected_table
      or p['source_key']!=e['source_key'] or p['table_id']!=t['table_id'] or p['rows']!=t['expected_rows']
      or p['observation_role']!=t['raw_role'] or p['request_url']!=(t['origin_url'] or e['url'])
      or p['source_amount_unit']!=t.get('source_amount_unit') or p['unit_multiplier']!=t.get('unit_multiplier')
      or p['additive_within_own_grain']!=t['additive_within_own_grain']
      or p['recognition_status']!='unconfirmed'):raise ValueError('Settlement2019 fixed original/table/row/recognition identity differs')
  if expected_origin and entry['origin']['object']!=expected_origin:raise ValueError('Origin object differs')
  structure=dict(
   hierarchy=['kan','kou','moku','setsu'] if financial else ['kan','kou','moku'] if t['raw_role']=='controls' else ['kan','kou','moku','project-remark'] if t['raw_role']=='projects' else ['kan','kou','moku','setsu'] if t['raw_role']=='revenue' else [],
   dimensions=[],funds=[dict(code='',label=next(a['name'] for a in e['accounts'] if a['id']==t['account_slug']))] if t['account_slug'] else [],
   scope=dict(granularity=t['grain'],observationRole=t['raw_role'],authoritativeExecuted=financial,
    financialLeaf=financial,nonadditive=not financial,sourceAmountUnit=t.get('source_amount_unit'),
    unitMultiplier=t.get('unit_multiplier'),projectSetsuLinkage='unconfirmed-independent-remark-totals',
    revenueGrainProof='kan-level reconciles to printed 歳入決算額; finer grain not yet proved',
    budgetColumnsAreNonadditiveReferences=True))
  source=dict(provider=NAMESPACE,sourceKey=e['source_key'],documentKind='settlement',documentLabel=e['document_label'],
   landingPage=e['landing_page'],url=t['origin_url'] or e['url'],sha256=t['origin_sha256'],originalBytes=t['origin_bytes'],
   licenseId=e['license_id'],attribution=e['attribution'],rawForm='extracted',namespace=NAMESPACE,
   tableId=t['table_id'],accountPartition=t['account_slug'],observationRole=t['raw_role'],grain=t['grain'],
   direction=t['direction'],phases=['executed'] if t['phase']=='executed' else [],sourceAmountUnit=t.get('source_amount_unit'),
   unitMultiplier=t.get('unit_multiplier'),additiveWithinOwnGrain=t['additive_within_own_grain'],
   canonicalExecuted=financial,canonicalChanges=False,nonadditive=not financial,
   recognitionStatus='unconfirmed',recognitionDate=None,printedSubmissionDate=e['submitted_date'],
   expenditureSetsuStatus='printed-code-name-legal-year-unassessed',projectSetsuLinkage='unconfirmed',
   cofogStatus='unclassified',gfsm=None,
   
   rawTableSha256=entry['table']['sha256'],rawTableBytes=entry['table']['bytes'],rawRowCount=p['rows'],rawSchema=p['raw_schema'],
   originalSourceTableId=p['original_source_table_id'],printedZeroRows=p['printed_zero_rows'],
   structure=structure)
  rows.append(dict(dataset_id=dataset_id(t),jurisdiction_code='132071',fiscal_year=2019,direction=t['direction'],document_kind='settlement',source_json=json.dumps(source,ensure_ascii=False,sort_keys=True)))
 return rows,history
