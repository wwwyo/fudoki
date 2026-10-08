"""v2 extractor: Komae FY2020 (R2) general-account supplementary budget no.1.

Token-lane parse of pdftotext -layout output (per-token x positions):
  revenue p7:   moku lane x<54 | setsu lane x~54-101 | 説明 lane x>=102
  exp.  p8-12:  moku lane x<54 | 財源 lane x54-113 (col-mapped natl/metro/bond/
                other/general) | setsu lane x114-142 | 説明 lane x>=143
Setsu attach to the moku block printed on the same page block; wrapped set su
labels (continuation lines without a new N. marker) extend the open setsu.
説明 lane and all remaining lines are kept as raw context; no linkage invented.
Controls: daihyou kou→kan→合計, sokkatsu, before+delta=total, moku delta sums
equal printed 計, setsu delta sums equal the moku delta of their block.
"""


def main():
    import re, json
    from pathlib import Path

    HERE = Path(__file__).resolve().parent
    import os
    EVID = Path(os.environ.get('EVID_DIR', HERE.parent/'evidence'))

    def n(s): return int(s.replace(',',''))
    def digits(s): return s.translate(str.maketrans('０１２３４５６７８９','0123456789'))
    def toks(l):
        return [(m.start(), digits(m.group())) for m in re.finditer(r'\S+', l)]
    def tailnums(s, cnt):
        v = re.findall(r'([\d,]+|△[\d,]+)(?=\s|$)', s)
        return [n(x.lstrip('△')) for x in v[-cnt:]] if len(v) >= cnt else None
    def label_of(s):
        s = digits(s.strip())
        s = re.sub(r'^[０-９\d]+[.．]', '', s)
        s = re.sub(r'(\s+[\d,]+)+\s*$', '', s)
        return re.sub(r'\s+', '', s)

    rows = []; seq = 0
    def add(**kw):
        global seq; seq += 1
        kw['source_row'] = seq
        rows.append(kw)

    # ---- page 4 第一表 ----
    direction=None; kan=None
    for l in (EVID/'page-4.txt').open(errors='replace').read().split('\n'):
        z=l.strip()
        vals=tailnums(digits(z),3)
        if '合' in z and vals:
            # printed 歳入合計/歳出合計 row of the 第一表
            dd='revenue' if '入' in z else 'expenditure'
            b,d0,tt=vals
            add(kind='control-total',direction=dd,before=b,delta=d0,total=tt,physical_page=4,raw_text=z); continue
        if z.startswith('歳') and '入' in z: direction='revenue'; continue
        if z.startswith('歳') and '出' in z: direction='expenditure'; continue
        if not direction or not z: continue
        if not vals: continue
        b,d,tt=vals
        if '合' in z:
            add(kind='control-total',direction=direction,before=b,delta=d,total=tt,physical_page=4,raw_text=z); continue
        km=re.match(r'^([１-９\d]+)[.．]',digits(z))
        if not km: continue
        if len(l)-len(l.lstrip())<20:
            kan=digits(km.group(1))
            add(kind='daihyou-kan',direction=direction,kan_code=kan,kan_label=label_of(z),before=b,delta=d,total=tt,physical_page=4,raw_text=z)
        else:
            add(kind='daihyou-kou',direction=direction,kan_code=kan,kou_code=digits(km.group(1)),kou_label=label_of(z),before=b,delta=d,total=tt,physical_page=4,raw_text=z)

    # ---- page 6 総括 ----
    direction=None
    for l in (EVID/'page-6.txt').open(errors='replace').read().split('\n'):
        z=l.strip(); w=z.replace(' ','')
        if w.startswith('（歳入'): direction='revenue'; continue
        if w.startswith('（歳出'): direction='expenditure'; continue
        if not direction or not z: continue
        km=re.match(r'^([１-９\d]+)[.．]',digits(z))
        cnt=3 if direction=='revenue' else 8
        if km:
            vals=tailnums(digits(z),cnt)
            if not vals: continue
            add(kind='sokkatsu-kan',direction=direction,kan_code=digits(km.group(1)),kan_label=label_of(z),
                before=vals[0],delta=vals[1],total=vals[2],
                natl=vals[3] if len(vals)>3 else None,metro=vals[4] if len(vals)>4 else None,
                bond=vals[5] if len(vals)>5 else None,other=vals[6] if len(vals)>6 else None,
                general=vals[7] if len(vals)>7 else None,physical_page=6,raw_text=z)
        elif w.startswith('歳出合計') or w.startswith('歳入合計'):
            vals=tailnums(digits(z),cnt)
            if vals:
                add(kind='sokkatsu-total',direction=direction,before=vals[0],delta=vals[1],total=vals[2],
                    natl=vals[3] if len(vals)>3 else None,metro=vals[4] if len(vals)>4 else None,
                    bond=vals[5] if len(vals)>5 else None,other=vals[6] if len(vals)>6 else None,
                    general=vals[7] if len(vals)>7 else None,physical_page=6,raw_text=z)

    # ---- detail pages: token lanes ----
    LANES={'revenue':(60,102),'expenditure':(96,142)}
    LABEL_MAX={'revenue':96,'expenditure':125}
    ZKEYS=['natl','metro','bond','other','general']
    def funding_centers(text):
        # five funding column centers = 4th..8th 千円 tokens on the line that carries
        # the column-marker row (max 千円 count)
        best=None
        for l in text.split('\n'):
            xs=[m.start() for m in re.finditer(r'千円',l)]
            if len(xs)>=8 and (best is None or len(xs)>len(best)):
                best=xs
        return best[3:8] if best else []
    def assign_zaigen(row,Z,cen):
        for x,tt in Z:
            if not re.fullmatch(r'[\d,]+',tt):continue
            i=min(range(5),key=lambda j:abs(cen[j]-(x+len(tt))))
            if abs(cen[i]-(x+len(tt)))<=6:row[ZKEYS[i]]=n(tt)

    state={};CEN={}
    def parse_detail(pg,direction):
        slo,shi=LANES[direction]
        cen=CEN.get(pg)
        kan=state.get('kan');kou=state.get('kou');cur=state.get('cur');open_setsu=state.get('open_setsu')
        def flush_zaigen(zdict):
            if cur is not None:
                for k,v in zdict.items():
                    cur.setdefault(k,v)
        moku_next=-1
        for li,l in enumerate((EVID/f'page-{pg}.txt').open(errors='replace').read().split('\n')):
            ts=toks(l)
            L=[t for t in ts if t[0]<54]
            Z=[t for t in ts if 47<=t[0]<114]
            S=[t for t in ts if slo<=t[0]<shi]
            mk_i=next((i for i,(x,tt) in enumerate(S) if re.fullmatch(r'\d+\.',tt)),None)
            if mk_i is not None: S=S[mk_i:]  # drop leading zaigen numbers left of the setsu marker
            E=[t for t in ts if t[0]>=shi]
            ltxt=''.join(t for _,t in L);lsp=' '.join(t for _,t in L)
            # headers (half or full width parens)
            mk=re.search(r'[（\(]款[）\)]\s*(\d+)[.．]\s*(\S.*?)(?:[（\(]項[）\)]\s*(\d+)[.．]\s*(.+))?$',digits(ltxt))
            if mk:
                nkan=(mk.group(1),re.sub(r'\s+','',mk.group(2)))
                nkou=(mk.group(3),re.sub(r'\s+','',mk.group(4))) if mk.group(3) else kou
                if not(cur is not None and kan==nkan and kou==nkou):
                    cur=None;open_setsu=None
                kan,kou=nkan,nkou
                if S or E: add(kind='context',direction=direction,kan_code=kan[0],kou_code=kou[0] if kou else None,physical_page=pg,raw_text=' '.join(t for _,t in S+E))
                continue
            mk2=re.search(r'[（\(]項[）\)]\s*(\d+)[.．]\s*(.+)',ltxt)
            if mk2: kou=(mk2.group(1),re.sub(r'\s+','',mk2.group(2)))
            # moku row
            mkm=re.match(r'^(\d+)[.．]',digits(ltxt))
            nums=[tt for _,tt in ts if re.fullmatch(r'[\d,]+',tt) and (',' in tt or tt=='0')]
            vals=[n(x) for x in nums[:3]] if len(nums)>=3 else None
            if mkm and vals:
                d0={'kind':'moku','direction':direction,'kan_code':kan[0] if kan else None,
                    'kou_code':kou[0] if kou else None,'moku_code':mkm.group(1),
                    'moku_label':label_of(lsp),'before':vals[0],'delta':vals[1],'total':vals[2],
                    'natl':None,'metro':None,'bond':None,'other':None,'general':None,
                    'physical_page':pg,'raw_text':lsp}
                d0['block_id']=f'{pg}:{seq+1}'
                if direction=='expenditure' and cen: assign_zaigen(d0,Z,cen)
                add(**d0);cur=rows[-1];open_setsu=None;moku_next=li+1
                # setsu/explanation on the same line as the moku row belong to it
                continue_after=True
            elif '計' in ltxt and vals:
                r={'kind':'kou-total','direction':direction,'kan_code':kan[0] if kan else None,
                   'kou_code':kou[0] if kou else None,'before':vals[0],'delta':vals[1],'total':vals[2],
                   'natl':None,'metro':None,'bond':None,'other':None,'general':None,
                   'physical_page':pg,'raw_text':lsp}
                if direction=='expenditure' and cen: assign_zaigen(r,Z,cen)
                add(**r);cur=None;open_setsu=None
                if S or E: add(kind='context',direction=direction,kan_code=kan[0] if kan else None,physical_page=pg,raw_text=' '.join(t for _,t in S+E))
                continue
            else:
                # non-anchor left text: printed moku label wraps to the line right
                # after the moku row only; column headers repeat further down
                if ltxt and not re.fullmatch(r'[\s\d,\.\-（）\(\)款項節区分金額説明計千円補正前の額目特定財源内訳の国支出都地方債そ一般金]*',ltxt):
                    if cur is not None and cur.get('kind')=='moku' and li==moku_next and re.fullmatch(r'[^\d]*',ltxt):
                        cur['moku_label']+=re.sub(r'\s+','',ltxt)
                elif ltxt and re.search(r'区|分|額|説|明|節|千円|目|計|項|款',ltxt):
                    pass
                elif ltxt:
                    add(kind='context',direction=direction,physical_page=pg,raw_text=lsp)
            # setsu lane
            if S:
                st=' '.join(t for _,t in S)
                sx=S[0][0]
                sm=re.match(r'^(\d+)\.\s*(.+)',digits(st))
                if sm and cur is not None:
                    rest=sm.group(2);am=re.search(r'([\d,]+)',rest)
                    add(kind='setsu',direction=direction,kan_code=kan[0] if kan else None,
                        kou_code=kou[0] if kou else None,moku_code=cur['moku_code'],block_id=cur['block_id'],
                        setsu_code=sm.group(1),setsu_label=re.sub(r'\s+','',re.sub(r'[\d,]+.*$','',rest)),
                        delta=n(am.group(1)) if am else None,physical_page=pg,raw_text=st,setsu_x=sx)
                    open_setsu=rows[-1]
                elif cur is not None and open_setsu:
                    lbl=[t2 for x2,t2 in S if x2<LABEL_MAX[direction] and not re.fullmatch(r'[\d,]+',t2)]
                    lt=re.sub(r'\s+','',digits(' '.join(lbl)))
                    if lbl and lt and not re.fullmatch(r'[区分金額千円説明節目項款補正前の額定財源内訳計国支出都地方債そ一般]*',lt):
                        open_setsu['setsu_label']=(open_setsu.get('setsu_label') or '')+lt
                    add(kind='setsu-cont',direction=direction,kan_code=kan[0] if kan else None,
                        kou_code=kou[0] if kou else None,moku_code=cur['moku_code'],block_id=cur['block_id'],
                        physical_page=pg,raw_text=st,setsu_x=sx)
                elif st:
                    add(kind='context',direction=direction,kan_code=kan[0] if kan else None,physical_page=pg,raw_text=st)
            # explanation lane -> context (raw only)
            if E:
                add(kind='context',direction=direction,kan_code=kan[0] if kan else None,kou_code=kou[0] if kou else None,
                    moku_code=cur['moku_code'] if cur else None,physical_page=pg,raw_text=' '.join(t for _,t in E))
        state.update(kan=kan,kou=kou,cur=cur,open_setsu=open_setsu)

    parse_detail(7,'revenue')
    state.clear()
    for pg in range(8,13):
        CEN[pg]=funding_centers((EVID/f'page-{pg}.txt').open(errors='replace').read())
        parse_detail(pg,'expenditure')

    for pg in [1,2,3,5,13]:
        for l in (EVID/f'page-{pg}.txt').open(errors='replace').read().split('\n'):
            z=l.strip()
            if z: add(kind='context',direction=None,physical_page=pg,raw_text=z)

    # top-level setsu flag: within each moku block, printed setsu codes ascend;
    # sub-items restart the numbering.
    from collections import defaultdict
    blocks=defaultdict(list)
    for r in rows:
        if r['kind']=='setsu':blocks[r['block_id']].append(r)
    for bid,sl in blocks.items():
        mx=0;base_x=None
        for s in sl:
            c=int(s['setsu_code']);x=s.get('setsu_x') or 0
            if base_x is None and c>mx: base_x=x
            top=(c>mx and base_x is not None and x<=base_x+3)
            s['setsu_level']='top' if top else 'sub'
            if top:mx=c
    out1=Path(os.environ.get('PART1_OUT',HERE/'part1.json'));json.dump(rows,open(out1,'w'),ensure_ascii=False,indent=1)
    from collections import Counter
    print(Counter(r['kind'] for r in rows))


if __name__ == '__main__':
    main()
