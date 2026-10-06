"""Typed multiset transport checks for three finite, noncanonical summary tables.

The normal caller supplies expenditure datasets only. The executed fiscal_datasets
relation supplies the additional revenue dataset; no rows are invented from specs.
Complete here means typed transport coverage, not source census or approval.
"""
from __future__ import annotations
from ingestion.inputs import source_metadata_bytes
import json
from pathlib import Path
from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, verify_object

NAMESPACE='akishima-supplementary2020-2025'
STG={'kan-summary-revenue':'stg_132071__supplementary_fy2025_01_revenue',
     'kan-summary-expenditure-purpose':'stg_132071__supplementary_fy2025_01_expenditure_purpose',
     'kan-summary-expenditure-nature':'stg_132071__supplementary_fy2025_01_expenditure_nature'}
INT='int_132071__supplementary_fy2025_01'
MART='fiscal_132071_supplementary_fy2025_01'
CSV_RELATIVE='fiscal/132071/supplementary_fy2025_01_kan_summary.csv'

def quote(name):return '"'+name.replace('"','""')+'"'
def records(con,sql,args=None):
 cur=con.execute(sql,args or []);cols=[c[0] for c in cur.description]
 return [dict(zip(cols,r,strict=True)) for r in cur.fetchall()]
def schema(con,sql,args=None):
 return {r[0]:r[1] for r in con.execute('describe '+sql,args or []).fetchall()}
def same_multiset(con,left,left_args,right,right_args,columns):
 fields=','.join(quote(c) for c in columns)
 a='select '+fields+' from ('+left+')';b='select '+fields+' from ('+right+')'
 forward=con.execute('select count(*) from (('+a+') except all ('+b+'))',left_args+right_args).fetchone()[0]
 reverse=con.execute('select count(*) from (('+b+') except all ('+a+'))',right_args+left_args).fetchone()[0]
 if forward or reverse:raise ValueError(f'Typed original row multiplicity differs: {forward}/{reverse}')
 return dict(forward_except_all=forward,reverse_except_all=reverse)

