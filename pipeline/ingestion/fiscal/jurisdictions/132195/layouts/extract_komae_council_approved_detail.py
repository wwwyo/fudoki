"""Finite Komae council-approved original project/printed-setsu extraction.

Separate from the frozen pilot and cover-approved wave; explicit original bytes,
numbered proposal/report identity and official resolution evidence are required.
No cabinet draft is promoted by later same-number approval. Existing monetary
geometry and independent controls are reused without changing their helpers.
"""
from __future__ import annotations

from importlib import import_module as _ingestion_module
from ingestion.inputs import record_input
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import duckdb
from ingestion.fiscal.management.history_expansion import extract_document
from ingestion.fiscal.layouts.fiscal_general.extract_supplementary_expenditure import COLUMNS as BASE_COLUMNS, norm, text, location, number, split_amount, validate
from ingestion.lib.pdf import chars_of, rows_of

VERSION = 2
TABLE_ID = 'supplementary-expenditure-project-setsu-council-original'
REPO = Path(__file__).resolve().parents[6]
WORK_DIR = REPO / '.agent/komae-approved-expansion'
CANONICAL_DIR = REPO / 'pipeline/.cache/acquisition/raw/council-approved-detail'
INTEGRATION_DIR = REPO / '.agent/komae-council-integration'
COLUMNS = {**BASE_COLUMNS, 'council_resolution_date':'VARCHAR',
    'printed_submission_date':'VARCHAR', 'executive_disposition_date':'VARCHAR',
    'effective_date':'VARCHAR', 'effective_date_basis':'VARCHAR',
    'approval_url':'VARCHAR', 'resolution_id':'VARCHAR',
    'original_cover_approval_status':'VARCHAR', 'approval_proof_json':'VARCHAR',
    'setsu_name_match_basis':'VARCHAR'}

def validate_candidate(c):
    if c.get('fiscal_year') not in range(2020,2027):raise ValueError('Finite Reiwa FY2020-2026 only')
    if c.get('fund_label') not in {'一般会計','国民健康保険特別会計','後期高齢者医療特別会計','介護保険特別会計','駐車場事業特別会計'}:
        raise ValueError('Enterprise or unidentified accounts are outside this grain')
    if not re.fullmatch(r'[0-9a-f]{64}',c.get('expected_sha256','')):raise ValueError('Explicit whole original SHA required')
    if not c.get('url','').startswith('https://www.city.komae.tokyo.jp/'):raise ValueError('Official original URL required')
    if not isinstance(c.get('amendment_number'),int) or c['amendment_number']<1:raise ValueError('Positive explicit amendment required')
    if not (isinstance(c.get('first_page'),int) and isinstance(c.get('last_page'),int) and 1<=c['first_page']<=c['last_page']):raise ValueError('Physical whole-account bounds required')
    if c.get('approval_status')!='council-approved-original' or c.get('edition_status')!='published':raise ValueError('Approved original only; drafts remain held')
    p=c.get('approval_proof',{})
    if [p.get(k) for k in ('fiscal_year','account','amendment_number')] != [c['fiscal_year'],c['fund_label'],c['amendment_number']]:raise ValueError('Resolution edition identity differs')
    if not re.fullmatch(r'(議案|報告)第[0-9]+号',p.get('resolution_id','')):raise ValueError('Exact numbered resolution required')
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',p.get('resolution_date','')):raise ValueError('Resolution date required')
    if not p.get('resolution_evidence') or not p.get('original_identity_evidence'):raise ValueError('Resolution and original version evidence required')

