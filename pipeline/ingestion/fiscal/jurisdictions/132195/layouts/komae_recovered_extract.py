"""Private cache-only provider, revision 2 — recovered Komae FY2019-22 initial
事項別明細 chapters (一般会計). Real row identity: stable source_id, sequential
source_row, physical_page, y, x-bbox per line; typed numeric columns (bigint);
setsu rows carry printed parent moku context (reading-order containment, marked
as such). Mirrors repo controls: fail closed on printed 款/項 total mismatch.
No network. Run: PYTHONPATH=pipeline uv run python provider.py
"""

from importlib import import_module as _ingestion_module
from ingestion.inputs import record_input
import hashlib,json,re,sys,unicodedata
from pathlib import Path
import duckdb

# ingestion package member: canonical layout (pipeline/ingestion/fiscal/)
PKG=Path(__file__).resolve().parents[5]         # pipeline/
CACHE=PKG/'.cache'
ORIGINS=CACHE/'objects'/'inputs'/'origin'/'sha256'
RAW=CACHE/'acquisition'/'raw'
from ingestion.lib.pdf import chars_of, rows_of  # noqa: E402
FULLW=str.maketrans('０１２３４５６７８９．，','0123456789.,')
NUMT=re.compile(r'^[0-9０-９,，\.．△▲()（）\-]+$')
def norm(s):return re.sub(r'\s+','',unicodedata.normalize('NFKC',s))
def text(row,lo=0.0,hi=1e9):return norm(''.join(c for x,c in sorted(row) if lo<=x<hi))
def parse_num(s):
    if s is None:return None
    s=str(s).strip()
    if not s:return None
    neg=s.startswith(('△','▲'));s=s.lstrip('△▲')
    if s[:1] in '(（' and s[-1:] in ')）':s=s[1:-1]
    t=s.translate(FULLW).replace(',','')
    if not re.fullmatch(r'[0-9]+(\.[0-9]+)?',t or ''):return None
    v=int(float(t));return -v if neg else v
def bbox(row):
    xs=[x for x,_ in row];return [min(xs),0,max(xs)+6,12] if xs else None

def load_manifest():
    load_recovered = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.komae_recovered_provider').load_recovered
    raw=load_recovered()
    docs=[]
    for s in raw.values():
        docs.append(dict(fiscal_year=s['fiscal_year'],direction=s['direction'],
            fund_label=s['fund_label'],table_id=s['table_id'],sha256=s['expected_sha256'],
            expected_table_sha256=s['expected_table_sha256'],expected_rows=s['expected_rows'],
            original_url=s['original_url'],wayback_url=s['wayback_url'],
            wayback_capture=s['wayback_capture'],bytes=s.get('bytes'),physical_pages=s.get('physical_pages')))
    return docs

def units_centers(pages,exp):
    need=8 if exp else 4
    for pr in pages:
        for row in pr:
            cells=sorted(row);centers=[];i=0
            while i<len(cells):
                x,c=cells[i]
                if c=='千' and i+1<len(cells) and cells[i+1][1]=='円':
                    centers.append((x+cells[i+1][0])/2);i+=2;continue
                if c=='千円':centers.append(x+3)
                i+=1
            if len(centers)>=need:return centers
    raise ValueError('No printed 千円 unit header row')

def cluster(row,lo,hi,gap=6.0):
    toks=sorted([(x,c) for x,c in row if lo<=x<hi])
    groups=[];cur=[];last=None
    for x,c in toks:
        if cur and x-last<gap and NUMT.match(c) and NUMT.match(cur[-1][1]):cur.append((x,c))
        else:
            if cur:groups.append(cur)
            cur=[(x,c)]
        last=x+len(c)*6
    if cur:groups.append(cur)
    return [((g[0][0]+g[-1][0]+len(g[-1][1])*6)/2,''.join(c for _,c in g)) for g in groups]

def hdr(alltext,tag):
    if tag not in alltext:return None,None
    rest=alltext.split(tag,1)[1]
    rest=re.split(r'[（\(]項[）\)]',rest)[0]
    rest=re.sub(r'[-−–][0-9０-９]+[-−–]','',rest)
    m=re.match(r'^(.*?)([0-9][0-9,，]*)千?円?$',rest)
    if m and re.fullmatch(r'[0-9,，]+',m.group(2)):
        return m.group(1),int(m.group(2).translate(FULLW).replace(',',''))
    return rest,None

def code_of(label):
    m=re.match(r'^[０-９0-9]+[\.．]',label or '')
    return m.group(0).rstrip('.．').translate(FULLW) if m else None

