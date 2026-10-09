"""Finite cache-only Komae native/cell-transcription input contract."""

from importlib import import_module as _ingestion_module
from copy import deepcopy
import hashlib,json,re
from pathlib import Path
from ingestion.inputs import OBJECTS
from ingestion.paths import REPO
verify_numbered_approval = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.extract_komae_council_approved_detail').verify_approval
CONFIG=Path(__file__).with_name('sources-native-council-approved.json')
SUPPORTED={(2021,'一般会計',4),(2021,'一般会計',6),(2021,'国民健康保険特別会計',1),
 (2021,'後期高齢者医療特別会計',1),(2021,'介護保険特別会計',1),(2021,'国民健康保険特別会計',2),
 (2022,'国民健康保険特別会計',1),(2022,'後期高齢者医療特別会計',1),(2022,'介護保険特別会計',1),(2022,'駐車場事業特別会計',1)}
class Runtime:
 def __init__(self,config=CONFIG,objects=OBJECTS):
  self.config=Path(config);self.objects=Path(objects);self.data=json.loads(self.config.read_text());self.candidates=self.data['candidates']
  if self.data['schema_version']!=1 or len(self.candidates)!=10 or {(c['fiscal_year'],c['fund_label'],c['amendment_number']) for c in self.candidates}!=SUPPORTED:raise ValueError('Exact ten-edition scope required; no six-edition or held-wave mixing')
  for name,sha in self.data['supported_dependency_sha256'].items():
   if hashlib.sha256((REPO/name).read_bytes()).hexdigest()!=sha:raise ValueError('Reviewed native decoder dependency changed: '+name)
  ref=self.data['visual_ledger_file'];b=self.config.with_name(ref['name']).read_bytes()
  if hashlib.sha256(b).hexdigest()!=ref['sha256'] or len(b)!=ref['bytes']:raise ValueError('Frozen visual cell ledger hash/size differs')
  self.visual_ledger=json.loads(b)
  self.cell_transcriptions=self.correction_file('native-direct-cell-transcriptions.json');self.moku_transcriptions=self.correction_file('native-direct-moku-transcriptions.json');self.verified={}
  for c in self.candidates:
   if not re.fullmatch('[a-f0-9]{64}',c['expected_table_sha256'] or ''):raise ValueError('Frozen proposed table hash contract required')
   p=c['approval_proof'];identity=[c['fiscal_year'],c['fund_label'],c['amendment_number']]
   if [p['fiscal_year'],p['account'],p['amendment_number']]!=identity or c['origin_object']['sha256']!=c['expected_sha256']:raise ValueError('Original/numbered approval identity differs')
   if c['approval_status']!='council-approved-original' or c['edition_status']!='published':raise ValueError('Only exact approved originals may be decoded')
   if set(c['native_page_refs'])!={str(x) for x in range(c['first_page'],c['last_page']+1)}:raise ValueError('Whole numbered attachment observation boundary incomplete')
 def correction_file(self,name):
  p=self.config.with_name(name);ref=self.data['correction_files'][name];b=p.read_bytes()
  if hashlib.sha256(b).hexdigest()!=ref['sha256'] or len(b)!=ref['bytes']:raise ValueError('Frozen correction declaration hash/size mismatch')
  return json.loads(b)
 def transcription_index(self,tr):return self.data['transcription_original_indices'][self.cell_transcriptions.index(tr)]
 def object_path(self,ref):
  key=ref.get('key',ref.get('object_key'));sha=ref['sha256'];size=ref['bytes']
  if not re.fullmatch(r'inputs/(origin|native-observation|native-render)/sha256/[a-f0-9]{64}',key or '') or not key.endswith('/'+sha):raise ValueError('Invalid immutable evidence object key')
  p=self.objects/key
  if key not in self.verified:
   b=p.read_bytes()
   if hashlib.sha256(b).hexdigest()!=sha or len(b)!=size:raise ValueError('Frozen evidence object hash/size mismatch: '+key)
   self.verified[key]=(sha,size)
  if self.verified[key]!=(sha,size):raise ValueError('Conflicting immutable evidence identity')
  return p
 def page_ref(self,c,page,base,kind='observation'):return c['native_page_refs'][str(page)][base][kind]
 def read_page(self,c,page,base):
  d=json.loads(self.object_path(self.page_ref(c,page,base)).read_bytes());self.object_path(self.page_ref(c,page,base,'render'))
  if d['physical_page']!=page or Path(d['pdf']).stem!=c['expected_sha256']:raise ValueError('Native observation physical original identity differs')
  return d
 def verify_approval(self,c,control):
  self.object_path(c['origin_object']);proof=deepcopy(c)
  # Legacy verifier is read-only. Canonical object keys and optional isolated acquisition handles are excluded
  # from declared/output proof; it reads the exact indexed bytes, not URLs.
  for e in proof['approval_proof']['original_identity_evidence']+proof['approval_proof']['resolution_evidence']:
   verified=self.object_path(e)
   if self.objects.resolve()!=OBJECTS.resolve():
    e['local_path']=str(verified);e.pop('object_key')
  verify_numbered_approval(proof,self.object_path(c['origin_object']),control)
 def verify_all_objects(self):
  for c in self.candidates:
   self.object_path(c['origin_object'])
   for e in c['approval_proof']['original_identity_evidence']+c['approval_proof']['resolution_evidence']:self.object_path(e)
   for page,variants in c['native_page_refs'].items():
    for base in variants:self.read_page(c,int(page),base)
   if c['date_anomaly']:self.object_path(c['date_anomaly']['rendered_date_crop'])

 def verify_rows(self,c,rows):
  editions=[e for e in self.visual_ledger['editions'] if e['identity']==c['identity']]
  if len(editions)!=1 or len(editions[0]['rows'])!=len(rows):raise ValueError('Whole row/cell ledger scope differs')
  for row,entry in zip(rows,editions[0]['rows'],strict=True):
   for field in ('source_row','printed_amount_text','amount_delta','source_amount_unit','setsu_code','setsu_label'):
    if row[field]!=entry[field]:raise ValueError('Frozen printed row/transcription differs: '+field)
   if row['source_grain']!=entry['grain']:raise ValueError('Original grain changed')
   for cid in entry['cell_ids']:
    cell=self.visual_ledger['cells'][cid]
    if cell['original_sha256']!=c['expected_sha256']:raise ValueError('Cell ledger cross-original identity')
    self.object_path(cell['native_observation_object']);self.object_path(cell['render_object'])

