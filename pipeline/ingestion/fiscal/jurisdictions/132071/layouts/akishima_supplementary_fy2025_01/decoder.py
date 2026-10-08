"""Akishima supplementary-budget (補正予算 概要) native decoder.

Print generations:
  A (FY2020): header 補正前の額/補正額/補正後の額; 歳入予算 / 歳出予算（目的別内訳）sections
              each with 款 rows (款|補正額) + content lines; annexes (債務負担行為/基金/市債).
  B (FY2021-25): cover + 款別集計表 ((1)歳入 (2)目的別歳出 (3)性質別歳出; columns
              款|補正前の額|構成比|補正額|計|構成比) + 補正予算の概要 (款+補正額+content lines)
              + 基金と市債の状況.
All amounts are printed cells only; blank cells stay NULL; △/▲ negatives preserved.
Delta columns are 増減 amounts; 補正前 and 計(補正後) stay separate columns.
"""
from __future__ import annotations
import re
from html.parser import HTMLParser

FULL={'０':'0','１':'1','２':'2','３':'3','４':'4','５':'5','６':'6','７':'7','８':'8','９':'9','，':',','．':'.','（':'(','）':')'}
NEG={'△','▲','−','-'}
def norm(s):return ''.join(FULL.get(c,c) for c in s)
def pnum(t):
    t=norm(t).replace(',','').replace(' ','').strip()
    return int(t) if re.fullmatch(r'-?\d+',t) else None

class W(HTMLParser):
    def __init__(self):super().__init__();self.pages=[];self.cur=None;self.in_word=False
    def handle_starttag(self,t,a):
        if t=='page':self.cur=[]
        elif t=='word' and self.cur is not None:
            d=dict(a);self.cur.append([float(d['xmin']),float(d['ymin']),float(d['xmax']),float(d['ymax']),'']);self.in_word=True
    def handle_data(self,d):
        if self.in_word:self.cur[-1][4]+=d
    def handle_endtag(self,t):
        if t=='word':self.in_word=False
        elif t=='page' and self.cur is not None:self.pages.append(self.cur);self.cur=None

def lines(words,tol=2.5):
    ws=sorted(words,key=lambda w:(w[1],w[0]));out=[]
    for w in ws:
        if out and abs(w[1]-out[-1][0][1])<=tol:out[-1].append(w)
        else:out.append([w])
    for l in out:l.sort(key=lambda w:w[0])
    return out

def ltext(l):return ''.join(w[4] for w in l)

def pcells(l):
    """Numeric cells with sign: a △/▲/− token immediately left of a number negates it."""
    out=[];sign=None
    for w in l:
        v=pnum(w[4]);t=norm(w[4]).replace(' ','')
        if v is not None:
            out.append((w[0],w[2],-v if sign else v));sign=None
        elif t in NEG:sign=True
        elif not re.fullmatch(r'[\d.,%]*',t):sign=None
        # plain dots/commas keep sign pending
    return out

def section_of(ln):
    t=norm(ltext(ln)).replace(' ','').replace(' ','')
    if t.startswith('※') or '連動' in t:return None
    if re.match(r'^\(?[0-9０-９]{1,2}\)?\s*歳入',t) or '歳入予算' in t or '歳入集計表' in t:return 'revenue',None
    if '歳出' in t and '性質別' in t:return 'expenditure','nature'
    if '歳出' in t and ('目的別' in t or '歳出予算' in t):return 'expenditure','purpose'
    if '債務負担行為' in t:return 'debt',None
    if t.startswith('基金と市債'):return 'fund',None
    # top-level numbered heading that is not a budget 款 row -> annex (fund/debt/etc.):
    # starts with an index number and carries NO money cell (kan rows always do)
    # numbered top-level heading with NO money digits after the index -> annex section
    mh=re.match(r'^\(?([0-9０-９]{1,2})\)?\s*(\D.*)$',t)
    if mh and ('歳入' not in t[:8]) and ('歳出' not in t[:8]) and not re.search(r'[0-9０-９]',mh.group(2)):
        return 'annex',None
    return None

def col_bounds(ln):
    words=[(w[4].replace(' ',''),w[0]) for w in ln]
    found={}
    summary = any(t.startswith('補正前') for t,_ in words) and any(t=='構成比' for t,_ in words)
    detail = any(t=='補正額' for t,_ in words) and any(t.startswith('説') for t,_ in words)
    if not (summary or detail):return None
    dz=None
    for t,x in words:
        if t.startswith('補正前'):found['before']=x
        elif t.startswith('補正額'):found['delta']=x;dz=x
    if detail:
        cont=[x for t,x in words if t in ('補','正','内','容','補正内容','内容') and dz and x>dz+30]
        if cont:found['content']=min(cont)
        note=[x for t,x in words if t.startswith('説')]
        if note:found['note']=min(note)
    if summary:
        aft=[x for t,x in words if t=='計' and dz and x>dz+10]
        if aft:found['after']=min(aft)
    return found

