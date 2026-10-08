#!/usr/bin/env python3
# batch4: native transcription of FY2020-FY2026 initial-budget (当初予算) PDFs.
# Ordinance books: account sections with 第１表 歳入歳出予算 (款・項 × 金額).
import json,re,os,subprocess
ZEN=str.maketrans('０１２３４５６７８９','0123456789')
def z2h(s): return s.translate(ZEN)
def int_amt(s):
    s=s.replace(',','').replace('，','').replace('△','-').replace('▲','-').replace('−','-')
    return int(s)
AMT=r'[△▲\-−]?\d[\d,]*'
AMTS=re.compile(AMT)
def canon(s): return re.sub(r'\s','',s)
def clean_name(s): return re.sub(r'\s+',' ',s.strip())

def parse(path):
    page_texts=subprocess.run(['pdftotext','-layout',path,'-'],capture_output=True,text=True).stdout.split('\f')
    rows=[]; secs=[]; sec_i=-1
    cur_dir=None; ctx=None; acc=None; sub_dates=[]
    for pno,pt in enumerate(page_texts,1):
        for lineno,raw in enumerate(pt.splitlines(),1):
            line=raw.rstrip()
            if not line.strip(): continue
            compact=canon(z2h(line))
            # account section header: '三鷹市...会計(の)?予算' (not 補正)
            m=re.search(r'(?:三鷹市(?:の)?|令和\d+年度三鷹市(?:の)?)?([^\s（(【・]*?会計)の?予算(?:は、次に|。|$)',compact)
            if not m:
                m=re.search(r'([^\s（(【・]*?会計)予算$',compact)
            if m and '補正' not in compact and '各会計' not in compact and len(m.group(1))>3:
                a=re.sub(r'^.*?年度','',m.group(1))
                a=re.sub(r'^三鷹市','',a)
                if a not in [s for s,_ in secs] and len(secs)<12:
                    secs.append((a,None)); acc=a; sec_i=len(secs)-1
                    cur_dir=None; ctx=None
            d=re.search(r'(令和|平成)([０-９0-9元]+)年([０-９0-9]+)月([０-９0-9]+)日提出',compact)
            if d: sub_dates.append((pno,compact))
            # ordinance total: 歳入歳出予算の総額は、歳入歳出それぞれ N 千円と定める
            if '歳入歳出予算の総額は' in compact or '歳入歳出予算の総額に' in compact:
                mm=AMTS.search(compact.split('それぞれ')[-1])
                if mm:
                    rows.append({'type':'ordinance_total','direction':None,'page':pno,'line':lineno,
                                 'printed_text':line.strip(),'amounts':[int_amt(mm.group(0))],
                                 'account':acc,'sec_i':sec_i})
            if '歳入歳出予算' in compact and ('第１表' in compact or '表' in compact[:6]): ctx='budget_table'
            elif '債務負担行為' in compact and '補正' not in compact: ctx='debt'
            elif '地方債' in compact and '補正' not in compact: ctx='bond'
            elif '繰越明許費' in compact: ctx='carryover'
            elif '明細書' in compact or '予算説明' in compact: ctx='detail'
            elif re.search(r'^第.{1,3}表',compact):
                if ctx is None: ctx='budget_table'
            if ctx=='budget_table':
                if re.match(r'^\s*[（(]?\s*歳\s*出\s*[)）]?',line): cur_dir='exp'
                if re.match(r'^\s*[（(]?\s*歳\s*入\s*[)）]?',line): cur_dir='rev'
                if '款（歳入）' in compact: cur_dir='rev'
                if '款（歳出）' in compact: cur_dir='exp'
                mt=re.match(r'^\s*歳\s*([入出])\s*合\s*計',line)
                if mt:
                    rows.append({'type':'total','direction':'rev' if mt.group(1)=='入' else 'exp',
                                 'page':pno,'line':lineno,'printed_text':line.strip(),
                                 'amounts':[int_amt(a) for a in AMTS.findall(line)],
                                 'account':acc,'sec_i':sec_i})
                    continue
                mk=re.match(r'^(\s*)([0-9０-９]+)[.．、]?\s*([^\d\s].*?)\s{2,}('+AMT+r')\s*$',line)
                if mk and cur_dir:
                    indent=len(mk.group(1))
                    typ='kou' if indent>8 else 'kan'
                    rows.append({'type':typ,'direction':cur_dir,'page':pno,'line':lineno,
                                 'indent':indent,'ordinal':z2h(mk.group(2)),'name':clean_name(mk.group(3)),
                                 'amounts':[int_amt(mk.group(4))],'printed_text':line.strip(),
                                 'account':acc,'sec_i':sec_i})
                    continue
            elif ctx in ('debt','bond','carryover'):
                amts=AMTS.findall(line)
                if amts and not re.match(r'^\s*(事項|期間|款|項)',line):
                    rows.append({'type':ctx+'_row','direction':None,'page':pno,'line':lineno,
                                 'printed_text':line.strip(),
                                 'amounts':[int_amt(a) for a in amts],'account':acc,'sec_i':sec_i})
    return {'sections':[{'account':a,'amendment':b} for a,b in secs],
            'submitted_dates':sub_dates,'rows':rows}

def controls(res):
    out=[]; groups={}
    for r in res['rows']:
        if r['type']=='kan' and r.get('direction'):
            groups.setdefault((r['sec_i'],r['account'],r['direction']),[]).append(r)
    for (si,a,d),kans in groups.items():
        tots=[r for r in res['rows'] if r['type']=='total' and r['direction']==d and r['sec_i']==si]
        ords=[r for r in res['rows'] if r['type']=='ordinance_total' and r['sec_i']==si]
        c={'sec_i':si,'account':a,'direction':d,'kan_sum':sum(r['amounts'][0] for r in kans)}
        if tots and tots[0]['amounts']:
            c['printed_total']=tots[0]['amounts'][0]
            c['pass']=c['kan_sum']==c['printed_total']
        elif ords and ords[0]['amounts']:
            c['printed_total']=ords[0]['amounts'][0]
            c['pass']=c['kan_sum']==c['printed_total']
            c['via']='ordinance_total'
        else:
            c['printed_total']=None; c['pass']=None
        out.append(c)
    return out

if __name__=='__main__':
    inv=json.load(open('inventory.json'))
    os.makedirs('transcribed',exist_ok=True)
    for x in inv:
        res=parse('../objects/'+x['sha256'])
        res.update({'sha256':x['sha256'],'fiscal_year':x['fiscal_year'],
                    'document_title':x['document_title'],'download_url':x['download_url']})
        res['controls']=controls(res)
        json.dump(res,open('transcribed/'+x['sha256'][:12]+'.json','w'),ensure_ascii=False,indent=1)
        fails=[c for c in res['controls'] if c['pass'] is False]
        print(x['fiscal_year'],x['sha256'][:10],'secs',len(res['sections']),'rows',len(res['rows']),
              'ctrls',len(res['controls']),'fail',len(fails))
