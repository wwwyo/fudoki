"""Compare independent PDFKit facts with read-back raw cells and printed sums."""
from __future__ import annotations
import argparse, collections, json, re
from pathlib import Path
import duckdb

FIELDS={'initial':'当初予算額','amendment':'補正予算額','prior':'継続費及び繰越事業費繰越額','transfer':'予備費支出及び流用増減','total':'計','executed':'支出済額','carry':'翌年度繰越額','unused':'不用額'}
SUMMARY={**FIELDS,'carry_continuing':'継続費逓次繰越','carry_authorized':'繰越明許費','carry_accident':'事故繰越し'}
PREFIX=['款','項','目']
def norm(v):return None if v is None else re.sub(r'\s+','',str(v))
def amount(v):
    if v is None:raise ValueError('Absent amount cannot be zero')
    return int(norm(v).replace(',','').replace('△','-').replace('▲','-').replace('−','-'))
def raw(path):
    with duckdb.connect() as c:
        q=c.execute('select * from read_parquet(?, hive_partitioning=false)',[str(path)]);names=[d[0] for d in q.description];rows=[dict(zip(names,r)) for r in q.fetchall()]
        types=c.execute('describe select * from read_parquet(?, hive_partitioning=false)',[str(path)]).fetchall()
    if any(any(t in d[1] for t in ['STRUCT','[',']','MAP','JSON']) for d in types):raise ValueError('Non-scalar raw')
    return rows,names

