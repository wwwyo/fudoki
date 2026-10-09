"""akishima_settlement2019 — native supported provider for the FY2019 settlement.

Nine intact split originals (config.json pins sha256+bytes). Extraction is
native pdftotext -bbox-layout on the immutable bytes, then the cell decoder produces
typed row sets: financial (moku×printed-setsu), hierarchy_controls,
bikou_remarks (independent, nonadditive), revenue (no canonical phase), and a
page inventory. Phase identity: executed applies ONLY to printed 支出済額 /
収入済額 cells; recognition metadata is NULL/unconfirmed.
"""
from __future__ import annotations
import json, hashlib, subprocess, tempfile
from pathlib import Path
from . import decoder

CONFIG = Path(__file__).with_name('config.json')

def load_config():
    cfg = json.loads(CONFIG.read_text())
    return cfg

def verify_originals(originals_dir):
    cfg = load_config(); out = []
    for e in cfg['originals']:
        f = Path(originals_dir)/e['file']
        b = f.read_bytes()
        sha = hashlib.sha256(b).hexdigest()
        assert sha == e['sha256'], f"{f}: sha {sha} != {e['sha256']}"
        assert len(b) == e['bytes']
        out.append({'file': e['file'], 'sha256': sha, 'bytes': len(b), 'role': e['role'], 'account': e['account']})
    return out

def extract_xml(pdf_bytes):
    with tempfile.TemporaryDirectory() as td:
        src = Path(td)/'o.pdf'; src.write_bytes(pdf_bytes)
        dst = Path(td)/'o.xml'
        subprocess.run(['pdftotext','-bbox-layout','-q',str(src),str(dst)],check=True)
        return dst.read_bytes()

FILES_ROLE = {e['file']: e for e in load_config()['originals']}
FILE_KEY = {'R01kessannsyohyousi.pdf':'hyousi','R01kessannsyosainyuu.pdf':'sainyuu',
 'R01kessannsyosaisyutu1.pdf':'saisyutu1','R01kessannsyosaisyutu2.pdf':'saisyutu2',
 'R01kessannsyokokuho.pdf':'kokuho','R01kessannsyokaigo.pdf':'kaigo',
 'R01kessannsyokouki.pdf':'kouki','R01kessannsyokukaku.pdf':'kukaku',
 'R01kessannsyogesui.pdf':'gesui'}

def produce(originals_dir):
    """Decode all nine originals -> {table_name: [row, ...]}."""
    out = {k: [] for k in ('raw_financial','raw_controls','raw_projects','raw_revenue','raw_pages')}
    for e in load_config()['originals']:
        b = (Path(originals_dir)/e['file']).read_bytes()
        sha = hashlib.sha256(b).hexdigest()
        key = FILE_KEY[e['file']]
        slug = decoder.ACCOUNT[key][0]
        ctx = {'kan':[None,None],'kou':[None,None],'moku':[None,None]}
        for i,(w,h,words) in enumerate(decoder.pages(extract_xml(b)),1):
            role = decoder.header_role(words)
            out['raw_pages'].append(dict(
                jurisdiction='132071', fiscal_year=2019, source_file=key, account=slug,
                physical_page=i, width=w, height=h, role=role,
                printed_page_labels=decoder.footers(words), word_count=len(words),
                origin_file=e['file'], origin_sha256=sha))
            if role=='expenditure-detail' and w>1000:
                fin,ctl,prj = decoder.decode_leaf(words,i,key,slug,sha,ctx)
                for r in fin+ctl+prj:
                    r.update(jurisdiction='132071',fiscal_year=2019,physical_page=i,
                             source_file=key,origin_file=e['file'],origin_sha256=sha)
                out['raw_financial']+=fin;out['raw_controls']+=ctl;out['raw_projects']+=prj
            elif role in ('summary-expenditure','summary-revenue') and w>1000:
                for row in decoder.rows_of(words):
                    left=sorted([w for w in row if decoder.LEFT_REGION[0]<=w[0]<decoder.LEFT_REGION[1] and not (decoder.MONEY.fullmatch(w[4]) and not decoder.NUM.fullmatch(w[4]))],key=lambda w:w[0])
                    digits=[w for w in left if decoder.NUM.fullmatch(w[4])]
                    names=[w[4] for w in left if not decoder.NUM.fullmatch(w[4])]
                    if not digits:continue
                    cells=[dict(text=w[4],x0=round(w[0],4),y=round(w[1],4)) for w in row if decoder.MONEY.fullmatch(w[4])]
                    out['raw_controls'].append(dict(
                        jurisdiction='132071',fiscal_year=2019,account=slug,
                        grain='summary_'+('expenditure' if role=='summary-expenditure' else 'revenue'),
                        kan_code=None,kan_name=None,kou_code=None,kou_name=None,moku_code=None,moku_name=None,
                        row_code=digits[0][4],row_name=''.join(names),
                        budget_initial=None,budget_supplementary=None,carry=None,reserve_transfer=None,
                        budget_current=None,executed=None,carry_next_continuing=None,carry_next_authorized=None,
                        carry_next_accident=None,unspent=None,exec_ratio=None,
                        row_words_json=json.dumps([[round(w[0],4),round(w[1],4),round(w[2],4),round(w[3],4),w[4]] for w in row],ensure_ascii=False),
                        money_cells_json=json.dumps(cells,ensure_ascii=False),
                        physical_page=i,source_file=key,origin_file=e['file'],origin_sha256=sha))
            elif role=='revenue-detail' and w>1000:
                rows = decode_revenue_leaf(words,ctx)
                for r in rows:
                    r.update(jurisdiction='132071',fiscal_year=2019,account=slug,
                             physical_page=i,source_file=key,origin_file=e['file'],origin_sha256=sha)
                out['raw_revenue']+=rows
    return out