def verify_reference(e):
    url=e.get('url','')
    if not any(url.startswith(s) for s in ('https://www.city.komae.tokyo.jp/','https://www.city.komae.tokyo.dbsr.jp/')):raise ValueError('Nonofficial proof URL')
    if 'object_key' in e:
        from ingestion.inputs import origin_path
        if e['object_key']!='inputs/origin/sha256/'+e['sha256']:
            raise ValueError('Approval object key differs from fixed SHA')
        path=origin_path(e['sha256'])
        if path.stat().st_size!=e['bytes']:raise ValueError('Approval object size differs')
    else:
        path=Path(e['local_path']).resolve()
        if not path.is_relative_to((REPO/'.agent').resolve()):raise ValueError('Proof objects must be isolated repository acquisition files')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=e['sha256']:raise ValueError('Proof object SHA differs')
    loc=e['location'];observed=norm(e['observed_text'])
    if not observed:raise ValueError('Empty observed proof')
    if 'physical_pdf_page' in loc:
        page=loc['physical_pdf_page']
        raw=subprocess.run(['pdftotext','-layout','-f',str(page),'-l',str(page),str(path),'-'],capture_output=True,check=True).stdout.decode()
        original=norm(raw)
    elif 'voice_code' in loc:
        raw=path.read_text();voice=loc['voice_code']
        m=re.search(r'<li class="voice-block[^>]*data-voice_code="'+str(voice)+r'"[^>]*>(.*?)</li>',raw,re.S)
        if not m:raise ValueError('Indexed approval voice absent')
        original=norm(html.unescape(re.sub('<[^>]*>','',m[1])))
    else:raise ValueError('Proof requires physical PDF page or indexed HTML voice')
    if observed not in original:raise ValueError('Observed approval/original text differs from indexed source bytes')
    return original

def verify_approval(c,pdf,control):
    p=c['approval_proof'];title=f"令和{c['fiscal_year']-2018}年度狛江市{c['fund_label']}補正予算(第{c['amendment_number']}号)"
    if '計数整理中' in control['printed_cover_text']:raise ValueError('Unfinished original counts cannot be waived')
    origins=[verify_reference(e) for e in p['original_identity_evidence']]
    if not any(title in t and p['resolution_id'] in t for t in origins):raise ValueError('Numbered original proposal/report must name exact title')
    if not any(e['sha256']==c['expected_sha256'] and e['url']==c['url'] for e in p['original_identity_evidence']):raise ValueError('Original byte edition is not explicitly bound to resolution proof')
    for e in p['resolution_evidence']:verify_reference(e)
    # Only the indexed observed decision, never another resolution on the
    # same PDF page, may establish approval of this numbered original.
    resolution=''.join(norm(e['observed_text']) for e in p['resolution_evidence'])
    if p['resolution_id'] not in resolution:raise ValueError('Resolution number absent in decision evidence')
    voted = any(s in resolution for s in ('原案可決','原案のとおり可決されました','承認されました','承認することに決しました'))
    if p['resolution_id'].startswith('報告'):
        voted = any(s in resolution for s in ('承認されました','承認することに決しました')) or ('専決処分の承認を求める' in resolution and resolution.count('承認')>=2)
    if not voted:raise ValueError('Completed council approval required; approval-request title alone is insufficient')
    year,month,day=map(int,p['resolution_date'].split('-'))
    for e in p['resolution_evidence']:
        if 'voice_code' in e['location']:
            anchor=re.search(r'VoiceExpand1=r(\d+)-(\d{2})(\d{2})_',e['url'])
            if not anchor or (2018+int(anchor[1]),int(anchor[2]),int(anchor[3]))!=(year,month,day):raise ValueError('Indexed meeting date differs from resolution date')
        elif f'{month}月{day}日' not in norm(e['observed_text']) or f'令和{year-2018}年' not in norm(e['observed_text']):
            raise ValueError('Resolution table header and decision date must be observed together')
        else:
            decision='承認' if p['resolution_id'].startswith('報告') else '原案可決'
            lines=[norm(line) for line in e['observed_text'].splitlines()]
            target=[line for line in lines if p['resolution_id'] in line]
            if len(target)!=1 or f'{month}月{day}日{decision}' not in target[0]:
                raise ValueError('Exact numbered PDF decision row/date must independently match')
            prefix=title.split('(第')[0]
            if prefix not in norm(e['observed_text']) or f'(第{c["amendment_number"]}号)' not in norm(e['observed_text']):
                raise ValueError('Indexed PDF resolution evidence must name this account/year/issue')
    # Speaker evidence may omit the title at the final vote; indexed original
    # and the exported exact same numbered agenda bind that case separately.
    if p['resolution_id'].startswith('報告'):
        if control['submitted_basis']!='専決' or p.get('executive_disposition_date')!=control['submitted_at']:raise ValueError('Executive disposition report needs exact printed disposition date')
        y,m,d=map(int,control['submitted_at'].split('-'))
        if not any(f'令和{y-2018}年{m}月{d}日' in t for t in origins):raise ValueError('Report must explicitly identify the printed disposition date')

