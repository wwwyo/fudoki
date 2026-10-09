"""Cache-only reconstruction of the five held Komae approved whole originals."""

from importlib import import_module as _ingestion_module
from ingestion.inputs import record_input
import argparse,hashlib,json
from pathlib import Path
import duckdb
Held5Runtime = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.held5_council_provider').Held5Runtime
HERE = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.held5_council_provider').HERE
parse = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.decode_komae_held5_observations').parse
COLUMNS = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.extract_komae_council_approved_detail').COLUMNS
OUTPUT=HERE.parents[1]/'.cache/acquisition/raw/held5-council-approved-detail'
def materialize(runtime,c,result):
    out=OUTPUT/f"jurisdiction=132195/year={c['fiscal_year']}/document_kind=supplementary/edition={c['expected_sha256']}/direction=expenditure/table={c['table_id']}"
    out.mkdir(parents=True,exist_ok=True)
    rows=result['rows']
    if any(set(r)!=set(COLUMNS)for r in rows):raise ValueError('Exact raw52 column set differs')
    with duckdb.connect() as con:
        con.execute('create table t ('+','.join(f'{k} {v}'for k,v in COLUMNS.items())+')')
        con.executemany('insert into t values ('+','.join('?'for _ in COLUMNS)+')',[[r[k]for k in COLUMNS]for r in rows])
        for name,fmt in [('data.parquet','parquet, compression zstd'),('data.csv','csv, header true')]:
            con.execute('copy (select * from t order by source_row) to ? (format '+fmt+')',[str(out/name)])
        rel=con.execute('select * from read_parquet(?,hive_partitioning=false) order by source_row',[str(out/'data.parquet')]);schema={a[0]:str(a[1])for a in rel.description};pq=[dict(zip(COLUMNS,x,strict=True))for x in rel.fetchall()]
        csv=[dict(zip(COLUMNS,x,strict=True))for x in con.execute("select * from read_csv(?,columns=?,header=true,hive_partitioning=false,nullstr='',allow_quoted_nulls=false) order by source_row",[str(out/'data.csv'),COLUMNS]).fetchall()]
    if schema!=COLUMNS or pq!=rows or csv!=rows:raise ValueError('Actual all-field typed output readback differs')
    hashes={name:runtime.digest(out/name)for name in ('data.parquet','data.csv')}
    for name,ref in hashes.items():
        if ref!=c['expected_output'][name]:raise ValueError('Accepted all-field original output bytes differ: '+name)
    proof={k:v for k,v in result.items()if k not in ('rows','original_candidate')}
    proof.update(schema_version=1,source_key=c['source_key'],table_id=c['table_id'],rows=len(rows),columns=COLUMNS,raw_form='extracted',roundtrip_verified=False,canonical_adopted=False,marts_verified=False,
        origin_object=runtime.inputs[c['expected_sha256']],namespace=runtime.config['namespace'],
        immutable_inputs=runtime.digest(HERE/'held5-immutable-inputs.json'),runtime_manifest=runtime.digest(HERE/'held5-runtime-manifest.json'),outputs=hashes,
        archival_path_semantics='Historical labels in raw52 are inert; no legacy path was opened',source_amount_unit='千円',baseline_status='unconfirmed',
        reserve_null_rows=sum(r['setsu_code']is None for r in rows))
    proof.update(sha256=c['expected_sha256'],jurisdiction_code='132195',fiscal_year=c['fiscal_year'],
        fund_label=c['fund_label'],amendment_number=c['amendment_number'],request_url=c['url'],
        source_url=c['url'],origin_fetched_at=c['fetched_at'],logical_input_path=runtime.config['namespace']+'/'+str(out.relative_to(OUTPUT)),
        pages=sorted(set(row['page_number']for row in rows)),grain='project × printed setsu; observed reserve NULL exceptions',
        unit_multiplier=1000,effective_at=None,extractor='extract_komae_held5_approved_detail.py@1',
        adoption_status='fixed-input-ready-private-stage-a',verification=result['totals'])
    record_input(out, proof)
    return {'identity':f"{c['fiscal_year']}-{c['fund_label']}-{c['amendment_number']}",'rows':len(rows),'columns':len(schema),'negative':sum(r['amount_delta']<0 for r in rows),'zero':sum(r['amount_delta']==0 for r in rows),'printed_code_rows':sum(r['setsu_code']is not None for r in rows),'reserve_null_rows':sum(r['setsu_code']is None for r in rows),'projects':len(result['project_checks']),'moku':result['moku_count'],'left':len(result['observed_left_controls']),'totals':result['totals'],'outputs':hashes,'directory':str(out),'all52_typed_readback':True}
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--describe',action='store_true',help='Describe the finite offline input/output contract without extracting')
    args=parser.parse_args()
    runtime=Held5Runtime()
    if args.describe:
        print(json.dumps({'schema_version':1,'editions':5,'rows':241,'raw_columns':COLUMNS,'immutable_objects':len(runtime.inputs),'output_namespace':runtime.config['namespace'],'default':'Frozen hash cache only; no OCR/network/legacy reads','canonical_adoption':False},ensure_ascii=False));return
    readbacks=[]
    for c in runtime.candidates:
        r=runtime.verify_result(c,parse(c,runtime));readbacks.append(materialize(runtime,c,r))
    report={'schema_version':1,'editions':readbacks,'rows':sum(x['rows']for x in readbacks),'fields':sum(x['rows']*x['columns']for x in readbacks),'objects':len(runtime.inputs),'canonical_adopted':False,'global_build_verified':False}
    OUTPUT.mkdir(parents=True,exist_ok=True);(OUTPUT/'readback.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
