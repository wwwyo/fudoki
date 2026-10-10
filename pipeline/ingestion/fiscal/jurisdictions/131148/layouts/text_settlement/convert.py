"""Assemble Nakano's printed settlement spread columns from Poppler word boxes."""

import bisect
from pathlib import Path
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

AMOUNT = re.compile(r"△?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")
BUDGET = ['当初予算額', '補正予算額', '継続費及び繰越事業費繰越額', '予備費支出及び流用増減', '計']
EXECUTED = ['支出済額', '継続費逓次繰越', '繰越明許費', '事故繰越し', '不用額']
PAGE_WIDTH = 595.32
BODY_TOP, BODY_BOTTOM = 112, 800
LABEL_RIGHT = 125
AMOUNT_LEFT, AMOUNT_RIGHT = 125, 497
SECTION_LEFT, SECTION_RIGHT = 495, 575
RIGHT_AMOUNTS_RIGHT = 1033.3
NOTE_LEFT = 1035
NOTE_RULE_LEFT, NOTE_RULE_RIGHT = 440, 568  # unshifted right-page x of the remarks column
SEGMENT = re.compile(r'([ML])\s+(-?[\d.]+)\s+(-?[\d.]+)')


def observe(pdf, first, last, path):
    subprocess.run(['pdftotext', '-f', str(first), '-l', str(last), '-bbox-layout',
                    str(pdf), str(path)], check=True)
    pages = []
    for number, page in enumerate(ET.parse(path).findall('.//{*}page'), first):
        if abs(float(page.get('width')) - PAGE_WIDTH) > .1 or abs(float(page.get('height')) - 841.92) > .1:
            raise ValueError(f'Unmeasured page dimensions at {number}')
        words = [dict(text=w.text or '', **{k: float(v) for k, v in w.attrib.items()})
                 for w in page.findall('.//{*}word')]
        pages.append((number, words))
    if len(pages) != last - first + 1:
        raise ValueError('Incomplete Poppler page range')
    spreads = []
    for index in range(0, len(pages), 2):
        left, right = pages[index], pages[index + 1]
        if right[0] != left[0] + 1:
            raise ValueError('Detail pages must alternate left/right facing pages')
        words = [w for w in left[1] if BODY_TOP <= w['yMin'] < BODY_BOTTOM]
        words += [{**w, 'xMin': w['xMin'] + PAGE_WIDTH, 'xMax': w['xMax'] + PAGE_WIDTH}
                  for w in right[1] if BODY_TOP <= w['yMin'] < BODY_BOTTOM]
        spreads.append((left[0], sorted(words, key=lambda w: (w['yMin'], w['xMin']))))
    return spreads


def ruling_edges(pdf, page, workdir):
    """Horizontal rules crossing the remarks column of one right page.

    The remarks column is ruled into merged cells whose vertical extent decides
    ownership; Poppler's SVG surface carries those strokes as vector paths.
    """
    svg = Path(workdir) / f'rules-{page}'
    subprocess.run(['pdftocairo', '-f', str(page), '-l', str(page), '-svg',
                    str(pdf), str(svg)], check=True)
    root = ET.parse(svg).getroot()
    ys = []
    for element in root:
        if element.tag.endswith('defs'):
            continue
        for path in [e for e in element.iter() if e.tag.endswith('path')]:
            matrix = [float(v) for v in re.split(r'[,\s]+', path.get('transform', 'matrix(1,0,0,1,0,0)')[7:-1].strip())]
            points = [(float(x), float(y)) for _, x, y in SEGMENT.findall(path.get('d') or '')]
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                xa = matrix[0] * x1 + matrix[2] * y1 + matrix[4]
                xb = matrix[0] * x2 + matrix[2] * y2 + matrix[4]
                ya = matrix[1] * x1 + matrix[3] * y1 + matrix[5]
                yb = matrix[1] * x2 + matrix[3] * y2 + matrix[5]
                if abs(ya - yb) > .5 or min(xa, xb) > NOTE_RULE_RIGHT or max(xa, xb) < NOTE_RULE_LEFT:
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


def amounts(row, left, right, count):
    values = [w for w in row if left <= w['xMin'] < right and AMOUNT.fullmatch(w['text'])]
    values.sort(key=lambda w: w['xMin'])
    if len(values) != count:
        raise ValueError(f'Expected {count} printed amounts at y={row[0]["yMin"]}: {[w["text"] for w in row]}')
    if any(a['xMax'] >= b['xMin'] for a, b in zip(values, values[1:])):
        raise ValueError(f'Overlapping printed amounts at y={row[0]["yMin"]}')
    return [w['text'] for w in values]


