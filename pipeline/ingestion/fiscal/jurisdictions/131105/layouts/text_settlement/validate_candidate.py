"""Compare read-back scalar Parquet with independent fixed-pitch source observations."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import duckdb

DETAIL={'initial':'当初予算額','amendment':'補正予算額','prior':'継続費及び繰越事業費繰越額','transfer':'予備費支出及び流用増減','total':'計','executed':'支出済額','carry_continuing':'継続費逓次繰越','carry_authorized':'繰越明許費','carry_accident':'事故繰越し','unused':'不用額'}
SUMMARY={'total':'予算現額','executed':'支出済額','carry':'翌年度繰越額','unused':'不用額','comparison':'予算現額と支出済額との比較'}
LEAF={k:('金額' if k=='total' else v) for k,v in DETAIL.items() if k not in ['initial','amendment','prior','transfer']}
LABELS=['款','項','目']
def compact(s):return re.sub(r'\s+','',s or '')
def number(s):
    if s is None:raise ValueError('Missing amount')
    if not re.fullmatch(r'△?\d[\d,]*',s):raise ValueError(f'Non-original amount: {s}')
    return int(s.replace(',','').replace('△','-'))

def validate(origin:Path,candidate:Path,out:Path,pdf:Path,remarks_origin:Path|None=None,table_id='general-setsu'):
    out.mkdir(parents=True,exist_ok=False)
    source=json.loads(origin.read_text());errors=[];checks=[];preserved=0;remarks=[]
    if hashlib.sha256(pdf.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('Origin SHA differs')
    expected={(n['kind'],tuple(n['path'])):n for n in source['nodes']}
    if len(expected)!=len(source['nodes']):raise ValueError('Duplicate source path')
    actual={}; tables={}
    def error(kind,path,page,column,observed,wanted,reason):
        errors.append(dict(kind=kind,path=path,page=page,column=column,unit='円',source=wanted,candidate=observed,reason=reason))
    def collect(kind,path,row,prefix,mapping,page):
        node=dict(kind=kind,path=list(path),page=page,name=row[prefix+'名称'] if prefix else row['区分_名称'],amounts={k:row[prefix+v] for k,v in mapping.items()})
        ident=(kind,tuple(path))
        if ident in actual and actual[ident]!=node:error(kind,list(path),page,'反復親',node,actual[ident],'Same parent path has differing repetitions')
        else:actual[ident]=node
    name=table_id
    p=candidate/f'{name}.parquet'
    with duckdb.connect() as c:
        q=c.execute('select * from read_parquet(?, hive_partitioning=false)',[str(p)])
        columns=[d[0] for d in q.description]
        if any(d[1] not in [duckdb.sqltypes.VARCHAR,duckdb.sqltypes.INTEGER,duckdb.sqltypes.BIGINT,duckdb.sqltypes.DOUBLE] for d in q.description):
            raise ValueError('Non-scalar raw type')
        rows=[dict(zip(columns,r)) for r in q.fetchall()]
    tables[name]=dict(rows=len(rows),columns=len(columns),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
    seen=set()
    for row in rows:
        path=tuple(row[x+'_番号'] for x in LABELS)
        leaf=path+(row['区分_番号'],)
        if leaf in seen:error('detail',list(leaf),row['物理頁'],'row',leaf,None,'Duplicate leaf')
        seen.add(leaf)
        for i,label in enumerate(LABELS):collect('detail',path[:i+1],row,label+'_',DETAIL,row[label+'_物理頁'])
        collect('detail',leaf,row,'',LEAF,row['物理頁'])
        for prefix in [x+'_' for x in LABELS]+['']:
            remarks.append(dict(path=list(leaf) if not prefix else list(path[:LABELS.index(prefix[:-1])+1]),page=row[prefix+'物理頁'] if prefix else row['物理頁'],text=row[prefix+'備考']))
    # Only the finest original records are official raw; summary and grand totals remain origin controls.
    expected={key:node for key,node in expected.items() if key[0]=='detail'}
    for ident in sorted(set(expected)|set(actual)):
        e,a=expected.get(ident),actual.get(ident)
        if e is None or a is None:error(ident[0],list(ident[1]),(e or a)['page'],'row',a,e,'Missing or extra original path');continue
        if a['page']!=e['page']:error(ident[0],list(ident[1]),e['page'],'物理頁',a['page'],e['page'],'Wrong physical source page')
        if compact(a['name'])!=compact(e['name']):error(ident[0],list(ident[1]),e['page'],'名称',a['name'],e['name'],'Name letters differ')
        else:preserved+=1
        for field,wanted in e['amounts'].items():
            if a['amounts'].get(field)!=wanted:error(ident[0],list(ident[1]),e['page'],field,a['amounts'].get(field),wanted,'Original numeric string differs')
            else:preserved+=1
    for ident,e in expected.items():
        children=[a for key,a in actual.items() if len(key[1])==len(ident[1])+1 and key[1][:-1]==ident[1]]
        if not children:continue
        for field,wanted in e['amounts'].items():
            if field not in children[0]['amounts']:continue
            value=sum(number(a['amounts'][field]) for a in children)
            checks.append(dict(kind='detail',hierarchy=f'{len(ident[1])+1}→{len(ident[1])}',path=list(ident[1]),page=e['page'],column=field,unit='円',parent=wanted,children=value,difference=value-number(wanted),status='一致' if value==number(wanted) else '不一致'))
    # Compare original printed totals directly to unique read-back kan paths, never SUM(DISTINCT amount).
    total=next(t for t in source['totals'] if t['kind']=='detail')
    kan=[a for key,a in actual.items() if len(key[1])==1]
    for field,wanted in total['amounts'].items():
        value=sum(number(a['amounts'][field]) for a in kan)
        checks.append(dict(kind='detail',hierarchy='1→0',path=[],page=total['page'],column=field,unit='円',parent=wanted,children=value,difference=value-number(wanted),status='一致' if value==number(wanted) else '不一致'))
    controls=[n for n in source['nodes'] if n['kind']=='summary']+[dict(t,path=[]) for t in source['totals'] if t['kind']=='summary']
    for control in controls:
        path=tuple(control['path']);a=actual.get(('detail',path))
        if path and a is None:continue
        values={k:sum(number(n['amounts'][k]) for n in kan) for k in DETAIL} if not path else {k:number(v) for k,v in a['amounts'].items()}
        for field,wanted in control['amounts'].items():
            value=sum(values[x] for x in ['carry_continuing','carry_authorized','carry_accident']) if field=='carry' else values['total']-values['executed'] if field=='comparison' else values[field]
            checks.append(dict(kind='summary-origin-control',hierarchy='same path',path=list(path),page=control['page'],column=field,unit='円',parent=wanted,children=value,difference=value-number(wanted),status='一致' if value==number(wanted) else '不一致'))
    if remarks_origin is not None:
        observation=json.loads(remarks_origin.read_text())
        if observation['sha256']!=source['sha256']:raise ValueError('Remarks origin SHA differs')
        origin_remarks={tuple(r['path']):r for r in observation['remarks']};candidate_remarks={}
        for r in remarks:
            path=tuple(r['path'])
            if path in candidate_remarks and r!=candidate_remarks[path]:error('remarks',list(path),r['page'],'備考',r,candidate_remarks[path],'Repeated parent remarks differ')
            candidate_remarks[path]=r
        candidate_remarks={path:r for path,r in candidate_remarks.items() if r['text']}
        for path in sorted(set(origin_remarks)|set(candidate_remarks)):
            e=origin_remarks.get(path);a=candidate_remarks.get(path)
            if compact((e or {}).get('text'))!=compact((a or {}).get('text')):error('remarks',list(path),(e or a)['page'],'備考',a,e,'Original remarks letters or cell membership differ')
            else:preserved+=1
    counts=Counter(c['status'] for c in checks)
    result=dict(remarks_paths=len(candidate_remarks),status='passed' if not errors and not counts['不一致'] else 'failed',tables=tables,original_nodes=len(expected),readback_nodes=len(actual),preserved_cells=preserved,cell_mismatches=len(errors),hierarchy_counts=dict(counts),hierarchies=dict(Counter(c['kind']+':'+c['hierarchy'] for c in checks)),pending=0,uncheckable=[dict(path=n['path'],page=n['page'],column=x,unit='円',parent=n['amounts'][x],children=None,difference=None,reason='節には当初・補正・前年度繰越・流用の個別内訳が印字されておらず、節→目のこの4列は検算不可。文字保持、目→項→款→合計の合計は別途確認。') for n in source['nodes'] if n['kind']=='detail' and n['level']==2 for x in ['initial','amendment','prior','transfer']])
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');(out/'cells.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2)+'\n');(out/'hierarchy.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n');(out/'remarks-readback.json').write_text(json.dumps(remarks,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='uncheckable'} | {'uncheckable':len(result['uncheckable'])},ensure_ascii=False));return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['origin','candidate','output','pdf']:p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--remarks-origin',type=Path,required=True)
    p.add_argument('--table-id',default='general-setsu')
    a=p.parse_args();r=validate(a.origin,a.candidate,a.output,a.pdf,a.remarks_origin,a.table_id);raise SystemExit(0 if r['status']=='passed' else 1)
