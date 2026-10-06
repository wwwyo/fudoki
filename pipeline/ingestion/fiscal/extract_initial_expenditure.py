"""Extract full printed, approved Komae initial project × setsu × department detail.

The default uses Git-managed declarations and fixed original SHA objects. An
optional finite manifest preserves exploratory extraction. Extraction never
allocates moku controls, creates absent zero rows or changes adopted inputs.
"""
from __future__ import annotations
from ingestion.inputs import record_input
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import duckdb
from ingestion.lib.pdf import pages_of, rows_of as _rows_of
from ingestion.fiscal.extract_supplementary_expenditure import norm, text, number, split_amount

REPO = Path(__file__).resolve().parents[3]
VERSION = 1
TABLE_ID = 'initial-expenditure-project-setsu'
WORK_DIR = REPO / '.agent/komae-initial-detail'
CANONICAL_DIR = REPO / 'pipeline/.cache/acquisition/raw/initial-detail'
INTEGRATION_DIR = REPO / '.agent/komae-initial-integration'
COLUMNS = {
    'source_row': 'BIGINT', 'jurisdiction_code': 'VARCHAR', 'fiscal_year': 'BIGINT',
    'fund_label': 'VARCHAR', 'source_url': 'VARCHAR',
    'origin_sha256': 'VARCHAR', 'origin_fetched_at': 'VARCHAR', 'submitted_date': 'VARCHAR',
    'approval_status': 'VARCHAR', 'edition_status': 'VARCHAR',
    'approval_date': 'VARCHAR', 'approval_evidence_json': 'VARCHAR',
    'kan_code': 'VARCHAR', 'kou_code': 'VARCHAR', 'moku_code': 'VARCHAR', 'moku_label': 'VARCHAR', 'kan_label': 'VARCHAR', 'kou_label': 'VARCHAR',
    'control_moku_source_row': 'BIGINT', 'control_moku_key': 'VARCHAR', 'control_moku_json': 'VARCHAR',
    'project_source_row': 'BIGINT', 'project_code': 'VARCHAR', 'project_label': 'VARCHAR',
    'project_printed_initial': 'BIGINT', 'project_evidence_json': 'VARCHAR',
    'department_text': 'VARCHAR', 'setsu_code': 'VARCHAR', 'setsu_label': 'VARCHAR',
    'amount_initial': 'BIGINT', 'printed_amount_text': 'VARCHAR', 'source_amount_unit': 'VARCHAR',
    'page_number': 'BIGINT', 'bbox_json': 'VARCHAR', 'printed_text': 'VARCHAR',
    'source_locations_json': 'VARCHAR', 'left_setsu_evidence_json': 'VARCHAR',
    'unit_evidence_json': 'VARCHAR', 'validation_status': 'VARCHAR', 'validation_reasons_json': 'VARCHAR',
    'source_grain': 'VARCHAR', 'observed_grain_validation_status': 'VARCHAR',
    'setsu_correspondence_status': 'VARCHAR',
}


class _SourceChars(list):
    """Character grid with the actual source word boxes retained alongside."""


def chars_of(pdf, first, last):
    for _, _, words in pages_of(pdf, first, last):
        chars = _SourceChars()
        chars.words = words
        for x0, y0, x1, _, raw in words:
            width = (x1-x0)/max(len(raw),1)
            chars.extend((x0+width*i,y0,c) for i,c in enumerate(raw))
        yield chars


def rows_of(chars):
    rows = _rows_of(chars)
    for row in rows:
        row.words = [w for w in chars.words if w[1] in row.ys]
    return rows


def location(row, page, lo, hi):
    words = [w for w in row.words if w[0] < hi and w[2] > lo]
    return dict(page_number=page,
        bbox=[min(w[0] for w in words),min(w[1] for w in words),max(w[2] for w in words),max(w[3] for w in words)] if words else None,
        printed_text=text(row,lo,hi),
        word_boxes=[dict(bbox=list(w[:4]),printed_text=w[4]) for w in words])

