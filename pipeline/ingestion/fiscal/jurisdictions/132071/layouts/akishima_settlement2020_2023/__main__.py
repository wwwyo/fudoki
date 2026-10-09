"""Machine-readable, cache-only finite construction CLI. No implicit paths."""
import argparse,json,sys,hashlib
from pathlib import Path
from .provider import Bundle,EvidenceError,restore_evidence
from .materialize import build
NAMESPACE='akishima-settlement2020-2023'
PARAMS={'cache':'explicit immutable evidence cache directory','manifest':'immutable manifest JSON file','output':'explicit construction output directory','dry_run':'validate all immutable objects and recognition rows without writing outputs'}
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['schema','build','restore-evidence']);parser.add_argument('--params',help='JSON object containing explicit paths; unknown keys fail')
 args=parser.parse_args()
 if args.command=='schema':return {'schema_version':1,'commands':{'build':PARAMS,'restore-evidence':{'cache':'local read-only object cache','manifest':'immutable manifest JSON','output':'explicit restore destination'}},'namespace':NAMESPACE,'financial_roles_per_account':['financial','controls','projects'],'scope':{'jurisdiction':'132071','fiscal_years':[2020,2021,2022,2023],'accounts':21,'financial_rows':4060,'printed_zero_rows':233,'blank_code_reserve_rows':21,'nonadditive_controls':2618,'project_controls':2236,'whole_account_controls':4,'physical_pages':1907},'network_fallback':False,'live_ocr':False}
 p=json.loads(args.params or '{}')
 if not isinstance(p,dict):raise EvidenceError('params must be a JSON object')
 if 'dry_run' in p and not isinstance(p['dry_run'],bool):raise EvidenceError('dry_run must be boolean')
 allowed=set(PARAMS) if args.command=='build' else {'cache','manifest','output'}
 if set(p)-allowed:raise EvidenceError('Unknown parameters: '+','.join(sorted(set(p)-allowed)))
 for key in ['cache','manifest']:
  if not isinstance(p.get(key),str) or any(ord(c)<32 for c in p[key]):raise EvidenceError('Explicit valid '+key+' is required')
 manifest=json.loads(Path(p['manifest']).read_bytes());bundle=Bundle(p['cache'],manifest)
 if args.command=='restore-evidence':
  if not isinstance(p.get('output'),str):raise EvidenceError('Explicit restore destination required')
  return restore_evidence(manifest,p['output'],lambda ref:bundle.object(ref['sha256']))
 checks=bundle.validate_all()
 configpath=Path(__file__).with_name('config.json')
 if hashlib.sha256(configpath.read_bytes()).hexdigest()!=bundle.bindings['config/config.json']:raise EvidenceError('Bundled Git declaration differs from immutable manifest declaration')
 config=json.loads(configpath.read_bytes())
 for y in config['years']:bundle.recognition(y['fiscal_year'],y)
 if p.get('dry_run',False):return {'dry_run':True,**checks,'years':len(config['years']),'writes':0}
 if not isinstance(p.get('output'),str) or any(ord(c)<32 for c in p['output']):raise EvidenceError('Explicit valid output directory is required')
 out=Path(p['output']).resolve();cache=Path(p['cache']).resolve()
 if out==cache or out in cache.parents or cache in out.parents:raise EvidenceError('Output and immutable input cache must be separate')
 summary=build(bundle,out)
 return {**summary,**checks,'output':str(out),'canonical_adoption':'unverified','global_build':'unverified','remote_storage':'unverified'}
if __name__=='__main__':
 try:print(json.dumps({'ok':True,'result':main()},ensure_ascii=False,sort_keys=True))
 except Exception as e:
  print(json.dumps({'ok':False,'error':{'code':type(e).__name__,'message':str(e)}},ensure_ascii=False,sort_keys=True));sys.exit(1)
