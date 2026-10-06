"""千代田区 令和7年度 各会計予算のネイティブ観測から固定8表を再構成する。凍結された原生の代替案は自動補正しない。

Usage: python -m ingestion.fiscal.chiyoda2025_native.replay <objects_root> <out_dir> [--dry-run]
objects_root は inputs/{origin,proof,table}/sha256/<sha> 形式の規格化オブジェクト格納先。"""
from pathlib import Path
import json, hashlib, re, sys
import duckdb

OBJECTS=Path(sys.argv[1]);OUTDIR=Path(sys.argv[2]);DRY='--dry-run' in sys.argv
MAN=json.loads((Path(__file__).resolve().parent/'object-manifest.json').read_text())
def obj(key):
    b=(OBJECTS/key).read_bytes()
    import hashlib as _h
    assert _h.sha256(b).hexdigest()==key.rsplit('/',1)[1],key
    return b
def page_json(n): return json.loads(obj(MAN['physical_pages'][str(n)]['observation']))
def render_digest(n):
    b=obj(MAN['physical_pages'][str(n)]['render']);return {'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def field_json(n): return json.loads(obj(MAN['field_observations'][str(n)]))
SHA='d8783bb65906f6780918a03286b6f0375c06562a8528f10784e682123a2f8235'
URL='https://www.city.chiyoda.lg.jp/documents/583/r7kaikeiyosan.pdf'
PRINTED={}
SCOPES={'general':(148,259),'national-health':(312,347),'care':(398,433),'elderly':(474,489)}
def enc(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(p): b=p.read_bytes();return {'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def account(n): return next((k for k,(a,b) in SCOPES.items() if a<=n<=b),None)
TRIANGLE=re.compile(r'^[A\u25b2\u25b3]([\d,\s]+)$')
def numeric(s):
    # Formatting spaces and comma separators only. OCR A, O, I and triangle ambiguities stay NULL.
    t=re.sub(r'\s+','',s)
    if not re.fullmatch(r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)',t):return None
    return int(t.replace(',',''))
def negative_triangle(s):
    # Printed negative mark (triangle) natively observed as 'A'/triangle; raw text stays frozen.
    m=TRIANGLE.match(re.sub(r'\s+$','',s))
    if not m:return None
    t=re.sub(r'\s+','',m.group(1))
    if not re.fullmatch(r'(?:\d{1,3}(?:,\d{3})+|\d+)',t):return None
    return -int(t.replace(',',''))
def mid(o): b=o['bbox_pdf_top_left'];return (b[1]+b[3])/2
def ident(n,p,i):return f'{SHA}:p{n}:{p}:{i}'
def observation(n,o,kind='native'):
    p=o.get('pass',o.get('column'));return dict(observed_id=ident(n,p,o['index']),origin_sha256=SHA,origin_url=URL,
      fiscal_year=2025,physical_page=n,source_ordinal=o['index']+1,pass_id=p,raw_text=o['text'],confidence=o['confidence'],
      bbox_json=enc(o['bbox_pdf_top_left']),alternatives_json=enc(o['alternatives']),source_json=enc(o),
      direction=None,phase=None,source_unit=None,amount=None,role=kind)
APPROVAL='approved-official-vote-evidence-2025-03-27'
def candidate(n,role,o,amount=None):
    p=o.get('column',o.get('pass'))
    col=o.get('column')
    phase=None
    appr='unconfirmed'
    return dict(observed_id=ident(n,p,o['index']),origin_sha256=SHA,origin_url=URL,fiscal_year=2025,
       account=account(n),physical_page=n,printed_page=PRINTED.get(n),source_ordinal=o['index']+1,role=role,direction='expenditure',
       phase=phase,source_unit='千円',unit_multiplier=1000,raw_text=o['text'],observed_amount=amount,
       amount_status='native-unconfirmed',bbox_json=enc(o['bbox_pdf_top_left']),source_json=enc(o),
       legal_setsu_id=None,project_setsu_correspondence='unconfirmed',approval_status=appr,
       raw_label=None,printed_code=None,moku_observed_id=None,related_fields_json=None)

DIRECT={  # observed_id -> (value, reason); all verified against original render crops in revision2/cell-inspection/
 'p154:whole:48':(424,'printed 424; legal row 19 扶助費'),
 'p158:whole:75':(48574,'printed 48,574; legal row 11 役務費'),
 'p196:whole:62':(30726,'printed 30,726; legal row 13 使用料及び賃借料'),
 'p250:whole:35':(4374,'printed 4,374; legal row 8 旅費'),
 'p160:prior:5':(102993,'printed 102,993; native separator misread as period'),
 'p165:explanation-amount:25':(4328869,'printed 4,328,869千円'),
 'p183:explanation-amount:6':(1661016,'printed 1,661,016千円'),
 'p203:explanation-amount:13':(1000020,'printed 1,000,020千円'),
 'p237:explanation-amount:14':(1966770,'printed 1,966,770千円'),
}
PHANTOM={'p416:legal-amount:3'}
import json as _j
_TRI=_j.loads(obj(MAN['evidence']['triangle-cells.json']))
TRIANGLE_EVIDENCE={c['id'].split(':',1)[1]: f'revision2/triangle-crops/t{i:02d}.png' for i,c in enumerate(_TRI)}  # no printed glyph at bbox in original render; single unfocused-pass artifact
pages=[];words=[];focused=[];cells=[];moku=[];legal=[];projects=[];unresolved=[]
CELL_EQUIV={}  # member suffix -> (verified_value, canonical_suffix) for cluster members of direct-corrected cells
for n in range(1,501):
    d=page_json(n)
    assert d['origin_sha256']==SHA and d['physical_page']==n and d['original_total_physical_pages']==500
    assert d['uses_language_correction'] is False
    printed=[o for o in d['observations'] if o['pass']=='whole' and o['bbox_pdf_top_left'][1]>800]
    for o in printed:
        match=re.fullmatch(r'[—−ー一\-]\s*(\d+)\s*[—−ー一\-]',o['text'])
        if match: PRINTED[n]=int(match.group(1))
    pages.append(dict(observed_id=f'{SHA}:p{n}',origin_sha256=SHA,origin_url=URL,fiscal_year=2025,physical_page=n,
        printed_footer_json=enc(printed),account=account(n),expenditure_scope=account(n) is not None,
        source_json=enc(d),observation_count=len(d['observations']),render_sha256=render_digest(n)['sha256'],
        render_bytes=render_digest(n)['bytes'],direction=None,phase=None,source_unit=None,amount=None))
    words.extend(observation(n,o) for o in d['observations'])
    if account(n) is None:continue
    f=field_json(n);obs=f['observations']
    focused.extend(observation(n,o,'focused-native') for o in obs)
    # Every native observed monetary cell is conserved, including invalid strings as NULL.
    monetary_columns={'current','prior','difference','legal-amount','explanation-amount'}
    for o in obs:
        if o['column'] not in monetary_columns or not (130<mid(o)<777):continue
        text=o['text'];value=numeric(text.replace('千円','')) if o['column']=='explanation-amount' else numeric(text)
        r=candidate(n,'observed-'+o['column'],o,value)
        key=f"p{n}:{o['column']}:{o['index']}"
        if key in DIRECT:
            dv,reason=DIRECT[key];r['observed_amount']=dv;r['amount_status']='direct-transcription-verified'
            r['related_fields_json']=enc({'direct_reading':dv,'reason':reason,'evidence':'revision2/cell-inspection crop of physical-%03d bbox %s'%(n,o['bbox_pdf_top_left']),'raw_text':text});value=dv
            r['source_json']=enc({'frozen_observation':o,'direct_evidence':r['related_fields_json']})
        tkey=f"p{n}:{o.get('column',o.get('pass'))}:{o['index']}"
        if value is None and o['column']=='difference' and tkey in TRIANGLE_EVIDENCE:
            neg=negative_triangle(text)
            if neg is not None:
                r['observed_amount']=neg
                r['amount_status']='triangle-minus-glyph-direct-verified'
                r['related_fields_json']=enc({'glyph_evidence':TRIANGLE_EVIDENCE[tkey],'glyph':'△ printed; native text A...','raw_text':text})
                value=neg
        if key in PHANTOM:
            r['observed_amount']=None;r['amount_status']='unresolved-no-printed-glyph'
            r['related_fields_json']=enc({'reason':'no printed glyph at bbox in original render','evidence':'revision2/cell-inspection/c416-800.png'});value=None
        cells.append(r)
        if value is None:unresolved.append(r)
    if n%2:
        # Explanation monetary observations retain all top-level/subordinate observations independently.
        # No depth, moku, name-only association or allocation is inferred.
        for o in obs:
            if o['column']=='explanation-amount' and 130<mid(o)<777 and '千円' in o['text']:
                v=numeric(o['text'].replace('千円',''))
                r=candidate(n,'independent-explanation-amount',o,v)
                ek=f"p{n}:explanation-amount:{o['index']}"
                if ek in DIRECT:
                    dv,reason=DIRECT[ek];r['observed_amount']=dv;r['amount_status']='direct-transcription-verified'
                    r['related_fields_json']=enc({'direct_reading':dv,'reason':reason,'evidence':'revision2/cell-inspection','raw_text':o['text']})
                else:
                    r['related_fields_json']=enc([x for x in d['observations'] if x['pass']=='whole' and abs(mid(x)-mid(o))<5])
                projects.append(r)
        continue
    current=[o for o in obs if o['column']=='current' and 130<mid(o)<777 and numeric(o['text']) is not None]
    labels=[o for o in obs if o['column']=='moku-label' and 130<mid(o)<777]
    page_moku=[]
    for o in current:
        nearby=[x for x in labels if abs(mid(x)-mid(o))<5]
        if not nearby:continue
        label=' '.join(x['text'] for x in nearby)
        code=re.match(r'^\s*(\d+)\s*([^\d].*)',label)
        r=candidate(n,'moku-control' if code else 'independent-printed-control',o,numeric(o['text']))
        r['raw_label']=label;r['printed_code']=code.group(1) if code else None
        fields={c:[x for x in obs if x['column']==c and abs(mid(x)-mid(o))<5] for c in ['moku-label','current','prior','difference']}
        r['related_fields_json']=enc(fields);moku.append(r)
        if code:page_moku.append((mid(o),r))
    label_rows=[o for o in obs if o['column']=='legal-label' and 130<mid(o)<777]
    starts=[o for o in label_rows if re.match(r'^\s*\d{1,2}\s*[^\d\W]',o['text'])]
    # Canonical observation clusters use original physical positions, not row counts or amount equality.
    # Full-page/right-half passes recover cells omitted by very narrow native recognition.
    all_money=[x for x in d['observations'] if x['pass'] in {'whole','right-half'} and x['bbox_pdf_top_left'][0]>477 and x['bbox_pdf_top_left'][2]<535 and 130<mid(x)<777 and numeric(x['text']) is not None]
    all_money += [x for x in obs if x['column']=='legal-amount' and 130<mid(x)<777 and numeric(x['text']) is not None]
    clusters=[]
    for x in sorted(all_money,key=mid):
        if clusters and abs(mid(x)-sum(mid(z) for z in clusters[-1])/len(clusters[-1]))<5:clusters[-1].append(x)
        else:clusters.append([x])
    for cluster in clusters:
        o=next((x for x in cluster if x.get('pass')=='whole'),cluster[0])
        values={numeric(x['text']) for x in cluster};value=next(iter(values)) if len(values)==1 else None
        r=candidate(n,'independent-left-legal-amount',o,value)
        lkey=f"p{n}:{o.get('pass')}:{o['index']}"
        if lkey in DIRECT:
            dv,reason=DIRECT[lkey];value=dv;r['observed_amount']=dv
            for x in cluster:
                mk=f"p{n}:{x.get('column',x.get('pass'))}:{x['index']}"
                if mk!=lkey:CELL_EQUIV[mk]=(dv,lkey,numeric(x['text']))
        r['source_json']=enc({'selected_observation':o,'same_original_cell_native_observations':cluster})
        r['amount_status']='direct-transcription-verified' if lkey in DIRECT else 'native-pass-agreement' if len(values)==1 and len(cluster)>1 else 'native-single-observation' if value is not None else 'unresolved-native-conflict'
        direct_evidence = {'direct_reading':DIRECT[lkey][0],'reason':DIRECT[lkey][1],'evidence':'revision2/cell-inspection','conflicting_pass_values':sorted(x for x in values if x is not None)} if lkey in DIRECT else None
        pk=f"p{n}:legal-amount:{o['index']}"
        if pk in PHANTOM or any(f"p{n}:{x.get('pass')}:{x['index']}" in PHANTOM for x in cluster):
            value=None;r['observed_amount']=None;r['amount_status']='unresolved-no-printed-glyph'
            r['related_fields_json']=enc({'reason':'single native observation without printed glyph at bbox; not adopted','evidence':'revision2/cell-inspection/c416-800.png'})
        if value is None:unresolved.append(r)
        same=[x for x in starts if abs(mid(x)-mid(o))<5]
        if len(same)==1:
            s=same[0];next_y=min([mid(x) for x in starts if mid(x)>mid(s)+5]+[778])
            label_obs=[x for x in label_rows if mid(s)-4<=mid(x)<next_y-4]
            r['raw_label']=' '.join(x['text'] for x in label_obs)
            match=re.match(r'^\s*(\d{1,2})\s*(.*)',s['text']);r['printed_code']=match.group(1)
            r['related_fields_json']=enc(label_obs)
        if direct_evidence:
            prev=json.loads(r['related_fields_json']) if r['related_fields_json'] else None
            r['related_fields_json']=enc({'label_observations':prev,'direct_evidence':direct_evidence})
        before=[r0 for y,r0 in page_moku if y<=mid(o)+5]
        if before:r['moku_observed_id']=before[-1]['observed_id']
        # Parent association only within a page displaying the moku start, never guessed across a blank continuation.
        legal.append(r)

schemas={
 'pages': [('observed_id','VARCHAR'),('origin_sha256','VARCHAR'),('origin_url','VARCHAR'),('fiscal_year','INTEGER'),('physical_page','INTEGER'),('printed_footer_json','VARCHAR'),('account','VARCHAR'),('expenditure_scope','BOOLEAN'),('source_json','VARCHAR'),('observation_count','INTEGER'),('render_sha256','VARCHAR'),('render_bytes','BIGINT'),('direction','VARCHAR'),('phase','VARCHAR'),('source_unit','VARCHAR'),('amount','BIGINT')],
 'observations':[(k,t) for k,t in [('observed_id','VARCHAR'),('origin_sha256','VARCHAR'),('origin_url','VARCHAR'),('fiscal_year','INTEGER'),('physical_page','INTEGER'),('source_ordinal','INTEGER'),('pass_id','VARCHAR'),('raw_text','VARCHAR'),('confidence','DOUBLE'),('bbox_json','VARCHAR'),('alternatives_json','VARCHAR'),('source_json','VARCHAR'),('direction','VARCHAR'),('phase','VARCHAR'),('source_unit','VARCHAR'),('amount','BIGINT'),('role','VARCHAR')]],
}
financial_schema=[(k,'INTEGER' if k in {'fiscal_year','physical_page','printed_page','source_ordinal','unit_multiplier'} else 'BIGINT' if k=='observed_amount' else 'VARCHAR') for k in candidate(148,'',{'pass':'whole','index':0,'text':'','bbox_pdf_top_left':[]},None)]
for row in cells+legal+projects+moku:
    key=row['observed_id'].split(':',1)[1]
    if key in CELL_EQUIV:
        vv,canon,nativev=CELL_EQUIV[key]
        if row.get('observed_amount')!=vv:
            prev=json.loads(row['related_fields_json']) if row.get('related_fields_json') else None
            row['related_fields_json']=enc({'cell_equivalence':{'canonical_observed_id':f'{SHA}:{canon}','verified_amount':vv,'raw_numeric':row.get('observed_amount')},'previous_related_fields':prev,'note':'same printed cell as canonical; native pass value superseded'})
            row['observed_amount']=vv;row['amount_status']='superseded-by-cluster-direct-verification'
seen=set();unresolved=[]
for row in cells+moku+legal+projects:
    if row.get('observed_amount') is None and row['observed_id'] not in seen:
        seen.add(row['observed_id']);unresolved.append(row)
tables={'pages':pages,'observations':words,'focused_observations':focused,'financial_cells':cells,'moku_controls':moku,'legal_amounts':legal,'explanation_amounts':projects,'unresolved_cells':unresolved}
if DRY:
    plan={'config':'pipeline/ingestion/fiscal/sources-chiyoda2025-initial-native.json','objects_root':str(OBJECTS),'input_objects':1288,'expected':{'pages':500,'observations':38738,'focused_observations':5197,'financial_cells':2221,'moku_controls':217,'legal_amounts':693,'explanation_amounts':1079,'unresolved_cells':1},'outputs':['staging_pages.csv','staging_observations.csv','staging_focused_observations.csv','intermediate_financial_cells.csv','intermediate_moku_controls.csv','intermediate_legal_amounts.csv','intermediate_explanation_amounts.csv','intermediate_unresolved_cells.csv','marts/ref_current_amounts.csv','marts/ref_prior_amounts.csv','marts/ref_difference_amounts.csv','marts/ref_legal_setsu.csv','marts/ref_explanation_amounts.csv','131016/2025/initial_expenditure_native_reference.csv'],'network':'none','original_paths':'none (object store only)'}
    print(enc(plan));sys.exit(0)
out=OUTDIR;out.mkdir(parents=True,exist_ok=True);db=duckdb.connect();manifest=[]
for name,rows in tables.items():
    schema=schemas['pages'] if name=='pages' else schemas['observations'] if name in {'observations','focused_observations'} else financial_schema
    db.execute(f'create table "{name}" ('+', '.join(f'"{k}" {t}' for k,t in schema)+')')
    vals=[tuple(r.get(k) for k,t in schema) for r in rows]
    if vals:db.executemany(f'insert into "{name}" values ('+','.join('?' for _ in schema)+')',vals)
    csvname={'pages':'staging_pages','observations':'staging_observations','focused_observations':'staging_focused_observations'}.get(name,'intermediate_'+name)
    path=out/(csvname+'.csv');db.execute(f"copy \"{name}\" to '{path}' (format csv, header)")
    colspec='{'+','.join(f"'{k}':'{t}'" for k,t in schema)+'}'
    reopened=db.execute(f"select * from read_csv('{path}',header=true,columns={colspec})").fetchall()
    assert reopened==vals,f'{name}: typed CSV readback mismatch'
    manifest.append(dict(role=name,path=str(path),rows=len(rows),schema=schema,**digest(path)))
# Nonadditive reference marts + dedicated CSV (full raw fields preserved; column roles declared in config).
db=duckdb.connect()
cells=out/'intermediate_financial_cells.csv'
marts={
 'ref_current_amounts':"role='observed-current'",
 'ref_prior_amounts':"role='observed-prior'",
 'ref_difference_amounts':"role='observed-difference'",
 'ref_legal_setsu':"role='observed-legal-amount'",
 'ref_explanation_amounts':"role='observed-explanation-amount'"}
(out/'marts').mkdir(exist_ok=True)
for mn,filt in marts.items():
    db.execute(f"copy (select * from read_csv('{cells}',header=true) where {filt}) to '{out}/marts/{mn}.csv' (format csv, header)")
    manifest.append(dict(role=mn,path=str(out/'marts'/f'{mn}.csv'),rows=db.execute(f"select count(*) from read_csv('{out}/marts/{mn}.csv',header=true)").fetchone()[0],schema=None,**digest(out/'marts'/f'{mn}.csv')))
(out/'131016'/'2025').mkdir(parents=True,exist_ok=True)
ded=out/'131016'/'2025'/'initial_expenditure_native_reference.csv'
db.execute(f'''copy (
 select *, 'additive: account expenditure total component (moku grain)' as grain_additivity from read_csv('{out}/intermediate_moku_controls.csv',header=true) where role='moku-control'
 union all select *, 'nonadditive: printed page subtotal (計) row' from read_csv('{out}/intermediate_moku_controls.csv',header=true) where role<>'moku-control'
 union all select *, 'nonadditive: independent legal-setsu grain (same totals, different decomposition)' from read_csv('{out}/intermediate_legal_amounts.csv',header=true)
 union all select *, 'nonadditive: independent project/explanation grain' from read_csv('{out}/intermediate_explanation_amounts.csv',header=true)
) to '{ded}' (format csv, header)''')
manifest.append(dict(role='dedicated_csv',path=str(ded),rows=db.execute(f"select count(*) from read_csv('{ded}',header=true)").fetchone()[0],schema=None,**digest(ded)))
db.close()
(OUTDIR/'materialization-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(enc([dict(role=r['role'],rows=r['rows'],sha256=r['sha256']) for r in manifest]))

def emit_locked_parquets(out: Path) -> dict:
    pdir=out/'locked-tables';pdir.mkdir(exist_ok=True)
    hashes={}
    dbl=duckdb.connect()
    for name in ['pages','observations','focused_observations','financial_cells','moku_controls','legal_amounts','explanation_amounts','unresolved_cells']:
        schema=schemas['pages'] if name=='pages' else schemas['observations'] if name in {'observations','focused_observations'} else financial_schema
        path=pdir/f'{name}.parquet'
        csvmap={'pages':'staging_pages','observations':'staging_observations','focused_observations':'staging_focused_observations'}.get(name,'intermediate_'+name)
        # Same inference path as inputs.restore: locked objects were produced by untyped read_csv.
        dbl.execute(f"copy (select * from read_csv('{out/csvmap}.csv',header=true)) to '{path}' (format parquet, compression zstd)")
        hashes[name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
    dbl.close()
    return hashes

if '--parquets' in sys.argv:
    lp=emit_locked_parquets(OUTDIR)
    print(enc(dict(locked_tables=lp)))