def native_council_sources(config=CONFIG):
 from ingestion.fiscal.management.sources import Source, Resource
 return {c['source_key']:Source(key=c['source_key'],catalog=None,jurisdiction_code='132195',jurisdiction_name='狛江市',
  fiscal_year=c['fiscal_year'],fiscal_year_label=None,document_kind='supplementary',document_label=c['document_title'],
  dataset_title=None,encoding='',redistribute=c['redistribute'],redistribute_basis=c['redistribute_basis'],
  license_id=c['license_id'],attribution=c['attribution'],landing_page=c['landing_page'],raw_form='extracted',
  resources=(Resource(direction='expenditure',resource_name=c['document_title'],url=c['url'],
    url_basis='Exactly numbered approved whole original, hash-fixed with observed attachment boundaries',table_id=c['table_id']),))
  for c in Runtime(config).candidates}

def evidence_objects(config=CONFIG):
 data=json.loads(Path(config).read_text());refs={}
 for c in data['candidates']:
  candidates=[c['origin_object']]
  candidates += [dict(key=e['object_key'],sha256=e['sha256'],bytes=e['bytes']) for e in c['approval_proof']['original_identity_evidence']+c['approval_proof']['resolution_evidence']]
  candidates += [ref for variants in c['native_page_refs'].values() for variant in variants.values() for ref in variant.values()]
  if c['date_anomaly']:candidates.append(c['date_anomaly']['rendered_date_crop'])
  for ref in candidates:
   if ref['key'] in refs and refs[ref['key']]!=ref:raise ValueError('Conflicting native immutable object identity')
   refs[ref['key']]=ref
 return sorted(refs.values(),key=lambda x:x['key'])

