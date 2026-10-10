"""Assemble Kita's printed settlement tables from Poppler word boxes.

One physical A3 page is one left/right spread. For the detail table the left
printed page holds 款項・目 names, five budget columns and the statutory-setsu
区分 column; the right printed page holds the setsu 金額, the execution columns
and 備考. For the summary table the spread holds 款・項 names and 予算現額 on
the left printed page and the execution columns on the right printed page.

Every text run on the detail pages is drawn twice in the content stream: pass A
draws the whole spread at base positions inside clip x<=620.79, pass B draws it
again shifted +42.52pt inside clip x>=578.27. Left-page ink is the pass-A copy
(lower x); right-page ink is the pass-B copy (real column position). The
visible set is recovered with `mutool trace`, which reports each drawn glyph
under its active clip; a poppler word is kept when its position matches a glyph
drawn inside the clip of the pass that owns its printed page half.
"""

import bisect
import glob
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

AMOUNT = re.compile(r"△?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")

BODY_TOP, BODY_BOTTOM = 142.0, 788.0

# Left printed page: name ladder + budget columns + statutory setsu column.
NAME_LEFT, NAME_RIGHT = 37.0, 137.3
LEVEL_KAN, LEVEL_KOU = 46.6, 55.2   # 款 number x < 46.6, 項 < 55.2, 目 beyond
BUDGET_EDGES = [(137.3, 204.4), (204.4, 271.6), (271.6, 333.7), (333.7, 392.2), (392.2, 459.4)]
BUDGET = ['当初予算額', '補正予算額', '継続費及び繰越事業費繰越額', '予備費支出及び流用増減', '計']
SETSU_LEFT, SETSU_RIGHT = 459.4, 574.6
# Right printed page: setsu amount + execution columns + remarks. All x are the
# real printed (pass-B) positions; left-page echoes stop below 617.5.
EXEC_EDGES = [(630.0, 725.4), (725.4, 792.5), (792.5, 848.2), (848.2, 906.7), (906.7, 961.0), (961.0, 1023.8)]
EXECUTED = ['金額', '支出済額', '継続費逓次繰越', '繰越明許費', '事故繰越し', '不用額']
NOTE_LEFT, NOTE_RIGHT = 961.0, 1154.5

# Summary table (款項表): 款 | 項 | 予算現額 on the left printed page,
# 支出済額 | 翌年度繰越額 | 不用額 | 比較 on the right printed page.
SUM_KAN = (36.0, 210.1)
SUM_KOU = (210.1, 384.2)
SUM_EDGES = [(384.2, 558.3), (638.7, 772.6), (772.6, 899.9), (899.9, 1027.1), (1027.1, 1154.3)]
SUM_COLUMNS = ['予算現額', '支出済額', '翌年度繰越額', '不用額', '比較']
SUM_BODY_TOP = 125.0


def find_mutool():
    for candidate in glob.glob('/Users/*/Library/pipx/venvs/mupdf*/bin/mutool') \
            + glob.glob(str(Path.home() / '.local/share/mise/installs/conda-mupdf/*/bin/mutool')) \
            + glob.glob('/opt/homebrew/bin/mutool') + glob.glob('/usr/local/bin/mutool'):
        if Path(candidate).exists():
            return candidate
    import shutil
    found = shutil.which('mutool')
    if not found:
        raise ValueError('mutool not found')
    return found


SPAN = re.compile(r'<span[^>]*trm="([^"]*)"[^>]*>(.*?)</span>', re.S)
GLYPH = re.compile(r'<g unicode="([^"]*)"[^>]*x="(-?[\d.]+)" y="(-?[\d.]+)"[^>]*adv="(-?[\d.]+)"')
TRACE_TAG = re.compile(
    r'<(fill_text|stroke_text|clip_text)([^>]*?)>|<clip_path([^>]*)>(.*?)</clip_path>|<pop_clip/?>',
    re.S)


