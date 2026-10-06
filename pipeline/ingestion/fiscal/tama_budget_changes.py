"""Native Tama supplementary candidates; signed changes never become adjusted totals.

Sources and account editions come exclusively from sources.json. This command
writes scratch candidates and never adopts inputs or assigns approval.
"""
from __future__ import annotations

import argparse
from http.client import HTTPException
import json
from pathlib import Path
import re
import subprocess

from ingestion.fiscal.source_registry import INVENTORY, load_registry
from ingestion.fiscal.tama_budget_detail import (location, money_cell, normalize, number,
    positioned_rows, reconcile, write_table)
from ingestion.inputs import OBJECTS, digest, encode, record_input, save_object
from ingestion.lib.pdf import pages_of
from ingestion.paths import REPO

NAMESPACE = 'tama-supplementary-native-candidate'
DEFAULT_OUTPUT = Path('/private/tmp/fudoki-tama-supplementary')


def inspect_original(pdf: Path, source: dict) -> dict:
    """Read one immutable original once, validating every declared account article."""
    spec = source['content_inspection']
    body = pdf.read_bytes()
    if digest(body) != spec['sha256'] or len(body) != spec['bytes']:
        raise ValueError('Original SHA256/bytes differ from sources.json')
    texts = subprocess.run(['pdftotext','-layout',str(pdf),'-'],
        check=True,capture_output=True).stdout.decode('utf-8').split('\f')
    if texts and not texts[-1].strip():
        texts.pop()
    pages = pages_of(pdf,1,spec['pages'])
    if len(texts) != spec['pages'] or len(pages) != spec['pages']:
        raise ValueError('Declared/native text/native bbox page counts differ')
    normalized = [normalize(t) for t in texts]
    editions = []
    all_starts = sorted({e['page'] for e in source['editions'] if e.get('page')})
    for edition in source['editions']:
        if (edition['in_scope']['status'] != 'included' or
            edition['document_phase'] != 'supplementary'):
            continue
        article_page = edition['page']
        article = normalized[article_page-1]
        year = f'令和{edition["fiscal_year"]-2018}年度'
        title = year+'多摩市'+edition['account_label']+'補正予算(第'+str(edition['amendment_number'])+'号)'
        if title not in article or '第1条' not in article:
            raise ValueError(f'Declared account/year/issue article differs on page {article_page}')
        bill = re.search(r'第(\d+)号議案',article)
        delta = re.search(r'歳入歳出それぞれ([\d,]+)千円を(追加|増額|減額)',article)
        if not bill or not delta:
            raise ValueError(f'Printed bill or first-article signed delta absent: {title}')
        end = min((n-1 for n in all_starts if n>article_page),default=len(pages))
        starts = [n for n in range(article_page,end+1)
                  if any(normalize(line)=='3歳出' for line in texts[n-1].splitlines())]
        if len(starts) != 1:
            raise ValueError(f'Account has no unique printed expenditure section: {title}')
        first = starts[0]
        stop = min((n for n in range(first+1,end+1)
                    if '給与費明細書' in normalized[n-1] or
                    normalized[n-1].startswith(('継続費について','繰越明許費について','債務負担行為について','債務負担行為で','地方債について','地方債の前')) or
                    re.match(r'第[234](?:表)?(?:継続費|債務負担|地方債)',normalized[n-1])),default=end+1)
        last = stop-1
        # Blank separators following a complete facing pair are not table pages.
        while last>first and not any(w[1]<pages[last-1][1]*.88 for w in pages[last-1][2]):
            last-=1
        if (last-first+1)%2:
            raise ValueError(f'Expenditure section does not end at a complete facing pair: {first}-{last}')
        total_delta = number(delta[1])*(-1 if delta[2]=='減額' else 1)
        editions.append(dict(edition=edition,article_page=article_page,bill=int(bill[1]),
            first=first,last=last,printed_delta=total_delta,article_text=texts[article_page-1]))
    return dict(source=source,sha256=spec['sha256'],pages=pages,texts=texts,editions=editions)