def decode_legacy(meta):
    parser=W();parser.feed(open(meta['xhtml'],encoding='utf-8').read())
    rows=[]
    section=None;cls=None;anchors={};cur_kan=None;section_seq=0
    for pi,pw in enumerate(parser.pages,1):
        ls=lines(pw)
        for ln in ls:
            t=ltext(ln);tc=t.replace(' ','');x0=ln[0][0]
            sec=section_of(ln)
            heading=bool(sec)
            if sec:
                section,cls=sec;anchors={};cur_kan=None;section_seq+=1
            cb=col_bounds(ln)
            if cb and section:anchors.update(cb);continue
            nums=pcells(ln)
            m_ap=re.search(r'令和([0-9０-９]+)年([0-9０-９]+)月([0-9０-９]+)日(専決|議決)',t)
            bbox=[min(w[0] for w in ln),min(w[1] for w in ln),max(w[2] for w in ln),max(w[3] for w in ln)]
            if m_ap:
                y2=int(norm(m_ap.group(1)))+2018
                rows.append(dict(base(meta,'printed_approval','meta',pi,ln[0][1],section_seq,bbox),
                                 approval_text=tc,approval_kind=m_ap.group(4),
                                 printed_date=f"{y2}-{int(norm(m_ap.group(2))):02d}-{int(norm(m_ap.group(3))):02d}"))
            for key in ('補正前の額','補正額','補正後の額'):
                if tc==key or (tc.startswith(key) and nums):
                    rows.append(dict(base(meta,'header_control','printed_header',pi,ln[0][1],section_seq,bbox),
                                     header=key,amount=nums[-1][2] if nums else None,unit='千円',raw_line=t));break
            if re.match(r'^歳[入出]\s*合\s*計',tc) or tc.startswith('合計'):
                vals=[c[2] for c in nums]
                rows.append(dict(base(meta,'printed_total','total',pi,ln[0][1],section_seq,bbox),
                                 annex=section in ('debt','fund','annex'),direction=section,classification=cls,total_label=tc,
                                 cells=[str(c) for c in vals],
                                 budget_before=vals[0] if len(vals)>=3 else None,
                                 amount_delta=vals[-2] if len(vals)>=3 else (vals[-1] if len(vals)==1 else None),
                                 budget_after=vals[-1] if vals else None,unit='千円',raw_line=t))
                continue
            cz=anchors.get('content');dz=anchors.get('delta');az=anchors.get('after');bz=anchors.get('before')
            # kan code is the leading numeric WORD (x<115, pure digits) -> never an amount
            code_v=None
            if re.fullmatch(r'\d{1,2}',norm(ln[0][4]).strip()) and ln[0][0]<115:
                code_v=int(norm(ln[0][4]))
            if code_v is not None and nums and nums[0][2]==code_v and nums[0][0]<115:
                nums=nums[1:]
            kan_cells=[];content_cells=[]
            for i,(x1,x2,v) in enumerate(nums):
                if cz and x1>=cz-45:content_cells.append((x1,x2,v))      # content/note zone
                elif dz and x1>=dz-45 and (az is None or x1<az-30):kan_cells.append((x1,x2,v))
                elif az and x1>=az-30:kan_cells.append((x1,x2,v))
                elif bz and x1>=bz-20 and (dz is None or x1<dz-20):kan_cells.append((x1,x2,v))
                elif not (dz or az or bz or cz):kan_cells.append((x1,x2,v))
                else:content_cells.append((x1,x2,v))
            # word-level code: first word may be '17' or merged '17都支出金'
            code=code_v and str(code_v);named=''
            w0=norm(ln[0][4]).strip()
            mw=re.match(r'^(\d{1,2})(.*)$',w0)
            if code is None and mw and ln[0][0]<115 and (mw.group(2)=='' or re.match(r'[^\d]',mw.group(2))):
                code=mw.group(1);named=mw.group(2)
            if mw and code is None:pass
            named=(named or ''.join(w[4] for w in ln[1:] if pnum(w[4]) is None and norm(w[4]).strip() not in NEG
                                    and not re.fullmatch(r'[\d.,%]*',norm(w[4]))))[:12]
            if code and x0<115 and kan_cells and not heading and section in ('revenue','expenditure') and named:
                nums=content_cells
                before=delta=after=None
                kvals=[c[2] for c in kan_cells]
                if bz and az and cz is None:
                    # summary table: positional [before,(delta,)after]; blank delta stays NULL
                    if len(kvals)>=3:before,delta,after=kvals[0],kvals[1],kvals[2]
                    elif len(kvals)==2:before,after=kvals
                    elif kvals:after=kvals[0]
                else:
                    for x1,x2,v in kan_cells:
                        if dz and abs(x1-dz)<60:delta=v
                        elif az and x1>=az-30:after=v
                        elif bz and x1<bz+45:before=v
                        else:delta=v if delta is None else delta
                    if delta is None and after is None and before is None and kvals:
                        delta=kvals[0]
                rows.append(dict(base(meta,'kan_summary','kan',pi,ln[0][1],section_seq,bbox),
                                 annex=section in ('debt','fund','annex'),direction=section,classification=cls,kan_code=code,kan_name=named,
                                 budget_before=before,amount_delta=delta,budget_after=after,
                                 unit='千円',cells=[str(c[2]) for c in kan_cells],raw_line=t))
                cur_kan=code
                nums=[c for c in content_cells]
                if not nums:continue
            if nums and section and not heading:
                nz=anchors.get('note')
                amts=[c for c in nums if nz is None or c[0]<nz-20]
                txt=''.join(w[4] for w in ln if pnum(w[4]) is None and norm(w[4]).strip() not in NEG and not re.fullmatch(r'[\d.]+%?',norm(w[4]).replace(',','')))
                note_txt=''.join(w[4] for w in ln if nz is not None and w[0]>=nz-15 and pnum(w[4]) is None)
                rows.append(dict(base(meta,'content_line','printed_item',pi,ln[0][1],section_seq,bbox),
                                 annex=section in ('debt','fund','annex'),direction=section,classification=cls,parent_kan=cur_kan,
                                 content_text=txt.strip() or None,
                                 note_text=note_txt.strip() or None,
                                 amounts=[str(c[2]) for c in nums],
                                 amount=amts[-1][2] if amts else None,unit='千円',raw_line=t))
    return rows