def trace_words(pdf, first, last):
    """Visible words per physical page, rebuilt from `mutool trace` glyphs.

    The imposition draws the whole spread's text twice under two page-half
    clip rects (left clip for pass A, right clip for pass B). Glyphs drawn
    outside their enclosing clip produce no ink, so the real layer is exactly
    the set of glyphs inside their page-half clip. Words are assembled from
    those glyphs; poppler word boxes are unusable here because it merges
    phantom and real glyphs into one word at the pass boundary.
    """
    out = subprocess.run([find_mutool(), 'trace', str(pdf), f'{first}-{last}'],
                         capture_output=True, check=True).stdout.decode('utf-8', 'replace')
    pages = {}
    for page_match in re.finditer(r'<page number="(\d+)"[^>]*>(.*?)</page>', out, re.S):
        page = int(page_match.group(1))
        seg = page_match.group(2)
        stack = []          # [is_page_clip, xlo, xhi, text_count]
        passes = []         # text-element count inside each page-half clip
        glyphs = {}         # visible: (unicode, x, baseline_y) -> advance width
        all_ink = {}        # every drawn glyph, for single-pass pages
        stats = {'描画glyph数': 0, 'clipA内': 0, 'clipB内': 0,
                 'clip無し': 0, 'clip外（幽霊）': 0}
        for m in TRACE_TAG.finditer(seg):
            if m.group(4) is not None:                   # clip_path element
                tm = re.search(r'transform="([^"]*)"', m.group(0))
                a, b, c, d, e, f = ([float(v) for v in tm.group(1).split()]
                                    if tm else (1, 0, 0, 1, 0, 0))
                xs = [float(v) for v in re.findall(r'x="(-?[\d.]+)"', m.group(4))]
                ys = [float(v) for v in re.findall(r'y="(-?[\d.]+)"', m.group(4))]
                if xs and ys:
                    dev = [(a * x + c * y + e, b * x + d * y + f) for x, y in zip(xs, ys)]
                    entry = [max(y for _, y in dev) - min(y for _, y in dev) > 700,
                             min(x for x, _ in dev), max(x for x, _ in dev), 0]
                    stack.append(entry)
                    if entry[0]:
                        passes.append(entry)
            elif m.group(0).startswith('<pop'):
                if stack:
                    stack.pop()
            else:                                        # text element
                tm = re.search(r'transform="([^"]*)"', m.group(2) or '')
                a, b, c, d, e, f = ([float(v) for v in tm.group(1).split()]
                                    if tm else (1, 0, 0, 1, 0, 0))
                endpos = seg.find('</' + m.group(1) + '>', m.end())
                body = seg[m.end():endpos if endpos > 0 else len(seg)]
                big = [s for s in stack if s[0]]
                clip = big[-1] if big else None
                if clip is not None:
                    clip[3] += 1
                for span in SPAN.finditer(body):
                    trm = [float(v) for v in span.group(1).split()]
                    size = trm[0]
                    for g in GLYPH.finditer(span.group(2)):
                        stats['描画glyph数'] += 1
                        u, x, y = g.group(1), float(g.group(2)), float(g.group(3))
                        adv = float(g.group(4))
                        dx, dy = a * x + c * y + e, b * x + d * y + f
                        all_ink[(u, round(dx, 2), round(dy, 2))] = (size * adv, size)
                        if clip is None:
                            stats['clip無し'] += 1
                            glyphs[(u, round(dx, 2), round(dy, 2))] = (size * adv, size)
                        elif clip[1] - .5 <= dx <= clip[2] + .5:
                            stats['clipA内' if clip[1] < 300 else 'clipB内'] += 1
                            glyphs[(u, round(dx, 2), round(dy, 2))] = (size * adv, size)
                        else:
                            stats['clip外（幽霊）'] += 1
        # Some pages draw the whole spread once inside the first half clip; the
        # later clip then holds only a page-number strip. There every drawn
        # glyph is real ink and clip membership must not filter words.
        if len(passes) >= 2 and min(p[3] for p in passes) * 20 < max(p[3] for p in passes):
            glyphs = all_ink
            stats['単一描画頁（clip判定なし）'] = True
        rows = {}
        for (u, x, y), (w, size) in glyphs.items():
            key = next((k for k in rows if abs(k - y) < .3), None)
            rows.setdefault(key if key is not None else y, []).append((x, u, w, size, y))
        words = []
        for baseline, row in rows.items():
            row.sort()
            current = None
            for x, u, w, size, y in row:
                if current and x - current['xMax'] > 1.5:
                    words.append(current)
                    current = None
                if not current:
                    current = {'text': u, 'xMin': x, 'xMax': x + w,
                               'yMin': y - .88 * size, 'yMax': y + .12 * size}
                else:
                    current['text'] += u
                    current['xMax'] = x + w
                    current['yMin'] = min(current['yMin'], y - .88 * size)
                    current['yMax'] = max(current['yMax'], y + .12 * size)
            if current:
                words.append(current)
        stats['可視glyph数（clip内）'] = len(glyphs)
        stats['組立単語数'] = len(words)
        pages[page] = {'words': words, 'stats': stats}
    if set(pages) != set(range(first, last + 1)):
        raise ValueError('Incomplete mutool trace page range')
    return sorted(pages.items())


