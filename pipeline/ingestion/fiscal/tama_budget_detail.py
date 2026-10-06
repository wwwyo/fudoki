"""Read native facing-page budget tables, retaining printed controls and leaves.

The registry supplies the original identity. This cache-only candidate reader
does not select an original, assign an approval phase, or change adopted inputs.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

from ingestion.fiscal.source_registry import INVENTORY, load_registry
from ingestion.inputs import digest, record_input, save_object
from ingestion.lib.pdf import pages_of, rows_of
from ingestion.paths import REPO


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def number(text: str) -> int | None:
    text = normalize(text)
    if not re.fullmatch(r"[△▲−-]?(?:\d+|\d{1,3}(?:,\d{3})+)", text):
        return None
    negative = text.startswith(("△", "▲", "−", "-"))
    return (-1 if negative else 1) * int(text.lstrip("△▲−-").replace(",", ""))


def positioned_rows(page, physical_page):
    width, height, words = page
    rows = rows_of([(w[0],w[1],w[4]) for w in words])
    groups = {y:i for i,row in enumerate(rows) for y in row.ys}
    row_words = [[] for _ in rows]
    for word in words:
        row_words[groups[word[1]]].append(word)
    result = []
    for row,group in zip(rows,row_words,strict=True):
        cells = sorted(group,key=lambda w:w[0])
        result.append(dict(page=physical_page, y=min(row.ys), words=cells,
                           text=" ".join(w[4] for w in cells), width=width, height=height))
    return result


def location(row, words):
    return dict(page=row['page'], bbox=[min(w[0] for w in words), min(w[1] for w in words),
                                        max(w[2] for w in words), max(w[3] for w in words)],
                printed_text=" ".join(w[4] for w in words), words=words)


def money_cell(words, right):
    candidates = [w for w in words if abs(w[2]-right) < 1.5 and number(w[4]) is not None]
    if len(candidates) > 1:
        raise ValueError('Multiple numbers in one printed amount cell')
    return candidates[0] if candidates else None


def page_text(pdf: Path, first: int, last: int) -> str:
    return subprocess.run(['pdftotext', '-layout', '-f', str(first), '-l', str(last),
                           str(pdf), '-'], check=True, capture_output=True).stdout.decode()


def inspect_scope(pdf: Path, source: dict, account: str, first: int, last: int):
    """Prove the requested range against this book's printed contents and footers."""
    toc = normalize(page_text(pdf, 5, 5))
    accounts = [e['account_label'] for e in source['editions']
                if e['in_scope']['status'] == 'included']
    start = toc.find(account)
    if start < 0:
        raise ValueError('Account absent from the printed contents')
    next_accounts = [toc.find(name, start + len(account)) for name in accounts if name != account]
    end = min((n for n in next_accounts if n >= 0), default=len(toc))
    block = toc[start:end]
    expenditure = re.search(r'3\.歳出(\d+)', block)
    payroll = re.search(r'給与費明細書(\d+)', block)
    if not expenditure or not payroll or (first, last) != (int(expenditure[1]), int(payroll[1])-1):
        raise ValueError('Requested range differs from the printed expenditure section')
    edition = next(e for e in source['editions'] if e['account_label'] == account
                   and e['in_scope']['status'] == 'included')
    if source['fiscal_year'] != 2026 or edition['document_phase'] != 'initial':
        raise ValueError('This native layout has only been inspected for FY2026 initial budgets')
    article_page = edition['page']
    article = normalize(page_text(pdf, article_page, article_page))
    if '令和8年度多摩市' + account + '予算' not in article:
        raise ValueError('Printed article differs from the declared year/account')
    total = re.search(r'歳入歳出それぞれ([\d,]+)千円', article)
    if not total:
        raise ValueError('Printed first-article account total absent')
    pages = pages_of(pdf, first, last)
    for physical_page, (width, height, words) in enumerate(pages, first):
        footer = normalize(''.join(w[4] for w in words if w[1] > height*.88))
        page_number = any(normalize(w[4]) == str(physical_page) and w[1] > height*.95
                          and width*.4 < w[0] < width*.6 for w in words)
        if ((physical_page-first) % 2 == 1 and account not in footer) or not page_number:
            raise ValueError(f'Printed account/page footer differs on physical page {physical_page}')
    scope = dict(contents_page=5, article_page=article_page, printed_account=account,
                fiscal_year=source['fiscal_year'], first=first, last=last,
                printed_total=number(total[1]), unit='千円', account_footers_checked=len(pages)//2,
                printed_page_numbers_checked=len(pages))
    return scope,pages