SCHEMA={
 'source_row':'bigint','physical_page':'integer','y':'double','bbox_json':'varchar',
 'record_kind':'varchar','printed_text':'varchar',
 'kan_code':'varchar','kan_label':'varchar','kou_code':'varchar','kou_label':'varchar',
 'printed_kan_total':'bigint','printed_kou_total':'bigint',
 'moku_code':'varchar','moku_label':'varchar',
 'current_text':'varchar','current_amount':'bigint',
 'prior_text':'varchar','prior_amount':'bigint',
 'change_text':'varchar','change_amount':'bigint',
 'natl_text':'varchar','natl_amount':'bigint',
 'metro_text':'varchar','metro_amount':'bigint',
 'bond_text':'varchar','bond_amount':'bigint',
 'other_src_text':'varchar','other_src_amount':'bigint',
 'general_text':'varchar','general_amount':'bigint',
 'setsu_no':'varchar','setsu_label':'varchar','setsu_text':'varchar','setsu_amount':'bigint',
 'parent_moku_code':'varchar','parent_moku_label':'varchar','parent_moku_source_row':'bigint',
 'parent_evidence':'varchar','description':'varchar',
 'fiscal_year':'integer','source_amount_unit':'varchar','source_url':'varchar',
 'source_sha256':'varchar','wayback_url':'varchar','wayback_capture':'varchar',
 'dataset_id':'varchar','fiscal_line_id':'varchar',
}

def extract(doc):
    pdf=ORIGINS/doc['sha256']
    sha=hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert sha==doc['sha256']
    doc['bytes']=pdf.stat().st_size
    exp=doc['direction']=='expenditure'
    pages=[rows_of(ch) for ch in chars_of(str(pdf),1,9999)]
    doc['physical_pages']=len(pages)
    centers=units_centers(pages,exp)
    if exp:
        mc=centers[:8];KEYS=['current','prior','change','natl','metro','bond','other_src','general'];sc=centers[8] if len(centers)>8 else None
    else:
        mc=centers[:3];KEYS=['current','prior','change'];sc=centers[3] if len(centers)>3 else None
    edges=[mc[0]-25]+[(a+b)/2 for a,b in zip(mc,mc[1:])]+[mc[-1]+25]
    rows=[];kan_l=kou_l=None;seq=0
    cur_moku=None  # (source_row, code, label) printed containment context
    kou_totals={};kan_totals={}
    def emit(**kw):
        nonlocal seq;seq+=1
        kw.update(source_row=seq);rows.append(kw)
    for pageno,pr in enumerate(pages,1):
        for row in pr:
            whole=text(row);r=dict(physical_page=pageno,y=None,bbox_json=json.dumps(bbox(row)),
                                   printed_text=''.join(c for _,c in sorted(row)))
            if '（款）' in whole or '(款)' in whole:
                nm,tot=hdr(whole,'（款）' if '（款）' in whole else '(款)')
                if '（項）' in whole or '(項)' in whole:
                    knm,ktot=hdr(whole,'（項）' if '（項）' in whole else '(項)')
                    if knm:kou_l=knm
                    if ktot is not None:kou_totals[(kan_l,kou_l)]=ktot
                if nm:kan_l=nm
                if tot is not None:kan_totals[kan_l]=tot
                emit(record_kind='kan_header',kan_label=kan_l,kan_code=code_of(kan_l),
                     kou_label=kou_l,kou_code=code_of(kou_l),printed_kan_total=tot,**r);continue
            if whole.startswith(('（項）','(項)')):
                nm,tot=hdr(whole,'（項）' if '（項）' in whole else '(項)')
                if nm:kou_l=nm
                if tot is not None:kou_totals[(kan_l,kou_l)]=tot
                emit(record_kind='kou_header',kan_label=kan_l,kan_code=code_of(kan_l),
                     kou_label=kou_l,kou_code=code_of(kou_l),printed_kou_total=tot,**r);continue
            cl=cluster(row,edges[0]-10,edges[-1]+10)
            amounts={}
            for ctr,t in cl:
                for i in range(len(edges)-1):
                    if edges[i]<=ctr<edges[i+1]:amounts[KEYS[i]]=amounts.get(KEYS[i],'')+t;break
            lcells=[(x,c) for x,c in sorted(row) if x<edges[0]]
            mk=None
            for i,(x,c) in enumerate(lcells):
                if re.fullmatch(r'[0-9０-９]+[\.．]',c):mk=c;break
                if re.fullmatch(r'[0-9０-９]+',c) and i+1<len(lcells) and lcells[i+1][1] in('.','．'):mk=c;break
            if mk:
                nm=re.sub(r'^[0-9０-９]+[\.．]?','',''.join(c for _,c in lcells))
                nm=''.join(ch for ch in nm if not NUMT.match(ch) or not ch.isascii())
                if amounts.get('current') and not nm.startswith(('歳入','歳出')):
                    kw=dict(record_kind='moku',kan_code=code_of(kan_l),kan_label=kan_l,
                            kou_code=code_of(kou_l),kou_label=kou_l,
                            moku_code=re.match(r'([0-9０-９]+)',mk).group(1).translate(FULLW),
                            moku_label=nm)
                    for k,v in amounts.items():
                        kw[f'{k}_text']=v;kw[f'{k}_amount']=parse_num(v)
                    emit(**{**kw,**r});cur_moku=(seq,kw['moku_code'],kw['moku_label']);continue
            if sc:
                sname=norm(''.join(c for x,c in sorted(row) if mc[-1]+8<x<sc-18))
                sm=re.match(r'([0-9０-９]+)[\.．](.*)',sname)
                samt=''.join(t for _,t in cluster(row,sc-18,sc+18))
                if sm:
                    emit(record_kind='setsu',kan_code=code_of(kan_l),kan_label=kan_l,
                         kou_code=code_of(kou_l),kou_label=kou_l,
                         setsu_no=sm.group(1).translate(FULLW),setsu_label=sm.group(2),
                         setsu_text=samt,setsu_amount=parse_num(samt),
                         parent_moku_code=cur_moku[1] if cur_moku else None,
                         parent_moku_label=cur_moku[2] if cur_moku else None,
                         parent_moku_source_row=cur_moku[0] if cur_moku else None,
                         parent_evidence='preceding printed moku row in reading order (same column layout)' if cur_moku else None,
                         description=norm(''.join(c for x,c in sorted(row) if x>sc+18)),**r);continue
            emit(record_kind='context',kan_label=kan_l,kan_code=code_of(kan_l),
                 kou_label=kou_l,kou_code=code_of(kou_l),**r)
    agg={k:dict(printed=v,sum=0,n=0) for k,v in kou_totals.items()}
    for r in rows:
        if r.get('record_kind')=='moku' and r.get('current_amount') is not None:
            k=(r['kan_label'],r['kou_label'])
            if k in agg:agg[k]['sum']+=r['current_amount'];agg[k]['n']+=1
    checks=[dict(kan=k[0],kou=k[1],**v,match=v['printed']==v['sum']) for k,v in agg.items()]
    kan_sum={}
    for (k_,ko),v in agg.items():kan_sum[k_]=kan_sum.get(k_,0)+v['printed']
    kan_checks=[dict(kan=k,printed=v,kou_sum=kan_sum.get(k),match=v==kan_sum.get(k)) for k,v in kan_totals.items()]
    bad=[c for c in checks if not c['match']]+[c for c in kan_checks if not c['match']]
    if bad:raise ValueError(f'printed controls fail: {bad[:4]}')
    return rows,checks,kan_checks,sha

