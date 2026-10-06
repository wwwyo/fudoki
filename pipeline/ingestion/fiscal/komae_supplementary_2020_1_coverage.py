"""Schema3 five-argument coverage; regenerated source metadata, physical22→typed25."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from ingestion.inputs import read_lock
from ingestion.fiscal.komae_supplementary_2020_1_contracts import (
    PROVIDER,NS,RAW_SCHEMA,require,same_typed,checked_bytes,verified_bytes,
)
FIELDS=['dataset_id','jurisdiction_code','fiscal_year','document_kind','origin_sha256',
        'structure_json','source_json','phases_json','line_count','direction']
DATASET_SELECT='select '+','.join(FIELDS)+' from main.int_fiscal_datasets'
def quote(v): return "'"+str(v).replace("'","''")+"'"

def cols(schema): return ','.join('"'+n+'"' for n,t in schema)

def describe(con, query):return [[r[0],r[1]] for r in con.execute('describe select * from '+query).fetchall()]

def both(con,a,b):
    for x,y in ((a,b),(b,a)):
        n=con.execute('select count(*) from (('+x+') except all ('+y+'))').fetchone()[0]
        require(n==0,f'typed EXCEPT ALL differs {n}')

def controls(con, raw, direction):
    """Positive queries only in design validation; no fabricated/fault rows."""
    q=raw;d=quote(direction)
    def zero(sql,why):
        n=con.execute(sql).fetchone()[0];require(n==0,f'{why}: {n}')
    def unique(kind,keys):
        zero(f"select count(*) from (select {keys} from {q} where kind='{kind}' "
             f"and direction={d} group by {keys} having count(*)<>1)",kind+' unique')
    def equal(a,b,why):
        for x,y in ((a,b),(b,a)):
            zero(f'select count(*) from (({x}) except all ({y}))',why)
    primary="('daihyou-kan','daihyou-kou','kou-total','sokkatsu-kan','sokkatsu-total','control-total','moku')"
    zero(f'select count(*) from {q} where kind in '+primary+
         f' and (direction is distinct from {d} or before_amt is null or delta is null or total is null)',
         'required direction/primary operands')
    zero(f'select count(*) from {q} where kind in '+primary+' and before_amt+delta<>total','primary arithmetic including sokkatsu-total')
    for kind in ('control-total','sokkatsu-total'):
        n=con.execute(f"select count(*) from {q} where kind='{kind}' and direction={d}").fetchone()[0]
        require(n==1,kind+' exactly1')
    for kind,keys in [('daihyou-kan','kan_code'),('sokkatsu-kan','kan_code'),
                      ('daihyou-kou','kan_code,kou_code'),('kou-total','kan_code,kou_code'),
                      ('moku','block_id')]:unique(kind,keys)
    zero(f"select count(*) from {q} where kind in ('daihyou-kan','sokkatsu-kan','daihyou-kou','kou-total','moku') "
         "and (kan_code is null or kan_code='')",'kan required key')
    zero(f"select count(*) from {q} where kind in ('daihyou-kou','kou-total','moku') "
         "and (kou_code is null or kou_code='')",'kou required key')
    zero(f"select count(*) from {q} where kind='moku' and (block_id is null or block_id='' "
         "or moku_code is null or moku_code='' or moku_label is null or moku_label='')",'moku required keys/labels')
    for kind in ('daihyou-kan','sokkatsu-kan','daihyou-kou','kou-total','moku'):
        require(con.execute(f"select count(*) from {q} where kind='{kind}' and direction={d}").fetchone()[0]>0,kind+' required')
    def key(kind,k,distinct=False):return f"select {'distinct ' if distinct else ''}{k} from {q} where kind='{kind}' and direction={d}"
    equal(key('sokkatsu-kan','kan_code,before_amt,delta,total'),key('daihyou-kan','kan_code,before_amt,delta,total'),'sokkatsu/daihyou all keyed operands')
    equal(key('sokkatsu-total','before_amt,delta,total'),key('control-total','before_amt,delta,total'),'total first-table all operands')
    equal(key('daihyou-kan','kan_code'),key('daihyou-kou','kan_code',True),'required kan/kou both sides')
    equal(key('daihyou-kou','kan_code,kou_code,before_amt,delta,total'),
          key('kou-total','kan_code,kou_code,before_amt,delta,total'),'required kou/printed計 all operands')
    equal(key('kou-total','kan_code,kou_code'),key('moku','kan_code,kou_code',True),'required計/moku group keys')
    # Only amended rows are printed; sums of BEFORE/AFTER of changed kan or moku
    # need not equal whole-account/whole-kou baseline. Sum signed deltas only.
    for child,parent,keys in [('daihyou-kou','daihyou-kan','kan_code'),('moku','kou-total','kan_code,kou_code')]:
        equal(f"select {keys},sum(delta) delta from {q} where kind='{child}' and direction={d} group by {keys}",
              key(parent,keys+',delta'),child+' delta/printed parent')
    equal(f"select sum(delta) from {q} where kind='sokkatsu-kan' and direction={d}",key('sokkatsu-total','delta'),'sokkatsu kan sum/total')
    zero(f"select count(*) from {q} s where s.kind in ('setsu','setsu-cont') and "
         f"(s.direction is distinct from {d} or s.block_id is null or not exists "
         f"(select 1 from {q} m where m.kind='moku' and m.direction={d} and m.block_id=s.block_id))",'setsu direction/orphan required parent')
    zero(f"select count(*) from {q} where kind='setsu' and (setsu_level is null or "
         "setsu_level not in ('top','sub') or delta is null or setsu_code is null or setsu_label is null)",'printed setsu operands/keys')
    equal(f"select block_id,sum(delta) delta from {q} where kind='setsu' and direction={d} and setsu_level='top' group by block_id",
          key('moku','block_id,delta'),'all moku require typed top setsu; correct kind/direction')

    unique('moku','kan_code,kou_code,moku_code')
    zero(f"select count(*) from (select block_id,setsu_code from {q} where kind='setsu' and direction={d} and setsu_level='top' group by block_id,setsu_code having count(*)<>1)",'exact unique printed top-setsu keys')
    zero(f"select count(*) from {q} s where s.kind in ('setsu','setsu-cont') and not exists (select 1 from {q} m where m.kind='moku' and m.direction={d} and m.block_id=s.block_id and m.kan_code is not distinct from s.kan_code and m.kou_code is not distinct from s.kou_code and m.moku_code is not distinct from s.moku_code)",'exact parent tuple for detail/continuation')
    # Amended-only child BEFORE/AFTER sums are not whole-parent baselines.
    # Preserve both residual operand chains explicitly; do not infer zero residual.
    for child,parent,keys in [('daihyou-kou','daihyou-kan','kan_code'),('moku','kou-total','kan_code,kou_code')]:
        join=' and '.join('p.'+k+'=c.'+k for k in keys.split(','))
        zero(f"select count(*) from (select {keys},sum(before_amt) b,sum(delta) dlt,sum(total) t from {q} where kind='{child}' and direction={d} group by {keys}) c join {q} p on {join} where p.kind='{parent}' and p.direction={d} and (p.delta<>c.dlt or p.before_amt-c.b<>p.total-c.t)",'keyed before/delta/total residual chain '+child+'/'+parent)
    zero(f"select count(*) from {q} p cross join (select sum(before_amt) b,sum(delta) dlt,sum(total) t from {q} where kind='sokkatsu-kan' and direction={d}) c where p.kind='sokkatsu-total' and p.direction={d} and (p.delta<>c.dlt or p.before_amt-c.b<>p.total-c.t)",'whole-account before/delta/total residual chain')

def metadata(con,ref,identity,schema):
    require(describe(con,ref)==schema,'schema/order/types: '+ref)
    n=con.execute(f'select count(*) from {ref} where dataset_id is distinct from ? '
                  "or phase is not null or approval_status is distinct from 'unconfirmed'",[identity]).fetchone()[0]
    require(n==0,'all-row phase/approval/identity guard: '+ref)
    n=con.execute(f'select count(*) from (select source_row from {ref} group by source_row having count(*)<>1)').fetchone()[0]
    require(n==0,'source_row uniqueness: '+ref)


def evaluate(con,candidate,hashes,lock_path,e,dataset,raw_root,repo):
    from ingestion.inputs import source_metadata_bytes
    from ingestion.fiscal.komae_supplementary_2020_1_contracts import (
        load,validate_entry,validate_generated,FACTS,NULL_COUNTS,
    )
    from ingestion.fiscal.komae_supplementary_2020_1_provider import source_json
    d=e['direction'];require(d in ('expenditure','revenue'),'direction')
    spec=load()['general-1-'+d];identity=validate_entry(e,spec)
    generated=json.loads(source_metadata_bytes(lock_path,e));validate_generated(e,spec,generated)
    sj=json.loads(dataset['source_json'])
    require(same_typed(sj,source_json(e,spec,generated)),'exact registered source metadata/identity')
    for name,value in dict(dataset_id=identity,jurisdiction_code='132195',fiscal_year=2020,
        direction=d,document_kind='supplementary',origin_sha256=e['originEdition'],
        phases_json='[]',line_count=FACTS[d]['rows']).items():
        require(name in dataset and same_typed(dataset[name],value),'registry typed required '+name)
    origin=e['origin']['object']
    verified_bytes(repo/'pipeline/.cache/objects'/origin['key'],{k:origin[k] for k in ('sha256','bytes')})
    pq=raw_root/e['path']/'data.parquet';verified_bytes(pq,{k:e['table'][k] for k in ('sha256','bytes')})
    raw='(select * from read_parquet('+quote(pq)+',hive_partitioning=false))'
    require(describe(con,raw)==RAW_SCHEMA,'physical22 schema/order/types')
    physical=con.execute('select name,num_children from parquet_schema(?)',[str(pq)]).fetchall()
    require(len(physical)==23 and physical[0][1]==22
        and [r[0] for r in physical[1:]]==[n for n,t in RAW_SCHEMA],'physical22 flat Parquet fields; exclude Hive5')
    require(con.execute('select count(*) from '+raw).fetchone()[0]==FACTS[d]['rows'],'raw count')
    for name,want in NULL_COUNTS[d].items():
        observed=con.execute('select count(*) from '+raw+' where "'+name+'" is null').fetchone()[0]
        require(observed==want,'pinned original NULL multiplicity '+name)
    require(con.execute('select count(*) from '+raw+' where source_row is null or source_row<=0 or kind is null '
        "or physical_page is null or physical_page not between 1 and 13 or raw_text is null or raw_text=''"
    ).fetchone()[0]==0,'original row/page/text required keys')
    require(con.execute('select count(*) from (select source_row from '+raw+' group by source_row having count(*)<>1)').fetchone()[0]==0,'raw source_row exactly unique')
    require(con.execute('select count(*) from '+raw+' where direction is not null and direction is distinct from ?',[d]).fetchone()[0]==0,'context NULL direction preserved; no wrong direction')
    if d=='revenue':
        require(con.execute('select count(*) from '+raw+' where natl is not null or metro is not null or bond is not null or other is not null or general is not null').fetchone()[0]==0,'all revenue funding NULL')
    controls(con,raw,d)
    schema25=RAW_SCHEMA+[['dataset_id','VARCHAR'],['phase','VARCHAR'],['approval_status','VARCHAR']]
    c22=cols(RAW_SCHEMA)
    for layer,ref in [('stg',f'main.stg_132195__supplementary_2020_1_{d}'),
        ('int',f'main.int_132195_supplementary_2020_1_{d}'),
        ('mart',f'main.fiscal_132195_supplementary_2020_1_{d}_lines')]:
        if layer=='stg':require(describe(con,ref)==RAW_SCHEMA,'staging exact22')
        else:metadata(con,ref,identity,schema25)
        both(con,'select '+c22+' from '+raw,'select '+c22+' from '+ref)
    mart=f'main.fiscal_132195_supplementary_2020_1_{d}_lines'
    shared=con.execute('select source_amount_kind,direction from main.fiscal_datasets where dataset_id=?',[identity]).fetchall()
    require(shared==[(None,d)],'shared mart exactly1 direction/NULLkind')
    rel=f'fiscal/132195/supplementary_2020_1_{d}.csv';require(rel in hashes,'CSV membership')
    body=checked_bytes(candidate/rel);require(hashlib.sha256(body).hexdigest()==hashes[rel],'CSV SHA')
    import csv,io
    require(next(csv.reader(io.StringIO(body.decode('utf-8'))))==[n for n,t in schema25],'CSV exact25 headers/order')
    types='{'+','.join(quote(n)+':'+quote(t) for n,t in schema25)+'}'
    csvrel='read_csv('+quote(candidate/rel)+",header=true,auto_detect=false,columns="+types+",nullstr='',allow_quoted_nulls=false)"
    metadata(con,csvrel,identity,schema25);both(con,'select * from '+mart,'select * from '+csvrel)
    return [e['path']+'/data.parquet',str(lock_path),rel]

def output_coverage(connection,candidate,hashes,lock_path,datasets):
    """Normal five-argument adapter; errors leave own registrations incomplete."""
    selected=[];entries=[];registry=[]
    try:
        selected=[d for d in datasets if json.loads(d.get('source_json') or '{}').get('provider')==PROVIDER]
        for dataset in selected:dataset['output_coverage']={'complete':False,'files':[],'accounts':{},'errors':[]}
        lock_path=Path(lock_path);lockbytes=checked_bytes(lock_path);lock=read_lock(lock_path)
        require(lock['schemaVersion']==3 and checked_bytes(lock_path)==lockbytes,'stable schema3 input lock')
        entries=[e for e in lock['entries'] if e['path'].startswith(NS)]
        if not entries:
            require(not selected,'provider caller without inputs');return
        require(len(entries)==2 and len({e['path'] for e in entries})==2 and {e['direction'] for e in entries}=={'expenditure','revenue'},'exact2 resource occurrences')
        from ingestion.paths import REPO
        repo=REPO
        rawroot=repo/'pipeline/.cache/inputs'/hashlib.sha256(lockbytes).hexdigest()/'raw'
        registry=[dict(zip(FIELDS,r,strict=True)) for r in connection.execute(DATASET_SELECT+" where json_extract_string(source_json,'$.provider')=?",[PROVIDER]).fetchall()]
        require(len(registry)==2 and len({r['dataset_id'] for r in registry})==2,'registry exactly2 unique')
        require(len({d['dataset_id'] for d in selected})==len(selected),'caller duplicate identity')
        require({d['dataset_id'] for d in selected}<={r['dataset_id'] for r in registry},'caller extra provider key')
        for r in registry:
            if not any(d.get('dataset_id')==r['dataset_id'] for d in selected):
                r['output_coverage']={'complete':False,'files':[],'accounts':{},'errors':[]};datasets.append(r);selected.append(r)
        for e in entries:
            identity=':'.join((e['jurisdiction'],str(e['fiscalYear']),e['direction'],e['documentKind'],e['originEdition'],e['path'].split('resource=')[-1]))
            matches=[d for d in selected if d['dataset_id']==identity];require(len(matches)==1,'required caller identity')
            dataset=matches[0];reg=next(r for r in registry if r['dataset_id']==identity)
            for name in FIELDS:
                if name in dataset:require(dataset[name]==reg[name],'caller/registry differs '+name)
                else:dataset[name]=reg[name]
            proof=dataset['output_coverage']
            try:
                proof['files']=evaluate(connection,Path(candidate),hashes,lock_path,e,dataset,rawroot,repo)
                require(checked_bytes(lock_path)==lockbytes,'input lock changed during audit');proof['complete']=True
            except Exception as exc:proof['errors'].append(str(exc))
    except Exception as exc:
        # Retain failure only on real caller/registry rows; never fabricate a
        # partial dataset that the common audit cannot consume.
        for dataset in selected:
            proof=dataset.setdefault('output_coverage',{'complete':False,'files':[],'accounts':{},'errors':[]})
            proof['complete']=False;proof['errors'].append(str(exc))
        if not selected:
            # Initial JSON/lock/registry failure cannot establish own absence.
            raise
        if entries:
            expected={':'.join((e['jurisdiction'],str(e['fiscalYear']),e['direction'],e['documentKind'],e['originEdition'],e['path'].split('resource=')[-1])) for e in entries}
            registered={r['dataset_id'] for r in registry}
            present={d['dataset_id'] for d in selected}
            if not expected<=registered or not expected<=present:
                # Missing expected identities must fail the upper audit.
                raise