def lines(words):
    result = []
    for word in sorted(words, key=lambda w: (w['yMin'], w['xMin'])):
        if not result or word['yMin'] - result[-1][0]['yMin'] > 1.5:
            result.append([])
        result[-1].append(word)
    return [sorted(row, key=lambda w: w['xMin']) for row in result]


def text(words):
    result = []
    for row in lines(words):
        value = ''
        previous = None
        for word in row:
            if previous and word['xMin'] - previous['xMax'] > 1:
                value += ' '
            value += word['text']
            previous = word
        result.append(value)
    return '\n'.join(result) or None


def select(words, left, right, low, high):
    return [w for w in words if left <= w['xMin'] and w['xMax'] <= right
            and low <= w['yMin'] < high]


def cell_amounts(row, edges):
    """One printed amount per declared column band; None where unprinted.

    Amounts may be fragmented into several words; fragments are rejoined in x
    order. Fragments must tile the cell contiguously to count as one value.
    """
    values = []
    for left, right in edges:
        pieces = [w for w in row if left <= w['xMin'] and w['xMax'] <= right]
        pieces.sort(key=lambda w: w['xMin'])
        pieces = [w for w in pieces if re.fullmatch(r'[△\-0-9,]+', w['text'])]
        value = ''
        previous = None
        for w in pieces:
            if previous is not None and w['xMin'] - previous['xMax'] > 2:
                raise ValueError(f'Split printed amounts in one column at y={row[0]["yMin"]}: '
                                 f'{[w["text"] for w in pieces]}')
            value += w['text']
            previous = w
        if value and not AMOUNT.fullmatch(value):
            raise ValueError(f'Non-amount text in amount column at y={row[0]["yMin"]}: {value!r}')
        values.append(value or None)
    return values


def ruling_edges(pdf, page, workdir):
    """Horizontal rules spanning the remarks region of one physical page."""
    svg = Path(workdir) / f'rules-{page}'
    subprocess.run(['pdftocairo', '-f', str(page), '-l', str(page), '-svg',
                    str(pdf), str(svg)], check=True)
    root = ET.parse(svg).getroot()
    ys = []
    for element in root.iter():
        if not element.tag.endswith('path') or 'stroke' not in element.attrib:
            continue
        matrix = [float(v) for v in re.split(r'[,\s]+',
                  element.get('transform', 'matrix(1,0,0,1,0,0)')[7:-1].strip())]
        points = [(float(x), float(y)) for _, x, y in SEGMENT.findall(element.get('d') or '')]
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            xa = matrix[0] * x1 + matrix[2] * y1 + matrix[4]
            ya = matrix[1] * x1 + matrix[3] * y1 + matrix[5]
            xb = matrix[0] * x2 + matrix[2] * y2 + matrix[4]
            yb = matrix[1] * x2 + matrix[3] * y2 + matrix[5]
            if abs(ya - yb) > .5 or max(xa, xb) < NOTE_LEFT or min(xa, xb) > NOTE_RIGHT:
                continue
            if max(xa, xb) - min(xa, xb) < 30:
                continue
            ys.append((ya + yb) / 2)
    ys.sort()
    edges = []
    for y in ys:
        if edges and y - edges[-1] <= 1:
            edges[-1] = (edges[-1] + y) / 2
        else:
            edges.append(y)
    return edges


