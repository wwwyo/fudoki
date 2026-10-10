"""Assemble Hino's settlement expenditure detail (歳出事項別明細書) from Poppler word boxes.

Measured against 日野市 2025年度決算 後期高齢者医療特別会計 (text PDF, A3
landscape single sheets: every column of one 明細表 sits on one physical
page). Budget columns are 当初予算額・補正予算額・継続費及び繰越事業費繰越額・
予備費支出及び流用増減・計, 節 columns are 区分/金額, execution columns are
支出済額・翌年度繰越額 (single column)・不用額, plus 備考. Unit 円.

The 備考 column holds a 事業 -> optional (N) sub-group -> 備考節見出し -> 細目
hierarchy whose amounts partition the 目's 支出済額 by 事業×節. Leaf raw rows
are the 備考細目; a 目 whose 備考 holds bare 事業 without 節見出し (the 予備費目)
is a 目-grain row with 目_備考 (coordinator-approved 0069 design; 0047 precedent).
The 法定節 list and the 歳出合計統制行 are local inspection observations, not
raw rows. Amounts keep their printed text (△, commas, parens).

Shared print baselines carry no meaning: subject/budget, 節, and 備考 zones of
one band are parsed independently by x position, never linked by equal y.
"""

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

BUDGET = ['当初予算額', '補正予算額', '継続費及び繰越事業費繰越額', '予備費支出及び流用増減', '計']
EXECUTED = ['支出済額', '翌年度繰越額', '不用額']
HEADER_TOP = 120.0
ROW_TOL = 2.0
NAME_GAP = 2.0

PATH_RIGHT = 140.0
BUDGET_BANDS = [(134.0, 205.0), (209.0, 275.0), (299.0, 340.0), (359.0, 395.0), (399.0, 460.0)]
SETSU_LEFT, SETSU_RIGHT = 455.0, 850.0
SETSU_MARK_RIGHT = 475.0
SETSU_NAME_LEFT = 460.0
SETSU_AMOUNT_BANDS = [(530.0, 605.0), (605.0, 672.0), (735.0, 778.0), (786.0, 848.0)]
SUBJECT_EXEC_BANDS = [(604.0, 672.0), (740.0, 775.0), (790.0, 845.0)]
NOTE_LEFT = 848.0
PROJECT_MARK_RIGHT = 858.0
NOTE_SETSU_MARK_RIGHT = 876.0
NOTE_AMOUNT_MIN_RIGHT = 1110.0

FRAG = re.compile(r'^[△0-9,]+$')
PAREN_AMOUNT = re.compile(r'^\([0-9,]+\)$')
PATH_TOKEN = re.compile(r'^([0-9]+)(.*)$')
SETSU_MARK = re.compile(r'^([0-9]+)(.*)$')
SUB_GROUP = re.compile(r'^([0-9]+)\)$')
FOOTER_KOU = re.compile(r'\(款\)\s*([0-9]+)')
FOOTER_KO = re.compile(r'\(項\)\s*([0-9]+)')


def observe(pdf, first, last, path):
    subprocess.run(['pdftotext', '-f', str(first), '-l', str(last), '-bbox-layout',
                    str(pdf), str(path)], check=True)
    pages = []
    for number, page in enumerate(ET.parse(str(path)).findall('.//{*}page'), first):
        width, height = float(page.get('width')), float(page.get('height'))
        words = [dict(text=w.text or '', **{k: float(v) for k, v in w.attrib.items()},
                      _id=f'{number}:{i}')
                 for i, w in enumerate(page.findall('.//{*}word'))]
        if (abs(width - 842.0) > 1 and abs(width - 1191.0) > 1) or \
           (abs(height - 842.0) > 1 and abs(height - 1191.0) > 1):
            raise ValueError(f'Unmeasured page dimensions at {number}: {width}x{height}')
        for w in words:
            if w['xMax'] > 1192.5 or w['yMax'] > 843.5:
                raise ValueError(f'Word outside the measured A3 landscape space at {number}: {w}')
        pages.append((number, words))
    if [p for p, _ in pages] != list(range(first, last + 1)):
        raise ValueError('Incomplete Poppler page range')
    return pages