def validate_printed_labels(candidate,control,moku_controls,projects,leaves,left_controls,problems,units,header_boxes):
    # Two observed statutory labels have comma glyph/column-split variants.
    # The left-cell splitter omits the trailing comma on a wrapped label;
    # original location.printed_text retains it. Preserve labels and locations;
    # require the complete, named legal label and unchanged monetary controls.
    aliases={'負担金,補助及び交付金':'負担金、補助及び交付金',
             '負担金補助及び交付金':'負担金、補助及び交付金',
             '償還金,利子及び割引料':'償還金、利子及び割引料',
             '償還金利子及び割引料':'償還金、利子及び割引料'}
    adjusted=[]
    for leaf in leaves:
        adjusted.append({**leaf,'setsu_label':aliases.get(leaf['setsu_label'],leaf['setsu_label'])})
    left=[{**c,'label':aliases.get(c['label'],c['label']),
           'original_printed_label':c['label']} for c in left_controls]
    result=validate(candidate,control,moku_controls,projects,adjusted,left,problems,units,header_boxes)
    for row,original in zip(result['rows'],leaves,strict=True):
        row['setsu_label']=original['setsu_label']
        match=json.loads(row['left_setsu_evidence_json'])
        left_original=match.get('original_printed_label')
        changed=left_original is not None and left_original!=original['setsu_label']
        row['setsu_name_match_basis']='explicit-two-legal-label-comma-wrap-alias' if changed else 'exact-printed-name'
        if changed:row['setsu_correspondence_status']='printed-name-comma-wrap-equivalent'
    return result


def bind_approval(result,c,control):
    p=c['approval_proof'];date=control['submitted_at'];executive=date if control['submitted_basis']=='専決' else None
    for row in result['rows']:
        row.update(approval_status='council-approved-original',approval_date=p['resolution_date'],
            approval_evidence_json=json.dumps(p['resolution_evidence'],ensure_ascii=False),
            council_resolution_date=p['resolution_date'],printed_submission_date=date,
            executive_disposition_date=executive,effective_date=executive,
            effective_date_basis='printed-executive-disposition-date' if executive else 'unconfirmed-parent-recording-contract',
            approval_url=p['resolution_evidence'][0]['url'],resolution_id=p['resolution_id'],
            original_cover_approval_status=control['approval_status'],approval_proof_json=json.dumps(p,ensure_ascii=False))
    result.update(approval_date=p['resolution_date'],approval_evidence=p['resolution_evidence'],
        council_resolution_date=p['resolution_date'],printed_submission_date=date,
        executive_disposition_date=executive,effective_date=executive,
        effective_date_basis='printed-executive-disposition-date' if executive else 'unconfirmed-parent-recording-contract',
        original_cover_approval_status=control['approval_status'],source_page_range=control['source_page_range'],
        approval_proof=p,nonadditive_with=['expenditure-moku-changes-all','expenditure-detail'])
    return result