def assign_notes(edges, words, anchors, account):
    """Attach each ruled remarks cell's full text to its owning row's 備考.

    Remarks are printed inside merged cells delimited by horizontal rules; a
    cell's vertical extent decides which rows it covers and the shallowest
    covered row owns the whole cell. anchors are (path, y, record) tuples in
    printed order, with record None for the expenditure total row.
    """
    note_words = [w for w in words if w['xMin'] >= NOTE_LEFT and w['text'] != account]
    if not note_words:
        return []
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
        if record is None:
            raise ValueError('Remarks cell owned by the printed expenditure total')
        if record['備考'] is not None:
            raise ValueError('Printed row owns more than one remarks cell')
        record['備考'] = text([w for line in cells[index] for w in line])
        resolved.append({'edges': [edges[index], edges[index + 1]],
                         'owner': list(owner),
                         'text': record['備考']})
    return resolved


def location(page, y, words):
    return {'物理頁': page, '上端': y, '下端': max(w['yMax'] for w in words)}


def parent_record(words, row, page, y, name_high):
    labels = [w for w in row if w['xMin'] < LABEL_RIGHT]
    marker = min(labels, key=lambda w: w['xMin'])
    match = re.match(r'([0-9]+)(.*)', marker['text'])
    if not match:
        # The final expenditure total occupies the same budget columns.
        if ''.join(w['text'] for w in labels) != '歳出合計':
            raise ValueError(f'Unnumbered printed path at page {page}, y={y}')
        return None
    level = '款' if marker['xMin'] < 45 else '項' if marker['xMin'] < 58 else '目' if marker['xMin'] < 95 else None
    if level is None:
        raise ValueError(f'Unmeasured indent at page {page}, y={y}')
    name_words = select(words, marker['xMin'] + 1, LABEL_RIGHT, y - 7.5, name_high)
    name_words = [w for w in name_words if w is not marker]
    if match[2]:
        name_words.append({**marker, 'text': match[2],
                           'xMin': marker['xMin'] + 4.5 * len(match[1])})
    return {'level': level, '番号': match[1], '名称': text(name_words),
            **{key: value for key, value in zip(BUDGET, amounts(row, AMOUNT_LEFT, AMOUNT_RIGHT, 5))},
            **{key: value for key, value in zip(EXECUTED, amounts(row, 690, RIGHT_AMOUNTS_RIGHT, 5))},
            '備考': None,
            **location(page, y, labels + name_words)}


def section_record(words, row, page, y, name_high):
    markers = [w for w in row if SECTION_LEFT <= w['xMin'] < 509 and w['xMax'] <= 510]
    if len(markers) != 1:
        raise ValueError(f'Missing section number at page {page}, y={y}')
    marker = markers[0]
    match = re.fullmatch(r'([0-9]+)', marker['text'])
    if not match:
        raise ValueError(f'Missing section number at page {page}, y={y}')
    name_words = select(words, 509, SECTION_RIGHT, y - 7.5, name_high)
    return {'区分_番号': match[1], '区分_名称': text(name_words),
            **{key: value for key, value in zip(['金額'] + EXECUTED, amounts(row, 600, RIGHT_AMOUNTS_RIGHT, 6))},
            '備考': None,
            **location(page, y, markers + name_words)}


def detail(spreads, edges, account):
    current = {}
    sections, parents, note_cells = [], [], []
    total_count = 0
    for page, words in spreads:
        events = []
        for row in lines(words):
            if any(AMOUNT_LEFT <= w['xMin'] < AMOUNT_RIGHT and AMOUNT.fullmatch(w['text']) for w in row):
                events.append((row[0]['yMin'], 'parent', row))
            if any(SECTION_LEFT <= w['xMin'] < 509 and w['xMax'] <= 510 for w in row):
                events.append((row[0]['yMin'], 'section', row))
        if len(events) != len({event[0] for event in events}):
            raise ValueError(f'Shared parent/section baseline at page {page}')
        parent_starts = [event[0] for event in events if event[1] == 'parent']
        anchors, pending = [], []
        for index, (y, kind, row) in enumerate(events):
            name_high = events[index + 1][0] - 7.5 if index + 1 < len(events) else BODY_BOTTOM
            if kind == 'parent':
                name_high = min([start - 7.5 for start in parent_starts if start > y + .5] + [BODY_BOTTOM])
                record = parent_record(words, row, page, y, name_high)
                if record is None:
                    total_count += 1
                    anchors.append(((), y, None))
                    continue
                level = record['level']
                if level == '款':
                    current = {}
                elif level == '項':
                    current.pop('目', None)
                current[level] = record
                path = tuple(current[ancestor]['番号'] for ancestor in ('款', '項', '目')
                             if ancestor in current)
                parents.append(record)
                anchors.append((path, y, record))
            else:
                if set(current) != {'款', '項', '目'}:
                    raise ValueError(f'Missing printed path at page {page}, y={y}')
                record = section_record(words, row, page, y, name_high)
                anchors.append((tuple(current[ancestor]['番号'] for ancestor in ('款', '項', '目'))
                                + (record['区分_番号'],), y, record))
                pending.append((record, dict(current)))
        for cell in assign_notes(edges.get(page + 1, []), words, anchors, account):
            note_cells.append({'page': page + 1, **cell})
        for record, context in pending:
            leaf = {}
            for level in ('款', '項', '目'):
                leaf.update({level + '_' + k: v for k, v in context[level].items() if k != 'level'})
            leaf.update(record)
            sections.append(leaf)
    if total_count != 1:
        raise ValueError('Expected one printed detail expenditure total')
    return sections, parents, note_cells