def layout(left, right):
    units = [w for row in left for w in row['words'] if normalize(w[4]) == '千円']
    headings = [w for row in left for w in row['words'] if normalize(w[4]) == '本年度予算額']
    right_units = [w for row in right for w in row['words'] if normalize(w[4]) == '千円']
    if not units or not headings or len(right_units) < 2:
        raise ValueError('Missing printed column/unit headers')
    unit_y = min(w[1] for w in units)
    left_units = sorted((w for w in units if abs(w[1]-unit_y) < 1), key=lambda w:w[0])
    right_y = min(w[1] for w in right_units)
    right_units = sorted((w for w in right_units if abs(w[1]-right_y) < 1), key=lambda w:w[0])
    if len(left_units) != 7 or len(right_units) != 2:
        raise ValueError('Expected seven left money columns and two right money columns')
    split = (right_units[0][2]+right_units[1][0])/2
    # The explanation column begins at the first printed department/project,
    # rather than at the midpoint of its two amount columns.
    starts = [w[0] for row in right if row['y'] > right_y
              for w in row['words'] if w[0] > right_units[0][2]+2 and w[0] < split
              and (normalize(w[4]).startswith('【') or re.fullmatch(r'\d{3}',w[4]))]
    if not starts:
        raise ValueError('No printed explanation project column')
    return dict(moku_right=min(w[0] for w in headings), current_right=left_units[0][2],
                left_unit_y=unit_y, right_unit_y=right_y, explanation_left=min(starts)-1,
                setsu_right=right_units[0][2], explanation_right=right_units[1][2])


def extract(pdf: Path, first: int, last: int, *, pages=None):
    if first < 1 or last < first or (last-first+1) % 2:
        raise ValueError('Expenditure range must contain complete facing-page pairs')
    pages = pages_of(pdf, first, last) if pages is None else pages
    if len(pages) != last-first+1:
        raise ValueError('PDF does not contain the declared full range')
    records, problems = [], []
    kan = kou = moku = project = setsu = None
    department = ''
    controls = {}
    left_setsu = None
    repeated_label = None

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
        cols = layout(left,right)
        events = sorted([(r['y'],0,r) for r in left]+[(r['y'],1,r) for r in right])
        for _, side, row in events:
            words = row['words']
            whole = normalize(row['text'])
            if (row['y'] > row['height']*.88 and
                (whole.endswith('特別会計') or
                 (whole == str(row['page']) and .4*row['width'] < words[0][0] < .6*row['width']))):
                continue
            if side == 0:
                heading = re.fullmatch(r'(\d*)(款|項)(.+?)([\d,]+)千円',whole)
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
                    if amount:
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
            if not names:
                continue
            label=normalize(''.join(w[4] for w in names))
            first_word=normalize(names[0][4])
            if label.startswith('【'):
                department=label
                emit('department',row,explanation,label=label)
            elif re.fullmatch(r'\d{3}',first_word) and abs(names[0][0]-(cols['explanation_left']+1)) < 1.5:
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