def bands(words):
    rows = []
    for word in sorted(words, key=lambda w: (w['yMin'], w['xMin'])):
        if not rows or abs(word['yMin'] - rows[-1][0]['yMin']) > ROW_TOL:
            rows.append([])
        rows[-1].append(word)
    return [sorted(row, key=lambda w: w['xMin']) for row in rows]


def join_text(words):
    """Join one line's words: no separator for touching glyphs, blank for gaps."""
    parts, previous = [], None
    for word in words:
        if previous is not None and word['xMin'] - previous['xMax'] > NAME_GAP:
            parts.append(' ')
        parts.append(word['text'])
        previous = word
    return ''.join(parts)


def norm(name):
    return (name or '').replace(' ', '').replace('\n', '')


def cell_amount(words, left, right, page, y, what, right_limit=None):
    frags = [w for w in words if left <= w['xMin'] < right and FRAG.fullmatch(w['text'])]
    limit = right_limit if right_limit is not None else right
    others = [w for w in words if left <= w['xMin'] < limit and (w['text'] or '').strip()
              and not FRAG.fullmatch(w['text'])]
    if others:
        raise ValueError(f'Non-amount print inside {what} at page {page}, y={y}: '
                         + join_text(others))
    if not frags:
        raise ValueError(f'Missing {what} at page {page}, y={y}')
    ordered = sorted(frags, key=lambda w: w['xMin'])
    for first, second in zip(ordered, ordered[1:]):
        if first['xMax'] > second['xMin'] + 0.01 and first['_id'] != second['_id']:
            raise ValueError(f'Overlapping printed amounts at page {page}, y={y}')
    return ''.join(w['text'] for w in ordered)


def path_tokens(row):
    """Subject tokens of one band keyed by level.

    A digit-leading word with xMin < 45 opens the 款/項/目 group its x
    indicates; spaced name glyphs drifting into a neighboring x zone stay
    with the open group. Amount fragments (x >= 135) end the path zone.
    """
    tokens, current, seen = {}, None, set()
    for word in sorted([w for w in row if w['xMin'] < PATH_RIGHT], key=lambda w: w['xMin']):
        if word['xMin'] >= 135 and FRAG.fullmatch(word['text']):
            break
        if word['xMin'] < 45 and re.match(r'[0-9]', word['text'] or ''):
            level = '款' if word['xMin'] < 20 else '項' if word['xMin'] < 30 else '目'
            if level in seen:
                raise ValueError(f'Repeated {level} marker in one band')
            seen.add(level)
            current = tokens.setdefault(level, [])
            current.append(word)
        elif current is None:
            raise ValueError(f'Path name before any number: {word["text"]!r}')
        else:
            current.append(word)
    for level, words in tokens.items():
        merged = ''.join(w['text'] for w in words)
        if not PATH_TOKEN.match(merged):
            raise ValueError(f'Unnumbered printed path at {level}: {merged!r}')
    return tokens


def path_name(token_words):
    merged = ''.join(w['text'] for w in token_words)
    match = PATH_TOKEN.match(merged)
    number = match[1]
    skip, name_words = len(number), []
    for word in token_words:
        if skip >= len(word['text']):
            skip -= len(word['text'])
            continue
        head = dict(word)
        head['text'] = word['text'][skip:]
        name_words.append(head)
        skip = 0
        for following in token_words[token_words.index(word) + 1:]:
            name_words.append(following)
        break
    return number, join_text(name_words) if name_words else None


def subject_amounts(row, page, y, level):
    if any(PATH_RIGHT <= w['xMin'] < SETSU_LEFT and (w['text'] or '').strip()
           and not FRAG.fullmatch(w['text']) for w in row):
        raise ValueError(f'Unexpected print between subject name and budget '
                         f'at page {page}, y={y}')
    amounts = [cell_amount(row, left, right, page, y, f'{level}{key}', right_limit=455.0)
               for (left, right), key in zip(BUDGET_BANDS, BUDGET)]
    executed = [cell_amount(row, left, right, page, y, f'{level}{key}')
                for (left, right), key in zip(SUBJECT_EXEC_BANDS, EXECUTED)]
    return dict(zip(BUDGET, amounts)) | dict(zip(EXECUTED, executed))