def output_coverage(connection,candidate:Path,hashes:dict,lock_path:Path,datasets:list[dict])->None:
 entries=[e for e in read_lock(lock_path)['entries'] if e['path'].startswith(NAMESPACE+'/')]
 if not entries:return
 from ingestion.fiscal.akishima_supplementary_fy2025_01_registry import specs,dataset_id,validate_provenance
 spec=specs()[0];tables={t['logical_path']:t for t in spec['tables']}
 if len(entries)!=3 or {e['path'] for e in entries}!=set(tables):raise ValueError('Exact three finite inputs required')
 actual=records(connection,"select * from fiscal_datasets where json_extract_string(source_json,'$.namespace')=? order by dataset_id",[NAMESPACE])
 expected_ids={dataset_id(spec,t) for t in tables.values()}
 if len(actual)!=3 or {r['dataset_id'] for r in actual}!=expected_ids:raise ValueError('Actual fiscal_datasets must register exact three inputs')
 if any(r['source_amount_kind'] is not None for r in actual):raise ValueError('Summary observations cannot acquire a canonical source amount kind')
 incoming=[r for r in datasets if json.loads(r['source_json']).get('namespace')==NAMESPACE]
 if len({r['dataset_id'] for r in incoming})!=len(incoming):raise ValueError('Incoming registered datasets repeat')
 registered={r['dataset_id']:r for r in incoming}
 if not set(registered)<=expected_ids:raise ValueError('Incoming dataset outside finite registry')
 for row in actual:
  if row['dataset_id'] not in registered:
   copied=dict(row);datasets.append(copied);registered[copied['dataset_id']]=copied
  else:
   for field in ['source_json','line_count','origin_sha256']:
    if registered[row['dataset_id']].get(field)!=row[field]:raise ValueError('Incoming dataset differs from executed registry: '+field)
  registered[row['dataset_id']]['output_coverage']=dict(complete=False,files=[CSV_RELATIVE],errors=[],original_rows=0,all_original_fields_preserved=False,semantic_source_completion=False)
 file=candidate/safe_relative(CSV_RELATIVE)
 if CSV_RELATIVE not in hashes or digest(file.read_bytes())!=hashes[CSV_RELATIVE]:raise ValueError('CSV absent or differs from artifact SHA membership')
 csv_types=schema(connection,'select * from '+quote(MART))
 csvsql="select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')"
 csv_args=[str(file),csv_types]
 csv_schema=schema(connection,csvsql,csv_args)
 if csv_schema!=csv_types:raise ValueError('Typed CSV schema differs from mart')
 # Whole CSV includes every mart field, NULL vs quoted-empty text and all duplicate counts.
 whole=same_multiset(connection,'select * from '+quote(MART),[],csvsql,csv_args,list(csv_types))
 for entry in entries:
  table=tables[entry['path']];tid=table['table_id'];sid=dataset_id(spec,table)
  prov=json.loads(source_metadata_bytes(lock_path, entry))
  validate_provenance(spec,table,prov,entry)
  for ref in [entry['origin']['object'],entry['table']]:verify_object(ref,(OBJECTS/safe_relative(ref['key'])).read_bytes())
  rawsql='select * from read_parquet(?,hive_partitioning=false)';rawargs=[str(OBJECTS/safe_relative(entry['table']['key']))];raw_types=schema(connection,rawsql,rawargs)
  declared={r['name']:r['type'].upper() for r in prov['raw_schema']}
  if len(raw_types)!=26 or declared!=raw_types:raise ValueError(tid+': sealed raw schema names/types differ')
  rawrows=records(connection,rawsql,rawargs)
  if len(rawrows)!=table['expected_rows'] or len(rawrows)!=prov['rows']:raise ValueError(tid+': original row count differs')
  if any(r['original_sha256']!=spec['expected_sha256'] or r['fiscal_year']!=2025 or r['unit']!='千円' or r['amendment_number']!=1 for r in rawrows):raise ValueError(tid+': edition/year/unit differs')
  if sum(r['amount_change'] or 0 for r in rawrows)!=table['printed_total']:raise ValueError(tid+': printed delta total differs')
  if any(r['budget_before']+r['amount_change']!=r['budget_after'] for r in rawrows if all(r[k] is not None for k in ['budget_before','amount_change','budget_after'])):raise ValueError(tid+': before+delta=after differs')
  checks=[]
  for relation in [STG[tid],INT,MART]:
   types=schema(connection,'select * from '+quote(relation))
   missing=set(raw_types)-set(types)
   if missing or any(types[c]!=t for c,t in raw_types.items()):raise ValueError(tid+': '+relation+' original column names/types differ; missing='+str(sorted(missing)))
   sql='select * from '+quote(relation)+' where dataset_id=?'
   checks.append(dict(relation=relation,schema_matches=True,**same_multiset(connection,rawsql,rawargs,sql,[sid],list(raw_types))))
  checks.append(dict(relation='typed_csv',schema_matches=all(csv_schema.get(c)==t for c,t in raw_types.items()),**same_multiset(connection,rawsql,rawargs,'select * from ('+csvsql+') where dataset_id=?',csv_args+[sid],list(raw_types))))
  row=next(r for r in actual if r['dataset_id']==sid);meta=json.loads(row['source_json'])
  if meta['rawTableSha256']!=entry['table']['sha256']  or row['line_count']!=len(rawrows):raise ValueError(tid+': actual registry identity differs')
  registered[sid]['output_coverage'].update(complete=True,original_rows=len(rawrows),all_original_fields_preserved=True,original_schema=raw_types,layer_checks=checks,whole_csv_check=whole,csv_sha256=hashes[CSV_RELATIVE],typed_null_empty_multiplicity_preserved=True,raw_null_counts={c:sum(r[c] is None for r in rawrows) for c in raw_types},raw_empty_string_counts={c:sum(r[c]=='' for r in rawrows) for c in raw_types})
