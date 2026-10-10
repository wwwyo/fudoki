"""Reject amount, ancestry, location, dictionary, carryover and remark corruptions."""
from __future__ import annotations
import argparse,json,os,tempfile
from copy import deepcopy
from pathlib import Path
import duckdb
from validate_care_candidate import digest,validate

def check(candidate,source,reference,rules):
 baseline=validate(candidate,source,reference,rules)
 if baseline['status']!='passed':raise ValueError('Negative checks require independently accepted baseline')
 receipt=json.loads((candidate/'receipt.json').read_text());results=[]
 cases=[('amount','details',"金額='1'","row_id=(SELECT row_id FROM test ORDER BY row_id LIMIT 1)",'original-money'),('ancestry','details',"款_row_id='nonexistent-parent'","row_id=(SELECT row_id FROM test ORDER BY row_id LIMIT 1)",'wrong-parent-reference'),('position','cell_observations','left_pt=left_pt+100',"table_id='details' AND field='金額'",'altered-native-coordinate'),('carryover-label','details',"翌年度繰越額_区分='未知の区分'","翌年度繰越額_区分 <> ''",'original-carryover-label'),('remark','details',"備考=''","備考 <> ''",'original-remark-text'),('remark-amount','remarks',"備考_金額='1'","row_id=(SELECT row_id FROM test ORDER BY row_id LIMIT 1)",'original-remark'),('remark-parent','remarks',"目_row_id='nonexistent-parent'","row_id=(SELECT row_id FROM test ORDER BY row_id LIMIT 1)",'wrong-remark-parent-reference'),('account-total-ancestry','detail_totals',"款='7諸支出金'","TRUE",'unprinted-total-ancestry')]
 for name,table,assignment,condition,expected in cases:
  with tempfile.TemporaryDirectory(prefix='care-rejection-') as tmp:
   d=Path(tmp);copied=deepcopy(receipt)
   for p in [*candidate.glob('*.parquet'),candidate/'unknowns.json']:
    if p.stem!=table:os.link(p,d/p.name)
   with duckdb.connect() as con:
    con.execute('CREATE TABLE test AS SELECT * FROM read_parquet(?)',[str(candidate/f'{table}.parquet')]);count=con.execute(f'SELECT count(*) FROM test WHERE {condition}').fetchone()[0]
    if not count:raise ValueError(f'Negative case has no target: {name}')
    con.execute(f'UPDATE test SET {assignment} WHERE {condition}');con.execute('COPY test TO ? (FORMAT PARQUET)',[str(d/f'{table}.parquet')])
   p=d/f'{table}.parquet';copied['tables'][table].update(sha256=digest(p),bytes=p.stat().st_size)
   (d/'receipt.json').write_text(json.dumps(copied,ensure_ascii=False));r=validate(d,source,reference,rules);kinds={i['kind'] for i in r['issues']}
   if r['status']!='failed' or expected not in kinds:raise AssertionError((name,expected,kinds))
   results.append({'case':name,'changed_rows':count,'rejected_by':expected})
 if not receipt.get('dictionary_name_corrections'):raise ValueError('Dictionary corruption case has no submitted correction; cannot silently skip')
 for mutation,expected in [('rule','wrong-whole-name-dictionary-application'),('binding','unbound-name-correction'),('role','unbound-name-dictionary')]:
  with tempfile.TemporaryDirectory(prefix='care-dictionary-rejection-') as tmp:
   d=Path(tmp);copied=deepcopy(receipt);c=copied['dictionary_name_corrections'][0]
   if mutation=='rule':
    dictionary=json.loads(Path(c['dictionary_path']).read_text());c['rule_id']=next(r['id'] for r in dictionary['rules'] if r['id']!=c['rule_id'])
   elif mutation=='binding':c['observation_ids']=['nonexistent-observation']
   else:copied['name_dictionary_refs']={}
   for p in [*candidate.glob('*.parquet'),candidate/'unknowns.json']:os.link(p,d/p.name)
   (d/'receipt.json').write_text(json.dumps(copied,ensure_ascii=False));r=validate(d,source,reference,rules);kinds={i['kind'] for i in r['issues']}
   if r['status']!='failed' or expected not in kinds:raise AssertionError((mutation,expected,kinds))
   results.append({'case':'dictionary-'+mutation,'rejected_by':expected})
 return results

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 for f in ('candidate','source','reference','rules','output'):ap.add_argument('--'+f,required=True,type=Path)
 a=ap.parse_args()
 if a.output.exists():raise FileExistsError(a.output)
 r=check(a.candidate,a.source,a.reference,a.rules);a.output.write_text(json.dumps(r,indent=2)+'\n');print(r)
if __name__=='__main__':main()