def validate_candidate(candidate):
    if candidate.get('fiscal_year') not in range(2023, 2027):
        raise ValueError('Supported initial fiscal years are 2023–2026')
    if candidate.get('fund_label') not in {
        '一般会計', '国民健康保険特別会計', '後期高齢者医療特別会計',
        '介護保険特別会計', '駐車場事業特別会計',
    }:
        raise ValueError('Enterprise/unknown accounts require separate source-grain support')
    if not re.fullmatch(r'132195-[0-9a-f]{12}', candidate.get('coverage_source_id', '')):
        raise ValueError('Invalid Komae coverage source ID')
    if not re.fullmatch(r'[0-9a-f]{64}', candidate.get('expected_sha256', '')):
        raise ValueError('An explicit full original SHA256 is required')
    if candidate.get('approval_status') != 'cover-approved' or candidate.get('edition_status') != 'published':
        raise ValueError('An approved original edition must be explicit')
    if not candidate.get('url', '').startswith('https://www.city.komae.tokyo.jp/'):
        raise ValueError('An official Komae original URL is required')
    if not (isinstance(candidate.get('first_page'), int) and isinstance(candidate.get('last_page'), int)
            and 1 <= candidate['first_page'] <= candidate['last_page']):
        raise ValueError('An explicit physical account page range is required')
    if candidate.get('cover_page') != 1:
        raise ValueError('Supported books require the account-specific approval evidence on physical cover page 1')


def initial_controls(pdf, candidate):
    """Independently read article, moku triples and printed hierarchy controls."""
    cover_rows = rows_of(next(chars_of(pdf, 1, 1)))
    account = candidate['fund_label']; year = candidate['fiscal_year']
    approval_rows = [r for r in cover_rows if f'狛江市{account}予算' in norm(text(r)) and '原案可決' in norm(text(r))]
    if len(approval_rows) != 1:
        raise ValueError('Unique account-specific printed cover approval absent')
    match = re.search(r'令和(\d+)年(\d+)月(\d+)日原案可決', norm(text(approval_rows[0])))
    date = f'{2018+int(match[1]):04d}-{int(match[2]):02d}-{int(match[3]):02d}'
    if date != candidate.get('approval_date'):
        raise ValueError('Printed approval date differs from finite candidate identity')
    if f'令和{year-2018}年度' not in ''.join(norm(text(r)) for r in cover_rows):
        raise ValueError('Printed cover fiscal year differs from requested year')
    pages = [rows_of(ch) for ch in chars_of(pdf, candidate['first_page'], candidate['last_page'])]
    opening = ''.join(norm(text(r)) for r in pages[0])
    if f'令和{year-2018}年度狛江市{account}予算' not in opening or '補正予算' in opening:
        raise ValueError('Initial account/year article title not independently verified')
    article = re.search(r'第1条歳入歳出予算の総額は[、,]?歳入歳出それぞれ([\d,]+)千円と定める', opening)
    if not article:
        raise ValueError('Printed initial first-article expenditure total absent')
    article_rows = [location(r, candidate['first_page'], 0, 900) for r in pages[0] if '第1条' in norm(text(r))]
    first_article = dict(amount_initial=number(article[1]), printed_text=article[0], locations=article_rows, unit='千円')
    submitted = re.search(r'令和(\d+)年(\d+)月(\d+)日提出', opening)
    submitted_at = f'{2018+int(submitted[1]):04d}-{int(submitted[2]):02d}-{int(submitted[3]):02d}' if submitted else None
    moku = []; keys=set(); kan=kou=None; kan_label=kou_label=''; expenditure=False; units=None
    hierarchy=[]; first_table=[]
    for page, rr in enumerate(pages, candidate['first_page']):
        for i, row in enumerate(rr):
            whole=norm(text(row))
            if re.match(r'3\.歳出', whole):
                expenditure=True; kan=kou=None
            if ('下水道事業会計予算' in whole) or re.match(r'2\.歳入',whole) or any(s in whole for s in ['給与費明細書','地方債の前前年度末','債務負担行為で翌年度以降']):
                expenditure=False
            if not expenditure:
                if whole.startswith('歳出合計'):
                    amt=re.search(r'歳出合計([\d,]+)$',whole)
                    if amt:first_table.append(dict(amount_initial=number(amt[1]), location=location(row,page,0,900)))
                continue
            h=re.search(r'\(款\)(\d+)\.([^()千]+?)(?:([\d,]+)千円|$|\(項\))',whole)
            if h:
                kan=h[1];kan_label=h[2];kou=None
                if h[3]:hierarchy.append(dict(level='kan',kan_code=kan,label=kan_label,amount_initial=number(h[3]),location=location(row,page,0,900)))
            h=re.search(r'\(項\)(\d+)\.([^()千]+?)(?:([\d,]+)千円|$)',whole)
            if h:
                kou=h[1];kou_label=h[2]
                if h[3]:hierarchy.append(dict(level='kou',kan_code=kan,kou_code=kou,label=kou_label,amount_initial=number(h[3]),location=location(row,page,0,900)))
            if re.fullmatch(r'(千円){10}',whole):
                anchors=[x for x,c in sorted(row) if c=='千']
                if any(abs(a-b)>1 for a,b in zip(anchors,[138.55,192.29,246.01,299.7,353.44,407.19,460.9,513.2,637.62,788.9])):
                    raise ValueError(f'Unsupported initial expenditure currency anchors at page {page}')
                units=dict(unit='千円',location=location(row,page,110,815))
            if '(款)' in whole or '(項)' in whole:continue
            cells=[norm(text(row,a,b)) for a,b in [(0,110),(110,155),(155,209),(209,270)]]
            heading=re.fullmatch(r'(\d+)\.(.+)',cells[0])
            if not heading or not all(re.fullmatch(r'[△\-]?\d[\d,]*',v) for v in cells[1:]):continue
            if kan is None or kou is None or units is None:
                raise ValueError(f'Printed hierarchy/unit missing from initial moku page {page}')
            key=kan,kou,heading[1],heading[2]

            current,previous,comparison=map(number,cells[1:])
            if current-previous!=comparison:raise ValueError(f'Initial/previous/comparison arithmetic fails at page {page}')
            label=heading[2];locs=[location(row,page,0,270)]
            for following in rr[i+1:]:
                tail=norm(text(following,0,110))
                if not tail or tail=='計' or not re.fullmatch(r'[一-龯ぁ-んァ-ヶー・及び]+',tail):break
                label+=tail;locs.append(location(following,page,0,110))
            key=kan,kou,heading[1],label
            if key in keys:raise ValueError(f'Duplicate full printed initial moku {key}')
            keys.add(key)
            moku.append(dict(source_row=len(moku)+1,kan_code=kan,kou_code=kou,moku_code=heading[1],kan_label=kan_label,kou_label=kou_label,moku_label=label,heading_label=heading[2],
                amount_initial=current,amount_previous=previous,amount_comparison=comparison,page_number=page,bbox_json=json.dumps(locs[0]['bbox']),
                printed_text='\n'.join(l['printed_text'] for l in locs),locations=locs,unit_evidence=units))
    if not moku or sum(r['amount_initial'] for r in moku)!=first_article['amount_initial']:
        raise ValueError(f"All printed initial moku total {sum(r['amount_initial'] for r in moku)} differs from first article {first_article['amount_initial']} (incomplete layout/font/account range)")
    if not first_table or any(r['amount_initial']!=first_article['amount_initial'] for r in first_table):
        raise ValueError('Printed first-table expenditure total absent/different from first article')
    checks=[]
    for h in hierarchy:
        relevant=[r for r in moku if r['kan_code']==h['kan_code'] and (h['level']=='kan' or r['kou_code']==h['kou_code'])]
        checks.append(dict(h,sum_moku=sum(r['amount_initial'] for r in relevant),complete=sum(r['amount_initial'] for r in relevant)==h['amount_initial']))
    if not checks or any(not c['complete'] for c in checks):
        raise ValueError('Printed kan/kou initial controls differ from full moku sum')
    from ingestion.fiscal.initial_detail_controls import first_table_hierarchy
    first_hierarchy = first_table_hierarchy(pdf, candidate, checks, first_article)
    return dict(rows=moku,first_article=first_article,first_table_controls=first_table,first_table_hierarchy_checks=first_hierarchy,hierarchy_checks=checks,approval_status='cover-approved',edition_status='published',
        effective_at=date,submitted_at=submitted_at,approval_evidence=[location(approval_rows[0],1,0,900)])