def subject_record(tokens, row, page, y):
    levels = [level for level in ('款', '項', '目') if level in tokens]
    if len(levels) != 1:
        raise ValueError(f'Mixed subject levels at page {page}, y={y}')
    level = levels[0]
    number, name = path_name(tokens[level])
    return {'level': level, '番号': number, '名称': name,
            **subject_amounts(row, page, y, level),
            '上端': y, '下端': max(w['yMax'] for w in row)}


def setsu_row(row, page, y):
    """A 法定節 row, or None when the band carries no 節 marker."""
    markers = sorted([w for w in row if SETSU_LEFT <= w['xMin'] < SETSU_MARK_RIGHT
                      and re.match(r'[0-9]', w['text'] or '')],
                     key=lambda w: w['xMin'])
    if not markers:
        return None
    merged = ''.join(w['text'] for w in markers)
    match = SETSU_MARK.match(merged)
    if not match:
        raise ValueError(f'Unnumbered section print at page {page}, y={y}: {merged!r}')
    name = join_text([w for w in row if SETSU_MARK_RIGHT <= w['xMin'] < SETSU_RIGHT
                      and not FRAG.fullmatch(w['text'] or '')])
    if match[2]:
        name = match[2] + (' ' + name if name else '')
    amounts = [cell_amount(row, left, right, page, y, f'節{key}')
               for (left, right), key in zip(SETSU_AMOUNT_BANDS, ['金額'] + EXECUTED)]
    return {'区分_番号': match[1], '区分_名称': name or None,
            **dict(zip(['金額'] + EXECUTED, amounts)),
            '上端': y, '下端': max(w['yMax'] for w in row if w['xMin'] < SETSU_RIGHT)}


AMOUNT_CHAR = re.compile(r'^[△0-9,()]+$')


def note_parts(row, page, y):
    """Split a band's 備考 zone into (non-amount words, joined amount).

    The amount is the rightmost cluster of amount-charset words (split
    parens like `( 836,078)` rejoin here); `(N)` subgroup markers stay
    left of any name and never form the rightmost cluster.
    """
    words = sorted([w for w in row if w['xMin'] >= NOTE_LEFT], key=lambda w: w['xMin'])
    charset = [w for w in words if AMOUNT_CHAR.fullmatch(w['text'])]
    clusters, current = [], []
    for word in charset:
        if current and word['xMin'] - current[-1]['xMax'] > 40:
            clusters.append(current)
            current = []
        current.append(word)
    if current:
        clusters.append(current)
    amount, rest, merged = None, list(words), []
    while clusters and amount is None:
        merged = clusters.pop() + merged
        joined = ''.join(w['text'] for w in merged)
        if FRAG.fullmatch(joined) or PAREN_AMOUNT.fullmatch(joined):
            if max(w['xMax'] for w in merged) < NOTE_AMOUNT_MIN_RIGHT:
                raise ValueError(f'Remark amount outside the amount column '
                                 f'at page {page}, y={y}: ' + join_text(row))
            amount = joined
            rest = [w for w in words if w not in merged]
        elif not clusters:
            raise ValueError(f'Multiple remark amounts at page {page}, y={y}: ' + join_text(row))
    return rest, amount