SEGMENT = re.compile(r"([ML])\s+(-?[\d.]+)\s+(-?[\d.]+)")


def location(page, y, words):
    return {'物理頁': page, '上端': y, '下端': max(w['yMax'] for w in words)}


def assign_notes(edges, words, anchors, account):
    """Attach each ruled remarks cell's text to its topmost covered row.

    Returns (assigned_cells, orphan_words): words in the remarks region of a
    page without any printed row (e.g. the next account's cover marker that
    shares the physical page) have no owner and are reported, not adopted.
    """
    # Amount words inside an execution column band are column values, not
    # remarks text, even when the ruled cell is merged across the boundary.
    note_words = [w for w in words if w['xMin'] >= NOTE_LEFT - 30 and w['text'] != account
                  and not (AMOUNT.fullmatch(w['text'])
                           and any(lo <= w['xMin'] and w['xMax'] <= hi for lo, hi in EXEC_EDGES))]
    if not note_words:
        return [], []
    if not anchors:
        return [], [w['text'] for w in note_words]
    if len(edges) < 2:
        raise ValueError('Printed remarks without enclosing horizontal rules')
    cells = {}
    for line in lines(note_words):
        index = bisect.bisect_right(edges, line[0]['yMin']) - 1
        if not 0 <= index < len(edges) - 1:
            raise ValueError(f'Remarks line outside ruled cells at y={line[0]["yMin"]}')
        cells.setdefault(index, []).append(line)
    resolved = []
    for index in sorted(cells):
        owners = [(len(path), order, path, record)
                  for order, (path, y, record) in enumerate(anchors)
                  if edges[index] <= y < edges[index + 1]]
        if not owners:
            raise ValueError(f'Remarks cell without a printed owner at y={edges[index]}')
        _, _, owner, record = min(owners)
        if record['備考'] is not None:
            raise ValueError('Printed row owns more than one remarks cell')
        record['備考'] = text([w for line in cells[index] for w in line])
        resolved.append({'edges': [edges[index], edges[index + 1]],
                         'owner': list(owner), 'text': record['備考']})
    return resolved, []


def parent_record(words, row, page, y, name_high):
    labels = [w for w in row if NAME_LEFT <= w['xMin'] < NAME_RIGHT]
    marker = min(labels, key=lambda w: w['xMin'])
    match = re.match(r'([0-9]+)(.*)', marker['text'])
    if not match:
        if ''.join(w['text'] for w in labels).replace(' ', '') != '歳出合計':
            raise ValueError(f'Unnumbered printed path at page {page}, y={y}')
        level = '合計'
    else:
        level = '款' if marker['xMin'] < LEVEL_KAN else '項' if marker['xMin'] < LEVEL_KOU else '目'
    name_words = select(words, marker['xMin'], NAME_RIGHT, y - 7.5, name_high)
    name_words = [w for w in name_words if w is not marker]
    if match and match[2]:
        name_words.append({**marker, 'text': match[2],
                           'xMin': marker['xMin'] + 4.5 * len(match[1])})
    record = {'行種別': level, '番号': match[1] if match else None,
              '名称': '歳出合計' if level == '合計' else text(name_words),
              **{key: value for key, value in zip(BUDGET, cell_amounts(row, BUDGET_EDGES))},
              **{key: value for key, value in zip(EXECUTED, cell_amounts(row, EXEC_EDGES))},
              '備考': None,
              **location(page, y, labels + name_words)}
    return record


