"""Private FY2021 Chiyoda settlement native-registration (r3kessansho-2, general account expenditure)."""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path

DIRECTORY=Path(__file__).resolve().parent
CONFIG=DIRECTORY/'sources-spec.json'
NAMESPACE='chiyoda2021-settlement-native'
FINANCIAL={'native-level-amounts','native-setsu-amounts'}
ROLES=FINANCIAL|{'native-page-observations','native-observations','native-note-observations'}

def identity(path):
 b=Path(path).read_bytes()
 return dict(path=str(Path(path).relative_to(Path(__file__).resolve().parents[4])),sha256=hashlib.sha256(b).hexdigest(),bytes=len(b))

def specifications():
 specs=json.loads(CONFIG.read_text())['native_scan']
 manifest=json.loads((DIRECTORY/'evidence-manifest.json').read_text())
 originals={x['sha256']:x for x in manifest['originals']}
 if len(specs)!=1 or sum(len(x['tables']) for x in specs.values())!=5:raise ValueError('Exact one-original/5-table scope required')
 seen=set()
 for key,s in specs.items():
  o=originals[s['origin_sha256']]
  if s['jurisdiction_code']!='131016' or s['financial_year']!=2021 or s['document_kind']!='settlement' or s['raw_form']!='extracted':raise ValueError('Settlement source scope changed')
  if s['url']!=o['url'] or s['origin_bytes']!=o['bytes'] or s['recognition_status']!='unconfirmed':raise ValueError('Settlement original identity changed')
  for t in s['tables']:
   if (key,t['table_id']) in seen or t['role'] not in ROLES:raise ValueError('Duplicate or unknown role')
   seen.add((key,t['table_id']))
   financial=t['role'] in FINANCIAL
   if financial and (t['direction'],t['phase'],t['source_amount_unit'],t['unit_multiplier'],t['legal_correspondence_status'])!=('expenditure',None,'円',1,'unconfirmed'):raise ValueError('Printed financial unit/phase/correspondence changed')
   if not financial and any(t.get(x) is not None for x in ['direction','phase','source_amount_unit','unit_multiplier']):raise ValueError('Nonmonetary proof cannot acquire a direction, phase or unit')
   expected_additive=t['role']=='native-setsu-amounts'
   if t['additive_within_own_grain']!=expected_additive or t['rows']<1 or not re.fullmatch('[a-f0-9]{64}',t['candidate_table_sha256']):raise ValueError('Count/hash/additivity changed')
 return specs

def evidence_objects():
 refs={}
 assets=json.loads((DIRECTORY/'evidence-manifest.json').read_text())['assets']
 for a in assets:
  ref=dict(key=a['object_key'],sha256=a['sha256'],bytes=a['bytes'])
  if ref['key']!=f"inputs/{'origin' if a['kind']=='original' else 'proof'}/sha256/{a['sha256']}":raise ValueError('Proof key is not its exact immutable kind/SHA identity')
  if ref['key'] in refs and refs[ref['key']]!=ref:raise ValueError('Conflicting proof object identity')
  refs[ref['key']]=ref
 if len(refs)!=len(assets):raise ValueError('Incomplete immutable evidence declaration')
 return sorted(refs.values(),key=lambda r:r['key'])

def restore_evidence(objects,*,remote=False):
 from ingestion.inputs import remote_object,verify_object,OBJECTS
 objects=Path(objects)
 for ref in evidence_objects():
  p=objects/ref['key']
  if not p.exists():
   if not remote:raise FileNotFoundError('Proof not cached: '+ref['key'])
   if objects.resolve()!=OBJECTS.resolve():raise ValueError('Remote restoration helper must target the explicit configured object cache')
   remote_object(ref,'get')
  verify_object(ref,p.read_bytes())
 return len(evidence_objects())

def native_settlement_sources():
 from ingestion.fiscal.sources import Source,Resource
 from ingestion.shared.jurisdictions import jurisdiction_name
 return {f'native-scan:{key}':Source(key=f'native-scan:{key}',catalog=None,jurisdiction_code='131016',
  jurisdiction_name=jurisdiction_name('131016'),fiscal_year=2021,fiscal_year_label=None,document_kind='settlement',
  document_label=s['document_label'],dataset_title=None,encoding='',redistribute=s['redistribute'],
  redistribute_basis=s['redistribute_basis'],license_id=s['license_id'],attribution=s['attribution'],
  landing_page=s['landing_page'],raw_form='extracted',
  resources=tuple(Resource(direction=t.get('direction'),resource_name=s['document_title']+' '+t['table_id'],
   url=s['url'],url_basis=s['url_basis'],table_id=t['table_id']) for t in s['tables'])) for key,s in specifications().items()}

def input_path(spec,table):
 token='expenditure' if table['role'] in FINANCIAL else 'observation'
 return f"{NAMESPACE}/jurisdiction=131016/year=2021/document_kind=settlement/edition={spec['origin_sha256']}/direction={token}/table={table['table_id']}"