def main():
 import argparse,subprocess
 from ingestion.inputs import BUCKET
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,default=CONFIG);parser.add_argument('--object-dir',type=Path,default=OBJECTS);parser.add_argument('--describe',action='store_true');parser.add_argument('--restore-evidence',action='store_true');parser.add_argument('--remote',action='store_true');args=parser.parse_args();refs=evidence_objects(args.config)
 if args.describe:
  print(json.dumps(dict(schema_version=1,editions=10,rows=85,objects=refs,restoration='Missing exact hash/size objects only, cf R2 get; no mutable current URL fallback',adoption='fixed-input-provider')));return
 if not args.restore_evidence:parser.error('--describe or --restore-evidence is required')
 for ref in refs:
  path=args.object_dir/ref['key']
  if not path.exists():
   if not args.remote:raise FileNotFoundError('Frozen observation/origin not cached: '+ref['key'])
   body=subprocess.run(['cf','r2','objects','get',ref['key'],'--bucket-name',BUCKET,'--quiet'],check=True,capture_output=True).stdout
   if hashlib.sha256(body).hexdigest()!=ref['sha256'] or len(body)!=ref['bytes']:raise ValueError('Immutable remote observation byte identity differs')
   path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
 Runtime(args.config,args.object_dir).verify_all_objects()
 print(json.dumps(dict(status='hash-verified-native-evidence',objects=len(refs),remote_was_authorized=args.remote)))
if __name__=='__main__':main()

NAMESPACE = 'native-council-approved-detail'
def register_native_council_declarations(rows,history,entries):
    from ingestion.inputs import source_metadata_bytes
    from ingestion.paths import INPUT_LOCK
    specs={c['source_key']:c for c in Runtime().candidates};seen=set()
    for entry in entries:
        if not entry['path'].startswith(NAMESPACE+'/'):continue
        p=json.loads(source_metadata_bytes(INPUT_LOCK,entry));s=specs[p['source_key']]
        expected_proof={**s['approval_proof'], 'original_identity_evidence':[e for e in s['approval_proof']['original_identity_evidence'] if '上記の議案' in e['observed_text'] or '地方自治法' in e['observed_text']]}
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
            or p['approval_proof']!=expected_proof or p['effective_date'] is not None or p['visual_ledger_file']!=Runtime().data['visual_ledger_file']):
            raise ValueError('Adopted council bytes/count/whole-grain/approval contract differs')
        dataset=f"132195:{s['fiscal_year']}:expenditure:supplementary:{entry['originEdition']}:{s['table_id']}"
        source=dict(documentKind='supplementary',documentLabel=s['document_title'],landingPage=s['landing_page'],
            url=s['url'],sha256=entry['originEdition'],licenseId=s['license_id'],attribution=s['attribution'],
            rawForm='extracted',tableId=s['table_id'],pages=p['pages'],grain=p['grain'],
            observationRole='authoritative-native-council-supplementary-detail',canonicalChanges=True,
            approvalStatus=s['approval_status'],approvalDate=p['council_resolution_date'],
            councilResolutionDate=p['council_resolution_date'],printedSubmissionDate=p['printed_submission_date'],
            executiveDispositionDate=p['executive_disposition_date'],effectiveDate=p['effective_date'],
            effectiveDateBasis=p['effective_date_basis'],approvalProof=p['approval_proof'],
            amendmentNumber=s['amendment_number'],fundLabel=s['fund_label'],sourceAmountUnit='千円',unitMultiplier=1000,
            
            rawTableSha256=entry['table']['sha256'],reserveExceptionRows=0,
            initialState='unconfirmed')
        row=dict(dataset_id=dataset,jurisdiction_code='132195',fiscal_year=s['fiscal_year'],direction='expenditure',
            document_kind='supplementary',source_json=json.dumps(source,ensure_ascii=False,sort_keys=True))
        rows.append(row)
        structure=dict(hierarchy=['kan','kou','moku','project','setsu'],dimensions=['department'],
            funds=[dict(code='',label=s['fund_label'])],scope=dict(granularity=p['grain'],
            authoritativeSupplementaryChanges=True,sourceAmountUnit='千円',initialState='unconfirmed',
            reserveExceptionRows=0,expenditureSetsuStatus='printed-code-full-name-active-year-master-required'))
        history.append(dict(**row,origin_sha256=entry['originEdition'],effective_at=p['effective_date'],
            amendment_number=s['amendment_number'],fund_label=s['fund_label'],line_count=p['rows'],
            structure_json=json.dumps(structure,ensure_ascii=False,sort_keys=True)))
    return rows,history