def extract(pdf: Path, candidate: dict) -> dict:
    validate_candidate(candidate)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if sha != candidate['expected_sha256']:
        raise ValueError('Official edition SHA differs from candidate manifest')
    control = extract_document(pdf, candidate['amendment_number'],
        fiscal_year=candidate['fiscal_year'], fund_label=candidate['fund_label'],
        source_url=candidate['url'], expected_sha256=sha,
        first_page=candidate['first_page'], last_page=candidate['last_page'])
    if control['edition_status'] == 'preliminary-counts':
        raise ValueError('Preliminary cabinet bytes cannot be promoted by later approval')
    candidate = {**candidate, 'submitted_at': control['submitted_at']}
    verify_approval(candidate, pdf, control)
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
    result = validate_printed_labels(candidate,control,moku_controls,projects,leaves,left_controls,problems,units,header_boxes)
    return bind_approval(result, candidate, control)


def materialize(directory,result,candidate):
    if not any(directory.resolve().is_relative_to(root.resolve()) for root in [WORK_DIR,CANONICAL_DIR,INTEGRATION_DIR]):
        raise ValueError('Output must stay in council acquisition or approved private verification directories')
    if not result['fully_complete_observed_grain']:raise ValueError('Whole observed-grain reconciliation required before materialization')
    directory.mkdir(parents=True,exist_ok=True)
    parquet=directory/'data.parquet'
    with duckdb.connect() as con:
        con.execute('create table t ('+','.join(f'{k} {v}' for k,v in COLUMNS.items())+')')
        con.executemany('insert into t values ('+','.join('?' for _ in COLUMNS)+')',[[r.get(k) for k in COLUMNS] for r in result['rows']])
        con.execute('copy (select * from t order by source_row) to ? (format parquet, compression zstd)',[str(parquet)])
    proof={**{k:v for k,v in result.items() if k!='rows'},'candidate':{k:v for k,v in candidate.items() if k!='pdf_path'},'rows':len(result['rows']),
        'table_id':candidate.get('table_id',TABLE_ID),'table_family':TABLE_ID,'header':COLUMNS,'parquet_sha256':hashlib.sha256(parquet.read_bytes()).hexdigest(),
        'extractor':f'extract_komae_council_approved_detail.py@{VERSION}',
        'dependencies':['history_expansion.py@1','extract_supplementary_expenditure.py@1'],
        'adoption_status':'candidate-only','baseline_status':'unconfirmed','source_amount_unit':'千円','raw_form':'extracted','roundtrip_verified':False}
    if candidate.get('source_key'):
        proof.update(source_key=candidate['source_key'],request_url=candidate['url'],sha256=candidate['expected_sha256'],
            fetched_at=candidate['fetched_at'],jurisdiction_code='132195',fiscal_year=candidate['fiscal_year'],
            fund_label=candidate['fund_label'],amendment_number=candidate['amendment_number'],
            document_kind='supplementary',direction='expenditure',pages=[candidate['first_page'],candidate['last_page']],
            document_title=candidate['document_title'],resource_name=candidate['document_title'],
            grain='printed project × expenditure setsu × department occurrence; explicit blank-code reserve exception',
            verification='independent-signed-moku-triples-project-right-left-legal-first-article-with-printed-reserve-exception-and-exact-numbered-approval',
            unit_multiplier=1000,observation_role='authoritative-council-supplementary-detail',
            effective_at=result['effective_date'],effective_at_basis=result['effective_date_basis'],
            extraction_evidence=dict(rows_one_to_one=True,reserve_exception_rows=candidate['reserve_exception_rows'],
                source_locations_column='source_locations_json',printed_value_column='printed_amount_text',unit_column='source_amount_unit'))
    record_input(directory, proof)
    return proof

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--describe',action='store_true');parser.add_argument('--manifest',type=Path)
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--fiscal-year',type=int);parser.add_argument('--fund-label');parser.add_argument('--amendment-number',type=int)
    args=parser.parse_args()
    if args.describe:
        print(json.dumps({'version':VERSION,'table_id':TABLE_ID,'columns':COLUMNS,'inputs':['default: Git sources-council-approved.json plus immutable origin/approval SHA cache','manifest?: finite exploratory candidates','output_dir?','dry_run?','fiscal_year?','fund_label?','amendment_number?'],'boundary':'Canonical scope exactly six Unicode approved original editions; native/manual recovery excluded; no preliminary waiver; full observed-grain required','canonical_proof_restore':'python -m ingestion.fiscal.jurisdictions.132195.layouts.council_approved_provider --restore-evidence --remote','exit_codes':{'0':'canonical contracts passed or finite exploratory outcomes recorded','1':'canonical byte/count/grain/proof contract failed','2':'invalid manifest/selection/path'}},ensure_ascii=False));return 0
    try:
        if args.manifest:candidates=json.loads(args.manifest.read_text())['candidates']
        else:
            canonical_candidates = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.council_approved_provider').canonical_candidates
            candidates=canonical_candidates()
        args.output_dir=args.output_dir or (WORK_DIR/'raw' if args.manifest else CANONICAL_DIR)
        if not any(args.output_dir.resolve().is_relative_to(root.resolve()) for root in [WORK_DIR,CANONICAL_DIR,INTEGRATION_DIR]):
            raise ValueError('Output outside supported council acquisition/verification directories')
        candidates=[c for c in candidates if (args.fiscal_year is None or c['fiscal_year']==args.fiscal_year)
            and (args.fund_label is None or c['fund_label']==args.fund_label)
            and (args.amendment_number is None or c['amendment_number']==args.amendment_number)]
        if not candidates:raise ValueError('No approved original editions match selection')
        for c in candidates:validate_candidate(c)
    except (ValueError,KeyError,OSError) as e:parser.error(str(e))
    if args.dry_run:print(json.dumps({'status':'validated-manifest-only','candidates':len(candidates)},ensure_ascii=False));return 0
    results=[]
    for c in candidates:
        summary={'fiscal_year':c['fiscal_year'],'fund_label':c['fund_label'],'amendment_number':c['amendment_number'],'url':c['url'],'sha256':c['expected_sha256'],'physical_page_range':[c['first_page'],c['last_page']]}
        try:
            result=extract(Path(c['pdf_path']),c)
            summary.update({k:v for k,v in result.items() if k!='rows'})
            if result['fully_complete_observed_grain']:
                out=args.output_dir/f"year={c['fiscal_year']}"/f"account={c['fund_label']}"/f"issue={c['amendment_number']}"/f"edition={c['expected_sha256']}"
                proof=materialize(out,result,c);summary.update(status='passed-candidate',rows=len(result['rows']),raw_path=str(out),parquet_sha256=proof['parquet_sha256'])
                if not args.manifest and (proof['parquet_sha256']!=c['expected_table_sha256'] or proof['rows']!=c['expected_rows']
                    or sum(r['setsu_code'] is None for r in result['rows'])!=c['reserve_exception_rows']):
                    raise ValueError('Canonical table SHA/count/printed-reserve contract differs')
            else:
                summary.update(status='held-incomplete-observed-grain',observed_rows=len(result['rows']))
                diagnostic=WORK_DIR/'diagnostics'/f"{c['fiscal_year']}-{c['fund_label']}-{c['amendment_number']}.json";diagnostic.parent.mkdir(parents=True,exist_ok=True);diagnostic.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        except Exception as e:summary.update(status='held-extraction-or-proof-gap',reason=str(e))
        results.append(summary)
        print(json.dumps({k:summary[k] for k in ('fiscal_year','fund_label','amendment_number','status','rows','observed_rows','reason') if k in summary},ensure_ascii=False),flush=True)
    args.output_dir.mkdir(parents=True,exist_ok=True);(args.output_dir/'wave-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    return 1 if not args.manifest and any(r['status']!='passed-candidate' for r in results) else 0
if __name__=='__main__':sys.exit(main())