REV_COLS={'budget_initial':(120,268),'budget_supplementary':(268,340),'carry':(340,352),
 'budget_current':(352,421),'kubun_amount':(479,560),
 'assessed':(640,740),'executed':(740,830),
 'bad_debt':(830,910),'uncollected':(910,1000),'ratio':(1000,1040)}
REV_SETSU=(400,545)

def decode_revenue_leaf(words,ctx):
    rows=[];pending=None
    for row in decoder.rows_of(words):
        row_kind='other'
        left=sorted([w for w in row if decoder.LEFT_REGION[0]<=w[0]<decoder.LEFT_REGION[1] and not (decoder.MONEY.fullmatch(w[4]) and not decoder.NUM.fullmatch(w[4]))],key=lambda w:w[0])
        setsu=decoder.take(row,*REV_SETSU)
        had_digits=False
        if left:
            digits=sorted([w for w in left if decoder.NUM.fullmatch(w[4])],key=lambda w:w[0])
            had_digits=bool(digits)
            names=[w[4] for w in left if not decoder.NUM.fullmatch(w[4])]
            name=''.join(names) if names else None
            name_x=min((w[0] for w in left if not decoder.NUM.fullmatch(w[4])),default=999)
            money={k:decoder.amount_in(row,*v) for k,v in REV_COLS.items()}
            # revenue leaves print kan/kou/moku code columns at x<44/x<68/x>=68
            levels=[('kan' if w[0]<44 else 'kou' if w[0]<68 else 'moku', w[4])
                    for w in digits]
            if levels and name:
                # name belongs to the deepest printed level only; shallower
                # codes keep their context names (combined continuation headers)
                ORDER=['kan','kou','moku']
                lv=dict(levels);deep=levels[-1][0];di=ORDER.index(deep)
                for lvl in ORDER[:di]:
                    if lvl in lv and ctx[lvl][0]!=lv[lvl]:ctx[lvl]=[lv[lvl],None]
                for lvl in ORDER[di+1:]:ctx[lvl]=[None,None]
                ctx[deep]=[lv[deep],name];ctx['last_level']=deep;row_kind='hdr'
                money['kubun_amount']=None  # 区分金額 belongs to the setsu grain only
                rec=dict(grain=deep,row_code=levels[-1][1],row_name=name,
                    kan_code=ctx['kan'][0],kan_name=ctx['kan'][1],kou_code=ctx['kou'][0],kou_name=ctx['kou'][1],
                    moku_code=ctx['moku'][0],moku_name=ctx['moku'][1],
                    printed_setsu_code=None,printed_setsu_name=None,**money)
                rows.append(rec);pending=rec;ctx['last_hdr_ref']=rec
            elif name and ctx.get('row_kind') in ('hdr','name_cont'):
                lvl=ctx.get('last_level')
                ref=(pending if pending is not None and pending.get('row_name') is not None
                     else ctx.get('last_hdr_ref'))
                if (ref is not None and ref.get('grain')==lvl
                        and lvl in ('kan','kou','moku') and ctx[lvl][0]==ref['row_code']):
                    ref['row_name']=(ref.get('row_name') or '')+name
                    ctx[lvl][1]=ref['row_name']
                    ref[lvl+'_name']=ctx[lvl][1]
                elif lvl in ('kan','kou','moku'):
                    ctx[lvl][1]+=name
                if pending is not None and pending.get('printed_setsu_name') is not None and lvl in ('kan','kou','moku'):
                    pending[lvl+'_name']=ctx[lvl][1]
                row_kind='name_cont'
        s=[w for w in setsu if w[0]<490]
        ctx['row_kind']=row_kind
        if s:
            code_w=[w for w in s if decoder.NUM.fullmatch(w[4]) and w[0]<442]
            name_w=[w for w in s if not decoder.NUM.fullmatch(w[4])]
            money={k:decoder.amount_in(row,*v) for k,v in REV_COLS.items()}
            if not name_w:
                continue  # bare '0' cells on header rows are not setsu rows
            if not code_w and pending is not None and pending.get('printed_setsu_name') is not None:
                pending['printed_setsu_name']+=''.join(w[4] for w in name_w);continue
            rec=dict(grain='setsu',row_code=None,row_name=None,
                kan_code=ctx['kan'][0],kan_name=ctx['kan'][1],kou_code=ctx['kou'][0],kou_name=ctx['kou'][1],
                moku_code=ctx['moku'][0],moku_name=ctx['moku'][1],
                printed_setsu_code=code_w[0][4] if code_w else None,
                printed_setsu_name=''.join(w[4] for w in name_w),**money)
            rows.append(rec);pending=rec
    return rows

def restore_evidence(originals_dir, evidence_dir):
    """Copy the nine immutable originals into an evidence dir (normal-route analogue)."""
    import shutil
    plan=[]
    for e in load_config()['originals']:
        src=Path(originals_dir)/e['file']
        dst=Path(evidence_dir)/e['file']; dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists():
            assert hashlib.sha256(dst.read_bytes()).hexdigest()==e['sha256']
        else:
            shutil.copyfile(src,dst)
        plan.append({'file':e['file'],'sha256':e['sha256'],'bytes':e['bytes'],'dest':str(dst)})
    return plan
