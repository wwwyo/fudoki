"""FY2019 (R1) Akishima settlement book native-cell decoder — typed candidates.

Each A3-landscape detail leaf (width 1191pt) is self-contained: left table
科目/款項目 rows and 節 rows with budget columns; shared right money columns
支出済額/翌年度繰越額(継続費逓次繰越・繰越明許費・事故繰越)/不用額/執行率;
far-right 事業備考 items. Preservation only — no legal-setsu judgement.
"""
from __future__ import annotations
import re, json, html, hashlib
from collections import defaultdict

def js(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'))
MONEY = re.compile(r'^(?:△|-)?[\d,]+$')
NUM = re.compile(r'^\d+$')

def pages(raw):
    result=[]
    for part in raw.decode('utf-8').split('<page ')[1:]:
        width=float(re.search(r'width="([\d.]+)',part).group(1))
        height=float(re.search(r'height="([\d.]+)',part).group(1))
        words=[]
        for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)"[^>]*>(.*?)</word>',part):
            words.append([float(m[i]) for i in range(1,5)]+[html.unescape(m[5])])
        result.append((width,height,words))
    return result

def rows_of(words,y0=140,y1=790,tol=2.0):
    ws=sorted(words,key=lambda w:(w[1],w[0]))
    out=[]
    for w in ws:
        if not y0<w[1]<y1:continue
        if not out or w[1]-out[-1][0][1]>tol:out.append([])
        out[-1].append(w)
    return out

def nums(row,x0,x1):
    return [w for w in row if MONEY.fullmatch(w[4]) and w[0]>=x0 and w[2]<=x1]

def n(words):
    return int(words[0][4].replace(',','').replace('△','-'))

def take(row,x0,x1):
    return [w for w in row if w[0]>=x0 and w[2]<=x1]

def amount_in(row,x0,x1):
    c=[w for w in row if MONEY.fullmatch(w[4]) and x0<=(w[0]+w[2])/2<x1]
    return n(c[:1]) if c else None

# Column x-bounds measured from the printed header words.
COLS={'budget_initial':(120,185),'budget_supplementary':(185,245),'carry':(245,300),
      'reserve_transfer':(300,350),'budget_current':(350,420),
      'kubun_amount':(490,545),           # 節 rows: 区分金額 under 節科目
      'executed':(640,715),'carry_next_continuing':(715,765),'carry_next_authorized':(765,830),
      'carry_next_accident':(830,885),'unspent':(885,960),'exec_ratio':(960,985),
      'bikou_no':(985,1005),'bikou_name':(1000,1013),'bikou_amount':(1090,1195),
      'bikou_setsu_name':(1013,1023),'bikou_item_name':(1023,1090)}
LEFT_REGION=(20,127)   # kan/kou/moku code+name
SETSU_REGION=(425,545) # 節 code+name+区分金額

ACCOUNT={'hyousi':('general','一般会計'),'sainyuu':('general','一般会計'),
 'saisyutu1':('general','一般会計'),'saisyutu2':('general','一般会計'),
 'kokuho':('kokuho','国民健康保険特別会計'),'kaigo':('kaigo','介護保険特別会計'),
 'kouki':('kouki','後期高齢者医療特別会計'),'kukaku':('kukaku','中神土地区画整理事業特別会計'),
 'gesui':('gesui','下水道事業特別会計')}

def header_role(words):
    t=' '.join(w[4] for w in sorted(words,key=lambda w:w[1])[:40])
    if 'との比較' in t or '決算書' in t:
        if '支出済額' in t:return 'summary-expenditure'
        if '収入済額' in t or '収 入 済 額' in t:return 'summary-revenue'
        return 'summary'
    if '支出済額' in t:return 'expenditure-detail'
    if '収入済額' in t or '収 入 済 額' in t:return 'revenue-detail'
    if '節　明　細' in t or '節明細' in t:return 'setsu-detail'
    if '明細書（歳出' in t:return 'divider-expenditure'
    if '明細書（歳入' in t:return 'divider-revenue'
    if '決　算　書' in t or '決算書' in t:return 'summary'
    if '目　次' in t or '目次' in t:return 'toc'
    if '明細書' in t:return 'detail-other'
    return 'other'