def supplementary_layout(left, right, previous=None):
    """Locate the three signed operands by printed supplementary headers and units."""
    for title in ('補正前の額','補正額','計'):
        if not any(title in normalize(row['text']) for row in left):
            raise ValueError('Supplementary printed operand header absent: '+title)
    units = [w for r in left for w in r['words'] if normalize(w[4])=='千円']
    runits = [w for r in right for w in r['words'] if normalize(w[4])=='千円']
    if not runits and previous is not None and any('予備費' in normalize(r['text']) for r in right):
        runits=[(previous['setsu_right']-15,min(w[1] for w in units),previous['setsu_right'],min(w[1] for w in units)+8,'千円'),
                (previous['explanation_right']-15,min(w[1] for w in units),previous['explanation_right'],min(w[1] for w in units)+8,'千円')]
    if not units or not runits:
        raise ValueError('Printed supplementary amount-unit headers absent')
    ly,ry=min(w[1] for w in units),min(w[1] for w in runits)
    units=sorted([w for w in units if abs(w[1]-ly)<1],key=lambda w:w[0])
    runits=sorted([w for w in runits if abs(w[1]-ry)<1],key=lambda w:w[0])
    if len(units)!=7 or len(runits)!=2:
        raise ValueError('Expected seven left and two right supplementary amount columns')
    split=(runits[0][2]+runits[1][0])/2
    starts=[w[0] for r in right if r['y']>ry for w in r['words']
        if runits[0][2]+2<w[0]<split and
        (normalize(w[4]).startswith('【') or re.fullmatch(r'\d{3}',normalize(w[4])))]
    heads=[w[0] for r in left for w in r['words'] if normalize(w[4])=='補正前の額']
    if not starts and previous is not None:
        if abs(previous['setsu_right']-runits[0][2])<1.5 and abs(previous['explanation_right']-runits[1][2])<1.5:
            starts=[previous['explanation_left']+1]
    if not starts or not heads:
        raise ValueError(f'No native explanation project or moku operand column on pair {left[0]["page"]}-{right[0]["page"]}')
    return dict(moku_right=min(heads),current_right=units[1][2],
        operand_rights=[w[2] for w in units[:3]],left_unit_y=ly,right_unit_y=ry,
        explanation_left=min(starts)-1,setsu_right=runits[0][2],explanation_right=runits[1][2],
        right_y_scale=(units[0][2]-units[0][0])/(runits[0][2]-runits[0][0]))


