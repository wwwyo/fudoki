"""Extract actually printed Komae supplementary project × expenditure setsu.

Separate from the frozen moku pilot. Parent/project/detail amounts are controls,
not additional expenditure rows. Unknown correspondence remains unconfirmed.
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
import tomllib
import unicodedata

import duckdb

from ingestion.fiscal.history_expansion import extract_document
from ingestion.lib.pdf import chars_of, rows_of

REPO = Path(__file__).resolve().parents[3]
VERSION = 1
TABLE_ID = 'supplementary-expenditure-project-setsu'
WORK_DIR = REPO / '.agent/komae-supplementary-detail'
COLUMNS = {
    'source_row': 'BIGINT', 'jurisdiction_code': 'VARCHAR', 'fiscal_year': 'BIGINT',
    'fund_label': 'VARCHAR', 'amendment_number': 'BIGINT', 'source_url': 'VARCHAR',
    'origin_sha256': 'VARCHAR', 'origin_fetched_at': 'VARCHAR', 'submitted_date': 'VARCHAR',
    'approval_status': 'VARCHAR', 'edition_status': 'VARCHAR',
    'approval_date': 'VARCHAR', 'approval_evidence_json': 'VARCHAR',
    'kan_code': 'VARCHAR', 'kou_code': 'VARCHAR', 'moku_code': 'VARCHAR', 'moku_label': 'VARCHAR',
    'control_moku_source_row': 'BIGINT', 'control_moku_key': 'VARCHAR', 'control_moku_json': 'VARCHAR',
    'project_source_row': 'BIGINT', 'project_code': 'VARCHAR', 'project_label': 'VARCHAR',
    'project_printed_delta': 'BIGINT', 'project_evidence_json': 'VARCHAR',
    'department_text': 'VARCHAR', 'setsu_code': 'VARCHAR', 'setsu_label': 'VARCHAR',
    'amount_delta': 'BIGINT', 'printed_amount_text': 'VARCHAR', 'source_amount_unit': 'VARCHAR',
    'page_number': 'BIGINT', 'bbox_json': 'VARCHAR', 'printed_text': 'VARCHAR',
    'source_locations_json': 'VARCHAR', 'left_setsu_evidence_json': 'VARCHAR',
    'unit_evidence_json': 'VARCHAR', 'validation_status': 'VARCHAR', 'validation_reasons_json': 'VARCHAR',
    'source_grain': 'VARCHAR', 'observed_grain_validation_status': 'VARCHAR',
    'setsu_correspondence_status': 'VARCHAR',
}


def norm(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def text(row, lo=0, hi=float('inf')):
    return ''.join(c for x, c in sorted(row) if lo <= x < hi)


def location(row, page, lo, hi):
    xs = [x for x, _ in row if lo <= x < hi]
    return dict(page_number=page, bbox=[min(xs), min(row.ys), max(xs) + 6, max(row.ys) + 12] if xs else None,
                printed_text=text(row, lo, hi))


def number(value):
    n = norm(value).replace(',', '').replace('△', '-')
    if not re.fullmatch(r'-?\d+', n):
        raise ValueError(f'Invalid signed printed amount: {value!r}')
    return int(n)


def validate_candidate(candidate):
    """This finite wave accepts explicit, separately approved ordinary accounts."""
    if candidate.get('fiscal_year') not in range(2023, 2027):
        raise ValueError('Supported fiscal years are 2023–2026')
    if candidate.get('fund_label') not in {
        '一般会計', '国民健康保険特別会計', '後期高齢者医療特別会計',
        '介護保険特別会計', '駐車場事業特別会計',
    }:
        raise ValueError('Unsupported account; enterprise accounts require a separate grain')
    if not re.fullmatch(r'132195-[0-9a-f]{12}', candidate.get('coverage_source_id', '')):
        raise ValueError('Invalid Komae coverage source ID')
    if not re.fullmatch(r'[0-9a-f]{64}', candidate.get('expected_sha256', '')):
        raise ValueError('An explicit full origin SHA256 is required')
    if candidate.get('approval_status') != 'cover-approved' or candidate.get('edition_status') != 'published':
        raise ValueError('Held proposals/preliminary editions are outside this approved detail wave')
    if not candidate.get('url', '').startswith('https://www.city.komae.tokyo.jp/'):
        raise ValueError('An official Komae origin URL is required')
    if not isinstance(candidate.get('amendment_number'), int) or candidate['amendment_number'] < 1:
        raise ValueError('An explicit positive account-specific amendment number is required')
    if not (isinstance(candidate.get('first_page'), int) and isinstance(candidate.get('last_page'), int)
            and 1 <= candidate['first_page'] <= candidate['last_page']):
        raise ValueError('An explicit physical page range is required')


def split_amount(row, lo, hi, right_edge):
    """A number is monetary only at the observed right-aligned amount edge."""
    chars = sorted((x, c) for x, c in row if lo <= x < hi)
    raw = ''.join(c for _, c in chars)
    m = re.search(r'([△\-]?\d[\d,]*)\s*$', norm(raw))
    if not m or not chars or abs(chars[-1][0] - right_edge) > 3:
        return norm(raw), None, None
    # Keep the printed full-width amount separately; labels are normalized.
    normalized = [norm(c) for _, c in chars]
    i = len(chars)
    while i and (normalized[i-1] in '0123456789,△-' or not normalized[i-1]):
        i -= 1
    return norm(''.join(c for _, c in chars[:i])), number(m[1]), ''.join(c for _, c in chars[i:])


def extract(pdf: Path, candidate: dict) -> dict:
    validate_candidate(candidate)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if sha != candidate['expected_sha256']:
        raise ValueError('Official edition SHA differs from candidate manifest')
    control = extract_document(pdf, candidate['amendment_number'],
        fiscal_year=candidate['fiscal_year'], fund_label=candidate['fund_label'],
        source_url=candidate['url'], expected_sha256=sha,
        first_page=candidate['first_page'], last_page=candidate['last_page'])
    if control['approval_status'] != 'cover-approved' or control['edition_status'] == 'preliminary-counts':
        raise ValueError('Project detail wave requires a cover-approved, non-preliminary edition')
    moku_controls = {(int(r['kan_code']), int(r['kou_code']), int(r['moku_code'])): r for r in control['rows']}
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
            if re.match(r'2\.歳入', whole) or any(s in whole for s in ['給与費明細書', '地方債の前前年度末', '債務負担行為で翌年度以降']):
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
            moku_amounts = [norm(text(row, tx(a), tx(b))) for a,b in [(110,160),(160,215),(215,270)]]
            if mh and all(re.fullmatch(r'[△\-]?\d[\d,]*', a) for a in moku_amounts):
                finish_pending(page)
                moku = (kan, kou, int(mh[1]))
                if moku not in moku_controls:
                    # A genuinely printed zero moku is not a synthetic unchanged row.
                    before, delta, after = map(number, moku_amounts)
                    if delta != 0 or before + delta != after:
                        raise ValueError(f'Moku control missing from independently extracted edition: {moku}')
                    moku_controls[moku] = dict(source_row=None, kan_code=str(kan), kou_code=str(kou), moku_code=mh[1],
                        moku_label=mh[2], amount_before=before, amount_delta=delta, amount_after=after,
                        page_number=page, bbox_json=json.dumps(location(row,page,0,tx(270))['bbox']))
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
            if any(s in exp for s in ['説明','区分','千円']) or exp == '-':
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
            printed_delta=p['amount'],setsu_sum=observed,setsu_rows=len(children),complete=p['amount'] is not None and bool(children) and p['amount']==observed,
            evidence=p['locations']))
    project_ok={p['source_row']:p['complete'] for p in project_checks}
    moku_status={};left_matches={};reserve_exceptions={}
    for key,original in moku_controls.items():
        ps=[p for p in projects if p['moku']==key]
        ls=[l for l in leaves if l['moku']==key]
        cs=[c for c in left_controls if c['moku']==key]
        reasons=[]
        if not ps:reasons.append('No printed explanation project×setsu; correspondence unconfirmed')
        if any(not project_ok[p['source_row']] for p in ps):reasons.append('Project printed delta differs from its complete setsu sum')
        if any(c['amount'] is None for c in cs):reasons.append('Left setsu printed amount missing')
        left_sum=sum(c['amount'] or 0 for c in cs)
        project_sum=sum(p['amount'] or 0 for p in ps)
        detail_sum=sum(l['amount'] for l in ls)
        if left_sum!=original['amount_delta']:reasons.append('Left setsu sum differs from printed moku delta')
        if project_sum!=original['amount_delta']:reasons.append('Printed project sum differs from printed moku delta')
        if detail_sum!=original['amount_delta']:reasons.append('Explanation setsu sum differs from printed moku delta')
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
        # Reserve has an actually printed explanation and project but an empty
        # statutory setsu column. Keep that different grain, never invent a code.
        reserve_exception = (original['moku_label']=='予備費' and not cs and bool(ps) and bool(ls)
            and all(project_ok[p['source_row']] for p in ps)
            and all(l['setsu_label']=='予備費' for l in ls)
            and project_sum==detail_sum==original['amount_delta']
            and not any(p['moku']==key for p in problems))
        reserve_exceptions[key]=reserve_exception
        moku_status[key]=(not reasons,reasons)
        moku_checks.append(dict(moku=key,moku_label=original['moku_label'],printed_delta=original['amount_delta'],
            printed_projects_sum=project_sum,explanation_setsu_sum=detail_sum,left_setsu_sum=left_sum,
            project_rows=len(ps),setsu_rows=len(ls),complete=not reasons,reasons=reasons,setsu_checks=setsu_checks,
            observed_grain_complete=not reasons or reserve_exception,
            grain_exception='Printed reserve explanation; statutory setsu column empty' if reserve_exception else None,
            original_control=original))
    for i,l in enumerate(leaves,1):
        p=l['project'];key=l['moku'];original=moku_controls[key];complete,reasons=moku_status[key]
        matched=left_matches.get((key,l['setsu_label']))
        output.append(dict(source_row=i,jurisdiction_code='132195',fiscal_year=candidate['fiscal_year'],fund_label=candidate['fund_label'],
            amendment_number=candidate['amendment_number'],source_url=candidate['url'],origin_sha256=candidate['expected_sha256'],
            origin_fetched_at=candidate.get('fetched_at'),submitted_date=candidate.get('submitted_at'),
            approval_status=control['approval_status'],edition_status=control['edition_status'],
            approval_date=control['effective_at'],approval_evidence_json=json.dumps(control['approval_evidence'],ensure_ascii=False),
            kan_code=str(key[0]),kou_code=str(key[1]),moku_code=str(key[2]),moku_label=original['moku_label'],
            control_moku_source_row=original['source_row'],control_moku_key='-'.join(map(str,key)),control_moku_json=json.dumps(original,ensure_ascii=False),
            project_source_row=p['source_row'],project_code=p['code'],project_label=p['label'],project_printed_delta=p['amount'],
            project_evidence_json=json.dumps(p['locations'],ensure_ascii=False),department_text=l['department'],
            setsu_code=matched['code'] if matched else None,setsu_label=l['setsu_label'],amount_delta=l['amount'],
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
    article=control['first_article']['amount_delta']
    totals=dict(first_article=article,all_moku_sum=sum(c['amount_delta'] for c in moku_controls.values()),
                printed_project_sum=sum(p['amount'] or 0 for p in projects),explanation_setsu_sum=sum(l['amount'] for l in leaves),
                left_setsu_sum=sum(c['amount'] or 0 for c in left_controls))
    fully_complete=bool(output) and all(c['complete'] for c in moku_checks) and all(v==article for v in totals.values()) and not problems
    reserve_control_sum=sum(moku_controls[k]['amount_delta'] for k,v in reserve_exceptions.items() if v)
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
        approval_date=control['effective_at'],first_article_evidence=control['first_article'],moku_header_locations=header_boxes)


def materialize(directory, result, candidate):
    allowed = [WORK_DIR.resolve(), (REPO/'pipeline/.cache/acquisition/raw/supplementary-detail').resolve()]
    if not any(directory.resolve().is_relative_to(root) for root in allowed):
        raise ValueError('Output must stay in isolated detail work or supplementary-detail acquisition cache')
    directory.mkdir(parents=True,exist_ok=True)
    parquet=directory/'data.parquet'
    with duckdb.connect() as con:
        con.execute('create table t ('+','.join(f'{k} {v}' for k,v in COLUMNS.items())+')')
        if result['rows']:
            con.executemany('insert into t values ('+','.join('?' for _ in COLUMNS)+')',[[r.get(k) for k in COLUMNS] for r in result['rows']])
        con.execute('copy (select * from t order by source_row) to ? (format parquet, compression zstd)',[str(parquet)])
    evidence={**{k:v for k,v in result.items() if k!='rows'},'candidate':candidate,'rows':len(result['rows']),'table_id':TABLE_ID,
        'source_grain':'printed project × expenditure setsu × printed department occurrence; explicit printed reserve exceptions',
        'source_amount_unit':'千円','header':COLUMNS,'extractor':f'extract_supplementary_expenditure.py@{VERSION}',
        'parquet_sha256':hashlib.sha256(parquet.read_bytes()).hexdigest(),'raw_form':'extracted','roundtrip_verified':False,
        'normalization':['NFKC and whitespace removal for exact name comparisons; original printed labels/amounts/locations retained'],
        'adoption_status':'candidate-only','baseline_status':'unconfirmed','nonadditive_with':['expenditure-detail','expenditure-moku-changes-all']}
    record_input(directory, evidence)
    return evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--describe',action='store_true')
    parser.add_argument('--manifest',type=Path,help='Optional exploratory manifest; default uses Git-managed supplementary_detail sources.toml')
    parser.add_argument('--origins-dir',type=Path,help='Optional exploratory origin directory; default uses fixed origin SHA cache')
    parser.add_argument('--output-dir',type=Path,default=WORK_DIR)
    parser.add_argument('--dry-run',action='store_true',help='Validate finite selection and paths without extraction or writes')
    parser.add_argument('--fiscal-year',type=int)
    parser.add_argument('--fund-label')
    parser.add_argument('--amendment-number',type=int)
    args=parser.parse_args()
    if args.describe:
        print(json.dumps(dict(table_id=TABLE_ID,columns=COLUMNS,inputs=['canonical sources.toml (default)','manifest?','origins_dir?','output_dir','fiscal_year?','fund_label?','amendment_number?'],
            candidate_required_fields=['coverage_source_id','fiscal_year','fund_label','amendment_number','url',
                'expected_sha256','first_page','last_page','approval_status','edition_status'],
            scope='cover-approved FY2023–26 Komae ordinary-account supplementary candidates only; partial detail remains unconfirmed',
            write_scope=[str(WORK_DIR),str(REPO/'pipeline/.cache/acquisition/raw/supplementary-detail')],
            origin_source='immutable fixed origin SHA cache by default; restore fixed inputs before extraction',
            exit_codes={'0':'finite wave completed; edition rejects/partial outcomes remain explicit','2':'invalid selection/input'},
            delta_semantics='Actually printed signed explanation setsu amount; project and moku totals are controls, not additive rows'),ensure_ascii=False));return
    allowed = [WORK_DIR.resolve(), (REPO/'pipeline/.cache/acquisition/raw/supplementary-detail').resolve()]
    if not any(args.output_dir.resolve().is_relative_to(root) for root in allowed):
        raise ValueError('Output directory must stay in isolated detail work or supplementary-detail acquisition cache')
    if args.manifest:
        candidates=tomllib.loads(args.manifest.read_text())['supplementary_moku_expansion']['adopted_candidates']
    else:
        from ingestion.fiscal.sources import load_supplementary_detail
        candidates=[dict(spec,fiscal_year=int(key.split(':')[1]),edition_status='published',
                         submitted_at=spec['submitted_at']) for key,spec in load_supplementary_detail().items()]
    selected=[c for c in candidates if (args.fiscal_year is None or c['fiscal_year']==args.fiscal_year)
        and (args.fund_label is None or c['fund_label']==args.fund_label)
        and (args.amendment_number is None or c['amendment_number']==args.amendment_number)]
    if not selected:
        raise ValueError('No cover-approved candidate matches the finite selection')
    if args.dry_run:
        for c in selected: validate_candidate(c)
        print(json.dumps(dict(status='dry-run',editions=len(selected),output_dir=str(args.output_dir)),ensure_ascii=False));return
    outcomes=[]
    for c in selected:
        out=dict(id=c['coverage_source_id'],year=c['fiscal_year'],account=c['fund_label'],issue=c['amendment_number'],url=c['url'],sha256=c['expected_sha256'])
        try:
            if args.origins_dir or args.manifest:
                pdf=(args.origins_dir or REPO/'.agent/komae-history-expansion/origins')/c['coverage_source_id']/'origin.pdf'
            else:
                from ingestion.inputs import origin_path
                pdf=origin_path(c['expected_sha256'])
            result=extract(pdf,c)
            directory=args.output_dir/'raw'/f'year={c["fiscal_year"]}/account={c["fund_label"]}/amendment={c["amendment_number"]}/edition={c["expected_sha256"]}'
            evidence=materialize(directory,result,c)
            out.update(status=('validated-candidate' if result['fully_complete'] else
                'validated-candidate-with-reserve-exception' if result['fully_complete_observed_grain'] else 'partial-unconfirmed'),
                rows=len(result['rows']),complete_rows=result['complete_rows'],complete_moku=result['complete_moku'],moku_count=result['moku_count'],
                totals=result['totals'],reserve_grain_checks=result['reserve_grain_checks'],
                fully_complete_observed_grain=result['fully_complete_observed_grain'],
                raw_path=str(directory),problems=result['parser_problems'])
        except (ValueError,OSError,subprocess.CalledProcessError,duckdb.Error) as error:out.update(status='rejected',reason=str(error))
        outcomes.append(out)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    name='wave-results'+(f'-{args.fiscal_year}' if args.fiscal_year else '')+('.json')
    (args.output_dir/name).write_text(json.dumps(outcomes,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(editions=len(outcomes),rows=sum(o.get('rows',0) for o in outcomes),complete_rows=sum(o.get('complete_rows',0) for o in outcomes),
        fully_complete=sum(o['status']=='validated-candidate' for o in outcomes),
        complete_observed_grain=sum(o.get('fully_complete_observed_grain',False) for o in outcomes),
        outcomes_file=str(args.output_dir/name)),ensure_ascii=False))


if __name__=='__main__':
    try:
        main()
    except (ValueError,OSError,KeyError,tomllib.TOMLDecodeError) as error:
        print(json.dumps(dict(status='error',reason=str(error)),ensure_ascii=False),file=sys.stderr)
        sys.exit(2)