def parse_note_band(row, page, y, state, setsu_names):
    """Classify one band's 備考 zone; mutate the 目 state; return events."""
    rest, amount = note_parts(row, page, y)
    if not rest and amount is None:
        return []
    if not rest:
        raise ValueError(f'Amount-only remarks band at page {page}, y={y}')
    if rest and rest[0]['text'] == '(':
        marker = [w for w in rest if w['xMin'] < 885 and SUB_GROUP.fullmatch(w['text'])]
        if len(marker) != 1 or amount is None or not PAREN_AMOUNT.fullmatch(amount):
            raise ValueError(f'Malformed subgroup row at page {page}, y={y}: ' + join_text(row))
        end = max(w['xMax'] for w in rest if w['xMin'] < 885)
        name = join_text([w for w in rest if w['xMin'] >= end - 1]) or None
        state['group'] = {'番号': SUB_GROUP.fullmatch(marker[0]['text'])[1],
                          '名称': name, '金額': amount,
                          '上端': y, '下端': max(w['yMax'] for w in row)}
        state['setsu'] = None
        state['last'] = state['group']
        return [('group', state['group'])]
    marker, after = [], list(rest)
    while after and re.fullmatch(r'[0-9]+', after[0]['text']):
        marker.append(after.pop(0))
    number = ''.join(w['text'] for w in marker) or None
    end = max((w['xMax'] for w in marker), default=None)
    if number is not None and marker[0]['xMin'] < PROJECT_MARK_RIGHT:
        name = join_text([w for w in after if w['xMin'] >= end - 1]) or None
        if name is None:
            raise ValueError(f'Project row without a name at page {page}, y={y}: '
                             + join_text(row))
        if amount is None or PAREN_AMOUNT.fullmatch(amount):
            raise ValueError(f'Project row without execution amount at page {page}, y={y}')
        state['project'] = {'番号': number, '名称': name, '金額': amount,
                            '上端': y, '下端': max(w['yMax'] for w in row),
                            'sections': [], 'details': []}
        state['group'] = None
        state['setsu'] = None
        state['last'] = state['project']
        return [('project', state['project'])]
    if number is not None and marker[0]['xMin'] < NOTE_SETSU_MARK_RIGHT:
        name = join_text([w for w in after if w['xMin'] >= end - 1]) or None
        if name is None or amount is None or PAREN_AMOUNT.fullmatch(amount):
            raise ValueError(f'Malformed note section row at page {page}, y={y}')
        if norm(name) not in setsu_names:
            raise ValueError(f'Note section outside the printed 法定節 list '
                             f'at page {page}, y={y}: {name}')
        if state['project'] is None:
            raise ValueError(f'Note section without a project at page {page}, y={y}')
        state['setsu'] = {'番号': number, '名称': name, '金額': amount,
                          '上端': y, '下端': max(w['yMax'] for w in row), 'details': []}
        state['project']['sections'].append(state['setsu'])
        state['last'] = state['setsu']
        return [('setsu', state['setsu'])]
    if state['project'] is None:
        raise ValueError(f'Remarks print outside any project at page {page}, y={y}: '
                         + join_text(row))
    name = join_text(rest) or None
    if amount is None:
        if state['last'] is None:
            raise ValueError(f'Amount-less remarks opener at page {page}, y={y}')
        state['last']['名称'] = (state['last']['名称'] or '') + '\n' + (name or '')
        state['last']['下端'] = max(state['last']['下端'], max(w['yMax'] for w in row))
        return [('continued', state['last'])]
    if state['setsu'] is None:
        raise ValueError(f'Detail print outside any note section at page {page}, y={y}: '
                         + join_text(row))
    detail = {'名称': name, '金額': amount,
              '上端': y, '下端': max(w['yMax'] for w in row)}
    state['setsu']['details'].append(detail)
    state['last'] = detail
    return [('detail', detail)]


COLUMNS = (
    [f'款_{k}' for k in ['番号', '名称', *BUDGET, *EXECUTED, '物理頁', '上端', '下端']] +
    [f'項_{k}' for k in ['番号', '名称', *BUDGET, *EXECUTED, '物理頁', '上端', '下端']] +
    [f'目_{k}' for k in ['番号', '名称', *BUDGET, *EXECUTED, '備考', '物理頁', '上端', '下端']] +
    ['事業_番号', '事業_名称', '事業_金額',
     '事業群_番号', '事業群_名称', '事業群_金額',
     '備考節_番号', '備考節_名称', '備考節_金額',
     '細目_名称', '細目_金額', '葉_物理頁', '葉_上端', '葉_下端']
)