def _extract_rows(pages, first: int, last: int):
    if first < 1 or last < first or (last-first+1) % 2:
        raise ValueError('Expenditure range must contain complete facing-page pairs')
    if len(pages) != last-first+1:
        raise ValueError('PDF does not contain the declared full range')
    records, problems = [], []
    kan = kou = moku = project = setsu = None
    department = ''
    controls = {}
    left_setsu = None
    repeated_label = None
    previous_cols = None

    def finish_label():
        nonlocal repeated_label
        if repeated_label is not None and repeated_label['label'] != moku['label']:
            problems.append(dict(page=repeated_label['page'],reason='Repeated moku label differs',
                                 printed=repeated_label['label'],prior=moku['label']))
        repeated_label = None

    def emit(kind, row, words, code=None, label=None, amount=None):
        obj = dict(source_row=len(records)+1, record_kind=kind, code=code, label=label,
                   amount=amount, amount_text=None, kan=kan, kou=kou, moku=moku,
                   project=project, setsu=setsu, department=department,
                   location=location(row,words))
        records.append(obj)
        return obj

    for offset in range(0,len(pages),2):
        left = positioned_rows(pages[offset],first+offset)
        right = positioned_rows(pages[offset+1],first+offset+1)
        for r in left:
            if re.fullmatch(r'\d*(?:款|項).+',normalize(r['text'])) and not normalize(r['text']).endswith('千円'):
                nearby=[a for a in left if abs(a['y']-r['y'])<2 and re.fullmatch(r'[△▲−\-]?[\d,]+千円',normalize(a['text']))]
                if len(nearby)==1:
                    r['words']=sorted(r['words']+nearby[0]['words'],key=lambda w:w[0]);r['text']=''.join(w[4] for w in r['words'])
        cols = supplementary_layout(left,right,previous_cols)
        previous_cols=cols
        events = sorted([(r['y'],0,r) for r in left]+[
            ((cols['left_unit_y']+(r['y']-cols['right_unit_y'])*cols['right_y_scale']) if abs(cols['left_unit_y']-cols['right_unit_y'])>5 else r['y'],1,r)
            for r in right])
        for _, side, row in events:
            words = row['words']
            whole = normalize(row['text'])
            if (row['y'] > row['height']*.88 and
                (whole.endswith('特別会計') or
                 (whole == str(row['page']) and .4*row['width'] < words[0][0] < .6*row['width']))):
                continue
            if '歳出予算書_事項別明細書' in whole:
                emit('page-artifact',row,words,label=whole)
                continue
            if side == 0:
                heading = re.fullmatch(r'(\d*)(款|項)(.+?)([△▲−\-]?[\d,]+)千円',whole)
                if heading:
                    code,kind,label,total = heading.groups()
                    code = code or None
                    if not code:
                        finish_label()
                        moku = project = setsu = left_setsu = None
                    if kind == '款':
                        kan, kou = (code,label), None
                    else:
                        kou = (code,label)
                    emit('kan' if kind=='款' else 'kou',row,words,code,label,number(total))
                    continue
                if row['y'] <= cols['left_unit_y']:
                    continue
                names = [w for w in words if w[0] < cols['moku_right']]
                numbered = names and re.fullmatch(r'\d+',normalize(names[0][4])) and len(names)>1 and re.search(r'[一-龯ぁ-ゖァ-ヺ]',names[1][4])
                retired = (names and normalize(names[0][4]) != '計' and kou and kou[0] is None
                           and money_cell(words,cols['current_right']) is not None)
                if numbered or retired:
                    if kan is None or kou is None:
                        raise ValueError('Printed moku lacks kan/kou context')
                    finish_label()
                    code = normalize(names[0][4]) if numbered else None
                    label = normalize(''.join(w[4] for w in (names[1:] if numbered else names)))
                    key = (kan[0],kou[0],code)
                    changed = moku is None or moku['key'] != key
                    if changed:
                        moku = dict(key=key,code=code,label=label)
                        project = setsu = left_setsu = None
                        department = ''
                    amount = money_cell(words,cols['current_right'])
                    operands = [money_cell(words,edge) for edge in cols['operand_rights']]
                    if amount:
                        if not all(operands):
                            raise ValueError(f'Incomplete printed moku operands on page {row["page"]}: {key}')
                        before, delta, after = [number(w[4]) for w in operands]
                        if before + delta != after:
                            raise ValueError(f'Printed moku before + delta differs from after: {key}')
                        moku.update(amount_before=before,amount_delta=delta,amount_after=after,
                                    operand_words=operands)
                        if key in controls:
                            raise ValueError('Repeated printed moku amount: '+str(key))
                        obj=emit('moku',row,words,code,label,number(amount[4]));obj['amount_text']=amount[4]
                        controls[key]=obj
                    elif key not in controls:
                        problems.append(dict(page=row['page'],reason='Moku continuation lacks prior amount',key=key))
                    else:
                        repeated_label = dict(label=label,page=row['page'])
                        emit('moku-continuation',row,words,code,label)
                    continue
                if moku and names and re.search(r'[一-龯ぁ-ゖァ-ヺ]',names[0][4]) and normalize(names[0][4]) not in ('計','目'):
                    label_target = repeated_label if repeated_label is not None else moku
                    label_target['label'] += normalize(''.join(w[4] for w in names))
                    emit('moku-label',row,names,label=normalize(''.join(w[4] for w in names)))
                continue
            if row['y'] <= cols['right_unit_y']:
                continue
            if moku is None:
                continue
            section = [w for w in words if w[0] < cols['explanation_left']]
            if section:
                amount=money_cell(section,cols['setsu_right'])
                names=[w for w in section if amount is None or w is not amount]
                if names and re.fullmatch(r'\d{1,2}',normalize(names[0][4])) and len(names)>1:
                    left_setsu=emit('left-setsu',row,section,normalize(names[0][4]),normalize(''.join(w[4] for w in names[1:])),number(amount[4]) if amount else None)
                    left_setsu['amount_text']=amount[4] if amount else None
                elif left_setsu and names:
                    left_setsu['label'] += normalize(''.join(w[4] for w in names))
                elif amount:
                    emit('left-setsu',row,section,amount=number(amount[4]))['amount_text']=amount[4]
            explanation=[w for w in words if w[0] >= cols['explanation_left'] and w[2] <= cols['explanation_right']+1.5]
            if not explanation:
                continue
            amount=money_cell(explanation,cols['explanation_right'])
            names=[w for w in explanation if amount is None or w is not amount]
            if names and any(normalize(w[4])=='予備費' for w in names):
                reserve_values=[w for w in explanation if number(w[4]) is not None
                                and w is not names[0]]
                if len(reserve_values)==1:
                    original_amount=reserve_values[0]
                    sign=[w for w in explanation if normalize(w[4]) in ('△','▲','−','-') and w[2]<=original_amount[0] and original_amount[0]-w[2]<8]
                    amount=tuple(original_amount[:4])+(('△' if sign else '')+original_amount[4],)
                    names=[w for w in explanation if w is not original_amount and w not in sign]
            if project is not None and records[project['row']-1]['amount'] is None:
                pending=records[project['row']-1]
                is_new=names and (normalize(names[0][4]).startswith('【') or
                                 re.fullmatch(r'\d{2,3}',normalize(names[0][4])))
                if not is_new:
                    if pending['location']['page']!=row['page']:
                        raise ValueError('Wrapped project amount crossed a physical page')
                    more=normalize(''.join(w[4] for w in names))
                    project['label']+=more
                    pending['label']=project['label']
                    all_words=pending['location']['words']+explanation
                    pending['location']=location(row,all_words)
                    if amount is not None:
                        pending['amount']=number(amount[4]);pending['amount_text']=amount[4]
                    continue
            if not names:
                if amount is not None:
                    obj=emit('detail' if setsu is not None else 'context',row,explanation,
                             amount=number(amount[4]))
                    obj['amount_text']=amount[4]
                continue
            label=normalize(''.join(w[4] for w in names))
            first_word=normalize(names[0][4])
            if label.startswith('【'):
                department=label
                emit('department',row,explanation,label=label)
            elif re.fullmatch(r'\d{3}',first_word) and (abs(names[0][0]-(cols['explanation_left']+1)) < 1.5 or normalize(''.join(w[4] for w in names[1:]))=='予備費'):
                project=dict(code=first_word,label=normalize(''.join(w[4] for w in names[1:])),row=len(records)+1)
                setsu=None
                obj=emit('project',row,explanation,project['code'],project['label'],number(amount[4]) if amount else None)
                obj['amount_text']=amount[4] if amount else None
            elif re.fullmatch(r'\d{2}',first_word):
                if project is None:
                    problems.append(dict(page=row['page'],reason='Setsu without printed project',text=label))
                setsu=dict(code=first_word,label=normalize(''.join(w[4] for w in names[1:])),row=len(records)+1)
                obj=emit('setsu',row,explanation,setsu['code'],setsu['label'],number(amount[4]) if amount else None)
                obj['amount_text']=amount[4] if amount else None
            else:
                obj=emit('detail' if setsu is not None else 'context',row,explanation,label=label,amount=number(amount[4]) if amount else None)
                obj['amount_text']=amount[4] if amount else None
        finish_label()
    return records, problems


