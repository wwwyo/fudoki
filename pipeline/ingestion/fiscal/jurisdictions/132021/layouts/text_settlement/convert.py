"""Assemble Tachikawa's settlement spread columns from Poppler word boxes.

Scope has two printed tables for one account: the 歳出決算款項表
(summary spreads) and the 歳出決算事項別明細書 (detail spreads).
`options['part']` selects which is built; each is a separate conversion.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

AMOUNT = re.compile(r"△?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")
AMOUNT_PART = re.compile(r"^[0-9,△.\-]+$")
BUDGET = ['当初予算額', '補正予算額', '継続費及び繰越事業費繰越額', '予備費支出及び流用増減', '計']
PAGE_WIDTH = 595.32
BODY_TOP, BODY_BOTTOM = 105, 775
LABEL_RIGHT = 110
BUDGET_LEFT, BUDGET_RIGHT = 95.0, 421.0
BUDGET_RULES = [(95.6, 167.0), (167.0, 238.3), (238.3, 297.8),
                (297.8, 355.7), (355.7, 420.4)]
SETSU_NUM_LEFT, SETSU_NUM_RIGHT = 415, 431
SETSU_NAME_LEFT, SETSU_NAME_RIGHT = 428, 482
SETSU_AMOUNT_LEFT = 482
R_PAID_RIGHT = 123
R_CARRY_RIGHT = 195
R_UNUSED_RIGHT = 257
NOTE_LEFT = 257
SEGMENT = re.compile(r'([ML])\s+(-?[\d.]+)\s+(-?[\d.]+)')
INNER_LABELS = ('繰越明許費', '事故繰越', '支出済額', '不用額', '本年度支出額', '翌年度繰越額')


def observe(pdf, first, last, path):
    subprocess.run(['pdftotext', '-f', str(first), '-l', str(last), '-bbox-layout',
                    str(pdf), str(path)], check=True)
    pages = {}
    for number, page in enumerate(ET.parse(path).findall('.//{*}page'), first):
        if abs(float(page.get('width')) - PAGE_WIDTH) > .1 or abs(float(page.get('height')) - 841.92) > .1:
            raise ValueError(f'Unmeasured page dimensions at {number}')
        words = [dict(text=w.text or '', **{k: float(v) for k, v in w.attrib.items()})
                 for w in page.findall('.//{*}word')]
        pages[number] = words
    if sorted(pages) != list(range(first, last + 1)):
        raise ValueError('Incomplete Poppler page range')
    return pages


def ruling_edges(pdf, page, workdir):
    """Return (horizontal, vertical) printed rules of the page grid.

    Horizontal full-width rules define row bands; vertical rules delimit the
    label / five budget / 節 columns (data bands and headers alike).
    """
    svg = Path(workdir) / f'rules-{page}'
    subprocess.run(['pdftocairo', '-f', str(page), '-l', str(page), '-svg',
                    str(pdf), str(svg)], check=True)
    root = ET.parse(svg).getroot()
    ys = []
    xs = []
    for element in root.iter():
        if not element.tag.endswith('path'):
            continue
        matrix = [float(v) for v in re.split(r'[,\s]+', element.get('transform', 'matrix(1,0,0,1,0,0)')[7:-1].strip())]
        points = [(float(x), float(y)) for _, x, y in SEGMENT.findall(element.get('d') or '')]
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            xa = matrix[0] * x1 + matrix[2] * y1 + matrix[4]
            xb = matrix[0] * x2 + matrix[2] * y2 + matrix[4]
            ya = matrix[1] * x1 + matrix[3] * y1 + matrix[5]
            yb = matrix[1] * x2 + matrix[3] * y2 + matrix[5]
            if abs(ya - yb) <= .5 and max(xa, xb) - min(xa, xb) >= 40:
                ys.append((ya + yb) / 2)
            elif abs(xa - xb) <= .5 and max(ya, yb) - min(ya, yb) >= 20:
                xs.append((xa + xb) / 2)

    def dedupe(values):
        out = []
        for v in sorted(values):
            if out and v - out[-1] <= 1:
                out[-1] = (out[-1] + v) / 2
            else:
                out.append(v)
        return out
    return dedupe(ys), dedupe(xs)


def lines(words):
    result = []
    for word in sorted(words, key=lambda w: (w['yMin'], w['xMin'])):
        if not result or word['yMin'] - result[-1][0]['yMin'] > 1.5:
            result.append([])
        result[-1].append(word)
    return [sorted(row, key=lambda w: w['xMin']) for row in result]


def join_text(rows):
    parts = []
    for row in rows:
        value = ''
        previous = None
        for word in row:
            if previous and word['xMin'] - previous['xMax'] > 1:
                value += ' '
            value += word['text']
            previous = word
        parts.append(value)
    return '\n'.join(p for p in parts if p) or None


def defrag_digits(text):
    """Rejoin digit runs that pdftotext split across spaced words
    (e.g. "5 ,000,000" -> "5,000,000"). Applied to note text only."""
    return re.sub(r'(?<=[0-9,△.-]) (?=[0-9,△.-])', '', text)


def location(page, words):
    return {'物理頁': page, '上端': min(w['yMin'] for w in words),
            '下端': max(w['yMax'] for w in words)}


def budget_amounts(words, unconfirmed, columns=BUDGET_RULES):
    """Assign amount fragments to the five printed budget columns by the
    measured vertical rules; fragments of one amount share its column."""
    values = {}
    for word in sorted((w for w in words if AMOUNT_PART.fullmatch(w['text'])),
                       key=lambda w: w['xMin']):
        mid = (word['xMin'] + word['xMax']) / 2
        hits = [i for i, (lo, hi) in enumerate(columns) if lo <= mid < hi]
        if len(hits) != 1:
            unconfirmed.append({'reason': '予算列の金額片の列帰属が不明',
                                'text': word['text'], 'x': word['xMin']})
            continue
        column = BUDGET[hits[0]]
        values[column] = (values.get(column) or '') + word['text']
    return values


def executed_amounts(words):
    paid = [w for w in words if w['xMin'] < R_PAID_RIGHT and AMOUNT_PART.fullmatch(w['text'])]
    carry_zone = [w for w in words if R_PAID_RIGHT <= w['xMin'] < R_CARRY_RIGHT]
    unused = [w for w in words if R_CARRY_RIGHT <= w['xMin'] < R_UNUSED_RIGHT
              and AMOUNT_PART.fullmatch(w['text'])]
    carry_amount = [w for w in carry_zone if AMOUNT_PART.fullmatch(w['text'])]
    carry_label = join_text(lines([w for w in carry_zone if not AMOUNT_PART.fullmatch(w['text'])]))
    # One printed amount can be split into several words; a second baseline
    # group in the same band would mean two distinct amounts.
    def join_single(zone_words):
        groups = {}
        for w in zone_words:
            groups.setdefault(round(w['yMin'], 1), []).append(w)
        if len(groups) > 1:
            raise ValueError(f'Multiple executed amounts in one row band: {zone_words}')
        if not groups:
            return None
        return ''.join(w['text'] for w in sorted(next(iter(groups.values())), key=lambda w: w['xMin']))
    result = {
        '支出済額': join_single(paid),
        '翌年度繰越額': join_single(carry_amount),
        '不用額': join_single(unused),
    }
    if carry_label:
        result['翌年度繰越額_区分'] = carry_label
    return result


def subject_record(left_words, right_words, page, top, bottom, unconfirmed, vcols=BUDGET_RULES):
    """Parse one band's 款/項/目 cells and budget columns; None if absent.

    Ancestor numbers are reprinted as bare digits in the 款 (x<30) and 項
    (x<40) columns when a row opens after a page or level boundary. The row's
    own marker is the deepest digit-leading word on the amount baseline; the
    目 column starts near x=40.
    """
    label_words = [w for w in left_words if w['xMax'] <= LABEL_RIGHT]
    if not label_words:
        return None
    amount_words = [w for w in left_words
                    if vcols[0][0] <= w['xMin'] < vcols[-1][1] and AMOUNT_PART.fullmatch(w['text'])]
    compact_label = ''.join(w['text'] for w in label_words)
    if '歳出合計' in compact_label:
        return {'kind': 'total', 'top': top,
                **budget_amounts(amount_words, unconfirmed, vcols), **executed_amounts(right_words),
                **location(page, left_words)}
    if not amount_words:
        numbers = [w for w in label_words if re.fullmatch(r'[0-9]+', w['text'])]
        if numbers and len(numbers) == len(label_words):
            result = {}
            for w in sorted(numbers, key=lambda w: w['xMin']):
                col = '款' if w['xMax'] < 31 else '項' if w['xMax'] < 39.5 else '目'
                result[col] = result.get(col, '') + w['text']
            return {'kind': 'reprint', 'numbers': result}
        baseline = min(w['yMin'] for w in label_words)
    else:
        baseline = amount_words[0]['yMin']
    on_base = [w for w in label_words if abs(w['yMin'] - baseline) <= 1.5]
    nums = [w for w in on_base if re.match(r'^[0-9]+', w['text'])]
    if not nums:
        if not re.search(r'[0-9]', compact_label):
            return None  # repeated column header band (款項 / 目 / 予算現額)
        raise ValueError(f'Unnumbered subject marker at page {page}, y={top}')
    # Number cells are right-aligned and may split into several words.
    # Bucket each digit-leading word by where its digits end:
    # 款 column <31, 項 column <39.5, 目 column deeper. The deepest populated
    # bucket is the row's own marker; shallower buckets reprint ancestors.
    buckets = {}
    remainders = []
    for w in sorted(nums, key=lambda w: w['xMin']):
        piece = re.match(r'([0-9]+)(.*)', w['text'])
        digit_end = w['xMin'] + 4.5 * len(piece.group(1))
        col = '款' if digit_end < 31 else '項' if digit_end < 39.5 else '目'
        entry = buckets.setdefault(col, {'digits': '', 'words': []})
        entry['digits'] += piece.group(1)
        entry['words'].append(w)
        if piece.group(2):
            remainders.append({**w, 'text': piece.group(2),
                               'xMin': w['xMin'] + 4.5 * len(piece.group(1))})
    level = '目' if '目' in buckets else '項' if '項' in buckets else '款'
    marker_num = buckets[level]['digits']
    ancestors = {lvl: b['digits'] for lvl, b in buckets.items() if lvl != level}
    name_words = ([w for w in label_words if id(w) not in
                   {id(nw) for nw in nums}] + remainders)
    return {'kind': 'subject', 'level': level, '番号': marker_num,
            '名称': join_text(lines(name_words)), 'ancestors': ancestors,
            **budget_amounts(amount_words, unconfirmed, vcols), **executed_amounts(right_words),
            **location(page, left_words)}


def setsu_record(left_words, right_words, page, top, bottom):
    zone = [w for w in left_words if w['xMin'] >= SETSU_NUM_LEFT]
    amount_words = [w for w in zone if w['xMin'] >= SETSU_AMOUNT_LEFT
                    and AMOUNT_PART.fullmatch(w['text'])]
    num_words = [w for w in zone if SETSU_NUM_LEFT <= w['xMin'] < SETSU_NUM_RIGHT
                 and re.match(r'^[0-9]', w['text'])]
    digits = ''
    remainders = []
    for w in sorted(num_words, key=lambda w: w['xMin']):
        piece = re.match(r'([0-9]+)(.*)', w['text'])
        if piece:
            digits += piece.group(1)
            if piece.group(2):
                remainders.append(piece.group(2))
    if not digits:
        if amount_words or num_words:
            raise ValueError(f'Section row without number at page {page}, y={top}: {zone}')
        return None
    name_words = [w for w in zone if SETSU_NAME_LEFT <= w['xMin'] < SETSU_NAME_RIGHT]
    for rest in remainders:
        name_words.append({'xMin': SETSU_NAME_LEFT, 'xMax': SETSU_NAME_LEFT,
                           'yMin': min(w['yMin'] for w in num_words),
                           'yMax': max(w['yMax'] for w in num_words),
                           'text': rest})
    return {'kind': 'setsu', '番号': digits,
            '名称': join_text(lines(name_words)),
            '金額': ''.join(w['text'] for w in sorted(amount_words, key=lambda w: w['xMin'])) or None,
            **executed_amounts(right_words),
            **location(page, zone)}


# ---- remarks cell (備考結合セル) content: notes + 事業説明 ----

def split_amount(row):
    """Collect the trailing run of amount fragments in the amount column.

    pdftotext splits printed amounts at arbitrary positions, e.g. the amount
    "147,680,774" arrives as the words "147,6" + "80,774".
    """
    row = list(row)
    frags = []
    if row and AMOUNT_PART.fullmatch(row[-1]['text']) and row[-1]['xMin'] > 400:
        frags = [row.pop()]
        # Fragments of one amount are x-adjacent; keep extending left while
        # the next word is a contiguous numeric fragment.
        while row and AMOUNT_PART.fullmatch(row[-1]['text']) \
                and frags[0]['xMin'] - row[-1]['xMax'] <= 2:
            frags.insert(0, row.pop())
    # The head of an amount can merge into the name's last word
    # ("…人事課】112,408,0" + "43"). Split off a comma-bearing digit tail.
    if row:
        m = re.search(r'([0-9][0-9,]{3,})$', row[-1]['text'])
        if m and ',' in m.group(1):
            tail = m.group(1)
            leftover = row[-1]['text'][:-len(tail)]
            if leftover:
                row[-1] = {**row[-1], 'text': leftover,
                           'xMax': row[-1]['xMax'] - 4.5 * len(tail)}
            else:
                row.pop()
            frags.insert(0, {'text': tail})
    if not frags:
        return row, None
    return row, ''.join(w['text'] for w in frags)


def parse_cell(words, setsu_names, unconfirmed, items):
    """Classify the merged cell's printed lines into notes and description
    items: 事業(説明1) → 節見出し(説明2) → 細目(説明3) → 内訳行(説明4).

    ``items`` is the accumulated item list for the whole 目 cell: ``pending``
    survives across band chunks so a wrapped continuation line can still reach
    the heading/leaf it belongs to.
    """
    notes = []
    pending = len(items) - 1 if items else None
    for row in lines(words):
        first = row[0]
        text_row = ' '.join(w['text'] for w in row)
        compact = re.sub(r'\s', '', text_row)
        # Leading number may be split across words ("1" + "4" + "工事請負費"),
        # and may be merged with the first name character ("12委託料").
        num_text = ''
        consumed = 0
        remainder_word = None
        while consumed < len(row):
            piece = re.match(r'([0-9]+)(.*)', row[consumed]['text'])
            if not piece or len(num_text) + len(piece.group(1)) > 2:
                break
            num_text += piece.group(1)
            if piece.group(2):
                w = row[consumed]
                remainder_word = {**w, 'text': piece.group(2),
                                  'xMin': w['xMin'] + 4.5 * len(piece.group(1))}
            consumed += 1
            if piece.group(2):
                break
        if num_text:
            num_end = remainder_word['xMin'] if remainder_word else row[consumed - 1]['xMax']
        else:
            num_end = 0
        if num_text and num_end <= 272:
            body, amount = split_amount(row[consumed:])
            if remainder_word:
                body = [remainder_word] + body
            items.append({'kind': 'jigyou', '番号': num_text,
                          '名称': join_text(lines(body)), '金額': amount, 'row': row})
            pending = len(items) - 1
            continue
        if num_text and num_end <= 282:
            number = num_text
            if not setsu_names or number in setsu_names:
                if not setsu_names:
                    unconfirmed.append({'reason': '節区分の無い目で節見出し候補を位置のみで判定',
                                        'text': text_row})
                body, amount = split_amount(row[consumed:])
                if remainder_word:
                    body = [remainder_word] + body
                items.append({'kind': 'desc_setsu', '番号': number,
                              '名称': join_text(lines(body)), '金額': amount, 'row': row})
                pending = len(items) - 1
                continue
            unconfirmed.append({'reason': '番号行が目の節区分・事業判別に一致しない',
                                'text': text_row, 'number': number,
                                'setsu_names': sorted(setsu_names, key=int)})
            items.append({'kind': 'leaf', '名称': text_row, '金額': None, 'row': row})
            pending = None
            continue
        if all(AMOUNT_PART.fullmatch(w['text']) and w['xMin'] > 400 for w in row):
            # An amount wrapped onto its own line: append to the pending item.
            fragment = ''.join(w['text'] for w in row)
            if pending is not None:
                items[pending]['金額'] = (items[pending]['金額'] or '') + fragment
            else:
                notes.append(text_row)
                unconfirmed.append({'reason': '孤立した金額片行', 'text': text_row})
            continue
        if first['xMin'] >= 300 and compact.startswith(INNER_LABELS):
            body, amount = split_amount(row)
            items.append({'kind': 'inner', '名称': join_text(lines(body)),
                          '金額': amount, 'row': row})
            pending = None
            continue
        # Wrapped continuation of an open heading (a 事業 line whose 【所管】
        # suffix and/or amount wrapped to the next printed line). The wrapped
        # line can re-enter the note indentation column (x<282).
        if pending is not None and items[pending]['kind'] in ('jigyou', 'desc_setsu') \
                and not compact.startswith('第') \
                and ('【' in text_row
                     or (items[pending]['kind'] == 'jigyou'
                         and '】' not in (items[pending]['名称'] or ''))):
            body, amount = split_amount(row)
            name = join_text(lines(body))
            items[pending]['名称'] = (items[pending]['名称'] or '') + '\n' + name
            if amount:
                items[pending]['金額'] = amount
            continue
        if first['xMin'] >= 296:
            body, amount = split_amount(row)
            name = join_text(lines(body))
            # A name-only line can continue a pending leaf's wrapped name, as
            # can the name-tail of a wrapped leaf line carrying the amount.
            # A "（第Nブロック）" line with its own amount is a child leaf.
            if pending is not None and items[pending]['金額'] is None \
                    and not (amount is not None and compact.startswith('（第')):
                items[pending]['名称'] = (items[pending]['名称'] or '') + '\n' + name
                if amount:
                    items[pending]['金額'] = amount
                continue
            items.append({'kind': 'leaf', '名称': name, '金額': amount, 'row': row})
            pending = len(items) - 1
            continue
        if first['xMin'] >= 282:
            body, amount = split_amount(row)
            items.append({'kind': 'leaf', '名称': join_text(lines(body)),
                          '金額': amount, 'row': row})
            pending = len(items) - 1
            continue
        notes.append(defrag_digits(text_row))
        pending = None
    return notes


def assemble_items(items, unconfirmed):
    """Emit leaf rows (説明3 or 説明4) with their 説明1/2 lineage.

    A printed heading that has no leaf/inner descendants is itself emitted as
    the leaf row (e.g. 事業行 with a printed amount but no detail lines, or a
    節見出し行 whose only content is its own amount).
    """
    rows = []
    context = {}
    pending_leaf = None
    open_heading = None  # (level, row) of the deepest heading awaiting children

    def flush_leaf():
        nonlocal pending_leaf
        if pending_leaf is not None:
            rows.append(pending_leaf)
            pending_leaf = None

    def flush_heading(closes_level):
        """A sibling-or-higher heading arrived: emit the deepest unclosed
        heading if it never received children."""
        nonlocal open_heading
        if open_heading is not None and open_heading[0] >= closes_level:
            rows.append(open_heading[1])
            open_heading = None

    for item in items:
        pos = location(item['page'], item['row'])
        if item['kind'] == 'jigyou':
            flush_leaf()
            flush_heading(1)
            context = {'説明1': {'番号': item['番号'], '名称': item['名称'],
                               '金額': item['金額'], **pos}}
            open_heading = (1, dict(context))
        elif item['kind'] == 'desc_setsu':
            flush_leaf()
            flush_heading(2)
            context['説明2'] = {'番号': item['番号'], '名称': item['名称'],
                                '金額': item['金額'], **pos}
            context.pop('説明3', None)
            context.pop('説明4', None)
            open_heading = (2, {k: v for k, v in context.items()
                                if k in ('説明1', '説明2')})
        elif item['kind'] == 'leaf':
            flush_leaf()
            open_heading = None
            entry = dict(context)
            entry['説明3'] = {'名称': item['名称'], '金額': item['金額'], **pos}
            context['説明3'] = entry['説明3']
            context.pop('説明4', None)
            pending_leaf = entry
        elif item['kind'] == 'inner':
            open_heading = None
            if '説明3' not in context:
                unconfirmed.append({'reason': '内訳行の親細目が無い', 'text': item['名称'],
                                    'page': item.get('page')})
            entry = dict(context)
            entry['説明4'] = {'名称': item['名称'], '金額': item['金額'], **pos}
            rows.append(entry)
            pending_leaf = None
    flush_leaf()
    flush_heading(1)
    return rows


def expand(record, prefix, keys):
    return {f'{prefix}_{key}': (record or {}).get(key) for key in keys}


SUBJECT_COLS = (['番号', '名称'] + BUDGET + ['支出済額', '翌年度繰越額',
                '翌年度繰越額_区分', '不用額', '備考', '物理頁', '上端', '下端'])
SETSU_COLS = (['番号', '名称', '金額', '支出済額', '翌年度繰越額',
              '翌年度繰越額_区分', '不用額', '物理頁', '上端', '下端'])
DESC_COLS = {
    '説明1': ['番号', '名称', '金額', '物理頁', '上端', '下端'],
    '説明2': ['番号', '名称', '金額', '物理頁', '上端', '下端'],
    '説明3': ['名称', '金額', '物理頁', '上端', '下端'],
    '説明4': ['名称', '金額', '物理頁', '上端', '下端'],
}


def detail(pages_words, pairs, edges):
    """Walk spreads; collect subjects, section rows, cell words per 目."""
    contexts = {}            # (款num,) / (款,項) / (款,項,目) -> {'款':..,..}
    current = {}             # {'款':..,'項':..,'目':..}
    current_key = None       # 目 key (page, top) of the active 目
    moku_seq = []            # ordered 目 keys
    moku_context = {}        # key -> {'款':..,'項':..,'目':..}
    moku_setsu_rows = defaultdict(list)
    moku_cell = defaultdict(list)     # key -> [{'page':.., 'words':[...]}]
    totals = []
    unconfirmed = []
    reprints = []

    def resolve(level, num, ancestors):
        """Build the current lineage for a new subject row."""
        ctx = {}
        for lvl in ('款', '項'):
            if level == lvl:
                break
            want = ancestors.get(lvl) or (current.get(lvl) or {}).get('番号')
            if want is None:
                continue
            # contexts keyed by (level, *numbers): 款->('款',n), 項->('款',n,'項',m)
            if lvl == '款':
                found = contexts.get(('款', want))
            elif '款' in ctx:
                found = contexts.get(('款', ctx['款']['番号'], '項', want))
            else:
                found = None
            if found is not None:
                ctx[lvl] = found
            elif lvl in current and current[lvl].get('番号') == want:
                ctx[lvl] = current[lvl]
            else:
                ctx[lvl] = {'番号': want, '名称': None}
                unconfirmed.append({'reason': f'祖先{lvl}行が未検出のため番号のみ',
                                    'level': level, 'number': num, 'ancestor': want})
        return ctx

    for left_page, right_page in pairs:
        rules, vedges = edges.get(left_page, ([], []))
        if not rules or len(rules) < 3:
            raise ValueError(f'No row rules on left page {left_page}')
        bands = list(zip(rules, rules[1:]))
        # 5 budget columns between the label edge (~95.6) and the 節 edge (~420.4)
        try:
            i0 = min(range(len(vedges)), key=lambda i: abs(vedges[i] - 95.6))
            if abs(vedges[i0] - 95.6) > 3:
                raise IndexError
            vcols = [(vedges[i0 + j], vedges[i0 + j + 1]) for j in range(5)]
            if abs(vcols[-1][1] - 420.4) > 3:
                raise IndexError
        except (IndexError, TypeError):
            vcols = BUDGET_RULES
            unconfirmed.append({'reason': '左頁の縦罫線から予算5列を確定できず既定座標を使用',
                                'page': left_page})
        left_words = [w for w in pages_words[left_page] if BODY_TOP <= w['yMin'] < BODY_BOTTOM]
        right_words = [w for w in pages_words[right_page] if BODY_TOP <= w['yMin'] < BODY_BOTTOM]
        head = [w for w in pages_words[left_page] if w['yMin'] < BODY_TOP
                and re.match(r'[款项]（', w['text'])]
        if head:
            reprints.append({'page': left_page, 'text': join_text(lines(head))})
        band_owner = {}
        data_tops = []
        for top, bottom in bands:
            lw = [w for w in left_words if top <= w['yMin'] < bottom]
            rw = [w for w in right_words if top <= w['yMin'] < bottom]
            subject = subject_record(lw, rw, left_page, top, bottom, unconfirmed, vcols)
            srow = setsu_record(lw, rw, left_page, top, bottom)
            if subject or srow:
                data_tops.append(top)
            if subject and subject['kind'] == 'total':
                totals.append({'page': left_page, **subject})
                band_owner[top] = None
                current_key = None
            elif subject and subject['kind'] == 'reprint':
                path = subject['numbers']
                if '目' in path and '款' in path and '項' in path:
                    key = ('款', path['款'], '項', path['項'], '目', path['目'])
                    if key in contexts:
                        current = contexts[key]
                        current_key = current['目'].get('_key')
                    else:
                        unconfirmed.append({'reason': '再掲番号の経路が未登録',
                                            'page': left_page, 'path': path})
                        current_key = None
                band_owner[top] = current_key
            elif subject:
                level, num, anc = subject['level'], subject['番号'], subject.get('ancestors', {})
                ctx = resolve(level, num, anc)
                ctx[level] = subject
                if level == '款':
                    contexts[('款', num)] = ctx['款']
                    current = {'款': subject}
                    current_key = None
                elif level == '項':
                    contexts[('款', ctx['款']['番号'], '項', num)] = ctx['項']
                    current = {'款': ctx['款'], '項': subject}
                    current_key = None
                else:
                    key = ('款', ctx.get('款', {}).get('番号'), '項', ctx.get('項', {}).get('番号'), '目', num)
                    if key in contexts:
                        # Reprinted 目 row (numbers and amounts re-shown on a
                        # continuation spread): re-assert context only.
                        current = contexts[key]
                        current_key = current['目'].get('_key')
                    else:
                        subject['_key'] = (left_page, top)
                        ctx['目'] = subject
                        contexts[key] = ctx
                        current = ctx
                        current_key = subject['_key']
                        moku_seq.append(current_key)
                        moku_context[current_key] = ctx
                band_owner[top] = current_key
            if srow:
                if current_key is None:
                    unconfirmed.append({'reason': '款項目経路の無い節行',
                                        'page': left_page, 'top': top})
                    continue
                moku_setsu_rows[current_key].append((srow, dict(current)))
                band_owner[top] = current_key
            if not subject and not srow:
                band_owner[top] = current_key
        first_data = min(data_tops) if data_tops else float('inf')
        owner = current_key
        for top, bottom in bands:
            if top < first_data:
                continue
            if top in band_owner:
                owner = band_owner[top]
            rw = [w for w in right_words if top <= w['yMin'] < bottom and w['xMin'] > NOTE_LEFT]
            if not rw:
                continue
            if owner is None:
                unconfirmed.append({'reason': '所属する目の無い備考セル文字',
                                    'page': right_page, 'top': top,
                                    'text': join_text(lines(rw))})
                continue
            moku_cell[owner].append({'page': right_page, 'words': rw})
    return moku_seq, moku_context, moku_setsu_rows, moku_cell, totals, unconfirmed, reprints


def convert_detail(source, destination, options, selected):
    pages = sorted(selected)
    if len(pages) % 2 or pages[0] % 2:
        raise ValueError('Detail scope must pair left/right spreads starting at an even page')
    pairs = [(p, p + 1) for p in pages[::2]]
    obs_dir = destination / 'observations'
    obs_dir.mkdir(parents=True, exist_ok=True)
    pages_words = observe(source['path'], pages[0], pages[-1], obs_dir / 'detail-bbox.html')
    with tempfile.TemporaryDirectory() as workdir:
        edges = {p: ruling_edges(source['path'], p, workdir) for p, _ in pairs}
    moku_seq, moku_context, moku_setsu_rows, moku_cell, totals, unconfirmed, reprints = \
        detail(pages_words, pairs, edges)

    detail_records = []   # grid leaf rows (節行, or the 目 itself when it has none)
    notes_records = []    # merged-cell explanation leaf rows
    for key in moku_seq:
        ctx = moku_context[key]
        setsu_names = {s['番号'] for s, _ in moku_setsu_rows.get(key, [])}
        notes = []
        items = []
        for chunk in moku_cell.get(key, []):
            before = len(unconfirmed)
            cell_notes = parse_cell(chunk['words'], setsu_names, unconfirmed, items)
            for entry in unconfirmed[before:]:
                entry.setdefault('page', chunk['page'])
            notes.extend(cell_notes)
            for it in items:
                it.setdefault('page', chunk['page'])
        moku_note = '\n'.join(notes) or None
        desc_rows = assemble_items(items, unconfirmed)
        for srow, owners in moku_setsu_rows.get(key, []):
            row = {}
            for lvl in ('款', '項', '目'):
                row.update(expand(owners[lvl], lvl, SUBJECT_COLS))
            row['目_備考'] = moku_note
            row.update(expand(srow, '節', SETSU_COLS))
            detail_records.append(row)
        for entry in desc_rows:
            row = {}
            for lvl in ('款', '項', '目'):
                row.update(expand(ctx[lvl], lvl, SUBJECT_COLS))
            row['目_備考'] = moku_note
            for prefix, cols in DESC_COLS.items():
                row.update(expand(entry.get(prefix), prefix, cols))
            notes_records.append(row)
        if not moku_setsu_rows.get(key):
            # The 目 grid row is itself the leaf (no 節 breakdown printed).
            row = {}
            for lvl in ('款', '項', '目'):
                row.update(expand(ctx.get(lvl), lvl, SUBJECT_COLS))
            row['目_備考'] = moku_note
            row.update(expand(None, '節', SETSU_COLS))
            detail_records.append(row)
            if not desc_rows:
                unconfirmed.append({'reason': '節行・説明を持たない目を科目行の葉とした',
                                    'moku': str(key)})
    if len(totals) != 1:
        unconfirmed.append({'reason': '歳出合計行の件数が1ではない', 'count': len(totals)})

    lineage = [f'{lvl}_{c}' for lvl in ('款', '項', '目') for c in SUBJECT_COLS]
    (obs_dir / 'checks.json').write_text(json.dumps(
        {'totals': totals, 'unconfirmed': unconfirmed, 'reprinted_headings': reprints,
         'moku_count': len(moku_seq),
         'setsu_rows': sum(len(v) for v in moku_setsu_rows.values()),
         'desc_rows': len(notes_records)},
        ensure_ascii=False, default=str, indent=1))

    prefix = options.get('table_prefix', 'general-expenditure')
    results = {}
    for kind, rows, leaf_cols in (
            ('details', detail_records, [f'節_{c}' for c in SETSU_COLS]),
            ('notes', notes_records,
             [f'{lvl}_{c}' for lvl, cols in DESC_COLS.items() for c in cols])):
        columns = lineage + leaf_cols
        for record in rows:
            for c in columns:
                record.setdefault(c, None)
        pq_columns = tuple(ParquetColumn(
            c, 'BIGINT' if c.endswith('物理頁')
               else 'DOUBLE' if c.endswith(('上端', '下端')) else 'VARCHAR')
            for c in columns)
        table_id = f'{prefix}-{kind}'
        output = write_conversion(destination / (table_id + '.parquet'), rows,
                                  columns=pq_columns,
                                  context=ConversionContext(source['sha256'],
                                                            table_id, __file__))
        results[table_id] = {'path': Path(output.path),
                             'metadata': detail_metadata(columns, kind)}
    return results


def detail_metadata(columns, kind):
    amounts = [c for c in columns
               if any(c.endswith('_' + k) for k in BUDGET + ['支出済額', '翌年度繰越額', '不用額'])
               or c.endswith('_金額') or c == '金額']
    contexts = []
    for level in ('款', '項', '目'):
        contexts.append({'columns': [c for c in columns if c.startswith(level + '_')],
                         'header_path': ['科目', level],
                         'grain_columns': [level + '_番号', level + '_物理頁', level + '_上端']})
    if kind == 'details':
        contexts.append({'columns': [c for c in columns if c.startswith('節_')],
                         'header_path': ['節'], 'semantic_role': 'setsu',
                         'grain_columns': ['節_番号', '節_物理頁', '節_上端']})
        note = ('左頁グリッドの法定最細行=節行（節_*列が印字値）。節を印字しない目は'
                'その科目行自体が葉（節_*列NULL）。款・項・目_*列は行が属する科目行の印字値'
                '（denorm、再掲行は同一値）。右頁備考結合セルのうち説明階層を構成しない行'
                '（流用注記・予備費支出先一覧等）は目_備考に原文改行で保持。'
                '説明分解は別表 general-expenditure-notes にあり、この表とは同一支出の別軸で'
                '合算しない。金額は原典の桁区切り・△符号を保持。'
                '歳出合計行・款（N）項（N）再掲見出し・会計標は観測に留め行にしない。')
    else:
        contexts.append({'columns': [c for c in columns if c.startswith('説明1_')],
                         'header_path': ['備考', '事業説明', '1'], 'semantic_role': 'project',
                         'grain_columns': ['説明1_物理頁', '説明1_上端']})
        contexts.append({'columns': [c for c in columns if c.startswith('説明2_')],
                         'header_path': ['備考', '事業説明', '2'], 'semantic_role': 'setsu',
                         'grain_columns': ['説明2_物理頁', '説明2_上端']})
        for prefix in ('説明3', '説明4'):
            contexts.append({'columns': [c for c in columns if c.startswith(prefix + '_')],
                             'header_path': ['備考', '事業説明', prefix[-1]],
                             'grain_columns': [prefix + '_物理頁', prefix + '_上端']})
        note = ('右頁備考結合セル内の事業説明の最細行（説明1=事業、説明2=セル内節見出し、'
                '説明3=細目、説明4=内訳行）。説明階層の見出し行で下位印字の無いものは'
                'その見出し自体を葉とする（金額0印字の事業・葉なし節見出し等）。'
                '説明内節見出し(説明2)と表グリッド節行の対応付けはraw列に実体化せず'
                '検査用観測に留める。説明3・説明4は同じ支出の別分解軸であり'
                '節表 general-expenditure-details とは合算しない。'
                '事業名の【所管】は名称の一部。金額は原典の桁区切り・△符号を保持。'
                '物理頁は各要素が印字された実頁（左頁・右頁それぞれ）。')
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': amounts}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}}],
            'column_contexts': contexts}


SUMMARY_COLS = (['款_番号', '款_名称', '項_番号', '項_名称', '予算現額', '支出済額',
                 '翌年度繰越額', '不用額', '予算現額と支出済額との比較',
                 '物理頁', '上端', '下端'])
SUMMARY_BOUNDS = [(60, 200, '支出済額'), (200, 340, '翌年度繰越額'),
                  (340, 460, '不用額'), (460, 580, '予算現額と支出済額との比較')]


def convert_summary(source, destination, options, selected):
    pages = sorted(selected)
    if len(pages) % 2 or pages[0] % 2:
        raise ValueError('Summary scope must pair left/right spreads starting at an even page')
    obs_dir = destination / 'observations'
    obs_dir.mkdir(parents=True, exist_ok=True)
    all_pages = observe(source['path'], pages[0], pages[-1], obs_dir / 'summary-bbox.html')
    records = []
    footers = []
    totals = 0
    cur_kan = (None, None)  # current 款 heading for 項 lineage
    for index in range(0, len(pages), 2):
        left_page, right_page = pages[index], pages[index + 1]
        left_rows = defaultdict(list)
        for w in all_pages[left_page]:
            left_rows[round(w['yMin'], 1)].append(w)
        right_rows = defaultdict(list)
        for w in all_pages[right_page]:
            right_rows[round(w['yMin'], 1)].append(w)
        label_rows = [y for y, lw in sorted(left_rows.items())
                      if 90 <= y < BODY_BOTTOM
                      and any(w['xMin'] < 460 for w in lw)]
        for y in label_rows:
            near = [w for yy, lw in left_rows.items() if abs(yy - y) < 2.5 for w in lw]
            label = sorted([w for w in near if w['xMin'] < 460], key=lambda w: w['xMin'])
            marker = min(label, key=lambda w: w['xMin'])
            m = re.match(r'([0-9]+)(.*)', marker['text'])
            is_total = '歳出合計' in ''.join(w['text'] for w in label)
            rw = [w for yy, rws in right_rows.items() if abs(yy - y) < 2.5 for w in rws]
            record = {'款_番号': None, '款_名称': None, '項_番号': None, '項_名称': None,
                      '支出済額': None, '翌年度繰越額': None, '不用額': None,
                      '予算現額と支出済額との比較': None,
                      '予算現額': ''.join(w['text'] for w in sorted(
                          [w for w in near if w['xMin'] >= 460 and AMOUNT_PART.fullmatch(w['text'])],
                          key=lambda w: w['xMin'])) or None,
                      '物理頁': left_page,
                      '上端': min(w['yMin'] for w in near + rw),
                      '下端': max(w['yMax'] for w in near + rw)}
            if is_total:
                record['款_名称'] = join_text(lines(label))
                totals += 1
            elif m and marker['xMin'] < 100:
                record['款_番号'] = m.group(1)
                name_words = [w for w in label if w is not marker]
                if m.group(2):
                    name_words.append({**marker, 'text': m.group(2),
                                       'xMin': marker['xMin'] + 4.5 * len(m.group(1))})
                record['款_名称'] = join_text(lines(name_words))
                cur_kan = (record['款_番号'], record['款_名称'])
            elif m:
                record['款_番号'], record['款_名称'] = cur_kan
                record['項_番号'] = m.group(1)
                name_words = [w for w in label if w is not marker]
                if m.group(2):
                    name_words.append({**marker, 'text': m.group(2),
                                       'xMin': marker['xMin'] + 4.5 * len(m.group(1))})
                record['項_名称'] = join_text(lines(name_words))
            else:
                # Printed lines below the ruled table (差引残額・基金繰入額):
                # observations only, not table rows.
                footers.append({'物理頁': left_page,
                                'text': join_text(lines(sorted(near, key=lambda w: (w['yMin'], w['xMin']))))})
                continue
            if is_total or m:
                for w in rw:
                    if not AMOUNT_PART.fullmatch(w['text']):
                        continue
                    hits = [c for lo, hi, c in SUMMARY_BOUNDS if lo <= w['xMin'] < hi]
                    if len(hits) == 1:
                        record[hits[0]] = ((record[hits[0]] or '') + w['text'])
            records.append(record)
    obs_dir.joinpath('summary-checks.json').write_text(json.dumps(
        {'rows': len(records), 'totals': totals, 'footers': footers},
        ensure_ascii=False, indent=1))
    if totals != 1:
        raise ValueError(f'Expected one printed expenditure total, got {totals}')
    columns = tuple(ParquetColumn(c, 'BIGINT' if c == '物理頁'
                                  else 'DOUBLE' if c in ('上端', '下端') else 'VARCHAR')
                    for c in SUMMARY_COLS)
    table_id = options['table_id']
    output = write_conversion(destination / (table_id + '.parquet'), records,
                              columns=columns,
                              context=ConversionContext(source['sha256'], table_id, __file__))
    metadata = {
        'units': [{'text': '円', 'scope': {'kind': 'columns',
                   'columns': ['予算現額', '支出済額', '翌年度繰越額', '不用額',
                               '予算現額と支出済額との比較']}}],
        'notes': [{'text': '歳出決算款項表。款・項の印字行と歳出合計（番号なし・名称「歳出合計」の制御行）。'
                           '項行には印字順序で一意に決まる款のlineage（款_番号・款_名称）を付与。'
                           '左頁の款項名称・予算現額と右頁の支出済額・翌年度繰越額・不用額・比較を同じ見開き行へ対応。'
                           '比較列は明細書にない独立した印字列。',
                    'scope': {'kind': 'table'}}],
        'column_contexts': [
            {'columns': ['款_番号', '款_名称'], 'header_path': ['款'],
             'grain_columns': ['款_番号']},
            {'columns': ['項_番号', '項_名称'], 'header_path': ['項'],
             'grain_columns': ['項_番号']}]}
    return {table_id: {'path': Path(output.path), 'metadata': metadata}}


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Tachikawa settlement requires one original')
    source = inputs[0]
    if (source['target']['jurisdiction'] != '132021'
            or source['target']['document_kind'] != 'settlement'
            or source['direction'] != 'expenditure'
            or source['format'] != 'pdf' or source['pdf_type'] != 'text'):
        raise ValueError('This measured layout is Tachikawa text settlement expenditure only')
    account = options.get('account', '一般会計')
    part = options['part']
    ranges = [scope for scope in source['scope'] if scope['account'] == account]
    if len(ranges) != 1:
        raise ValueError(f'Expected one scope entry for {account}')
    pages = sorted(p for first, last in ranges[0]['pages'] for p in range(first, last + 1))
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if part == 'detail':
        selected = [p for p in pages if p >= 82]
    elif part == 'summary':
        selected = [p for p in pages if p < 82]
    else:
        raise ValueError(f'Unknown part: {part}')
    if not selected:
        raise ValueError(f'No pages resolved for part {part}')
    if part == 'detail':
        return convert_detail(source, destination, options, selected)
    return convert_summary(source, destination, options, selected)
