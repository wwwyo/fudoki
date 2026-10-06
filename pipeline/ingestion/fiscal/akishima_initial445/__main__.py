"""Machine-readable, cache-only finite construction CLI."""
import argparse,json,sys,hashlib
from pathlib import Path
from .provider import Bundle,EvidenceError,restore_evidence
from .materialize import build
import duckdb
PARAMS={'cache':'explicit immutable evidence cache directory','manifest':'immutable manifest JSON file','output':'explicit construction output directory','dry_run':'validate all immutable objects and approval rows without writing outputs'}
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['schema','build','restore-evidence']);parser.add_argument('--params',help='JSON object containing explicit paths; unknown keys fail')
 args=parser.parse_args()
 if args.command=='schema':return {'schema_version':1,'commands':{'build':PARAMS,'restore-evidence':{'manifest':'immutable manifest JSON','cache':'local read-only object cache','output':'explicit restore destination'}},'financial_tables_per_edition':['explanation-detail','nonadditive-controls','printed-left-legal-setsu'],'scope':{'jurisdiction':'132071','editions':8,'explanation_rows':445},'network_fallback':False,'live_ocr':False}
 p=json.loads(args.params or '{}')
 if not isinstance(p,dict):raise EvidenceError('params must be a JSON object')
 if 'dry_run' in p and not isinstance(p['dry_run'],bool):raise EvidenceError('dry_run must be boolean')
 allowed=set(PARAMS) if args.command=='build' else {'cache','manifest','output'}
 if set(p)-allowed:raise EvidenceError('Unknown parameters: '+','.join(sorted(set(p)-allowed)))
 for key in ['cache','manifest']:
  if not isinstance(p.get(key),str) or any(ord(c)<32 for c in p[key]):raise EvidenceError('Explicit valid '+key+' is required')
 manifest=json.loads(Path(p['manifest']).read_bytes());bundle=Bundle(p['cache'],manifest)
 configpath=Path(__file__).with_name('editions.json');configs=bundle.json('config/editions.json')
 if hashlib.sha256(configpath.read_bytes()).hexdigest()!=bundle.bindings['config/editions.json']:raise EvidenceError('Bundled Git declaration differs from immutable manifest declaration')
 if args.command=='restore-evidence':
  if not isinstance(p.get('output'),str):raise EvidenceError('Explicit restore destination required')
  return restore_evidence(manifest,p['output'],lambda ref:bundle.object(ref['sha256']))
 checks=bundle.validate_all()
 for c in configs:bundle.approval(c)
 if p.get('dry_run',False):return {'dry_run':True,**checks,'editions':len(configs),'writes':0}
 if not isinstance(p.get('output'),str) or any(ord(c)<32 for c in p['output']):raise EvidenceError('Explicit valid output directory is required')
 out=Path(p['output']).resolve();cache=Path(p['cache']).resolve()
 if out==cache or out in cache.parents or cache in out.parents:raise EvidenceError('Output and immutable input cache must be separate')
 summary=build(bundle,configs,out)
 pages,docs=bundle.observed_scope(configs)
 def write(name,x):(out/name).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
 write('all-page-observed-scope.json',pages);write('document-and-approval-evidence.json',docs)
 write('account-year-matrix.json',bundle.json('account-year-matrix.json'))
 write('direct-transcription-ledger.json',configs)
 write('direct-field-transcription-evidence.json',bundle.json('config/field-transcription-evidence.json'))
 # Full row/control readback and all native observation positions remain independent ledgers.
 manifest_rows=json.loads((out/'candidate-manifest.json').read_bytes());row_ledger=[]
 with duckdb.connect() as db:
  for edition in manifest_rows:
   for table in edition['tables']:
    cursor=db.execute('SELECT * FROM read_parquet(?) ORDER BY source_row',[str(out/table['path'])]);keys=[x[0] for x in cursor.description]
    row_ledger.append({'origin_sha256':edition['origin_sha256'],'table_kind':table['kind'],'schema':table['schema'],'rows':[dict(zip(keys,row)) for row in cursor.fetchall()]})
 write('all-row-control-ledger.json',row_ledger)
 native=[]
 for config in configs:
  sha=config['identity']['prior_sha256']
  for name in ['vision-observations.jsonl','vision-cells.jsonl','vision-amount-cells.jsonl']:
   logical=f'origins/{sha}/{name}'
   native.append({'origin_sha256':sha,'object_sha256':bundle.bindings[logical],'observation_kind':name,'phase':None,'amount_unit':None,'amount':None,'pages':bundle.jsonl(logical)})
 write('all-native-cell-observation-ledger.json',native)
 return {**summary,**checks,'output':str(out),'canonical_adoption':'unverified','global_build':'unverified','remote_storage':'unverified'}
if __name__=='__main__':
 try:print(json.dumps({'ok':True,'result':main()},ensure_ascii=False,sort_keys=True))
 except Exception as e:
  print(json.dumps({'ok':False,'error':{'code':type(e).__name__,'message':str(e)}},ensure_ascii=False,sort_keys=True));sys.exit(1)