def flatten(context, project, group, setsu, detail, memo, page, y, bottom):
    row = {}
    for level in ('款', '項', '目'):
        record = context[level]
        for key in ['番号', '名称', *BUDGET, *EXECUTED]:
            row[f'{level}_{key}'] = record[key]
        row[f'{level}_物理頁'] = record['page']
        row[f'{level}_上端'] = record['上端']
        row[f'{level}_下端'] = record['下端']
    row['目_備考'] = memo
    row['事業_番号'], row['事業_名称'], row['事業_金額'] = (
        (project['番号'], project['名称'], project['金額']) if project else (None, None, None))
    row['事業群_番号'], row['事業群_名称'], row['事業群_金額'] = (
        (group['番号'], group['名称'], group['金額']) if group else (None, None, None))
    row['備考節_番号'], row['備考節_名称'], row['備考節_金額'] = (
        (setsu['番号'], setsu['名称'], setsu['金額']) if setsu else (None, None, None))
    row['細目_名称'], row['細目_金額'] = (
        (detail['名称'], detail['金額']) if detail else (None, None))
    row['葉_物理頁'], row['葉_上端'], row['葉_下端'] = page, y, bottom
    return row


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Hino settlement expenditure requires one original')
    source = inputs[0]
    if (source['target']['jurisdiction'] != '132128' or source['target']['document_kind'] != 'settlement'
            or source['direction'] != 'expenditure' or source['format'] != 'pdf'
            or source['pdf_type'] != 'text'):
        raise ValueError('This measured layout is Hino text settlement expenditure only')
    account = options['account']
    selected = [p for scope in source['scope'] if scope.get('account', account) == account
                for first, last in scope['pages'] for p in range(first, last + 1)]
    if not selected or sorted(selected) != list(range(selected[0], selected[-1] + 1)):
        raise ValueError(f'Measured scope for {account} must be one contiguous page range')
    first, last = selected[0], selected[-1]
    destination = Path(destination)
    observations = destination / 'observations'
    observations.mkdir(parents=True, exist_ok=True)
    pages = observe(source['path'], first, last, observations / 'bbox.xml')

    def setsu_band_kind(row):
        if any(SETSU_LEFT <= w['xMin'] < SETSU_MARK_RIGHT
               and re.match(r'[0-9]', w['text'] or '') for w in row):
            return 'marker'
        if any(SETSU_NAME_LEFT <= w['xMin'] < SETSU_RIGHT and (w['text'] or '').strip()
               and not FRAG.fullmatch(w['text']) for w in row):
            return 'continuation'
        return None

    setsu_names, assembled = set(), []
    for page, words in pages:
        for row in bands([w for w in words if w['yMin'] >= HEADER_TOP]):
            if '(款)' in join_text(row) or '(項)' in join_text(row):
                continue
            kind = setsu_band_kind(row)
            if kind == 'marker':
                record = setsu_row(row, page, row[0]['yMin'])
                record['page'] = page
                assembled.append(record)
            elif kind == 'continuation':
                if not assembled or assembled[-1]['page'] != page:
                    raise ValueError('Section continuation without an open section '
                                     f'at page {page}, y={row[0]["yMin"]}')
                name_words = [w for w in row
                              if SETSU_NAME_LEFT <= w['xMin'] < SETSU_RIGHT]
                assembled[-1]['区分_名称'] += '\n' + join_text(name_words)
                assembled[-1]['下端'] = max(assembled[-1]['下端'],
                                            max(w['yMax'] for w in name_words))
    for record in assembled:
        if record['区分_名称']:
            setsu_names.add(norm(record['区分_名称']))
    if not setsu_names:
        raise ValueError('No printed 法定節 list observed')

    leaves, setsu_list, totals, footers = [], [], [], []
    context, current_moku = {}, None
    state = {'project': None, 'group': None, 'setsu': None, 'last': None}
    consumed = set()

    def close_moku():
        if current_moku is None:
            return
        sections = [s for p in current_moku['projects'] for s in p['sections']]
        if not sections:
            if not current_moku['projects']:
                raise ValueError('目 without remarks hierarchy cannot set grain implicitly: '
                                 + str(current_moku['record']))
            parts = []
            for project in current_moku['projects']:
                if project['sections']:
                    raise ValueError('Project mixes bare and sectioned remarks')
                parts.append(f"{project['番号']} {project['名称']} {project['金額']}")
            record = current_moku['record']
            leaves.append(flatten(context, None, None, None, None, '\n'.join(parts),
                                  record['page'], record['上端'], record['下端']))
            return
        for project in current_moku['projects']:
            if not project['sections']:
                raise ValueError('Project without note sections beside sectioned siblings')
            for section in project['sections']:
                if not section['details']:
                    raise ValueError('Note section without details: ' + str(section))

    for page, words in pages:
        header = [w for w in words if w['yMin'] < HEADER_TOP]
        if '単位：円' not in norm(join_text(header)):
            raise ValueError(f'Missing unit header at page {page}')
        for row in bands([w for w in words if w['yMin'] >= HEADER_TOP]):
            y = row[0]['yMin']
            for w in row:
                consumed.add(w['_id'])
            texts = join_text(row)
            if '(款)' in texts or '(項)' in texts:
                kou = FOOTER_KOU.search(texts)
                ko = FOOTER_KO.search(texts)
                if kou and context.get('款', {}).get('番号') != kou[1]:
                    raise ValueError(f'Footer 款 mismatch at page {page}, y={y}: {texts!r}')
                if ko and context.get('項', {}).get('番号') != ko[1]:
                    raise ValueError(f'Footer 項 mismatch at page {page}, y={y}: {texts!r}')
                if not kou and not ko:
                    raise ValueError(f'Unparsed footer at page {page}, y={y}')
                footers.append({'page': page, 'text': texts})
                continue
            path_head = join_text([w for w in row if w['xMin'] < PATH_RIGHT])
            if norm(path_head) == '歳出合計':
                close_moku()
                current_moku = None
                record = {'level': '合計', '番号': None, '名称': '歳出合計',
                          **subject_amounts(row, page, y, '合計'),
                          '上端': y, '下端': max(w['yMax'] for w in row)}
                totals.append({**record, 'page': page})
                continue
            tokens = path_tokens(row)
            kind = setsu_band_kind(row)
            if kind == 'marker':
                record = setsu_row(row, page, y)
                if set(context) != {'款', '項', '目'}:
                    raise ValueError(f'Section row outside 目 context at page {page}, y={y}')
                record['page'] = page
                record['path'] = tuple(context[level]['番号'] for level in ('款', '項', '目'))
                setsu_list.append(record)
            elif kind == 'continuation':
                name_words = [w for w in row
                              if SETSU_NAME_LEFT <= w['xMin'] < SETSU_RIGHT]
                if not setsu_list or setsu_list[-1]['page'] != page:
                    raise ValueError('Section continuation without an open section '
                                     f'at page {page}, y={y}')
                setsu_list[-1]['区分_名称'] += '\n' + join_text(name_words)
                setsu_list[-1]['下端'] = max(setsu_list[-1]['下端'],
                                            max(w['yMax'] for w in name_words))
            if tokens:
                kinds = [level for level in ('款', '項', '目') if level in tokens]
                budgeted = any(135.0 <= w['xMin'] < 455.0 and FRAG.fullmatch(w['text'])
                               for w in row)
                if not budgeted:
                    expected = tuple(context[ancestor]['番号']
                                     for ancestor in ('款', '項', '目') if ancestor in context)
                    got = []
                    for ancestor in ('款', '項', '目'):
                        if ancestor in tokens:
                            number, _ = path_name(tokens[ancestor])
                            got.append(number)
                    if tuple(got) != expected[:len(got)] or len(got) != 3:
                        raise ValueError('Continuation label outside current 目 '
                                         f'at page {page}, y={y}')
                else:
                    if len(kinds) != 1:
                        raise ValueError(f'Mixed subject levels at page {page}, y={y}')
                    level = kinds[0]
                    close_moku()
                    record = subject_record(tokens, row, page, y)
                    if record['level'] == '款':
                        context = {}
                    elif record['level'] == '項':
                        context.pop('目', None)
                    if record['level'] == '目':
                        current_moku = {'record': record, 'projects': []}
                    else:
                        current_moku = None
                    record['page'] = page
                    context[record['level']] = record
                    state.update(project=None, group=None, setsu=None, last=None)
            if any(w['xMin'] >= NOTE_LEFT for w in row):
                if current_moku is None:
                    raise ValueError(f'Remarks print outside any 目 at page {page}, y={y}')
                for kind, item in parse_note_band(row, page, y, state, setsu_names):
                    if kind == 'project':
                        current_moku['projects'].append(item)
                    elif kind == 'detail':
                        leaves.append(flatten(context, state['project'], state['group'],
                                              state['setsu'], item,
                                              None, page, item['上端'], item['下端']))
    close_moku()
    if len(totals) != 1:
        raise ValueError(f'Expected one printed expenditure total, got {len(totals)}')
    body_ids = {w['_id'] for _, words in pages for w in words if w['yMin'] >= HEADER_TOP}
    if body_ids - consumed:
        raise ValueError('Unassigned body print exists')
    if not leaves:
        raise ValueError('No detail leaves assembled')

    table_id = options['table_id']
    columns = tuple(ParquetColumn(k, 'BIGINT' if k.endswith('物理頁') else 'DOUBLE'
                                  if k.endswith(('上端', '下端')) else 'VARCHAR')
                    for k in COLUMNS)
    for leaf in leaves:
        for key in COLUMNS:
            leaf.setdefault(key, None)
        extra = set(leaf) - set(COLUMNS)
        if extra:
            raise ValueError(f'Undeclared columns: {sorted(extra)}')
    output = write_conversion(destination / (table_id + '.parquet'), leaves, columns=columns,
                              context=ConversionContext(source['sha256'], table_id, __file__))
    (observations / 'setsu-list.json').write_text(
        json.dumps(setsu_list, ensure_ascii=False, indent=2) + '\n')
    (observations / 'expenditure-total.json').write_text(
        json.dumps(totals, ensure_ascii=False, indent=2) + '\n')
    (observations / 'footer-context.json').write_text(
        json.dumps(footers, ensure_ascii=False, indent=2) + '\n')
    return {table_id: {'path': Path(output.path), 'metadata': metadata(COLUMNS, account)}}


