"""Observe printed Shinjuku settlement cells through PDFKit, independently of conversion."""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, unicodedata
from pathlib import Path

SHA='ca3f8658f6dbe295978db484227ec1c7adbdc15eeb136f109fa406798511c1eb'
AMOUNTS=['initial','amendment','prior','transfer','total','executed','carry','unused']
def compact(s): return re.sub(r'\s+', '', s)
def numeric(s): return bool(re.fullmatch(r'[△▲−-]?[0-9][0-9,]*',compact(s)))
def line(cells,y,tolerance=2):
    return ''.join(s['text'] for s in sorted(cells,key=lambda s:s['x']) if abs(s['y']-y)<tolerance).strip()
def money(cells,y):
    value=line(cells,y)
    if not numeric(value):raise ValueError(f'Missing/non-scalar money at {y}: {value!r}')
    minus=[s for s in cells if '△' in s['text'] and y-15<s['y']<y+2]
    return ('△' if minus and '△' not in value else '')+compact(value)
def name(cells,y,end):
    selected=sorted((s for s in cells if y-2<=s['y']<end-2),key=lambda s:(s['y'],s['x']))
    return compact(''.join(s['text'] for s in selected))
def observe(pages, *, summary_page=3, kan_boundary=30, kou_boundary=48):
    parents=[]; setsu=[]; remarks=[]; summary=[]; annotations=[]; detail_totals=[]; current=[None,None,None]
    for page in pages:
        n=page['page']; cols=page['columns']
        if n==summary_page:
            anchors=[s['y'] for s in cols['initial'] if s['y']>225 and numeric(s['text'])]
            for i,y in enumerate(anchors):
                # Summary names can be centred over two lines, starting above numeric baseline.
                low=(anchors[i-1]+y)/2 if i else y-15
                high=(y+anchors[i+1])/2 if i+1<len(anchors) else y+15
                label=name(cols['hierarchy'],low,high)
                match=re.search(r'(\d+)',label)
                label_without_number=re.sub(r'\d+','',label)
                summary.append({'page':n,'y':y,'number':match[1] if match else None,'name':label_without_number if match else label,'amounts':{k:money(cols[k],y) for k in ['initial','amendment','prior','transfer','total','executed','carry_continuing','carry_authorized','carry_accident','unused']}})
            continue
        panchors=sorted(s['y'] for s in cols['initial'] if s['y']>150 and numeric(s['text']))
        sanchors=sorted(s['y'] for s in cols['setsu_total'] if s['y']>150 and numeric(s['text']))
        ranchors=sorted(s['y'] for s in cols['remarks_amount'] if s['y']>150 and numeric(s['text']))
        events=[]
        for i,y in enumerate(panchors):
            first=sorted((s for s in cols['hierarchy'] if abs(s['y']-y)<2),key=lambda s:s['x'])
            if not first: raise ValueError(f'No hierarchy p{n} y{y}')
            if '歳出合計' in compact(''.join(s['text'] for s in first)):
                detail_totals.append({'page':n,'y':y,'amounts':{k:money(cols[k],y) for k in AMOUNTS}})
                continue
            x=first[0]['x'];level=0 if x<kan_boundary else 1 if x<kou_boundary else 2
            end=panchors[i+1] if i+1<len(panchors) else 780
            label=name(cols['hierarchy'],y,end)
            m=re.fullmatch(r'(\d+)(.+)',label)
            if not m:raise ValueError(f'Bad parent p{n}: {label!r}')
            note_end=min([v for v in ranchors if v>=y-2 and re.match(r'^\d{3}',line(cols['remarks'],v))]+[end])
            # Numbered wrapped remarks can begin above the amount baseline.
            note_end=min([v['y'] for v in cols['remarks'] if y-2<=v['y']<end and re.match(r'^\d{3}(?:\s|$)',v['text'].strip())]+[note_end])
            note_text=name(cols['remarks']+cols['remarks_amount'],y,note_end) or None
            carry_label=compact(''.join(v['text'] for v in cols['carry'] if y-15<v['y']<y+2 and not numeric(v['text']))) or None
            events.append((y,'parent',{'page':n,'y':y,'level':level,'number':m[1],'name':m[2],'notes':note_text,'carry_label':carry_label,'amounts':{k:money(cols[k],y) for k in AMOUNTS}}))
        for i,y in enumerate(sanchors):
            end=min([v for v in panchors+sanchors if v>y+2]+[780])
            label=name(cols['setsu'],y,end);m=re.fullmatch(r'(\d+)(.+)',label)
            if not m:raise ValueError(f'Bad setsu p{n} y{y}: {label!r}')
            events.append((y,'setsu',{'page':n,'y':y,'number':m[1],'name':m[2],'amounts':{k:money(cols[k],y) for k in ['setsu_total','executed','carry','unused']}}))
        starts=sorted({s['y'] for s in cols['remarks'] if s['y']>150 and re.match(r'^\d{3}(?:\s|$)',s['text'].strip())})
        covered=set()
        for i,y in enumerate(starts):
            end=min([v for v in panchors+starts if v>y+2]+[780])
            label=name(cols['remarks'],y,end);m=re.fullmatch(r'(\d{3})(.+)',label)
            if not m:raise ValueError(f'Bad numbered remarks p{n} y{y}: {label!r}')
            values=[v for v in ranchors if y-2<=v<end-2]
            if len(values)!=1:raise ValueError(f'Non-scalar numbered remark p{n}: {label} {values}')
            covered.update(values)
            events.append((y,'remarks',{'page':n,'y':y,'number':m[1],'name':m[2],'amount':money(cols['remarks_amount'],values[0])}))
        for y in ranchors:
            if y in covered:continue
            label=line(cols['remarks'],y)
            events.append((y,'annotation',{'page':n,'y':y,'name':compact(label),'amount':money(cols['remarks_amount'],y)}))
        for y,kind,item in sorted(events,key=lambda e:(e[0],0 if e[1]=='parent' else 1)):
            if kind=='parent':
                level=item['level'];current[level]=item
                for l in range(level+1,3):current[l]=None
                if any(x is None for x in current[:level+1]):raise ValueError(f'Missing hierarchy p{n} level{level} {item}')
                item['path']=[x['number'] for x in current[:level+1]];parents.append(item)
            elif kind=='annotation':
                item['path']=[x['number'] for x in current if x is not None]; annotations.append(item)
            else:
                if any(x is None for x in current):raise ValueError(f'Missing parent context p{n} y{y}')
                item['path']=[x['number'] for x in current]
                (setsu if kind=='setsu' else remarks).append(item)
    return {'summary':summary,'parents':parents,'setsu':setsu,'remarks':remarks,'annotations':annotations,'detail_totals':detail_totals}