def main():
    summary=[]
    for doc in load_manifest():
        rows,checks,kan_checks,sha=extract(doc)
        src=f"132195:{doc['fiscal_year']}:{doc['direction']}:budget:{sha}:{doc['table_id']}"
        for r in rows:
            r.update(fiscal_year=doc['fiscal_year'],source_amount_unit='千円',
                     source_url=doc['original_url'],source_sha256=sha,
                     wayback_url=doc['wayback_url'],wayback_capture=doc['wayback_capture'],
                     dataset_id=src,fiscal_line_id=f"{src}:{r['source_row']}")
        out=RAW/f"initial-detail-recovered/jurisdiction=132195/year={doc['fiscal_year']}/document_kind=budget/edition={sha}/direction={doc['direction']}/resource={doc['table_id']}"
        out.mkdir(parents=True,exist_ok=True)
        con=duckdb.connect()
        cols=','.join(f'"{k}" {t}' for k,t in SCHEMA.items())
        assert len(rows)==doc['expected_rows'],(len(rows),doc['expected_rows'])
        con.execute(f'create table t ({cols})')
        con.executemany(f'insert into t values ({",".join("?"*len(SCHEMA))})',
                        [[r.get(k) for k in SCHEMA] for r in rows])
        tmp=out/'data.parquet.tmp'
        con.execute(f"copy (select * from t order by source_row) to '{tmp}' (format parquet, compression zstd)")
        got=hashlib.sha256(tmp.read_bytes()).hexdigest()
        if got!=doc['expected_table_sha256']:
            tmp.unlink();raise ValueError(f"replay bytes differ for {doc['table_id']}: {got} != {doc['expected_table_sha256']}")
        tmp.rename(out/'data.parquet')
        prov=dict(jurisdiction_code='132195',fiscal_year=doc['fiscal_year'],direction=doc['direction'],
                  document_kind='budget',edition=sha,resource=doc['table_id'],
                  original_url=doc['original_url'],wayback_url=doc['wayback_url'],
                  wayback_capture=doc['wayback_capture'],bytes=doc['bytes'],
                  physical_pages=doc['physical_pages'],rows=len(rows),
                  moku_rows=sum(1 for r in rows if r['record_kind']=='moku'),
                  setsu_rows=sum(1 for r in rows if r['record_kind']=='setsu'),
                  approval_status='unconfirmed',source_amount_unit='千円',
                  schema=SCHEMA,extractor='provider.py revision2 (private mirror; chapter layout, no cover)',
                  controls=dict(kou=checks,kan=kan_checks))
        record_input(out, prov)
        summary.append(dict(year=doc['fiscal_year'],dir=doc['direction'],rows=len(rows),
                            moku=prov['moku_rows'],setsu=prov['setsu_rows'],
                            kou=f"{sum(c['match'] for c in checks)}/{len(checks)}"))
        print(summary[-1])
    json.dump(summary,open(CACHE.parents[0]/'komae-recovered-replay-summary.json','w'),ensure_ascii=False,indent=2)

if __name__=='__main__':main()