def metadata(columns, account):
    amounts = [c for c in columns
               if c.split('_', 1)[1] in BUDGET + EXECUTED + ['金額'] or c.endswith('_金額')]
    contexts = []
    for level in ('款', '項', '目'):
        contexts.append({'columns': [c for c in columns if c.startswith(level + '_')],
                         'header_path': ['科目', level],
                         'grain_columns': [level + '_番号', level + '_物理頁', level + '_上端']})
    contexts.append({'columns': ['事業_番号', '事業_名称', '事業_金額'],
                     'header_path': ['説明', '事業'],
                     'grain_columns': ['目_番号', '目_物理頁', '目_上端', '事業_番号']})
    contexts.append({'columns': ['事業群_番号', '事業群_名称', '事業群_金額'],
                     'header_path': ['説明', '事業群'],
                     'grain_columns': ['目_番号', '目_物理頁', '目_上端', '事業_番号', '事業群_番号']})
    contexts.append({'columns': ['備考節_番号', '備考節_名称', '備考節_金額'],
                     'header_path': ['説明', '節'],
                     'grain_columns': ['目_番号', '目_物理頁', '目_上端', '事業_番号', '備考節_番号']})
    contexts.append({'columns': ['細目_名称', '細目_金額', '葉_物理頁', '葉_上端', '葉_下端'],
                     'header_path': ['説明', '細目'],
                     'grain_columns': ['葉_物理頁', '葉_上端']})
    note = ('日野市決算歳出事項別明細書（A3横単票）の備考細目を行とする。'
            '名称は単語間隔が2pt超の箇所を空白、欄内折返しを改行で保持する（印字のまま）。'
            '款・項・目の予算5列・執行3列・印字位置を反復し、事業・事業群・備考節を展開する。'
            '金額は印字原文（△・桁区切り・括弧のまま）。事業_名称は担当課の括弧書きを含む原文。'
            '予備費目は目の粒度とし、備考の bare 事業文を目_備考へ保持する（0069承認・0047先例）。'
            '同一印字行帯の科目・節・備考はx帯で独立に解釈し、高さの一致を対応の根拠にしない。'
            '法定節一覧と歳出合計はlocal観測（observations/）に留め、明細行へ加えない。'
            'p2は款1項2目1の備考溢れ頁で、前頁の文脈を継承する。'
            '頁頭の「後期 (単位：円)」は単位の根拠、会計の同定は上流scopeによる。'
            f'対象会計は{account}。')
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': amounts}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}}],
            'column_contexts': contexts}
