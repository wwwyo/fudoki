"""Independent comparison of printed lending and reserve-transfer axes."""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from inspect_origin import FIELDS, number
from validate_candidate import normalized, read_raw


def validate(directory: Path, observations: Path, output: Path,
             table_ids=('chuo-general-lending-status', 'chuo-general-reserve-transfers')) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    origin = json.loads(observations.read_text())
    pages = {p['page']: p['words'] for p in origin['pages']}
    issues, checks, tables = [], [], {}

    def compare(label, expected, actual):
        checks.append({'label': label, 'origin': expected, 'raw': actual,
                       'status': '一致' if normalized(str(expected)) == normalized(str(actual)) else '不一致'})

    def controls(rows):
        for i, row in enumerate(rows):
            for position, tier in enumerate(('款','項','目')):
                # The NHI reserve block prints 第５項 with a fullwidth digit;
                # membership lookup normalizes width while the verbatim field
                # comparison still requires the printed form.
                path = {key: unicodedata.normalize('NFKC', str(row[key+'_番号']))
                        for key in ('款','項','目')[:position+1]}
                source = next((c for c in origin['controls'] if c['level']==tier and c['path']==path), None)
                if source is None:
                    issues.append({'kind':'unknown fiscal ancestor','row':i,'path':path})
                    continue
                for field in ('名称', *FIELDS):
                    compare(f'{i}/{tier}/{field}', source['name'] if field=='名称' else source['values'][field], row.get(tier+'_'+field))
                compare(f'{i}/{tier}/page', source['page'], row.get(tier+'_原典物理頁'))

    for name in table_ids:
        path = directory / (name+'.parquet')
        rows, schema = read_raw(path)
        tables[name] = {'rows':len(rows),'columns':len(schema),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
        for column, type_ in schema:
            if any(t in type_ for t in ('STRUCT','[]','JSON','MAP')) or column in ('jurisdiction','fiscal_year','unit','row_id','node_id'):
                issues.append({'kind':'non-original scalar schema','column':column})
        controls(rows)
        if name.endswith('lending-status'):
            expected = [r for r in origin['monetary_rows'] if r['page']==112 and not r['is_total']]
            compare('lending row count',len(expected),len(rows))
            used=set()
            for source in expected:
                matches=[(i,r) for i,r in enumerate(rows) if r.get('内表_金額_原典物理頁')==112 and abs(r.get('内表_金額_原典yMin',-1)-source['y'])<.05]
                if len(matches)!=1:
                    issues.append({'kind':'lending original row coverage','source':source,'matches':len(matches)});continue
                i,row=matches[0];used.add(i)
                words=sorted([w for w in pages[112] if 45<w['x0']<365 and abs(w['y0']-source['y'])<1], key=lambda w:w['x0'])
                compare(f'loan{i}/区分',''.join(w['text'] for w in words if w['x0']<260),row.get('内表_区分'))
                compare(f'loan{i}/件数',''.join(w['text'] for w in words if 260<w['x0']<300),row.get('内表_件数'))
                compare(f'loan{i}/金額',''.join(w['text'] for w in words if w['x0']>300),row.get('内表_金額'))
                for field,key in [('xMin','x0'),('xMax','x1')]:
                    if abs(row['内表_金額_原典'+field]-source[key])>.05: issues.append({'kind':'lending amount coordinate','row':i,'field':field})
                for tier in ('事業','内訳1'):
                    ws=[w for w in pages[112] if row[tier+'_原典xMin']-1<w['x0'] and w['x1']<row[tier+'_原典xMax']+1 and abs(w['y0']-row[tier+'_原典yMin'])<1]
                    text=normalized(''.join(w['text'] for w in ws))
                    for field in ('名称','金額'):
                        if normalized(row[tier+'_'+field]) not in text: issues.append({'kind':'loan parent source preservation','row':i,'tier':tier,'field':field})
            total=next(r for r in origin['monetary_rows'] if r['page']==112 and r['is_total'])
            total_words=[w for w in pages[112] if abs(w['y0']-total['y'])<1 and 260<w['x0']<300]
            compare('貸付金額計 千円',number(total['amount']),sum(number(r['内表_金額'].replace('千円','')) for r in rows))
            compare('貸付件数計 件',number(''.join(w['text'] for w in total_words)),sum(number(r['内表_件数'].replace('件','')) for r in rows))
        else:
            reserve_page = origin.get('reserve_page', 163)
            page_words = pages[reserve_page]
            heading_y = min(w['y0'] for w in page_words if w['x0'] < 540 and '充用した科目' in w['text'])
            total_control = next(c for c in origin['controls'] if c['level']=='合計')
            ws=sorted([w for w in page_words if w['x0']<540 and heading_y-1<w['y0']<total_control['y']-1 and w['text'].strip()],key=lambda w:(w['y0'],w['x0']))
            lines=[]
            for word in ws:
                if not lines or abs(lines[-1][0]['y0']-word['y0'])>1:lines.append([])
                lines[-1].append(word)
            ancestor={};expected=[];total=None;pending_tier=None
            for line in lines:
                line.sort(key=lambda w:w['x0'])
                text=normalized(''.join(w['text'] for w in line)); monetary=[w['text'] for w in line if re.fullmatch(r'[\d,]+',w['text'])]
                if '円' not in text:
                    monetary=[]
                if text.startswith('充用した科目'):
                    total=monetary[0]
                elif (match:=re.match(r'第(\d+)(款|項|目)',text)):
                    amount=monetary[-1] if monetary else None;label=re.sub(r'[\d,]+円$','',text[match.end():])
                    for child in {'款':('項','目'),'項':('目',),'目':()}[match[2]]:ancestor.pop(child,None)
                    ancestor[match[2]]={'番号':match[1],'名称':label,'金額':amount+'円' if amount else None}
                    pending_tier=match[2] if amount is None else None
                elif text.startswith('（'):
                    expected.append({'path':dict(ancestor),'name':text,'name_y':line[0]['y0']})
                    if monetary:
                        expected[-1]['name']=re.sub(r'[\d,]+円$','',text)
                        expected[-1]['amount']=monetary[-1]+'円';expected[-1]['y']=line[-2]['y0']
                elif monetary and expected:
                    if pending_tier:
                        # A folded destination item name is followed by its
                        # amount before the next parenthesized project row.
                        ancestor[pending_tier]['名称'] += re.sub(r'[\d,]+円$','',text)
                        ancestor[pending_tier]['金額']=monetary[-1]+'円';pending_tier=None
                    else:
                        expected[-1]['amount']=monetary[-1]+'円';expected[-1]['y']=line[-2]['y0']
                elif pending_tier and not monetary:
                    ancestor[pending_tier]['名称'] += text
            compare('reserve row count',len(expected),len(rows))
            for i, source in enumerate(expected):
                matches=[r for r in rows if r['原典物理頁']==reserve_page and abs(r['原典yMin']-source['y'])<.1]
                if len(matches)!=1:issues.append({'kind':'reserve original row coverage','source':source});continue
                row=matches[0]
                compare(f'reserve{i}/事業',source['name'],row.get('充用先_事業'))
                compare(f'reserve{i}/金額',source['amount'],row.get('充用先_金額'))
                compare(f'reserve{i}/総額',total+'円',row.get('充用した科目（事業）及び金額'))
                for tier,cells in source['path'].items():
                    for field,value in cells.items():compare(f'reserve{i}/{tier}/{field}',value,row.get('充用先_'+tier+'_'+field))
            compare('充用先金額計 円',number(total),sum(number(r['充用先_金額']) for r in rows))
            for position,tier in enumerate(('款','項','目')):
                groups=collections.defaultdict(list)
                for row in rows:
                    key=tuple(row['充用先_'+part+'_番号'] for part in ('款','項','目')[:position+1])
                    groups[key].append(row)
                for key,members in groups.items():
                    parent_values={r['充用先_'+tier+'_金額'] for r in members}
                    if len(parent_values)!=1:
                        issues.append({'kind':'inconsistent repeated reserve ancestor','path':key,'level':tier});continue
                    parent_amount=number(next(iter(parent_values)))
                    if tier=='目':
                        child_total=sum(number(r['充用先_金額']) for r in members)
                    else:
                        child_tier=('項','目')[position]
                        children={r['充用先_'+child_tier+'_番号']:r['充用先_'+child_tier+'_金額'] for r in members}
                        child_total=sum(number(value) for value in children.values())
                    checks.append({'label':'充用先内訳→'+tier,'level':tier,'path':key,'page':reserve_page,
                                   'field':'充用額','unit':'円','origin':parent_amount,'sum':child_total,
                                   'delta':child_total-parent_amount,'status':'一致' if child_total==parent_amount else '不一致'})
            reserve=next(c for c in origin['controls'] if c['level']=='目' and c['page']==reserve_page and normalized(c['name'])=='予備費')
            compare('予備費減額との符号反対一致 円',-number(reserve['values']['予備費支出']),sum(number(r['充用先_金額']) for r in rows))
    counts=dict(collections.Counter(c['status'] for c in checks))
    summary={'status':'failed' if issues or counts.get('不一致') else 'passed','tables':tables,'preservation_issues':len(issues),'checks':counts}
    for name,value in [('summary',summary),('checks',checks),('issues',issues)]: (output/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--observations',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--table-id',action='append')
    args=parser.parse_args();result=validate(args.directory,args.observations,args.output,args.table_id or ('chuo-general-lending-status','chuo-general-reserve-transfers'));print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['status']=='passed' else 1)