def base(meta,role,grain,page,y,seq,bbox=None):
    return dict(source_row_id=f"{meta['sha256']}:{meta['file']}:{role}:{page}:{y:.6f}",
                bbox_xmin=bbox[0] if bbox else None,bbox_ymin=bbox[1] if bbox else None,
                bbox_xmax=bbox[2] if bbox else None,bbox_ymax=bbox[3] if bbox else None,
                jurisdiction_id='132071',fiscal_year=meta['fiscal_year'],document_kind='supplementary',
                account_id='general',amendment_number=meta['amendment'],original_url=meta['url'],
                original_sha256=meta['sha256'],original_bytes=meta['bytes'],
                source_table_id=f"akishima-fy{meta['fiscal_year']}-supplementary-{meta['amendment']:02d}-{meta['file']}",
                source_grain=grain,role=role,physical_page=page,section_index=seq)


def decode(meta):
    """Finite FY2025 No.1 summary correction from printed row geometry.

    Row cells stay at their exact native coordinates. Name glyphs belong to the
    vertical span between adjacent printed code baselines, including two-line
    names centred above/below the amount baseline. Nature code+first-glyph words
    are split before all remaining glyphs are joined. No blank delta is zeroed.
    """
    rows=decode_legacy(meta)
    parser=W();parser.feed(open(meta['xhtml'],encoding='utf-8').read())
    regions=[(2,1,'revenue',None,110,720),(3,2,'expenditure','purpose',115,420),
             (3,3,'expenditure','nature',485,735)]
    existing={(r['section_index'],r['kan_code']):r for r in rows if r['role']=='kan_summary' and r['section_index'] in (1,2,3)}
    corrected=[]
    for page,seq,direction,classification,y0,y1 in regions:
        words=parser.pages[page-1]
        codes=[]
        for w in words:
            m=re.fullmatch(r'(\d{1,2})([^\d]*)',norm(w[4]).strip())
            if m and 75<=w[0]<90 and y0<w[1]<y1:
                codes.append((w,m.group(1),m.group(2)))
        codes.sort(key=lambda x:x[0][1])
        for index,(codeword,code,first) in enumerate(codes):
            cy=codeword[1]
            low=(codes[index-1][0][1]+cy)/2 if index else y0
            high=(codes[index+1][0][1]+cy)/2 if index+1<len(codes) else cy+(cy-codes[index-1][0][1])/2
            # printed label column ends before the measured 補正前 column.
            labels=[w for w in words if 89<=w[0]<200 and low<w[1]<high and pnum(w[4]) is None]
            label=(first+''.join(w[4] for w in sorted(labels,key=lambda w:(w[1],w[0])))).replace(' ','')
            ln=next(l for l in lines(words) if codeword in l)
            before=delta=after=None
            for x0,x1,value in pcells(ln):
                center=(x0+x1)/2
                if 205<=center<280:before=value
                elif 330<=center<410:delta=value
                elif 410<=center<490:after=value
            original=existing.get((seq,code))
            if original is None:
                bbox=[min(w[0] for w in ln),min(w[1] for w in ln),max(w[2] for w in ln),max(w[3] for w in ln)]
                original=dict(base(meta,'kan_summary','kan',page,ln[0][1],seq,bbox),annex=False,direction=direction,classification=classification,kan_code=code,unit='千円',cells=[str(x) for x in [before,delta,after] if x is not None],raw_line=ltext(ln))
            rec=dict(original,kan_name=label,budget_before=before,amount_delta=delta,budget_after=after)
            corrected.append(rec)
    if [sum(r['section_index']==i for r in corrected) for i in (1,2,3)]!=[23,13,11]:
        raise ValueError('Finite printed row census differs from23/13/11')
    # Keep non-summary evidence from the legacy decoder; summaries use corrected native positions.
    return [r for r in rows if not (r['role']=='kan_summary' and r['section_index'] in (1,2,3))]+corrected
