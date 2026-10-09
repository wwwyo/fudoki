"""Independent XML-text observation; no construction modules are imported."""
import argparse, hashlib, json, re, subprocess, xml.etree.ElementTree as ET
from pathlib import Path
SHA='7d2b4b818e99e43e95c02ef7c33c0022b93e1bab83335004924bd30894bcb280'
def canon(s): return re.sub(r'\s+','',s or '')
def ordered(items):
    lines=[]
    for t in sorted(items,key=lambda t:(t['y'],t['x'])):
        if not lines or t['y']-lines[-1][0]['y']>3: lines.append([])
        lines[-1].append(t)
    return ''.join(t['text'] for line in lines for t in sorted(line,key=lambda t:t['x']))
def observe_reports(root):
    pages={int(p.attrib['number']):p for p in root.findall('page')}
    result={}
    left_columns=['当初予算額','補正予算額','予備費支出額','流用増減額']
    for label,lp,rp in [('revenue-report',4,5),('capital-report',6,7)]:
        capital=lp==6
        entries={p:[{'x':float(t.attrib['left']),'y':float(t.attrib['top']),'text':''.join(t.itertext())} for t in pages[p].findall('text') if ''.join(t.itertext()).strip()] for p in (lp,rp)}
        start=next(t['y'] for t in entries[lp] if '第１款' in t['text'] and ('資本的支出' if capital else '事業費') in t['text'])
        labels=sorted([t for t in entries[lp] if t['y']>=start and re.match(r'^第[１２３４]([款項])',t['text'])],key=lambda t:t['y'])
        assert len(labels)==5
        lc=left_columns+(['小計','地方公営企業法第26条の規定による前年度繰越額'] if capital else ['地方公営企業法第24条第3項の規定による支出額'])
        rc=(['継続費逓次繰越額','合計','決算額','地方公営企業法第26条の規定による繰越額','翌年度繰越額_継続費逓次繰越額','翌年度繰越額_合計','不用額'] if capital else ['小計','地方公営企業法第26条第２項の規定による繰越額','合計','決算額','地方公営企業法第26条第2項の規定による繰越額','不用額'])
        rows=[]
        for t in labels:
            y=t['y'];values={}
            names=[v for v in entries[lp] if v['x']<230 and abs(v['y']-y)<=12]
            values['区分']=canon(t['text']+ordered([v for v in names if v is not t]))
            for p,columns in [(lp,lc),(rp,rc)]:
                nums=[]
                for v in sorted(entries[p],key=lambda v:v['x']):
                    if abs(v['y']-y)<=3 and re.fullmatch(r'[0-9,]+(?: [0-9,]+)*',v['text']):nums.extend(v['text'].split())
                if len(nums)!=len(columns):raise ValueError(('Report column count',p,y,nums))
                values.update(dict(zip(columns,nums)))
            remark=[v for v in entries[rp] if v['x']>730 and abs(v['y']-y-10)<=3 and re.fullmatch(r'[0-9,]+',v['text'])]
            assert len(remark)==1
            values.update({'備考_名称':'うち仮払消費税','備考_金額':remark[0]['text'],'page':lp,'y':y})
            rows.append(values)
        result[label]=rows
    return result

def observe(pdf,out):
    if hashlib.sha256(pdf.read_bytes()).hexdigest()!=SHA: raise ValueError('Original SHA differs')
    subprocess.run(['pdftohtml','-xml','-hidden','-i',str(pdf),str(out/'origin.xml')],check=True,stdout=subprocess.DEVNULL)
    root=ET.parse(out/'origin.xml'); observations=[]; controls=[]; contexts={}
    for page in root.findall('page'):
        p=int(page.attrib['number'])
        if p not in [24,25,26,27,28,30,31]:continue
        group='income' if p<30 else 'capital'
        context=contexts.setdefault(group,{})
        entries=[{'x':float(t.attrib['left']),'y':float(t.attrib['top']),'text':''.join(t.itertext())} for t in page.findall('text') if ''.join(t.itertext()).strip()]
        anchors=sorted([t for t in entries if 380<t['x']<525 and re.fullmatch(r'[0-9,]+',t['text'])],key=lambda t:t['y'])
        sections=[]
        for a in anchors:
            near=[t for t in entries if t['x']<390 and abs(t['y']-a['y'])<=12]
            numbered=[t for t in near if re.match(r'^\s*[１２３４５６７]',t['text'])]
            # Continued moku on p25/p27 shares the first section row, with no moku amount.
            continuation=p in (25,27) and a==anchors[0]
            if numbered and not continuation:
                first=min(numbered,key=lambda t:t['x']); x=first['x']
                level=('款' if p in (24,30) and a==anchors[0] else '項' if x<110 else '目')
                text=canon(ordered(near)); digit=re.search('[１２３４５６７]',text).group()
                text=digit+text.replace(digit,'',1)
                context[level]=text; context[level+'_金額']=a['text']
                if level=='款':
                    for k in ['項','目','項_金額','目_金額']:context.pop(k,None)
                elif level=='項':
                    for k in ['目','目_金額']:context.pop(k,None)
                controls.append({'page':p,'y':a['y'],'level':level,'name':text,'amount':a['text'],'path':dict(context)})
                continue
            if continuation:
                text=canon(ordered(near)); prefix=context['目']
                if not text.startswith(prefix):raise ValueError(('Continuation label differs',p,text,prefix))
                name=text[len(prefix):]
            else:name=canon(ordered([t for t in near if t['x']>=265]))
            if not name:raise ValueError(('Unassigned amount',p,a))
            section={'page':p,'y':a['y'],'name':name,'amount':a['text'],'path':dict(context),'remarks':[],'budget':None}
            sections.append(section); observations.append(section)
        # Remark amount/name pairs are independently observed from the right-hand text blocks.
        remarks=[]
        for a in [t for t in entries if t['x']>700 and re.fullmatch(r'[0-9,]+',t['text'])]:
            labels=[t for t in entries if 510<t['x']<700 and abs(t['y']-a['y'])<=3]
            label=canon(ordered(labels))
            if label:remarks.append({'y':a['y'],'name':label,'amount':a['text']})
        budgets=sorted([r for r in remarks if r['name']=='予算額'],key=lambda r:r['y'])
        budget_sections={}
        for b in budgets:
            following=[s for s in sections if s['y']>=b['y']]
            if not following:raise ValueError(('Budget without section',p,b))
            s=following[0];s['budget']=b['amount'];budget_sections[s['y']]=b['y']
        for r in sorted(remarks,key=lambda r:r['y']):
            if r['name']=='予算額':continue
            eligible=[]
            for i,s in enumerate(sections):
                lo=budget_sections.get(s['y'], -999 if i==0 else s['y']-20 if sections[i-1]['y'] in budget_sections else (sections[i-1]['y']+s['y'])/2)
                hi=9999 if i+1==len(sections) else budget_sections.get(sections[i+1]['y'], sections[i+1]['y']-20 if s['y'] in budget_sections else (s['y']+sections[i+1]['y'])/2)
                if lo<=r['y']<=hi:eligible.append(s)
            if len(eligible)!=1:raise ValueError(('Remark ownership ambiguous',p,r,[(s['name'],s['y']) for s in eligible]))
            eligible[0]['remarks'].append(r)
    result={'sha256':SHA,'controls':controls,'sections':observations,'reports':observe_reports(root)}
    (out/'origin.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pdf',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=False,parents=True)
    r=observe(a.pdf,a.out);print(json.dumps({'controls':len(r['controls']),'sections':len(r['sections']),'remarks':sum(len(s['remarks']) for s in r['sections'])}))