def extract(pdf: Path, candidate: dict) -> dict:
    validate_candidate(candidate)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if sha != candidate['expected_sha256']:
        raise ValueError('Official edition SHA differs from candidate manifest')
    control = initial_controls(pdf, candidate)
    moku_controls = {(int(r['kan_code']), int(r['kou_code']), int(r['moku_code']),r['source_row']): r for r in control['rows']}
    projects, leaves, left_controls, problems = [], [], [], []
    moku = project = pending_setsu = left_open = None
    department = ''
    kan = kou = None
    expenditure = False
    scale, shift = 1.0, 0.0
    units = None
    header_boxes = []
    def tx(x): return x * scale + shift
    def add_issue(reason, page=None):
        problems.append(dict(reason=reason, moku=moku, project=project['source_row'] if project else None, page_number=page))
    def finish_pending(page=None):
        nonlocal pending_setsu
        if pending_setsu is not None:
            add_issue('Unfinished printed explanation setsu name/amount', page)
            pending_setsu = None
    def emit_setsu(name, amount, raw, locs):
        if project is None:
            add_issue('Printed setsu amount has no preceding numbered project', locs[0]['page_number'])
            return
        leaves.append(dict(project=project, moku=moku, department=department, setsu_label=name,
                           amount=amount, raw_amount=raw, locations=locs, unit_evidence=units,
                           same_row_left_region=dict(page_number=locs[-1]['page_number'],
                               bbox=[tx(528),min(row.ys),tx(650),max(row.ys)+12],
                               printed_text=text(row,tx(528),tx(650)))))
    for page, chars in enumerate(chars_of(pdf, candidate['first_page'], candidate['last_page']), candidate['first_page']):
        page_rows = rows_of(chars)
        for row in page_rows:
            whole = norm(text(row))
            if re.match(r'3\.歳出', whole):
                expenditure = True
                kan = kou = None
                continue
            if ('下水道事業会計予算' in whole) or re.match(r'2\.歳入', whole) or any(s in whole for s in ['給与費明細書', '地方債の前前年度末', '債務負担行為で翌年度以降']):
                if expenditure: finish_pending(page)
                expenditure = False
                continue
            if not expenditure:
                continue
            h = re.search(r'\(款\)(\d+)\.', whole)
            if h: kan, kou = int(h[1]), None
            h = re.search(r'\(項\)(\d+)\.', whole)
            if h: kou = int(h[1])
            if re.fullmatch(r'(千円){10}', whole):
                anchors = [x for x, c in sorted(row) if c == '千']
                scale = (anchors[1] - anchors[0]) / (192.29 - 138.55)
                shift = anchors[0] - 138.55 * scale
                if not 0.85 < scale < 1.1:
                    raise ValueError(f'Unsupported expenditure table scale at page {page}')
                units = dict(explanation=location(row, page, tx(650), tx(810)),
                             left_setsu=location(row, page, tx(528), tx(650)), unit='千円')
                continue
            if '(款)' in whole or '(項)' in whole:
                # A table heading/footnote does not end the previous page's project.
                continue
            left_cell = norm(text(row, 0, tx(110)))
            mh = re.fullmatch(r'(\d+)\.(.+)', left_cell)
            moku_amounts = [norm(text(row, tx(a), tx(b))) for a,b in [(110,155),(155,209),(209,270)]]
            if mh and all(re.fullmatch(r'[△\-]?\d[\d,]*', a) for a in moku_amounts):
                finish_pending(page)
                matching = [k for k,r in moku_controls.items() if k[:3]==(kan,kou,int(mh[1])) and r['page_number']==page and r['heading_label']==mh[2] and abs(r['locations'][0]['bbox'][1]-min(row.ys))<1]
                if len(matching)!=1:raise ValueError(f'Printed initial moku occurrence not uniquely controlled at page {page}: {mh[0]}')
                moku = matching[0]
                if moku not in moku_controls:
                    raise ValueError(f'Printed initial moku absent from independent controls: {moku}')
                project = left_open = None
                department = ''
                header_boxes.append(dict(moku=moku, location=location(row,page,0,tx(270))))
            if moku is None:
                continue
            # Left setsu totals are independent of explanation rows and subdetails.
            left_chars = sorted((x,c) for x,c in row if tx(528) <= x < tx(650))
            if left_chars:
                start = left_chars[0][0]
                name, amt, raw = split_amount(row,tx(528),tx(650),tx(646.4))
                heading = re.fullmatch(r'(\d+)\.(.*)',name)
                if abs(start-tx(531.49)) < 2.2 and heading:
                    left_open = dict(moku=moku, code=heading[1], label=heading[2], amount=amt, raw_amount=raw,
                                     locations=[location(row,page,tx(528),tx(650))], name_open=True)
                    left_controls.append(left_open)
                elif left_open and abs(start-tx(550.66)) < 2.2 and name and amt is None and left_open['name_open']:
                    left_open['label'] += name
                    left_open['locations'].append(location(row,page,tx(528),tx(650)))
                elif abs(start-tx(539.96)) < 2.2:
                    if left_open: left_open['name_open'] = False
            # Explanation project/setsu share a base indent; subdetail lines are indented.
            exp_chars = sorted((x,c) for x,c in row if tx(650) <= x < tx(810))
            if not exp_chars:
                continue
            exp = norm(''.join(c for _,c in exp_chars))
            if exp in {'説明','区分','千円','-'}:
                continue
            loc = location(row,page,tx(650),tx(810))
            start = exp_chars[0][0]
            name, amt, raw = split_amount(row,tx(650),tx(810),tx(796.4))
            numbered = re.match(r'^(\d+)\.(.*)', name)
            base = abs(start-tx(659.51)) <= 2.5
            if numbered and base:
                finish_pending(page)
                project = dict(source_row=len(projects)+1, moku=moku, code=numbered[1], label=numbered[2],
                               amount=amt, raw_amount=raw, locations=[loc], name_open=True)
                projects.append(project)
                department = ''
                continue
            if exp.startswith('〔'):
                department = exp
                if project: project['name_open'] = False
                continue
            if project and project['amount'] is None:
                # Printed project header wraps before its amount; no value is inferred.
                if amt is not None and not name:
                    project['amount'],project['raw_amount']=amt,raw
                    project['locations'].append(loc)
                elif (base or abs(start-tx(677.51)) <= 2.5) and amt is not None:
                    project['label'] += name
                    project['amount'],project['raw_amount']=amt,raw
                    project['locations'].append(loc)
                elif (base or abs(start-tx(677.51)) <= 2.5) and name:
                    project['label'] += name
                    project['locations'].append(loc)
                else:
                    add_issue('Project header continuation could not be paired with its printed amount',page)
                continue
            if base and name:
                if project: project['name_open']=False
                if pending_setsu:
                    name = pending_setsu['name'] + name
                    locs = pending_setsu['locations'] + [loc]
                else: locs=[loc]
                if amt is not None:
                    emit_setsu(name,amt,raw,locs)
                    pending_setsu=None
                else:
                    pending_setsu=dict(name=name,locations=locs)
            elif amt is not None and not name and pending_setsu:
                emit_setsu(pending_setsu['name'],amt,raw,pending_setsu['locations']+[loc])
                pending_setsu=None
            # Deeper, indented detail amounts (including parenthesized values) remain annotations.
    finish_pending()
    return validate(candidate,control,moku_controls,projects,leaves,left_controls,problems,units,header_boxes)