def reconcile(records, problems):
    """Compare three separately printed breakdowns; never allocate a residual."""
    projects={r['source_row']:r for r in records if r['record_kind']=='project'}
    mokus={tuple(r['moku']['key']):r for r in records if r['record_kind']=='moku'}
    leaves=[]
    project_sums=defaultdict(int)
    moku_sums=defaultdict(int)
    setsu_sums=defaultdict(int)
    left=defaultdict(int)
    left_null=[]
    for r in records:
        if r['record_kind']=='left-setsu':
            key=(tuple(r['moku']['key']),str(int(r['code'])) if r['code'] is not None else None)
            if r['amount'] is None:
                left_null.append(r['source_row'])
            else:
                left[key]+=r['amount']
        if r['record_kind'] not in ('setsu','detail') or r['amount'] is None:
            continue
        if r['project'] is None or r['setsu'] is None:
            problems.append(dict(row=r['source_row'],reason='Printed amount lacks project/setsu context'))
            continue
        code=str(int(r['setsu']['code']))
        key=tuple(r['moku']['key'])
        leaf=dict(r,source_grain='project-setsu-detail',printed_setsu_code=r['setsu']['code'],
                  normalized_printed_setsu_code=code)
        leaves.append(leaf)
        project_sums[r['project']['row']]+=r['amount']
        moku_sums[key]+=r['amount']
        setsu_sums[(key,code)]+=r['amount']
    exceptions=[]
    for n,r in projects.items():
        if n not in project_sums and r['label']=='予備費' and r['amount'] is not None:
            key=tuple(r['moku']['key'])
            if any(tuple(control['moku']['key']) == key for control in records
                   if control['record_kind'] == 'left-setsu'):
                problems.append(dict(row=n,reason='Reserve has unmatched printed coded setsu'))
                continue
            leaves.append(dict(r,source_grain='project',printed_setsu_code=None,normalized_printed_setsu_code=None))
            project_sums[n]=r['amount'];moku_sums[key]+=r['amount']
            exceptions.append(dict(row=n,page=r['location']['page'],bbox=r['location']['bbox'],
                                   amount=r['amount'],reason='Reserve amount printed; expenditure setsu code not printed',
                                   independent_left_setsu_control='unavailable'))
    project_differences=[dict(row=n,printed=r['amount'],extracted=project_sums[n])
                         for n,r in projects.items() if r['amount']!=project_sums[n]]
    moku_differences=[dict(key=key,printed=r['amount'],extracted=moku_sums[key])
                      for key,r in mokus.items() if r['amount']!=moku_sums[key]]
    setsu_differences=[dict(key=key,printed=left.get(key),extracted=setsu_sums.get(key))
                       for key in sorted(left.keys() | setsu_sums.keys()) if left.get(key)!=setsu_sums.get(key)]
    result=dict(leaves=len(leaves),projects=len(projects),mokus=len(mokus),amount=sum(r['amount'] for r in leaves),
                project_differences=project_differences,moku_differences=moku_differences,
                left_setsu_differences=setsu_differences,left_amounts_unconfirmed=left_null,
                parser_problems=problems,grain_exceptions=exceptions)
    result['complete_observed_grain']=not any((project_differences,moku_differences,setsu_differences,left_null,problems))
    return leaves,result


def write_table(directory: Path, records: list[dict], *, financial: bool):
    import duckdb
    directory.mkdir(parents=True, exist_ok=True)
    columns = [('source_row', 'BIGINT'), ('source_observation_row', 'BIGINT'),
               ('record_kind', 'VARCHAR'), ('code', 'VARCHAR'), ('label', 'VARCHAR'),
               ('amount', 'BIGINT'), ('amount_text', 'VARCHAR'), ('physical_page', 'INTEGER'),
               ('bbox_json', 'VARCHAR'), ('printed_text', 'VARCHAR'), ('words_json', 'VARCHAR'),
               ('context_json', 'VARCHAR'), ('source_grain', 'VARCHAR'), ('printed_setsu_code', 'VARCHAR')]
    values = [(n if financial else r['source_row'], r['source_row'], r['record_kind'], r['code'],
               r['label'], r['amount'], r['amount_text'], r['location']['page'],
               json.dumps(r['location']['bbox']), r['location']['printed_text'],
               json.dumps(r['location']['words'], ensure_ascii=False),
               json.dumps({k:r[k] for k in ('kan','kou','moku','project','setsu','department')}, ensure_ascii=False),
               r.get('source_grain'), r.get('printed_setsu_code')) for n,r in enumerate(records,1)]
    with duckdb.connect() as connection:
        connection.execute('create table candidate (' + ','.join(f'{name} {kind}' for name,kind in columns) + ')')
        connection.executemany('insert into candidate values (' + ','.join('?' for _ in columns) + ')', values)
        connection.execute('copy candidate to ? (format parquet,compression zstd)', [str(directory/'data.parquet')])