def extract(original: dict, edition: dict):
    """Extract one declared account while retaining raw signed operands and controls."""
    scopes=[s for s in original['editions'] if s['edition']==edition]
    if len(scopes)!=1:
        raise ValueError('Edition is absent or repeated in inspected original')
    scope=scopes[0]
    first,last=scope['first'],scope['last']
    pages=original['pages'][first-1:last]
    for n,(width,height,words) in enumerate(pages,first):
        footer=[w for w in words if w[1]>height*.88]
        if not any(normalize(w[4])==str(n) and width*.4<w[0]<width*.6 for w in footer):
            raise ValueError(f'Printed physical page footer differs: {n}')
        account_names=[normalize(w[4]) for w in footer if normalize(w[4]).endswith('特別会計')]
        if any(name!=edition['account_label'] for name in account_names):
            raise ValueError(f'Printed account footer differs: {n}')
    records,problems=_extract_rows(pages,first,last)
    leaves,checks=reconcile(records,problems)
    checks['account_difference']=None if checks['amount']==scope['printed_delta'] else dict(
        printed=scope['printed_delta'],extracted=checks['amount'])
    checks['complete_observed_grain'] &= checks['account_difference'] is None
    # Each amount is backed by a native word at an explicitly discovered money edge.
    observed=[]
    previous_cols=None
    for offset in range(0,len(pages),2):
        left=positioned_rows(pages[offset],first+offset)
        right=positioned_rows(pages[offset+1],first+offset+1)
        cols=supplementary_layout(left,right,previous_cols)
        previous_cols=cols
        for row in right:
            if row['y']<=cols['right_unit_y']:
                continue
            cell=money_cell([w for w in row['words'] if w[0]>=cols['explanation_left']],cols['explanation_right'])
            if cell is None and any(normalize(w[4])=='予備費' for w in row['words']):
                reserve=[w for w in row['words'] if w[0]>=cols['explanation_left']
                         and w[0]>cols['explanation_left']+30 and number(w[4]) is not None]
                if len(reserve)==1:
                    cell=reserve[0]
            if cell:
                observed.append((row['page'],tuple(cell)))
    from collections import Counter
    recorded=[]
    for record in records:
        if record['record_kind'] not in ('project','setsu','detail','context','department') or record['amount'] is None:
            continue
        words=record['location']['words']
        matches=[w for w in words if number(w[4])==record['amount'] and w[4]==record['amount_text']]
        if not matches and record['amount_text'] and record['amount_text'].startswith('△'):
            candidates=[w for w in words if number(w[4]) == abs(record['amount'])]
            signs=[w for w in words if normalize(w[4]) in ('△','▲','−','-')]
            if len(candidates)==1 and any(0<=candidates[0][0]-w[2]<8 for w in signs):
                matches=candidates
        if matches:
            recorded.append((record['location']['page'],tuple(matches[-1])))
    missing,extra=Counter(observed)-Counter(recorded),Counter(recorded)-Counter(observed)
    checks['native_explanation_money_tokens']=len(observed)
    checks['omitted_native_money_tokens']=list(missing.elements())
    checks['excess_native_money_tokens']=list(extra.elements())
    checks['complete_observed_grain'] &= not missing and not extra
    return records,leaves,checks,scope