def metadata(columns, account):
    amounts = [c for c in columns if c in BUDGET + EXECUTED + ['金額']
               or any(c.endswith('_' + key) for key in BUDGET + EXECUTED)]
    contexts = []
    for level in ('款', '項', '目'):
        contexts.append({'columns': [c for c in columns if c.startswith(level + '_')],
                         'header_path': ['科目', level],
                         'grain_columns': [level + '_番号', level + '_物理頁', level + '_上端']})
    contexts.append({'columns': ['区分_番号', '区分_名称', '金額', *EXECUTED, '備考'],
                     'header_path': ['節'], 'semantic_role': 'setsu',
                     'grain_columns': ['目_物理頁', '目_上端', '区分_番号']})
    note = ('法定節が原典の最細明細。所属する款・項・目の予算5列・執行5列・備考・印字位置を反復。'
            '節の金額は予算現額（右頁の節金額欄）、節の支出済額以下5列は執行実績。'
            '同じ欄の名称折り返しは改行、単語間の印字間隔は空白で保持。'
            '上端は印字先頭行の上端、下端は名称の全印字行を囲む下端。'
            '備考欄は水平罫線の結合セルが所属範囲を定め、セルが縦に覆う行のうち最上位の行'
            '（款・項・目のいずれか）の備考欄へセル全文を印字行の改行のまま保持する。'
            '節自身に所属する備考セルはこの原典に存在しない。'
            '原典は左右見開きで、科目・予算・節区分は左頁、節金額・執行・備考は右頁に印字される。'
            '物理頁は左頁を記録し、右側各欄は物理頁+1の頁に印字される。'
            f'見開き末尾の「{account}」会計標は行の備考ではないため除く。')
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': amounts}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}}],
            'column_contexts': contexts}


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Nakano general settlement requires one original')
    source = inputs[0]
    if (source['target']['jurisdiction'] != '131148' or source['target']['document_kind'] != 'settlement'
            or source['direction'] != 'expenditure' or source['format'] != 'pdf' or source['pdf_type'] != 'text'):
        raise ValueError('This measured layout is Nakano text settlement expenditure only')
    account = options.get('account', '一般会計')
    selected = [p for scope in source['scope'] if scope['account'] == account
                for first, last in scope['pages'] for p in range(first, last + 1)]
    if not selected or sorted(selected) != list(range(selected[0], selected[-1] + 1)):
        raise ValueError(f'Measured scope for {account} must be one contiguous page range')
    # The first spread of each account's expenditure scope is the printed
    # 歳出決算事項別明細総括; detail spreads follow it.
    detail_pages = selected[2:]
    if len(detail_pages) % 2:
        raise ValueError(f'Detail pages for {account} must pair into left/right spreads')
    destination = Path(destination)
    observations = destination / 'nakano-observations'
    observations.mkdir()
    spreads = observe(source['path'], detail_pages[0], detail_pages[-1], observations / 'detail-bbox.html')
    with tempfile.TemporaryDirectory() as workdir:
        edges = {page + 1: ruling_edges(source['path'], page + 1, workdir)
                 for page, _ in spreads}
    sections, parents, note_cells = detail(spreads, edges, account)
    (observations / 'parents.json').write_text(json.dumps({'detail': parents}, ensure_ascii=False, indent=2) + '\n')
    (observations / 'note-cells.json').write_text(json.dumps(
        {'edges': {str(p): e for p, e in edges.items()}, 'cells': note_cells},
        ensure_ascii=False, indent=2) + '\n')
    table_id = options['table_id']
    columns = tuple(ParquetColumn(k, 'BIGINT' if k.endswith('物理頁') else 'DOUBLE' if k.endswith(('上端', '下端')) else 'VARCHAR') for k in sections[0])
    output = write_conversion(destination / (table_id + '.parquet'), sections, columns=columns,
                              context=ConversionContext(source['sha256'], table_id, __file__))
    return {table_id: {'path': Path(output.path), 'metadata': metadata(list(sections[0]), account)}}