def dataset_id(spec,table):
 token='expenditure' if table['role'] in FINANCIAL else 'observation'
 return f"131016:2021:{token}:settlement:{spec['origin_sha256']}:{table['table_id']}"

def register_native_settlement2021_declarations(rows,history,entries,lock_path):
 from ingestion.inputs import source_metadata_bytes
 specs=specifications();sources=native_settlement_sources();by_key={f'native-scan:{k}':v for k,v in specs.items()};seen=set()
 originals={x['sha256']:x for x in json.loads((DIRECTORY/'evidence-manifest.json').read_text())['originals']}
 definitions={n:identity(DIRECTORY/n) for n in ['sources-spec.json','evidence-manifest.json']}
 for e in entries:
  if not e['path'].startswith(NAMESPACE+'/'):continue
  p=json.loads(source_metadata_bytes(lock_path,e));s=by_key[p['source_key']]
  ts=[t for t in s['tables'] if t['table_id']==p['table_id']]
  if len(ts)!=1:raise ValueError('Ambiguous source-key/table tuple')
  t=ts[0];source=sources[p['source_key']]
  expected_origin=dict(key='inputs/origin/sha256/'+s['origin_sha256'],sha256=s['origin_sha256'],bytes=s['origin_bytes'])
  expected_table=dict(key='inputs/table/sha256/'+t['candidate_table_sha256'],sha256=t['candidate_table_sha256'],bytes=t['candidate_table_bytes'])
  if (e['path']!=input_path(s,t) or e['path'] in seen or e['jurisdiction']!='131016' or e['fiscalYear']!=2021
      or e['documentKind']!='settlement' or e['direction']!=t.get('direction') or e['originEdition']!=s['origin_sha256']
      or e['origin']['object']!=expected_origin or e['table']!=expected_table
      or p['request_url']!=s['url'] or p['rows']!=t['rows'] or p['observation_role']!=t['role']
      or p.get('source_amount_unit')!=t.get('source_amount_unit') or p.get('unit_multiplier')!=t.get('unit_multiplier')
      or p['recognition_status']!='unconfirmed' or p['legal_correspondence_status']!='unconfirmed'):raise ValueError('Adopted settlement source identity differs')
  matches=[r for r in source.resources if (r.direction,r.url,r.table_id)==(e['direction'],p['request_url'],p['table_id'])]
  if len(matches)!=1:raise ValueError('Exact source-key/URL/table/direction registration differs')
  seen.add(e['path'])
  structure=dict(hierarchy=['account','kan','kou','moku','setsu'] if t['role']=='native-setsu-amounts' else ['account','kan','kou','moku'] if t['role']=='native-level-amounts' else [],
   dimensions=[],funds=[],scope=dict(granularity=t['grain'],observationRole=t['role'],independentBreakdown=True,
   additiveWithinOwnGrain=t['additive_within_own_grain'],financialLeaf=t['role']=='native-setsu-amounts',
   nonadditive=not t['additive_within_own_grain'],sourceAmountUnit=t.get('source_amount_unit'),
   unitMultiplier=t.get('unit_multiplier'),expenditureSetsuStatus='unconfirmed',projectSetsuLinkage='unconfirmed',
   recognitionStatus='unconfirmed',phase=None,approvalStatus='unconfirmed'))
  src=dict(provider=NAMESPACE,sourceKey=p['source_key'],documentKind='settlement',documentLabel=s['document_label'],
   landingPage=s['landing_page'],url=s['url'],sha256=e['originEdition'],originalBytes=s['origin_bytes'],
   originalFetch=originals[e['originEdition']],licenseId=s['license_id'],attribution=s['attribution'],rawForm='extracted',canonicalInitial=False,canonicalChanges=False,
   tableId=t['table_id'],observationRole=t['role'],grain=t['grain'],direction=t.get('direction'),
   phases=[],phase=None,approvalStatus='unconfirmed',sourceAmountUnit=t.get('source_amount_unit'),
   unitMultiplier=t.get('unit_multiplier'),recognitionStatus='unconfirmed',expenditureSetsuStatus='unconfirmed',
   projectSetsuLinkage='unconfirmed',independentBreakdown=True,additiveWithinOwnGrain=t['additive_within_own_grain'],
   
   rawTableSha256=e['table']['sha256'],rawTableBytes=e['table']['bytes'],rawSchema=p['raw_schema'],
   pages=p['pages'],definitionFiles=definitions,immutableProofObjects=len(evidence_objects()),structure=structure)
  rows.append(dict(dataset_id=dataset_id(s,t),jurisdiction_code='131016',fiscal_year=2021,direction=t.get('direction'),
   document_kind='settlement',source_json=json.dumps(src,ensure_ascii=False,sort_keys=True)))
 return rows,history
