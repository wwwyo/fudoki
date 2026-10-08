"""Approved finite cache-only initial445 extraction and explicit immutable evidence restore."""

from importlib import import_module as _ingestion_module
import argparse,hashlib,json,subprocess
from pathlib import Path
Bundle = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_initial445.provider').Bundle
EvidenceError = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_initial445.provider').EvidenceError
restore_evidence = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_initial445.provider').restore_evidence
build = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_initial445.materialize').build
specs = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_initial445_registry').specs
PACKAGE=Path(__file__).with_name('akishima_initial445');MANIFEST=PACKAGE/'evidence-manifest.json'
class RepoBundle(Bundle):
 def __init__(self,objects,manifest):
  super().__init__(objects,manifest);self.origins={e['expected_sha256'] for e in specs()}
 def object(self,sha):
  if sha not in self.objects:raise EvidenceError('Undeclared immutable evidence SHA')
  kind='origin' if sha in self.origins else 'proof';p=self.cache/f'inputs/{kind}/sha256/{sha}';b=p.read_bytes();ref=self.objects[sha]
  if len(b)!=ref['bytes'] or hashlib.sha256(b).hexdigest()!=sha:raise EvidenceError('Frozen evidence SHA/byte mismatch: '+sha)
  self.accesses.add(sha);return b

def evidence_objects():
 m=json.loads(MANIFEST.read_bytes());origins={e['expected_sha256'] for e in specs()}
 return [dict(key=f"inputs/{'origin' if o['sha256'] in origins else 'proof'}/sha256/{o['sha256']}",sha256=o['sha256'],bytes=o['bytes']) for o in m['objects']]

def restore(objects,remote=False):
 objects=Path(objects)
 for ref in evidence_objects():
  p=objects/ref['key']
  if p.exists():b=p.read_bytes()
  elif remote:
   r=subprocess.run(['cf','r2','objects','get',ref['key'],'--bucket-name','fudoki-inputs','--quiet'],capture_output=True,check=True);b=r.stdout
  else:raise FileNotFoundError('Exact evidence is not cached: '+ref['key'])
  if len(b)!=ref['bytes'] or hashlib.sha256(b).hexdigest()!=ref['sha256']:raise EvidenceError('Frozen restored object identity differs')
  if not p.exists():
   p.parent.mkdir(parents=True,exist_ok=True)
   with p.open('xb') as f:f.write(b)
 return {'objects_verified':len(evidence_objects()),'remote_explicitly_authorized':remote}

def extract(objects,output):
 m=json.loads(MANIFEST.read_bytes());bundle=RepoBundle(objects,m);bundle.validate_all();configs=bundle.json('config/editions.json')
 if hashlib.sha256((PACKAGE/'editions.json').read_bytes()).hexdigest()!=m['bindings']['config/editions.json']:raise EvidenceError('Supported Git declaration differs from immutable config input')
 result=build(bundle,configs,output)
 # Exactly accepted output bytes are checked against independently declared immutable output descriptors.
 actual=json.loads((Path(output)/'candidate-manifest.json').read_bytes());lookup={(e['expected_sha256'],t['accepted_kind']):t for e in specs() for t in e['tables']}
 for e in actual:
  for t in e['tables']:
   s=lookup[(e['origin_sha256'],t['kind'])]
   if t['sha256']!=s['expected_table_sha256'] or t['bytes']!=s['expected_table_bytes'] or t['row_count']!=s['expected_rows']:raise EvidenceError('Re-extracted complete table bytes/count differ from approved fixed resource')
 return result|{'input_manifest_sha256':hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),'immutable_inputs':216}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['describe','restore-evidence','extract']);p.add_argument('--object-dir',type=Path);p.add_argument('--output',type=Path);p.add_argument('--remote',action='store_true');a=p.parse_args()
 if a.command=='describe':return {'editions':8,'financial_tables':24,'objects':evidence_objects(),'cache_only_extract':True,'explanation_legal_codes':None,'remote_restore_requires_explicit_flag':True}
 if a.object_dir is None:p.error('--object-dir is required; no implicit private cache')
 if a.command=='restore-evidence':return restore(a.object_dir,a.remote)
 if a.remote:p.error('--remote is available only for explicit restore-evidence, never extraction')
 if a.output is None:p.error('--output is required')
 return extract(a.object_dir,a.output)
if __name__=='__main__':
 try:print(json.dumps({'ok':True,'result':main()},ensure_ascii=False,sort_keys=True))
 except Exception as e:
  print(json.dumps({'ok':False,'error':{'type':type(e).__name__,'message':str(e)}},ensure_ascii=False));raise SystemExit(1)