def main():
    p=argparse.ArgumentParser();p.add_argument('--pdf',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--account',default='一般会計');p.add_argument('--summary-page',type=int,default=3);p.add_argument('--detail-start',type=int,default=65);p.add_argument('--detail-end',type=int,default=147);p.add_argument('--context-page',type=int,default=1)
    p.add_argument('--kan-boundary',type=float,default=30);p.add_argument('--kou-boundary',type=float,default=48);a=p.parse_args()
    if not 1<=a.detail_start<=a.detail_end<=186 or not 1<=a.summary_page<=186 or not 1<=a.context_page<=186 or not 0<a.kan_boundary<a.kou_boundary or not a.account or any(ord(c)<32 for c in a.account):raise ValueError('Invalid scope/column boundaries')
    if hashlib.sha256(a.pdf.read_bytes()).hexdigest()!=SHA:raise ValueError('Original SHA differs')
    a.output.mkdir(parents=True,exist_ok=False)
    subprocess.run(['xcrun','swift',str(Path(__file__).with_name('inspect_pdfkit.swift')),str(a.pdf.resolve()),str(a.output/'pdfkit.json'),str(a.summary_page),str(a.detail_start),str(a.detail_end),str(a.context_page)],check=True)
    pages=json.loads((a.output/'pdfkit.json').read_text())
    title=compact(unicodedata.normalize('NFKC',pages[0]['context_title']))
    if '令和7年度' not in title or a.account not in title:raise ValueError('Original year/account heading differs')
    if any('単位:円' not in compact(unicodedata.normalize('NFKC',p['text'])) for p in pages if p['page']!=a.summary_page):raise ValueError('Original unit heading differs')
    facts=observe(pages,summary_page=a.summary_page,kan_boundary=a.kan_boundary,kou_boundary=a.kou_boundary)
    facts['header_observation']={'context_page':a.context_page,'text':pages[0]['context_title'],'account':a.account,'year':'令和7年度','unit':'円','unit_verified_physical_pages':list(range(a.detail_start,a.detail_end+1))}

    facts['original_sha256']=SHA;facts['physical_pages']=[a.summary_page,*range(a.detail_start,a.detail_end+1)];facts['engine']='macOS PDFKit column selections'
    (a.output/'origin.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:len(facts[k]) for k in ['summary','parents','setsu','remarks']}))
if __name__=='__main__':main()
