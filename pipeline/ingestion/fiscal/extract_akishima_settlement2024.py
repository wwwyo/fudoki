"""Exact cache-only settlement2024 construction and explicit immutable evidence restore."""
import argparse,hashlib,json,subprocess,tempfile
from pathlib import Path
from ingestion.fiscal.akishima_settlement2024.provider import Bundle,EvidenceError
from ingestion.fiscal.akishima_settlement2024.materialize import build
from ingestion.fiscal.akishima_settlement2024_registry import specs
PACKAGE=Path(__file__).with_name('akishima_settlement2024');MANIFEST=PACKAGE/'evidence-manifest.json'
ORIGIN_KINDS={'original_pdf'};KIND_BY_ROLE={'original_pdf':'origin','native_bbox':'proof','config':'proof','recognition_html':'proof','health_summary_direct_cells':'proof','health_summary_render':'proof'}
def _objects():
 m=json.loads(MANIFEST.read_bytes())
 if m['schema_version']!=1 or m['namespace']!='akishima-settlement2024':raise EvidenceError('Unsupported settlement2024 manifest')
 return m
def evidence_objects():
 m=_objects();role_of={x['sha256']:x['roles'][0] for x in m['objects']}
 return [dict(key=f"inputs/{KIND_BY_ROLE[role_of[o['sha256']]]}/sha256/{o['sha256']}",sha256=o['sha256'],bytes=o['bytes']) for o in m['objects']]
class RepoBundle(Bundle):
 def object(self,sha):
  if sha not in self.objects:raise EvidenceError('Undeclared immutable evidence SHA')
  role=self.objects[sha]['roles'][0];kind=KIND_BY_ROLE[role]
  p=self.cache/f'inputs/{kind}/sha256/{sha}';b=p.read_bytes();ref=self.objects[sha]
  if len(b)!=ref['bytes'] or hashlib.sha256(b).hexdigest()!=sha:raise EvidenceError('Frozen evidence SHA/byte mismatch: '+sha)
  self.accesses.add(sha);return b
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
 m=_objects();bundle=RepoBundle(objects,m);bundle.validate_all()
 configpath=PACKAGE/'config.json'
 if hashlib.sha256(configpath.read_bytes()).hexdigest()!=m['bindings']['config/config.json']:raise EvidenceError('Supported Git declaration differs from immutable config input')
 result=build(bundle,output)
 actual=json.loads((Path(output)/'raw-table-manifest.json').read_bytes());lookup={t['table_id']:t for e in specs() for t in e['tables']}
 if len(actual)!=19:raise EvidenceError('Nineteen fixed raw resources required')
 for t in actual:
  s=lookup[t['table_id']]
  if t['sha256']!=s['expected_table_sha256'] or t['bytes']!=s['expected_table_bytes'] or t['rows']!=s['expected_rows']:raise EvidenceError('Reconstructed raw table bytes/count differ from approved fixed resource: '+t['table_id'])
 return result|{'input_manifest_sha256':hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),'immutable_inputs':len(m['objects'])}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['describe','restore-evidence','extract']);p.add_argument('--object-dir',type=Path);p.add_argument('--output',type=Path);p.add_argument('--remote',action='store_true');a=p.parse_args()
 if a.command=='describe':return {'accounts':6,'raw_tables':19,'objects':evidence_objects(),'cache_only_extract':True,'remote_restore_requires_explicit_flag':True}
 if a.object_dir is None:p.error('--object-dir is required; no implicit private cache')
 if a.command=='restore-evidence':return restore(a.object_dir,a.remote)
 if a.remote:p.error('--remote is available only for explicit restore-evidence, never extraction')
 if a.output is None:p.error('--output is required')
 return extract(a.object_dir,a.output)
if __name__=='__main__':
 try:print(json.dumps({'ok':True,'result':main()},ensure_ascii=False,sort_keys=True))
 except Exception as e:
  print(json.dumps({'ok':False,'error':{'type':type(e).__name__,'message':str(e)}},ensure_ascii=False));raise SystemExit(1)