def section_record(words, row, page, y, name_high):
    # The statutory-setsu number prints at the left edge of the 区分 column and
    # may be fragmented ('1' + '3使用料及び賃借料' prints 13使用料及び賃借料);
    # rejoin contiguous pieces on the marker baseline before splitting digits.
    pieces = sorted([w for w in row if SETSU_LEFT <= w['xMin'] < SETSU_LEFT + 16],
                    key=lambda w: w['xMin'])
    if not pieces:
        raise ValueError(f'Missing section number at page {page}, y={y}')
    marker_text, marker_end = '', None
    marker_start = pieces[0]['xMin']
    taken = []
    for w in pieces:
        if marker_end is not None and w['xMin'] - marker_end > 2:
            break
        marker_text += w['text']
        marker_end = w['xMax']
        taken.append(w)
    match = re.match(r'([0-9]+)(.*)', marker_text)
    if not match:
        raise ValueError(f'Section marker without a number at page {page}, y={y}')
    marker_pieces = {id(w) for w in taken}
    name_words = select(words, SETSU_LEFT, SETSU_RIGHT + 5, y - 7.5, name_high)
    name_words = [w for w in name_words if id(w) not in marker_pieces]
    if match[2]:
        rest_width = marker_end - marker_start
        digit_width = rest_width * len(match[1]) / max(len(marker_text), 1)
        name_words.append({'text': match[2], 'xMin': marker_start + digit_width,
                           'xMax': marker_end, 'yMin': row[0]['yMin'], 'yMax': row[0]['yMax']})
    return {'行種別': '節', '番号': None, '名称': None, '区分_番号': match[1],
            '区分_名称': text(name_words),
            **{key: None for key in BUDGET},
            **{key: value for key, value in zip(EXECUTED, cell_amounts(row, EXEC_EDGES))},
            '備考': None,
            **location(page, y, taken + name_words)}


PARENT_PREFIX_KEYS = ['番号', '名称', *BUDGET, *EXECUTED, '備考', '物理頁', '上端', '下端']


def lineage(context):
    """款・項・目 printed records repeated onto a leaf row as prefixed columns."""
    leaf = {}
    for level in ('款', '項', '目'):
        if level in context:
            leaf.update({level + '_' + key: context[level].get(key)
                         for key in PARENT_PREFIX_KEYS})
    return leaf