def validate(candidate,control,moku_controls,projects,leaves,left_controls,problems,units,header_boxes):
    project_checks=[];moku_checks=[];output=[]
    by_project=defaultdict(list)
    for leaf in leaves:by_project[leaf['project']['source_row']].append(leaf)
    for p in projects:
        children=by_project[p['source_row']]
        observed=sum(c['amount'] for c in children)
        project_checks.append(dict(source_row=p['source_row'],moku=p['moku'],project_code=p['code'],project_label=p['label'],
            printed_initial=p['amount'],setsu_sum=observed,setsu_rows=len(children),complete=p['amount'] is not None and bool(children) and p['amount']==observed,
            evidence=p['locations']))
    project_ok={p['source_row']:p['complete'] for p in project_checks}
    moku_status={};left_matches={};reserve_exceptions={}
    for key,original in moku_controls.items():
        ps=[p for p in projects if p['moku']==key]
        ls=[l for l in leaves if l['moku']==key]
        cs=[c for c in left_controls if c['moku']==key]
        reasons=[]
        if not ps:reasons.append('No printed explanation project×setsu; correspondence unconfirmed')
        if any(not project_ok[p['source_row']] for p in ps):reasons.append('Project printed initial amount differs from its complete setsu sum')
        if any(c['amount'] is None for c in cs):reasons.append('Left setsu printed amount missing')
        left_sum=sum(c['amount'] or 0 for c in cs)
        project_sum=sum(p['amount'] or 0 for p in ps)
        detail_sum=sum(l['amount'] for l in ls)
        if left_sum!=original['amount_initial']:reasons.append('Left setsu sum differs from printed moku initial amount')
        if project_sum!=original['amount_initial']:reasons.append('Printed project sum differs from printed moku initial amount')
        if detail_sum!=original['amount_initial']:reasons.append('Explanation setsu sum differs from printed moku initial amount')
        grouped=defaultdict(int)
        for l in ls:grouped[l['setsu_label']]+=l['amount']
        names=defaultdict(list)
        for c in cs:names[c['label']].append(c)
        setsu_checks=[]
        for label,amount in grouped.items():
            matches=names[label]
            complete=len(matches)==1 and matches[0]['amount']==amount
            if not complete:reasons.append(f'Exact printed left-setṣu correspondence/amount not verified: {label}')
            if len(matches)==1:left_matches[(key,label)]=matches[0]
            setsu_checks.append(dict(setsu_label=label,explanation_sum=amount,left_printed=sum(c['amount'] or 0 for c in matches),exact_matches=len(matches),complete=complete))
        if set(names)!=set(grouped):reasons.append('Printed left setsu and explanation setsu name sets differ')
        reasons += [p['reason'] for p in problems if p['moku']==key]
        reasons=list(dict.fromkeys(reasons))
        comparison_only_zero = original['amount_initial']==0 and not ps and not ls and not cs and not any(p['moku']==key for p in problems)
        if comparison_only_zero:reasons=[]
        # Reserve has an actually printed explanation and project but an empty
        # statutory setsu column. Keep that different grain, never invent a code.
        reserve_exception = (original['moku_label']=='予備費' and not cs and bool(ps) and bool(ls)
            and all(project_ok[p['source_row']] for p in ps)
            and all(l['setsu_label']=='予備費' for l in ls)
            and project_sum==detail_sum==original['amount_initial']
            and not any(p['moku']==key for p in problems))
        reserve_exceptions[key]=reserve_exception
        moku_status[key]=(not reasons,reasons)
        moku_checks.append(dict(moku=key,moku_label=original['moku_label'],kan_label=original['kan_label'],kou_label=original['kou_label'],printed_initial=original['amount_initial'],
            printed_projects_sum=project_sum,explanation_setsu_sum=detail_sum,left_setsu_sum=left_sum,
            project_rows=len(ps),setsu_rows=len(ls),complete=not reasons,reasons=reasons,setsu_checks=setsu_checks,
            observed_grain_complete=not reasons or reserve_exception,
            grain_exception='Printed reserve explanation; statutory setsu column empty' if reserve_exception else ('Printed zero initial moku with previous-year comparison only; no synthetic detail row' if comparison_only_zero else None),
            original_control=original))
    for i,l in enumerate(leaves,1):
        p=l['project'];key=l['moku'];original=moku_controls[key];complete,reasons=moku_status[key]
        matched=left_matches.get((key,l['setsu_label']))
        output.append(dict(source_row=i,jurisdiction_code='132195',fiscal_year=candidate['fiscal_year'],fund_label=candidate['fund_label'],
            source_url=candidate['url'],origin_sha256=candidate['expected_sha256'],
            origin_fetched_at=candidate.get('fetched_at'),submitted_date=control['submitted_at'],
            approval_status=control['approval_status'],edition_status=control['edition_status'],
            approval_date=control['effective_at'],approval_evidence_json=json.dumps(control['approval_evidence'],ensure_ascii=False),
            kan_code=str(key[0]),kou_code=str(key[1]),moku_code=str(key[2]),moku_label=original['moku_label'],kan_label=original['kan_label'],kou_label=original['kou_label'],
            control_moku_source_row=original['source_row'],control_moku_key='-'.join(map(str,key)),control_moku_json=json.dumps(original,ensure_ascii=False),
            project_source_row=p['source_row'],project_code=p['code'],project_label=p['label'],project_printed_initial=p['amount'],
            project_evidence_json=json.dumps(p['locations'],ensure_ascii=False),department_text=l['department'],
            setsu_code=matched['code'] if matched else None,setsu_label=l['setsu_label'],amount_initial=l['amount'],
            printed_amount_text=l['raw_amount'],source_amount_unit='千円',page_number=l['locations'][0]['page_number'],
            bbox_json=json.dumps(l['locations'][0]['bbox']),printed_text='\n'.join(x['printed_text'] for x in l['locations']),
            source_locations_json=json.dumps(l['locations'],ensure_ascii=False),
            left_setsu_evidence_json=json.dumps(matched if matched else dict(
                kind='No printed statutory setsu at this explanation amount row',
                same_row_region=l['same_row_left_region']),ensure_ascii=False),
            unit_evidence_json=json.dumps(l['unit_evidence'],ensure_ascii=False),validation_status='complete' if complete else 'unconfirmed',
            validation_reasons_json=json.dumps(reasons,ensure_ascii=False),
            source_grain='project × printed reserve explanation' if reserve_exceptions[key] else 'project × expenditure setsu',
            observed_grain_validation_status='complete' if complete or reserve_exceptions[key] else 'unconfirmed',
            setsu_correspondence_status='unconfirmed-no-printed-setsu-code' if reserve_exceptions[key] else ('exact-printed-name' if matched else 'unconfirmed')))
    article=control['first_article']['amount_initial']
    totals=dict(first_article=article,all_moku_sum=sum(c['amount_initial'] for c in moku_controls.values()),
                printed_project_sum=sum(p['amount'] or 0 for p in projects),explanation_setsu_sum=sum(l['amount'] for l in leaves),
                left_setsu_sum=sum(c['amount'] or 0 for c in left_controls))
    fully_complete=bool(output) and all(c['complete'] for c in moku_checks) and all(v==article for v in totals.values()) and not problems
    reserve_control_sum=sum(moku_controls[k]['amount_initial'] for k,v in reserve_exceptions.items() if v)
    reserve_checks=dict(printed_reserve_moku_sum=reserve_control_sum,
        printed_reserve_explanation_sum=sum(l['amount'] for l in leaves if reserve_exceptions[l['moku']]),
        expected_statutory_left_setsu_sum=totals['all_moku_sum']-reserve_control_sum,
        actual_statutory_left_setsu_sum=totals['left_setsu_sum'],
        statutory_left_setsu_complete=totals['left_setsu_sum']==totals['all_moku_sum']-reserve_control_sum)
    observed_complete=bool(output) and all(c['observed_grain_complete'] for c in moku_checks) and not problems and (
        totals['printed_project_sum']==totals['explanation_setsu_sum']==totals['all_moku_sum']==article
        and reserve_checks['statutory_left_setsu_complete'])
    return dict(rows=output,project_checks=project_checks,moku_checks=moku_checks,totals=totals,parser_problems=problems,
        reserve_grain_checks=reserve_checks,fully_complete_observed_grain=observed_complete,
        fully_complete=fully_complete,complete_moku=sum(c['complete'] for c in moku_checks),moku_count=len(moku_checks),
        complete_rows=sum(r['validation_status']=='complete' for r in output),approval_evidence=control['approval_evidence'],
        approval_date=control['effective_at'],first_article_evidence=control['first_article'],first_table_controls=control['first_table_controls'],hierarchy_checks=control['hierarchy_checks'],first_table_hierarchy_checks=control['first_table_hierarchy_checks'],moku_header_locations=header_boxes)