def main():
    parser=argparse.ArgumentParser(description=__doc__, epilog='Exit 0: candidate written; 1: invalid original or failed reconciliation. No adoption or approval phase assignment.')
    parser.add_argument('--source-id',required=True)
    parser.add_argument('--pdf',required=True,type=Path)
    parser.add_argument('--account',required=True)
    parser.add_argument('--first-page',required=True,type=int)
    parser.add_argument('--last-page',required=True,type=int)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    source=next((s for s in load_registry(INVENTORY)['sources'] if s['id']==args.source_id),None)
    if source is None or source['jurisdiction'] != '132241' or args.account not in source['account_labels']:
        raise ValueError('Unknown original/account in the registry')
    if not any(e['account_label']==args.account and e['in_scope']['status']=='included' for e in source['editions']):
        raise ValueError('Account is not an included original edition')
    body=args.pdf.read_bytes()
    if (digest(body)!=source['content_inspection']['sha256']
        or len(body)!=source['content_inspection']['bytes']):
        raise ValueError('Original differs from inspected registry bytes')
    scope,pages=inspect_scope(args.pdf,source,args.account,args.first_page,args.last_page)
    records,problems=extract(args.pdf,args.first_page,args.last_page,pages=pages)
    leaves,checks=reconcile(records,problems)
    checks['account_difference']=dict(printed=scope['printed_total'],extracted=checks['amount']) if scope['printed_total'] != checks['amount'] else None
    checks['complete_observed_grain'] &= checks['account_difference'] is None
    result=dict(source_id=source['id'],account=args.account,rows=len(records),scope=scope,checks=checks,adopted=False,approval_phase_assigned=False)
    if not checks['complete_observed_grain']:
        print(json.dumps(result,ensure_ascii=False))
        return 1
    args.output.mkdir(parents=True,exist_ok=True)
    origin=save_object('origin',body)
    table_id=f'initial-2026-pages-{args.first_page}-{args.last_page}'
    definition_paths = [Path(__file__).relative_to(REPO).as_posix(),
                        'pipeline/ingestion/lib/pdf.py', 'pipeline/ingestion/inputs.py',
                        'pipeline/ingestion/fiscal/source_registry.py',
                        INVENTORY.relative_to(REPO).as_posix(),
                        'pipeline/ingestion/fiscal/sources.schema.json', 'uv.lock']
    definitions = {}
    for relative_path in definition_paths:
        content=(REPO/relative_path).read_bytes()
        definitions[relative_path]=dict(sha256=digest(content),bytes=len(content))
    entries=[]
    for role,rows in [('observations',records),('expenditure',leaves)]:
        directory=args.output/role
        write_table(directory,rows,financial=role=='expenditure')
        metadata=dict(jurisdiction_code=source['jurisdiction'],fiscal_year=source['fiscal_year'],
                      document_kind='budget',direction='expenditure',raw_form='extracted',origin_sha256=origin['sha256'],
                      source_key=source['id'],request_url=source['download_url'],
                      final_url=source['content_inspection']['final_url'],landing_page=source['landing_url'],
                      document_title=source['document_title'],fund_label=args.account,account=args.account,
                      table_id=table_id+'-'+role,pages=[args.first_page,args.last_page],
                      source_amount_unit='千円',unit_multiplier=1000,printed_total=scope['printed_total'],
                      observation_role=role,grain='printed-project-setsu-detail-or-unprinted-setsu-reserve' if role=='expenditure' else 'nonadditive-printed-control-and-explanation',
                      nonadditive=role=='observations',phases=[],recognition_status='candidate_only',
                      recognition_basis='Printed project/code/detail positions; legal correspondence and phase not assigned by reader',
                      definition_files=definitions,
                      extractor='ingestion.fiscal.tama_budget_detail',source_position_method='native-pdftotext-bbox-layout')
        logical=(f'tama-initial-native/jurisdiction={source["jurisdiction"]}/year={source["fiscal_year"]}/'
                 f'document_kind=budget/edition={origin["sha256"]}/direction=expenditure/table={metadata["table_id"]}')
        entry=record_input(directory,metadata,logical_path=logical)
        entries.append(dict(role=role,path=entry['path'],rows=len(rows),table=entry['table']))
    result['candidate_inputs']=entries
    (args.output/'inspection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        print(json.dumps(dict(error=str(error),adopted=False)),file=sys.stderr)
        sys.exit(1)