def detail(pages, edges, account):
    """Leaf rows only: statutory setsu rows, or a 目 row when it has no setsu.

    Printed 款・項・目・合計 rows are lineage columns and the local parents.json
    observation, not rows in the raw table.
    """
    current = {}
    leaves, parents, note_cells, orphans = [], [], [], []
    for page, words in pages:
        body = [w for w in words if BODY_TOP <= w['yMin'] < BODY_BOTTOM]
        events = []
        for row in lines(body):
            kinds = set()
            if any(BUDGET_EDGES[0][0] <= w['xMin'] < SETSU_LEFT and AMOUNT.fullmatch(w['text']) for w in row):
                kinds.add('parent')
            if any(SETSU_LEFT <= w['xMin'] < SETSU_LEFT + 16 and re.match(r'[0-9]+', w['text']) for w in row):
                kinds.add('section')
            for kind in kinds:
                events.append((row[0]['yMin'], kind, row))
        if len(events) != len({event[0] for event in events}):
            raise ValueError(f'Shared parent/section baseline at page {page}')
        anchors, pending = [], []
        # A 目 becomes a leaf only when the next event is another parent; queue
        # it and emit after assign_notes so a merged remarks cell on the same
        # page is already attached to its record.
        delayed_moku = []           # (record, context) closed by a new parent
        moku_leaf = None            # (record, context) for a 目 awaiting its first 節
        for index, (y, kind, row) in enumerate(events):
            name_high = events[index + 1][0] - 7.5 if index + 1 < len(events) else BODY_BOTTOM
            if kind == 'parent':
                if moku_leaf is not None:
                    delayed_moku.append(moku_leaf)
                    moku_leaf = None
                name_high = min([start - 7.5 for start, k, _ in events if k == 'parent' and start > y + .5]
                                + [BODY_BOTTOM])
                record = parent_record(body, row, page, y, name_high)
                level = record['行種別']
                if level == '款':
                    current = {'款': record}
                elif level == '項':
                    current = {'款': current['款'], '項': record}
                elif level == '目':
                    current['目'] = record
                    moku_leaf = (record, dict(current))
                elif level == '合計':
                    current = {}
                parents.append(record)
                path = tuple(current[ancestor]['番号'] for ancestor in ('款', '項', '目')
                             if ancestor in current)
                anchors.append((path, y, record))
            else:
                if set(current) != {'款', '項', '目'}:
                    raise ValueError(f'Missing printed path at page {page}, y={y}')
                moku_leaf = None      # the open 目 has a setsu row: not a leaf
                record = section_record(body, row, page, y, name_high)
                pending.append((record, dict(current)))
                anchors.append((tuple(current[a]['番号'] for a in ('款', '項', '目'))
                                + (record['区分_番号'],), y, record))
        cells, orphan = assign_notes(edges.get(page, []), body, anchors, account)
        for cell in cells:
            note_cells.append({'物理頁': page, **cell})
        if orphan:
            orphans.append({'物理頁': page, '行なし領域の文字': orphan})
        for record, context in delayed_moku:
            leaves.append({'区分_番号': None, '区分_名称': None,
                           **{key: record.get(key) for key in EXECUTED},
                           '備考': record.get('備考'), '物理頁': record['物理頁'],
                           '上端': record['上端'], '下端': record['下端'],
                           **lineage(context)})
        for record, context in pending:
            leaf = {key: record.get(key)
                    for key in ('区分_番号', '区分_名称', *EXECUTED, '備考', '物理頁', '上端', '下端')}
            leaf.update(lineage(context))
            leaves.append(leaf)
    if moku_leaf is not None:
        record, context = moku_leaf
        leaves.append({'区分_番号': None, '区分_名称': None,
                       **{key: record.get(key) for key in EXECUTED},
                       '備考': record.get('備考'), '物理頁': record['物理頁'],
                       '上端': record['上端'], '下端': record['下端'],
                       **lineage(context)})
    return leaves, parents, note_cells, orphans