def materialize(directory, result, candidate):
    allowed = [WORK_DIR.resolve(), CANONICAL_DIR.resolve(), INTEGRATION_DIR.resolve()]
    if not any(directory.resolve().is_relative_to(root) for root in allowed):
        raise ValueError('Output must stay in isolated detail work or initial-detail work')
    directory.mkdir(parents=True,exist_ok=True)
    parquet=directory/'data.parquet'
    with duckdb.connect() as con:
        con.execute('create table t ('+','.join(f'{k} {v}' for k,v in COLUMNS.items())+')')
        if result['rows']:
            con.executemany('insert into t values ('+','.join('?' for _ in COLUMNS)+')',[[r.get(k) for k in COLUMNS] for r in result['rows']])
        con.execute('copy (select * from t order by source_row) to ? (format parquet, compression zstd)',[str(parquet)])
    evidence={**{k:v for k,v in result.items() if k!='rows'},'candidate':candidate,'rows':len(result['rows']),'table_id':candidate.get('table_id', TABLE_ID),'table_family':TABLE_ID,
        'source_grain':'printed project × expenditure setsu × printed department occurrence; explicit printed reserve exceptions',
        'source_amount_unit':'千円','source_position_method':'pdftotext -bbox-layout original word boxes plus source-preserving character spans; row boxes are union of actual intersecting words','header':COLUMNS,'extractor':f'extract_initial_expenditure.py@{VERSION}',
        'parquet_sha256':hashlib.sha256(parquet.read_bytes()).hexdigest(),'raw_form':'extracted','roundtrip_verified':False,
        'normalization':['NFKC and whitespace removal for exact name comparisons; original printed labels/amounts/locations retained'],
        'adoption_status':'candidate-only','baseline_status':'candidate-only; exact correspondence proof separate; no canonical identity changes'}
    if candidate.get('table_id'):
        evidence.update(source_key=candidate['source_key'], request_url=candidate['url'],
            sha256=candidate['expected_sha256'], fetched_at=candidate['fetched_at'],
            document_title=candidate['document_title'], fiscal_year=candidate['fiscal_year'],
            jurisdiction_code='132195', direction='expenditure', document_kind='budget')
    record_input(directory, evidence)
    return evidence



