"""Create reviewable candidate partitions only from actual reconstructed raw rows."""
from pathlib import Path
import json,hashlib,duckdb,collections
import argparse

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--definitions',type=Path,required=True);parser.add_argument('--raw-dir',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 B=args.definitions;D=args.raw_dir;O=args.output;O.mkdir(parents=True,exist_ok=True)
 manifest=json.loads((B/'evidence-manifest.json').read_text());schema=json.loads((B/'raw-schema.json').read_text());originals={x['sha256']:x for x in manifest['originals']};c=duckdb.connect();partitions=[]
 for p in sorted(D.glob('*.parquet')):
  role=p.stem;rows=[json.loads(x[0]) for x in c.execute('select to_json(t) from read_parquet(?) t',[str(p)]).fetchall()];groups=collections.defaultdict(list)
  for r in rows:groups[(r['origin_sha256'],r.get('account'))].append(r)
  restored=[]
  for (sha,account),group in sorted(groups.items(),key=lambda x:(originals[x[0][0]]['part'],x[0][1] or '')):
   original=originals[sha];table_id=role+('-'+account if account else '');key=f"tama-2020-native-part{original['part']:02}";directory=O/key;directory.mkdir(exist_ok=True);out=directory/(table_id+'.parquet')
   columns=schema[role];con=duckdb.connect();con.execute('create table observation ('+', '.join('"'+x['name']+'" '+x['type'] for x in columns)+')');con.executemany('insert into observation values ('+', '.join('?' for _ in columns)+')',[[r[x['name']] for x in columns] for r in group]);con.execute('copy observation to ? (format parquet,compression zstd)',[str(out)])
   observed=[json.loads(x[0]) for x in con.execute('select to_json(t) from read_parquet(?) t',[str(out)]).fetchall()]
   if observed!=group:raise ValueError('Partition changed a raw field/position')
   restored.extend(observed);body=out.read_bytes();financial=role in ['legal-observations','hierarchy-controls','independent-account-controls']
   partitions.append({'source_key':'native-scan:'+key,'table_id':table_id,'role':role,'source_sha256':sha,'url':original['url'],'part':original['part'],'financial_year':2020,'account':account,'direction':'expenditure' if financial else None,'phase':'executed' if financial else None,'source_amount_unit':'円' if financial else None,'unit_multiplier':1 if financial else None,'grain':{'legal-observations':'printed-moku-by-printed-setsu','hierarchy-controls':'printed-kan-kou-moku-control-nonadditive','independent-account-controls':'independently-printed-account-summary-nonadditive','page-observations':'physical-page-native-observation-proof'}.get(role,'native-recognition-word-observation'),'legal_correspondence_status':'unconfirmed' if financial else None,'additive_within_own_grain':role=='legal-observations','path':str(out),'rows':len(group),'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'schema':columns,'exact_field_position_readback':True,'recognition_status':'unconfirmed'})
  if sorted(x['observed_id'] for x in restored)!=sorted(x['observed_id'] for x in rows):raise ValueError('Partition conservation failed')
 result={'status':'private-proposal-only','canonical_adoption':False,'r2_uploaded':False,'partition_count':len(partitions),'partitions':partitions,'role_rows':dict(collections.Counter({role:sum(x['rows'] for x in partitions if x['role']==role) for role in schema}))}
 (O/'partition-readback.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')

 print(json.dumps({'partitions':len(partitions),'role_rows':result['role_rows'],'all_fields_equal':True}))


if __name__ == "__main__":
 main()