def emit_candidates(output: Path, original: dict, edition: dict) -> dict:
    records,leaves,checks,scope=extract(original,edition)
    source=original['source']
    result=dict(source_id=source['id'],account=edition['account_label'],
        fiscal_year=edition['fiscal_year'],amendment_number=edition['amendment_number'],
        bill=scope['bill'],pages=[scope['first'],scope['last']],checks=checks,
        status='candidate_extracted' if checks['complete_observed_grain'] else 'candidate_reconciliation_failed',
        adopted=False,approval_phase_assigned=False,phases=[])
    output.mkdir(parents=True,exist_ok=True)
    if checks['complete_observed_grain']:
        definitions={}
        for relative in ('pipeline/ingestion/fiscal/tama_budget_changes.py',
                         'pipeline/ingestion/fiscal/tama_budget_detail.py',
                         'pipeline/ingestion/lib/pdf.py'):
            body=(REPO/relative).read_bytes()
            definitions[relative]=dict(sha256=digest(body),bytes=len(body))
        entries=[]
        for role,rows in (('observations',records),('expenditure',leaves)):
            directory=output/role
            write_table(directory,rows,financial=role=='expenditure')
            table=f'supplementary-{edition["amendment_number"]}-pages-{scope["first"]}-{scope["last"]}-{role}'
            metadata=dict(namespace=NAMESPACE,source_key=source['id'],
                jurisdiction_code=source['jurisdiction'],fiscal_year=edition['fiscal_year'],
                document_kind='supplementary',direction='expenditure',origin_sha256=original['sha256'],
                request_url=source['download_url'],landing_page=source['landing_url'],
                final_url=source['content_inspection']['final_url'],document_title=source['document_title'],
                account=edition['account_label'],fund_label=edition['account_label'],
                amendment_number=edition['amendment_number'],bill=scope['bill'],table_id=table,
                pages=[scope['first'],scope['last']],source_amount_unit='千円',unit_multiplier=1000,
                printed_total=scope['printed_delta'],phases=[],canonical_changes=False,
                approval_status='unconfirmed',approval_proof=None,nonadditive=role=='observations',
                observation_role=role,raw_form='extracted',
                grain='printed-project-setsu-detail-or-unprinted-setsu-reserve' if role=='expenditure'
                      else 'nonadditive-supplementary-printed-operands-and-explanation',
                phase_semantics='signed supplementary change; not adjusted total',
                project_setsu_linkage='printed-right-code; legal correspondence unassigned',
                extractor='ingestion.fiscal.tama_budget_changes',definition_files=definitions)
            logical=(f'{NAMESPACE}/jurisdiction={source["jurisdiction"]}/year={edition["fiscal_year"]}/'
                f'document_kind=supplementary/edition={original["sha256"]}/direction=expenditure/table={table}')
            entry=record_input(directory,metadata,logical_path=logical)
            entries.append(dict(role=role,path=entry['path'],rows=len(rows),table=entry['table']))
        result['candidate_inputs']=entries
    (output/'inspection.json').write_bytes(encode(result))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--source-id',action='append',help='Optional native original restriction; default all Tama supplementary originals.')
    parser.add_argument('--fetch-missing',action='store_true',help='Use shared HTTP cache for absent original bytes; never remote PUT.')
    args=parser.parse_args(argv)
    sources=[s for s in load_registry(INVENTORY)['sources'] if s['jurisdiction']=='132241'
        and s['document_phase']=='supplementary' and s['format']=='pdf'
        and s.get('content_inspection',{}).get('sha256') and
        any(e['in_scope']['status']=='included' for e in s['editions'])
        and (not args.source_id or s['id'] in args.source_id)]
    results=[]
    for source in sources:
        pdf=OBJECTS/f'inputs/origin/sha256/{source["content_inspection"]["sha256"]}'
        try:
            try:
                original=inspect_original(pdf,source)
            except FileNotFoundError:
                if not args.fetch_missing:
                    raise
                from ingestion.lib.http import http_get
                import os
                # Shared fetch normally honors acquisition-wide remote storage flags.
                # Candidate command must never inherit that remote PUT side effect.
                if os.environ.get('FUDOKI_STORE_ORIGIN_REMOTE')=='1':
                    raise ValueError('Candidate fetch requires FUDOKI_STORE_ORIGIN_REMOTE unset')
                fetched=http_get(source['download_url'])
                spec=source['content_inspection']
                if digest(fetched.body)!=spec['sha256'] or len(fetched.body)!=spec['bytes']:
                    raise ValueError('Fetched original differs from declared SHA256/bytes')
                save_object('origin',fetched.body)
                original=inspect_original(pdf,source)
            for scope in original['editions']:
                edition=scope['edition']
                directory=args.output/source['id']/f'account-page-{scope["article_page"]}'
                try:
                    results.append(emit_candidates(directory,original,edition))
                except (ValueError,OSError,HTTPException,subprocess.CalledProcessError) as error:
                    results.append(dict(source_id=source['id'],account=edition['account_label'],
                        fiscal_year=edition['fiscal_year'],amendment_number=edition['amendment_number'],
                        status='unsupported',reason=str(error),adopted=False))
        except (ValueError,OSError,HTTPException,subprocess.CalledProcessError) as error:
            for edition in source['editions']:
                if edition['in_scope']['status']=='included':
                    results.append(dict(source_id=source['id'],account=edition['account_label'],
                        fiscal_year=edition['fiscal_year'],amendment_number=edition['amendment_number'],
                        status='unsupported',reason=str(error),adopted=False))
    result=dict(originals=len(sources),scopes=len(results),results=results,adopted=False,
        approval_phase_assigned=False,complete=all(r['status']=='candidate_extracted' for r in results))
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'batch.json').write_bytes(encode(result))
    print(json.dumps(dict(originals=result['originals'],scopes=result['scopes'],complete=result['complete']),ensure_ascii=False))
    return 0 if result['complete'] else 1


if __name__=='__main__':
    raise SystemExit(main())
