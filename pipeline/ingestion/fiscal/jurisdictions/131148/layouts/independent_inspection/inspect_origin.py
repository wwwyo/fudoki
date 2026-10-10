"""Independent Poppler observations of Nakano's text settlement spread.

Reads only the original PDF. No construction modules are imported.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as E

SHA = 'cced2994de2438b24d4e446b325adba573a6fe55a458b010b85ebef2ab2b9f96'
NS = '{http://www.w3.org/1999/xhtml}'
NUM = re.compile(r'△?\d[\d,]*')
LEFT = ['initial', 'amendment', 'prior', 'transfer', 'total']
RIGHT = ['executed', 'carry_continuing', 'carry_authorized', 'carry_accident', 'unused']

def words(page):
    return [dict(text=w.text or '', **{k:float(v) for k,v in w.attrib.items()}) for w in page.iter(NS+'word')]

def lines(ws):
    rows=[]
    for w in sorted(ws,key=lambda w:(w['yMin'],w['xMin'])):
        if not rows or abs(rows[-1][0]-w['yMin'])>1: rows.append((w['yMin'],[]))
        rows[-1][1].append(w)
    return [(y,sorted(row,key=lambda w:w['xMin'])) for y,row in rows]

def value(s): return int(s.replace(',','').replace('△','-'))

def observe(pdf, out):
    if hashlib.sha256(pdf.read_bytes()).hexdigest()!=SHA: raise ValueError('Original SHA differs')
    out.mkdir(parents=True,exist_ok=False)
    xml=subprocess.check_output(['pdftotext','-f','104','-l','145','-bbox-layout',str(pdf),'-'])
    (out/'bbox.html').write_bytes(xml)
    pages={i:words(p) for i,p in enumerate(E.fromstring(xml).iter(NS+'page'),104)}
    nodes=[]; summary=[]; notes=[]; page_inventory=[]; path=[]
    for p in range(106,146,2):
        lw,rw=pages[p],pages[p+1]
        anchors=[(y,row) for y,row in lines([w for w in rw if w['yMin']>118 and w['yMin']<800]) if any(NUM.fullmatch(w['text']) and abs(w['xMax']-165.92)<.3 for w in row)]
        labels=[]
        for y,row in lines([w for w in lw if 118<w['yMin']<800 and (w['xMax']<125 or w['xMin']>495)]):
            for side in ['parent','setsu']:
                part=[w for w in row if (w['xMax']<125 if side=='parent' else w['xMin']>495)]
                if not part:continue
                if NUM.fullmatch(part[0]['text']):
                    level=3 if side=='setsu' else min(range(3),key=lambda n:abs(part[0]['xMin']-[36.36,50.88,65.4][n]))
                    labels.append(dict(y=y,level=level,number=part[0]['text'],parts=[(y,''.join(w['text'] for w in part[1:]))],side=side))
                elif side=='parent' and ''.join(w['text'] for w in part)=='歳出合計':
                    labels.append(dict(y=y,level=-1,number='',parts=[(y,'歳出合計')],side=side))
                else:
                    owners=[n for n in labels if n['side']==side and n['y']<=y]
                    if not owners:raise ValueError(('Unowned name fragment',p,y,part))
                    owners[-1]['parts'].append((y,''.join(w['text'] for w in part)))
        local=[]
        for y,row in anchors:
            match=[n for n in labels if abs(n['y']-y)<1]
            if len(match)!=1:raise ValueError(('Left/right alignment',p,y,match))
            n=match[0]; level=n['level']
            vals=[w['text'] for w in row if NUM.fullmatch(w['text']) and w['xMax']<440]
            expected=6 if level==3 else 5
            if len(vals)!=expected:raise ValueError(('Right columns',p,y,vals))
            amount=dict(zip((['total'] if level==3 else [])+RIGHT,vals))
            if level!=3:
                nums=[w['text'] for yy,rr in lines(lw) if abs(yy-y)<1 for w in rr if NUM.fullmatch(w['text']) and 125<w['xMin'] and w['xMax']<495]
                if len(nums)!=5:raise ValueError(('Left columns',p,y,nums))
                amount.update(zip(LEFT,nums))
            if level==-1:node_path=[]
            else:
                if level<3:path=path[:level]
                if len(path)!=(3 if level==3 else level):raise ValueError(('Hierarchy gap',p,y,path,n))
                node_path=path+[n['number']]
                if level<3:path=node_path
            node=dict(page=p,right_page=p+1,y=y,level=level,number=n['number'],name='\n'.join(t for _,t in n['parts']),path=node_path,amounts=amount)
            nodes.append(node);local.append(node)
        if len(local)!=len(labels):raise ValueError(('Unmatched source labels',p,len(local),len(labels)))
        # Keep every nonfinancial note token, including printed years and amounts.
        note_lines=[dict(y=y,text=''.join(w['text'] for w in row)) for y,row in lines([w for w in rw if w['xMin']>=440 and w['text']!='一般会計' and 118<w['yMin']<800])]
        notes.append(dict(page=p+1,lines=note_lines))
        page_inventory.append(dict(left=p,right=p+1,rows=len(local),levels=dict(Counter(n['level'] for n in local)),notes=len(note_lines)))
    # Summary is an independently printed decomposition of the same 13款.
    left_rows=[(y,row) for y,row in lines(pages[104]) if y>118 and any(NUM.fullmatch(w['text']) and abs(w['xMax']-225.02)<.4 for w in row)]
    right_rows=[(y,row) for y,row in lines(pages[105]) if y>118 and any(NUM.fullmatch(w['text']) and abs(w['xMax']-143.4)<.4 for w in row)]
    if len(left_rows)!=14 or len(right_rows)!=14: raise ValueError(('Summary anchors',len(left_rows),len(right_rows)))
    for i,((y,lrow),(ry,rrow)) in enumerate(zip(left_rows,right_rows)):
        nums=[w['text'] for w in lrow if NUM.fullmatch(w['text']) and w['xMin']>125]
        if len(nums)!=5:raise ValueError(('Summary left',i,nums))
        vals=[w['text'] for w in rrow if NUM.fullmatch(w['text'])]
        later=[w['text'] for yy,row in lines(pages[105]) if ry<yy<ry+35 for w in row if NUM.fullmatch(w['text']) and 290<w['xMax']<300]
        if len(vals)!=3 or len(later)!=2:raise ValueError(('Summary right',i,vals,later))
        summary.append(dict(number=str(i+1) if i<13 else '',page=104,right_page=105,amounts=dict(zip(LEFT,nums))|dict(zip(RIGHT,[vals[0],vals[1],*later,vals[2]]))))
    result=dict(sha256=SHA,pages=[104,145],engine='Poppler bbox-layout, numeric right-edge anchors and independent left labels',nodes=nodes,summary=summary,notes=notes,page_inventory=page_inventory)
    (out/'origin.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(nodes=len(nodes),levels=dict(Counter(n['level'] for n in nodes)),summary=len(summary),note_lines=sum(len(n['lines']) for n in notes))))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pdf',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();observe(a.pdf,a.output)