def summary(pages, account):
    rows = []
    kan = None
    for page, words in pages:
        body = [w for w in words if SUM_BODY_TOP <= w['yMin'] < BODY_BOTTOM]
        entries, fragments = [], []
        for row in lines(body):
            labels = [w for w in row if SUM_KAN[0] <= w['xMin'] < SUM_KOU[1]]
            amounts = cell_amounts(row, SUM_EDGES)
            if not labels and not any(amounts):
                continue
            marker = min(labels, key=lambda w: w['xMin']) if labels else None
            match = re.match(r'([0-9]+)(.*)', marker['text']) if marker else None
            joined = ''.join(w['text'] for w in labels).replace(' ', '')
            # A wrapped name prints its first line(s) above and its last line
            # below the numbered baseline; those lines hold labels only.
            if labels and not any(amounts) and not match and joined != '歳出合計':
                fragments.append({'yMin': row[0]['yMin'],
                                  'yMax': max(w['yMax'] for w in labels),
                                  'text': text(labels)})
                continue
            entries.append({'row': row, 'labels': labels, 'amounts': amounts,
                            'marker': marker, 'match': match, 'joined': joined,
                            'prefix': [], 'suffix': []})
        for frag in fragments:
            if not entries:
                raise ValueError(f'Name fragment without a numbered row at page {page}')
            near = min(range(len(entries)),
                       key=lambda i: abs(entries[i]['row'][0]['yMin'] - frag['yMin']))
            key = 'prefix' if frag['yMin'] < entries[near]['row'][0]['yMin'] else 'suffix'
            entries[near][key].append(frag)
        for entry in entries:
            row, labels, amounts = entry['row'], entry['labels'], entry['amounts']
            marker, match = entry['marker'], entry['match']
            name_words = [w for w in labels if w is not marker]
            if match and match[2]:
                name_words.append({**marker, 'text': match[2],
                                   'xMin': marker['xMin'] + 4.5 * len(match[1])})
            if entry['joined'] == '歳出合計':
                level = '合計'
            elif marker and match and marker['xMin'] < SUM_KOU[0]:
                level = '款'
            elif marker and match and SUM_KOU[0] <= marker['xMin'] < SUM_KOU[1]:
                level = '項'
            else:
                raise ValueError(f'Unrecognised summary row at page {page}, y={row[0]["yMin"]}')
            name = '歳出合計' if level == '合計' else text(name_words)
            if entry['prefix'] or entry['suffix']:
                name = '\n'.join(part for part in
                                 [f['text'] for f in entry['prefix']]
                                 + [name] + [f['text'] for f in entry['suffix']] if part)
            record = {'番号': match[1] if match else None,
                      '名称': name,
                      **{key: value for key, value in zip(SUM_COLUMNS, amounts)},
                      '物理頁': page,
                      '上端': min([row[0]['yMin']] + [f['yMin'] for f in entry['prefix']]),
                      '下端': max([w['yMax'] for w in labels
                                   + [w for w in row if AMOUNT.fullmatch(w['text'])]]
                                  + [f['yMax'] for f in entry['suffix']])}
            if level == '款':
                kan = {'番号': record['番号'], '名称': record['名称']}
            elif level == '項':
                if kan is None:
                    raise ValueError(f'Summary kou without kan at page {page}')
                record.update({'款_番号': kan['番号'], '款_名称': kan['名称']})
            rows.append(record)
    return rows


DETAIL_COLUMNS = (['区分_番号', '区分_名称', *EXECUTED, '備考', '物理頁', '上端', '下端']
                  + [f'{level}_{key}' for level in ('款', '項', '目') for key in PARENT_PREFIX_KEYS])
KANKOU_COLUMNS = ['番号', '名称', *SUM_COLUMNS, '物理頁', '上端', '下端', '款_番号', '款_名称']


def table_columns(keys):
    return tuple(ParquetColumn(k, 'BIGINT' if k == '物理頁' or k.endswith('_物理頁')
                               else 'DOUBLE' if k.endswith(('上端', '下端')) else 'VARCHAR')
                 for k in keys)


def detail_metadata(columns, account):
    amounts = [c for c in columns if c in BUDGET + EXECUTED
               or any(c.endswith('_' + key) for key in BUDGET + EXECUTED)]
    contexts = [{'columns': [c for c in columns if c.startswith(level + '_')],
                 'header_path': ['款項', level],
                 'grain_columns': [level + '_番号', level + '_物理頁', level + '_上端']}
                for level in ('款', '項', '目')]
    contexts.append({'columns': ['区分_番号', '区分_名称', *EXECUTED, '備考'],
                     'header_path': ['節'], 'semantic_role': 'setsu',
                     'grain_columns': ['目_物理頁', '目_上端', '区分_番号']})
    note = ('最細行のみ: 法定節（区分番号+区分名称）が原典の最細明細で、'
            '節のない目（予備費等）は目行が葉行（区分_列は空）。'
            '款・項・目・合計の印字行は行にせず、所属する行の番号・名称・予算5列・'
            '執行6列・備考・印字位置を款_/項_/目_列として各leaf行へ反復する。'
            '款・項・目・歳出合計の印字行自体はlocal観測 parents.json に保持する。'
            '左印字頁に科目・予算5列・節区分、右印字頁に節金額・執行6列・備考が'
            '印字される。'
            '備考欄は水平罫線の結合セルが所属範囲を定め、セルが縦に覆う行のうち'
            '最上位の行の備考欄へセル全文を印字行の改行のまま保持する。'
            '物理頁はPDFの物理頁。名称の折り返しは改行、字間の印字間隔は空白で保持。'
            '本文の文字は描画が二重（クリップ済みの幽霊層は含めない）。'
            f'見開き末尾の「{account}」会計標は行の備考ではないため除く。')
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': amounts}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}}],
            'column_contexts': contexts}