def validate(facts,source,controls=None,*,table_id="general-expenditure-detail",summary_page=3,detail_pages=None):
    detail_pages=list(range(65,148)) if detail_pages is None else list(detail_pages)
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*',table_id) or not detail_pages or any(not 1<=v<=186 for v in detail_pages) or not 1<=summary_page<=186:raise ValueError('Invalid table ID/scope')
    if facts.get('original_sha256')!='ca3f8658f6dbe295978db484227ec1c7adbdc15eeb136f109fa406798511c1eb' or facts.get('physical_pages')!=[summary_page,*detail_pages]:raise ValueError('Independent origin identity/scope differs')
    checks=[]
    def record(kind,path,page,col,expected,observed,status=None,reason=None):
        eq=norm(expected)==norm(observed)
        if kind in ['独立法定節→目','備考→目','目→項','項→款','款→総括','総括款→歳出合計','款→明細歳出合計'] and expected is not None and observed is not None:eq=amount(expected)==amount(observed)
        checks.append({'kind':kind,'path':list(path),'page':page,'column':col,'unit':'円','origin_parent_amount':expected,'detail_sum':observed,'difference':None if expected is None or observed is None or not re.fullmatch(r'[△▲−\-0-9,\s]+',str(expected)) or not re.fullmatch(r'[△▲−\-0-9,\s]+',str(observed)) else amount(observed)-amount(expected),'status':status or ('一致' if eq else '不一致'),'reason':reason})
    tables={};schemas={}
    tables[table_id],schemas[table_id]=raw(source/(table_id+'.parquet'))
    forbidden={'区分_番号','区分_名称','金額','支出済額','翌年度繰越額','不用額'}
    if forbidden.intersection(schemas[table_id]):raise ValueError('Independent legal setsu columns in formal detail')
    parents={}
    for p in facts['parents']:
        key=tuple(p['path'])
        if key in parents:
            record('origin_parent_repeat',key,p['page'],'金額',str(parents[key]['amounts']),str(p['amounts']))
        else:parents[key]=p
    rparents={}
    for id,rows in tables.items():
        for r in rows:
            for l,prefix in enumerate(PREFIX):
                key=tuple(r[x+'_番号'] for x in PREFIX[:l+1])
                if any(v is None for v in key):raise ValueError('Missing raw parent path')
                fields={k:r.get(prefix+'_'+col) for k,col in FIELDS.items()}; fields['name']=r[prefix+'_名称']
                for suffix in ['備考','備考_注記名称','備考_注記金額','備考_流用注記名称','備考_流用注記金額','翌年度繰越額_区分','物理頁','上端','下端']:fields[suffix]=r.get(prefix+'_'+suffix)
                if key in rparents and fields!=rparents[key]['fields']:record('raw_parent_repeat',key,r['物理頁'],prefix,str(rparents[key]['fields']),str(fields))
                else:rparents[key]={'fields':fields,'row':r,'prefix':prefix}
    for key,p in parents.items():
        rp=rparents.get(key)
        if rp is None:record('parent_coverage',key,p['page'],'parent',p['name'],None);continue
        record('parent_name',key,p['page'],'名称',p['name'],rp['fields']['name'])
        row=rp['row'];prefix=rp['prefix']
        record('parent_notes',key,p['page'],'備考',p.get('notes'),row.get(prefix+'_備考'))
        record('parent_carry_label',key,p['page'],'翌年度繰越額_区分',p.get('carry_label'),row.get(prefix+'_翌年度繰越額_区分'))
        record('parent_source_page',key,p['page'],'物理頁',str(p['page']),str(row[prefix+'_物理頁']))
        record('parent_source_y',key,p['page'],'上端',str(round(p['y'],1)),str(round(row[prefix+'_上端'],1)))
        for k,v in p['amounts'].items():record('parent_cell',key,p['page'],FIELDS[k],v,rp['fields'][k])
    for key in rparents.keys()-parents.keys():record('extra_parent',key,rparents[key]['row']['物理頁'],'parent',None,rparents[key]['fields']['name'])
    for id,kind,numcol,namecol,amtcols in [(table_id,'remarks','備考_番号','備考_名称',{'amount':'備考_金額'})]:
        actual={(r['物理頁'],round(r['上端'],1)):r for r in tables[id] if r[numcol] is not None}
        if len(actual)!=sum(r[numcol] is not None for r in tables[id]):raise ValueError('Duplicate leaf coordinates')
        used=set()
        for s in facts[kind]:
            key=(s['page'],round(s['y'],1));r=actual.get(key);path=s['path']+[s['number']]
            if r is None:record('leaf_coverage_'+kind,path,s['page'],numcol,s['number'],None);continue
            used.add(key)
            record('leaf_path_'+kind,path,s['page'],'所属','/'.join(s['path']),'/'.join(r[p+'_番号'] for p in PREFIX))
            record('leaf_number_'+kind,path,s['page'],numcol,s['number'],r[numcol]);record('leaf_name_'+kind,path,s['page'],namecol,s['name'],r[namecol])
            for k,col in amtcols.items():record('leaf_cell_'+kind,path,s['page'],col,s['amounts'][k] if kind=='setsu' else s[k],r[col])
        for key in actual.keys()-used:record('extra_leaf_'+kind,[actual[key][p+'_番号'] for p in PREFIX],key[0],numcol,None,actual[key][numcol])
        origin_leaf_paths={tuple(s['path']) for s in facts[kind]}
        expected_empty={key for key,p in parents.items() if len(key)==3 and key not in origin_leaf_paths}
        actual_empty={tuple(r[p+'_番号'] for p in PREFIX) for r in tables[id] if r[numcol] is None}
        record('detail_row_count',[],None,'rows',len(facts[kind])+len(expected_empty),len(tables[id]))
        for key in expected_empty|actual_empty:record('empty_leaf_'+kind,key,parents[key]['page'],numcol,str(key in expected_empty),str(key in actual_empty))
    for s in facts['summary']:
        if s['number'] is None:continue
        key=(s['number'],)
        rows=[r for r in tables[table_id] if r['款_番号']==s['number']]
        for r in rows:
            for k in ['carry_continuing','carry_authorized','carry_accident']:
                record('summary_parent_cell',key,summary_page,'款_'+SUMMARY[k],s['amounts'][k],r.get('款_'+SUMMARY[k]))
            record('summary_parent_page',key,summary_page,'款_総括_物理頁',summary_page,r.get('款_総括_物理頁'))
            record('summary_parent_y',key,summary_page,'款_総括_上端',round(s['y'],1),round(r['款_総括_上端'],1))
    for s in facts['annotations']:
        key=tuple(s['path']);rp=rparents[key];r=rp['row'];prefix=rp['prefix'];text=norm(r.get(prefix+'_備考')) or ''
        full=s.get('name_block') or s['name']
        expected=full+s['amount']
        record('annotation',key,s['page'],'備考',expected,expected if expected in text else text)
        record('annotation_tail',key,s['page'],'備考',expected,text[len(text)-len(expected):] if text else text,
               status='一致' if text.endswith(expected) else '不一致')
        note='備考_注記' if '前年度繰越事業費不用額' in s['name'] else '備考_流用注記'
        if full.endswith('流用') or s['name'].endswith('流用'):
            names=[s['name']]+([full] if full!=s['name'] else [])
            actual=r.get(prefix+'_'+note+'名称')
            record('annotation_name',key,s['page'],note+'名称','|'.join(names),actual,status='一致' if norm(actual) in {norm(v) for v in names} else '不一致')
            record('annotation_amount',key,s['page'],note+'金額',s['amount'],r.get(prefix+'_'+note+'金額'))
        else:
            # Notes without a 流用 title (e.g. 予備費充用額 or a destination …へ)
            # stay literal in the parent 備考; the dedicated columns are for
            # 流用-titled notes only and must remain NULL rather than backfilled.
            reason='流用title以外の注記は親_備考に原典保持し専用列対象外'
            record('annotation_name',key,s['page'],note+'名称',None,r.get(prefix+'_'+note+'名称'),reason=reason)
            record('annotation_amount',key,s['page'],note+'金額',None,r.get(prefix+'_'+note+'金額'),reason=reason)
    # Raw-to-original hierarchy sums, each printed parent counted exactly once.
    for key,p in parents.items():
        kids=[k for k in parents if len(k)==len(key)+1 and k[:-1]==key]
        if len(key)<3:
            for col in FIELDS:
                value=sum(amount(rparents[k]['fields'][col]) for k in kids) if kids and all(k in rparents for k in kids) else None
                record('目→項' if len(key)==2 else '項→款',key,p['page'],FIELDS[col],p['amounts'][col],str(value) if value is not None else None,status=None if value is not None else '保留',reason=None if value is not None else 'Incomplete raw child coverage')
        else:
            # Legal setsu is an independent origin control, never a formal output leaf.
            independent=[s for s in facts['setsu'] if tuple(s['path'])==key]
            for col,origin_col in [('setsu_total','total'),('executed','executed'),('carry','carry'),('unused','unused')]:
                if not independent:
                    record('独立法定節→目',key,p['page'],FIELDS[origin_col],p['amounts'][origin_col],None,status='検算不可',reason='原典に法定節内訳なし')
                else:
                    record('独立法定節→目',key,p['page'],FIELDS[origin_col],p['amounts'][origin_col],str(sum(amount(s['amounts'][col]) for s in independent)))
            rr=[r for r in tables[table_id] if tuple(r[x+'_番号'] for x in PREFIX)==key and r['備考_番号'] is not None]
            original_leaves=[s for s in facts['remarks'] if tuple(s['path'])==key]
            if not original_leaves:
                record('備考→目',key,p['page'],'備考_金額',p['amounts']['executed'],None,status='検算不可',reason='原典に備考事業内訳なし')
            else:
                record('備考→目',key,p['page'],'備考_金額',p['amounts']['executed'],str(sum(amount(r['備考_金額']) for r in rr)))
    for s in facts['summary']:
        if s['number'] is None:continue
        key=(s['number'],)
        for col in ['initial','amendment','prior','transfer','total','executed','unused']:
            record('款→総括',key,summary_page,FIELDS[col],s['amounts'][col],rparents[key]['fields'][col])
        carry=sum(amount(s['amounts'][x]) for x in ['carry_continuing','carry_authorized','carry_accident'])
        record('款→総括',key,summary_page,'翌年度繰越額',str(carry),rparents[key]['fields']['carry'])
    for col in ['initial','amendment','prior','transfer','total','executed','carry_continuing','carry_authorized','carry_accident','unused']:
        total=next(s for s in facts['summary'] if s['number'] is None)
        value=sum(amount(s['amounts'][col]) for s in facts['summary'] if s['number'] is not None)
        record('総括款→歳出合計',['歳出合計'],summary_page,SUMMARY[col],total['amounts'][col],str(value))
    for total in facts.get('detail_totals',[]):
        for col in FIELDS:
            value=sum(amount(rparents[(s['number'],)]['fields'][col]) for s in facts['summary'] if s['number'] is not None)
            record('款→明細歳出合計',['歳出合計'],total['page'],FIELDS[col],total['amounts'][col],str(value))
    if controls is not None:
        for ident,kind,numcol,namecol,columns in [
            (table_id.removesuffix('-expenditure-detail')+'-summary','summary','款_番号','款_名称',{k:v for k,v in SUMMARY.items() if k!='carry'}),
            (table_id.removesuffix('-expenditure-detail')+'-setsu','setsu','区分_番号','区分_名称',{'setsu_total':'金額','executed':'支出済額','carry':'翌年度繰越額','unused':'不用額'})]:
            rows,_=raw(controls/(ident+'.parquet'))
            keyed={(r['物理頁'],round(r['上端'],1)):r for r in rows if kind=='summary' or r[numcol] is not None}
            if len(keyed)!=sum(kind=='summary' or r[numcol] is not None for r in rows):raise ValueError('Duplicate local control')
            expected={(s['page'],round(s['y'],1)) for s in facts[kind]}
            record('local_control_coverage',[],None,kind,str(sorted(expected)),str(sorted(keyed)))
            for s in facts[kind]:
                r=keyed.get((s['page'],round(s['y'],1)))
                path=s.get('path',[])+[s['number'] or '歳出合計']
                if r is None:continue
                record('local_control_number',path,s['page'],numcol,s['number'],r[numcol])
                record('local_control_name',path,s['page'],namecol,s['name'],r[namecol])
                if kind=='setsu':record('local_control_path',path,s['page'],'所属','/'.join(s['path']),'/'.join(r[p+'_番号'] for p in PREFIX))
                for k,col in columns.items():record('local_control_cell',path,s['page'],col,s['amounts'][k],r[col])
    # Missing leaves keep all leaf fields NULL, never fabricated zero or names.
    for r in tables[table_id]:
        if r['備考_番号'] is None:
            key=[r[p+'_番号'] for p in PREFIX]
            for col in ['備考_名称','備考_金額']:
                record('empty_leaf_cell',key,r['物理頁'],col,None,r[col])
    counts=collections.Counter(c['status'] for c in checks);kinds={k:dict(collections.Counter(c['status'] for c in checks if c['kind']==k)) for k in sorted({c['kind'] for c in checks})}
    return {'status':'passed' if not counts['不一致'] and not counts['保留'] else 'failed','counts':dict(counts),'by_kind':kinds,'independent_origin_controls':{'summary':len(facts['summary']),'setsu':len(facts['setsu'])},'tables':{id:{'rows':len(tables[id]),'columns':len(schemas[id])} for id in tables},'checks':checks}
def main():
    p=argparse.ArgumentParser();p.add_argument('--origin',required=True,type=Path);p.add_argument('--candidate',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--controls',type=Path,help='Optional local summary/setsu observations, never formal tables')
    p.add_argument('--table-id',default='general-expenditure-detail');p.add_argument('--summary-page',type=int,default=3);p.add_argument('--detail-start',type=int,default=65);p.add_argument('--detail-end',type=int,default=147);a=p.parse_args()
    result=validate(json.loads(a.origin.read_text()),a.candidate,a.controls,table_id=a.table_id,summary_page=a.summary_page,detail_pages=range(a.detail_start,a.detail_end+1));a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:result[k] for k in ['status','counts','by_kind','tables']},ensure_ascii=False))
    raise SystemExit(0 if result['status']=='passed' else 1)
if __name__=='__main__':main()