def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--describe',action='store_true',help='Machine-readable API and exact raw schema')
    parser.add_argument('--manifest',type=Path,help='Optional finite exploratory JSON manifest; default uses Git-managed sources-initial-detail.toml and fixed original SHA cache')
    parser.add_argument('--output-dir',type=Path,default=CANONICAL_DIR)
    parser.add_argument('--fiscal-year',type=int)
    parser.add_argument('--fund-label')
    parser.add_argument('--dry-run',action='store_true',help='Validate selection, identity, SHA and output scope without extraction or writes')
    args=parser.parse_args()
    if args.describe:
        print(json.dumps(dict(table_id=TABLE_ID,version=VERSION,columns=COLUMNS,inputs=['canonical Git-managed initial_detail provider (default)','manifest?','output_dir?','fiscal_year?','fund_label?'],
            required_candidate_fields=['coverage_source_id','fiscal_year','fund_label','url','expected_sha256','first_page','last_page','cover_page','approval_status','edition_status','approval_date','pdf_path'],
            scope='Supported full printed approved Komae FY2023–26 initial ordinary-account detail; extraction itself never changes adoption',write_scope=[str(WORK_DIR),str(CANONICAL_DIR),str(INTEGRATION_DIR)],canonical_origin_source='fixed SHA object cache; no .agent runtime dependency',resource_identity='initial-expenditure-project-setsu-<account-slug>',
            semantics='Signed printed initial amounts in 千円; project/moku/left setsu/previous-year values are independent nonadditive controls',
            exit_codes={'0':'successful canonical wave or finite exploratory outcomes recorded','1':'canonical extraction failed byte/count/control contract','2':'invalid input/selection/write scope'}),ensure_ascii=False));return
    if not any(args.output_dir.resolve().is_relative_to(root.resolve()) for root in [WORK_DIR,CANONICAL_DIR,INTEGRATION_DIR]):
        raise ValueError('Materialization must stay in approved isolated initial-detail output directories')
    if args.manifest:
        candidates=json.loads(args.manifest.read_text())
    else:
        from ingestion.fiscal.initial_detail_provider import load_initial_detail
        from ingestion.inputs import origin_path
        candidates=[dict(spec,source_key='initial-detail:'+key,pdf_path=str(origin_path(spec['expected_sha256']))) for key,spec in load_initial_detail().items()]
    if not isinstance(candidates,list):raise ValueError('Manifest must be a JSON candidate list')
    selected=[c for c in candidates if (args.fiscal_year is None or c['fiscal_year']==args.fiscal_year) and (args.fund_label is None or c['fund_label']==args.fund_label)]
    if not selected:raise ValueError('No initial editions match selection')
    seen=set()
    for c in selected:
        validate_candidate(c)
        key=c['fiscal_year'],c['fund_label'],c['expected_sha256']
        if key in seen:raise ValueError('Duplicate finite initial edition')
        seen.add(key)
        if hashlib.sha256(Path(c['pdf_path']).read_bytes()).hexdigest()!=c['expected_sha256']:
            raise ValueError('Manifest original byte SHA mismatch')
    if args.dry_run:
        print(json.dumps(dict(status='dry-run',editions=len(selected),output_dir=str(args.output_dir)),ensure_ascii=False));return
    outcomes=[]
    for c in selected:
        out=dict(id=c['coverage_source_id'],year=c['fiscal_year'],account=c['fund_label'],url=c['url'],sha256=c['expected_sha256'])
        try:
            result=extract(Path(c['pdf_path']),c)
            directory=args.output_dir/'raw'/f'year={c["fiscal_year"]}/account={c["fund_label"]}/edition={c["expected_sha256"]}'
            evidence=materialize(directory,result,c)
            if not args.manifest and (evidence['parquet_sha256']!=c['expected_table_sha256'] or len(result['rows'])!=c['expected_rows'] or not result['fully_complete_observed_grain']):
                raise ValueError('Canonical re-extraction differs from the adopted full-detail byte/count/control contract')
            out.update(status='validated-candidate' if result['fully_complete'] else 'validated-candidate-with-reserve-exception' if result['fully_complete_observed_grain'] else 'partial-unconfirmed',
                rows=len(result['rows']),complete_rows=result['complete_rows'],complete_moku=result['complete_moku'],moku_count=result['moku_count'],
                project_count=len(result['project_checks']),totals=result['totals'],reserve_grain_checks=result['reserve_grain_checks'],
                fully_complete_observed_grain=result['fully_complete_observed_grain'],raw_path=str(directory),problems=result['parser_problems'])
        except (ValueError,OSError,subprocess.CalledProcessError,duckdb.Error) as error:
            out.update(status='rejected',reason=str(error))
        outcomes.append(out)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    name='wave-results'+(f'-{args.fiscal_year}' if args.fiscal_year else '')+'.json'
    (args.output_dir/name).write_text(json.dumps(outcomes,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(editions=len(outcomes),rows=sum(o.get('rows',0) for o in outcomes),complete_observed_grain=sum(o.get('fully_complete_observed_grain',False) for o in outcomes),outcomes_file=str(args.output_dir/name)),ensure_ascii=False))
    if not args.manifest and any(not o.get('fully_complete_observed_grain') for o in outcomes):
        raise SystemExit(1)


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError) as error:
        print(json.dumps(dict(status='error',reason=str(error)),ensure_ascii=False),file=sys.stderr);sys.exit(2)