def summary_metadata(columns):
    amounts = [c for c in columns if c in SUM_COLUMNS]
    contexts = [{'columns': ['款_番号', '款_名称'], 'header_path': ['款'],
                 'grain_columns': ['款_番号']},
                {'columns': ['番号', '名称', *SUM_COLUMNS],
                 'header_path': ['款', '項'], 'grain_columns': ['番号', '物理頁', '上端']}]
    note = ('歳出款項表の印字行（款行・項行・歳出合計行をそのまま保持）。'
            '項行は所属する款の番号・名称を款_列として保持する（款列と項列の'
            '罫線・印字位置で所属が一意に定まる）。'
            '比較列は原典見出し「予算現額と支出済額との比較」の値（不用額と同額）。'
            '物理頁はPDFの物理頁（A3見開き1頁=印字2頁、左印字頁に款・項・予算現額、'
            '右印字頁に支出済額・翌年度繰越額・不用額・比較が印字される）。')
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': amounts}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}}],
            'column_contexts': contexts}


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Kita general settlement requires one original')
    source = inputs[0]
    if source['format'] != 'pdf' or source.get('pdf_type') != 'text':
        raise ValueError('This measured layout is Kita text settlement expenditure only')
    account = options.get('account', '一般会計')
    scopes = [scope for scope in source['scope'] if scope['account'] == account]
    if len(scopes) != 1 or len(scopes[0]['pages']) < 2:
        raise ValueError(f'{account} scope must hold a summary range and a detail range')
    raw = scopes[0]['pages']
    spans = [(p['start'], p['end']) if isinstance(p, dict) else tuple(p) for p in raw]
    part = options['part']
    if part == 'summary':
        first, last = spans[0]
    elif part == 'detail':
        spans = spans[1:]
        first, last = spans[0][0], spans[-1][1]
        if [p for a, b in spans for p in range(a, b + 1)] != list(range(first, last + 1)):
            raise ValueError('Detail range must be contiguous')
    else:
        raise ValueError(f'Unknown part: {part}')
    destination = Path(destination)
    observations = destination / 'kita-observations'
    observations.mkdir(parents=True, exist_ok=True)
    traced = trace_words(source['path'], first, last)
    pages = [(page, entry['words']) for page, entry in traced]
    (observations / 'phantom-words.json').write_text(json.dumps(
        [{'物理頁': page, **entry['stats']} for page, entry in traced],
        ensure_ascii=False, indent=2) + '\n')
    table_id = options['table_id']
    if part == 'summary':
        rows = summary(pages, account)
        columns = KANKOU_COLUMNS
        meta = summary_metadata(columns)
    else:
        with tempfile.TemporaryDirectory() as workdir:
            edges = {page: ruling_edges(source['path'], page, workdir) for page, _ in pages}
        rows, parents, note_cells, orphans = detail(pages, edges, account)
        (observations / 'note-cells.json').write_text(json.dumps(
            {'edges': {str(p): e for p, e in edges.items()}, 'cells': note_cells,
             'orphan_words': orphans},
            ensure_ascii=False, indent=2) + '\n')
        (observations / 'parents.json').write_text(json.dumps(
            {'款項目合計の印字行': parents}, ensure_ascii=False, indent=2) + '\n')
        columns = DETAIL_COLUMNS
        meta = detail_metadata(columns, account)
    output = write_conversion(destination / (table_id + '.parquet'),
                              [{key: row.get(key) for key in columns} for row in rows],
                              columns=table_columns(columns),
                              context=ConversionContext(source['sha256'], table_id, __file__))
    return {table_id: {'path': Path(output.path), 'metadata': meta}}