def footers(words):
    return [w[4] for w in sorted(words,key=lambda w:(w[0])) if w[1]>785 and NUM.fullmatch(w[4])]

def decode_leaf(words,page_no,file_no,account_slug,sha,ctx):
    """One expenditure-detail leaf -> fin setsu rows, ctl hier totals, prj bikou."""
    fin=[];ctl=[];prj=[]
    pending_fin=None;pending_ctl=None
    bikou_open=ctx.get('bikou_open')

    def _bikou(row):
        nonlocal bikou_open
        bo=take(row,*COLS['bikou_no'])
        ba=amount_in(row,*COLS['bikou_amount'])
        bs=[w for w in row if 1013<=w[0]<1023 and not MONEY.fullmatch(w[4])]
        bi=[w for w in row if 1023<=w[0]<1090 and not MONEY.fullmatch(w[4])]
        name_words=[w[4] for w in row if 1000<=w[0]<1013 and not MONEY.fullmatch(w[4]) and not NUM.fullmatch(w[4])]
        if bo and NUM.fullmatch(bo[0][4]):
            all_name=[w[4] for w in row if not MONEY.fullmatch(w[4]) and not NUM.fullmatch(w[4]) and w[0]>=1000]
            bikou_open=dict(account=account_slug,printed_bikou_no=bo[0][4],
                kan_code=ctx['kan'][0],kou_code=ctx['kou'][0],moku_code=ctx['moku'][0],
                kan_name=ctx['kan'][1],kou_name=ctx['kou'][1],moku_name=ctx['moku'][1],
                name=''.join(all_name),amount=ba,lines=[],
                row_words_json=js([[round(w[0],4),round(w[1],4),round(w[2],4),round(w[3],4),w[4]] for w in row]))
            prj.append(bikou_open);ctx['bikou_open']=bikou_open;return
        if bikou_open is not None:
            sn=''.join(w[4] for w in bs);it=''.join(w[4] for w in bi)
            if name_words and not sn and not it:
                # header-name continuation, possibly carrying the item amount
                bikou_open['name']+=''.join(name_words)
                if ba is not None and bikou_open['amount'] is None:bikou_open['amount']=ba
                return
            if ba is not None and not sn and not it and bikou_open['amount'] is None and not bikou_open['lines']:
                bikou_open['amount']=ba;return
            if sn or it or ba is not None:
                bikou_open['lines'].append(dict(setsu_name=sn,item_name=it,
                    name=''.join(name_words),amount=ba))

    for row in rows_of(words):
        row_kind='other'
        left=sorted([w for w in row if LEFT_REGION[0]<=w[0]<LEFT_REGION[1] and not (MONEY.fullmatch(w[4]) and not NUM.fullmatch(w[4]))],key=lambda w:w[0])
        setsu=take(row,*SETSU_REGION)
        had_digits=False
        if left:
            digits=sorted([w for w in left if NUM.fullmatch(w[4])],key=lambda w:w[0])
            had_digits=bool(digits)
            names=[w[4] for w in left if not NUM.fullmatch(w[4])]
            name=''.join(names) if names else None
            name_x=min((w[0] for w in left if not NUM.fullmatch(w[4])),default=999)
            money={k:amount_in(row,*v) for k,v in COLS.items() if k in
                   ('budget_initial','budget_supplementary','carry','reserve_transfer','budget_current',
                    'executed','carry_next_continuing','carry_next_authorized','carry_next_accident','unspent','exec_ratio')}
            # each digit's level is fixed by its printed column position:
            # kan x<44, kou x<58, moku x>=58 on expenditure leaves
            levels=[('kan' if w[0]<44 else 'kou' if w[0]<58 else 'moku', w[4])
                    for w in digits]
            # control rows carry budget-column cells; a combined header+setsu
            # row carries only setsu amounts (x>=490) so it emits no ctl
            has_money=any(money[k] is not None for k in
                          ('budget_initial','budget_supplementary','carry','reserve_transfer','budget_current'))
            if levels and name:
                ORDER=['kan','kou','moku']
                # a combined header row carries the name only at the deepest
                # printed level; shallower codes keep their context names
                lv=dict(levels)
                deep=levels[-1][0];di=ORDER.index(deep)
                for lvl in ORDER[:di]:
                    if lvl in lv and ctx[lvl][0]!=lv[lvl]:ctx[lvl]=[lv[lvl],None]
                for lvl in ORDER[di+1:]:ctx[lvl]=[None,None]
                ctx[deep]=[lv[deep],name]
                ctx['last_level']=deep
                row_kind='hdr'
                if has_money:
                    level=levels[-1][0]
                    rec=dict(account=account_slug,grain=level,
                             kan_code=ctx['kan'][0],kan_name=ctx['kan'][1],
                             kou_code=ctx['kou'][0],kou_name=ctx['kou'][1],
                             moku_code=ctx['moku'][0],moku_name=ctx['moku'][1],
                             row_code=levels[-1][1],row_name=name,
                             row_words_json=js([[round(w[0],4),round(w[1],4),round(w[2],4),round(w[3],4),w[4]] for w in row]),
                             **money)
                    ctl.append(rec);pending_ctl=rec
                    ctx['last_hdr_ref']=rec
                else:ctx['last_hdr_ref']=None
                pending_fin=None
            elif name and ctx.get('row_kind') in ('hdr','name_cont'):
                # wrapped name: continuation belongs to the most recent header
                # level; repair its control record only when it is the same row
                lvl=ctx.get('last_level')
                ref=pending_ctl or ctx.get('last_hdr_ref')
                if ref is not None and ref['grain']==lvl and ctx[lvl][0]==ref['row_code']:
                    ref['row_name']+=name
                    ctx[lvl][1]=ref['row_name']
                    ref[lvl+'_name']=ctx[lvl][1]
                elif lvl in ('kan','kou','moku'):
                    ctx[lvl][1]+=name
                if pending_fin is not None and lvl in ('kan','kou','moku'):
                    pending_fin[lvl+'_name']=ctx[lvl][1]
                row_kind='name_cont'
        s=sorted(setsu,key=lambda w:w[0])
        ctx['row_kind']=row_kind if row_kind!='other' or (left or s) else 'other'
        if s:
            code_w=[w for w in s if NUM.fullmatch(w[4]) and w[0]<442]
            name_w=[w for w in s if not NUM.fullmatch(w[4]) and w[0]<490]
            if not code_w and pending_fin is not None:
                pending_fin['printed_setsu_name']+=''.join(w[4] for w in name_w)
            else:
                amount=amount_in(row,*COLS['kubun_amount'])
                right={k:amount_in(row,*v) for k,v in COLS.items() if k in
                       ('executed','carry_next_continuing','carry_next_authorized','carry_next_accident','unspent','exec_ratio')}
                no=take(row,*COLS['bikou_no'])
                rec=dict(account=account_slug,
                         kan_code=ctx['kan'][0],kan_name=ctx['kan'][1],
                         kou_code=ctx['kou'][0],kou_name=ctx['kou'][1],
                         moku_code=ctx['moku'][0],moku_name=ctx['moku'][1],
                         printed_setsu_code=code_w[0][4] if code_w else None,
                         printed_setsu_name=''.join(w[4] for w in name_w),
                         kubun_amount=amount,bikou_no=no[0][4] if no else None,
                         row_words_json=js([[round(w[0],4),round(w[1],4),round(w[2],4),round(w[3],4),w[4]] for w in row]),
                         **right)
                fin.append(rec);pending_fin=rec;pending_ctl=None
        _bikou(row)

    ctx['bikou_open']=bikou_open
    return fin,ctl,prj
