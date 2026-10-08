"""Deterministic per-(file,role) table materialization from the 9 pinned originals."""
import json, hashlib
from pathlib import Path
from . import provider

ROLE_SORT={'financial':0,'controls':1,'projects':2,'revenue':3,'page_inventory':4}

def _rowkey(r):return (r['physical_page'],json.dumps(r,ensure_ascii=False,sort_keys=True))

def table_bytes(rows):
    return ''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in sorted(rows,key=_rowkey)).encode()

ORIG_BYTES={'hyousi':706837,'sainyuu':856277,'saisyutu1':1556830,'saisyutu2':1547311,'kokuho':891151,'kaigo':909894,'kouki':741806,'kukaku':1235009,'gesui':798261}
FILE_KEY={s:f'R01kessannsyo{s}.pdf' for s in ORIG_BYTES}
ORIG_URL={s:f'https://www.city.akishima.lg.jp/s102/R01kessannsyo{s}.pdf' for s in ORIG_BYTES}
SCHEMA_FIELDS={
 'financial':['jurisdiction_id','fiscal_year','account_id','account_name','kan_code','kan_name','kou_code','kou_name','moku_code','moku_name','printed_setsu_code','printed_setsu_name','kubun_amount','bikou_no','executed','carry_next_continuing','carry_next_authorized','carry_next_accident','unspent','exec_ratio','unit','source_grain','row_words_json','physical_page','source_file','original_file','original_sha256','original_url','original_bytes','source_table_id','source_row_ordinal','source_row_id'],
 'controls':['jurisdiction_id','fiscal_year','account_id','account_name','grain','kan_code','kan_name','kou_code','kou_name','moku_code','moku_name','row_code','row_name','budget_initial','budget_supplementary','carry','reserve_transfer','budget_current','executed','carry_next_continuing','carry_next_authorized','carry_next_accident','unspent','exec_ratio','unit','source_grain','row_words_json','money_cells_json','physical_page','source_file','original_file','original_sha256','original_url','original_bytes','source_table_id','source_row_ordinal','source_row_id'],
 'projects':['jurisdiction_id','fiscal_year','account_id','account_name','printed_bikou_no','kan_code','kan_name','kou_code','kou_name','moku_code','moku_name','name','amount','unit','source_grain','lines','row_words_json','physical_page','source_file','original_file','original_sha256','original_url','original_bytes','source_table_id','source_row_ordinal','source_row_id'],
 'revenue':['jurisdiction_id','fiscal_year','account_id','account_name','grain','row_code','row_name','kan_code','kan_name','kou_code','kou_name','moku_code','moku_name','printed_setsu_code','printed_setsu_name','kubun_amount','budget_initial','budget_supplementary','carry','budget_current','assessed','executed','bad_debt','uncollected','ratio','unit','source_grain','physical_page','source_file','original_file','original_sha256','original_url','original_bytes','source_table_id','source_row_ordinal','source_row_id'],
 'page_inventory':['jurisdiction_id','fiscal_year','source_file','account_id','account_name','physical_page','width','height','role','printed_page_labels','word_count','unit','source_grain','original_file','original_sha256','original_url','original_bytes','source_table_id','source_row_ordinal','source_row_id']}
BIG={'fiscal_year','kubun_amount','executed','carry_next_continuing','carry_next_authorized','carry_next_accident','unspent','budget_initial','budget_supplementary','carry','reserve_transfer','budget_current','assessed','bad_debt','uncollected','amount','physical_page','word_count','original_bytes','source_row_ordinal'}
DBL={'width','height','exec_ratio','ratio'}
RENAME={'jurisdiction':'jurisdiction_id','account':'account_id','origin_sha256':'original_sha256','origin_file':'original_file'}
ACC={'general':'一般会計','kokuho':'国民健康保険特別会計','kaigo':'介護保険特別会計','kouki':'後期高齢者医療特別会計','gesui':'下水道事業特別会計','kukaku':'中神土地区画整理事業特別会計'}
SOURCE_GRAIN={'financial':'moku x printed setsu','controls':'printed kan/kou/moku controls and summary reprints','projects':'printed bikou remark item','revenue':'printed revenue detail','page_inventory':'physical page'}
SCHEMA_ROLE={'financial':'financial','controls':'controls','projects':'projects','revenue':'revenue','page_inventory':'page_inventory'}

def canonize(rows,tid,sha_by_file):
    out=[];ord_=0
    for r in sorted(rows,key=_rowkey):
        ord_+=1
        nr={RENAME.get(k,k):v for k,v in r.items()}
        for k,v in list(nr.items()):
            if isinstance(v,(list,dict)):nr[k]=json.dumps(v,ensure_ascii=False,sort_keys=True)
        f=r['source_file']
        nr['original_sha256']=sha_by_file[f];nr['original_file']=FILE_KEY[f]
        nr['original_url']=ORIG_URL[f];nr['original_bytes']=ORIG_BYTES[f]
        nr['source_table_id']=tid;nr['source_row_ordinal']=ord_
        nr['source_row_id']=tid+':'+str(ord_)
        nr['account_name']=ACC[nr['account_id']]
        nr['unit']='円'
        nr['source_grain']=SOURCE_GRAIN[tid.rsplit('-',1)[1] if not tid.endswith('page_inventory') else 'page_inventory']
        out.append(nr)
    return out

def build(originals_dir,outdir):
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    import collections,duckdb,tempfile
    cfg=json.loads((Path(__file__).with_name('config.json')).read_bytes())
    sha_by_file={e['file'].replace('R01kessannsyo','').replace('.pdf',''):e['sha256'] for e in cfg['originals']}
    tables=provider.produce(originals_dir)
    part=collections.defaultdict(list)
    for role in ('financial','controls','projects','revenue','page_inventory'):
        src='raw_pages' if role=='page_inventory' else f'raw_{role}'
        for r in tables[src]:part[(r['source_file'],role)].append(r)
    manifest=[];con=duckdb.connect()
    for (f,role),rows in sorted(part.items(),key=lambda x:(x[0][0],ROLE_SORT[x[0][1]])):
        tid=f'fy2019-{f}-{role}'
        canon=canonize(rows,tid,sha_by_file)
        jl=outdir/f'{tid}.jsonl'
        with open(jl,'w') as fh:
            for r in canon:fh.write(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n')
        cols=', '.join(f"{n}:'{'BIGINT' if n in BIG else 'DOUBLE' if n in DBL else 'VARCHAR'}'" for n in SCHEMA_FIELDS[role])
        pq=outdir/f'{tid}.parquet'
        con.execute(f"copy (select * from read_json('{jl}',format='newline_delimited',columns={{{cols}}})) to '{pq}' (format parquet, compression zstd)")
        b=pq.read_bytes()
        manifest.append(dict(table_id=tid,raw_role=role,rows=len(canon),sha256=hashlib.sha256(b).hexdigest(),bytes=len(b)))
    (outdir/'raw-table-manifest.json').write_text(json.dumps(manifest,indent=1)+'\n')
    return {'tables':len(manifest),'rows':sum(m['rows'] for m in manifest)}
