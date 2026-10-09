"""Assemble Meguro's printed settlement columns from Poppler word boxes."""

from pathlib import Path
import json
import re
import subprocess
import xml.etree.ElementTree as ET

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

AMOUNT = re.compile(r"△?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")
BUDGET = ['当初予算額', '補正予算額', '継続費及び繰越事業費繰越額', '予備費支出及び流用増減', '計']
EXECUTED = ['支出済額', '継続費逓次繰越', '繰越明許費', '事故繰越し', '不用額']
BUDGET_EDGES = [(104, 174), (174, 245), (245, 305), (305, 364), (364, 436)]
EXECUTED_EDGES = [(559, 701), (701, 761), (761, 821), (821, 880), (880, 953)]


def observe(pdf, first, last, path):
    subprocess.run(['pdftotext', '-f', str(first), '-l', str(last), '-bbox-layout',
                    str(pdf), str(path)], check=True)
    pages = []
    for number, page in enumerate(ET.parse(path).findall('.//{*}page'), first):
        if abs(float(page.get('width')) - 1190.55) > .1:
            raise ValueError(f'Unmeasured page dimensions at {number}')
        words = [dict(text=w.text or '', **{k: float(v) for k, v in w.attrib.items()})
                 for w in page.findall('.//{*}word')]
        pages.append((number, sorted(words, key=lambda w: (w['yMin'], w['xMin']))))
    if len(pages) != last - first + 1:
        raise ValueError('Incomplete Poppler page range')
    return pages


def lines(words):
    result = []
    for word in sorted(words, key=lambda w: (w['yMin'], w['xMin'])):
        if not result or word['yMin'] - result[-1][0]['yMin'] > .5:
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


def cell(words, y, edges):
    left, right = edges
    nearby = [w for w in words if abs(w['yMin'] - y) < .5]
    values = select(nearby, left, right, y - .5, y + .5)
    # The reserve has a printed 0 adjacent to a negative transfer. Poppler
    # combines those two cells into one word; split only this measured boundary.
    for word in nearby:
        if word['xMin'] < 305 < word['xMax'] and re.fullmatch(r'0△[0-9,]+', word['text']):
            if edges == (245, 305):
                values.append({**word, 'text': '0', 'xMax': word['xMin'] + 4.5})
            elif edges == (305, 364):
                values.append({**word, 'text': word['text'][1:], 'xMin': word['xMin'] + 4.5})
    value = ''.join(w['text'] for w in sorted(values, key=lambda w: w['xMin']))
    if not AMOUNT.fullmatch(value):
        raise ValueError(f'Incomplete amount y={y}, bounds={edges}: {value!r}')
    return value


def location(page, y, words):
    return {'物理頁': page, '上端': y, '下端': max(w['yMax'] for w in words)}


def body(words):
    units = [w['yMin'] for w in words if w['text'] == '円' and 104 <= w['xMin'] < 953]
    if not units:
        raise ValueError('No printed currency header')
    top = min(units)
    # The first wrapped name starts just below the currency header, above
    # its numbered row's financial baseline.
    return [w for w in words if top + .5 <= w['yMin'] < 800]


def financial_starts(words, edges):
    left, right = edges
    numeric = [w for w in words if left <= w['xMin'] and w['xMax'] <= right
               and re.fullmatch(r'[△0-9,]+', w['text'])]
    return [row[0]['yMin'] for row in lines(numeric)]


def parent_record(words, page, y, name_high, note_high):
    labels = select(words, 20, 104, y - .5, y + .5)
    marker = min(labels, key=lambda w: w['xMin'])
    match = re.match(r'([0-9]+)(.*)', marker['text'])
    if not match:
        # The final expenditure total occupies the same budget columns.
        return None
    level = '款' if marker['xMin'] < 30 else '項' if marker['xMin'] < 39 else '目'
    name_words = select(words, marker['xMin'] + 1, 104, y - 7.5, name_high)
    name_words = [w for w in name_words if w is not marker]
    if match[2]:
        name_words.append({**marker, 'text': match[2],
                           'xMin': marker['xMin'] + 4.5 * len(match[1])})
    return {'level': level, '番号': match[1], '名称': text(name_words),
            **{key: cell(words, y, edge) for key, edge in zip(BUDGET + EXECUTED, BUDGET_EDGES + EXECUTED_EDGES)},
            '備考': text(select(words, 953, 1180, y - 7.5, note_high)),
            **location(page, y, labels)}


def detail(pages):
    current = {}
    sections, parents = [], []
    total_count = 0
    for page, words in pages:
        words = body(words)
        parent_starts = financial_starts(words, BUDGET_EDGES[0])
        section_starts = financial_starts(words, (493.5, 559))
        events = sorted([(y, 'parent') for y in parent_starts] + [(y, 'section') for y in section_starts])
        for index, (y, kind) in enumerate(events):
            note_high = events[index + 1][0] - 7.5 if index + 1 < len(events) else 800
            if kind == 'parent':
                name_high = min([start - 7.5 for start in parent_starts if start > y + .5] + [800])
                record = parent_record(words, page, y, name_high, note_high)
                if record is None:
                    total_count += 1
                    continue
                level = record['level']
                if level == '款':
                    current = {}
                elif level == '項':
                    current.pop('目', None)
                current[level] = record
                parents.append(record)
            else:
                if set(current) != {'款', '項', '目'}:
                    raise ValueError(f'Missing printed path at page {page}, y={y}')
                markers = select(words, 436, 493.5, y - .5, y + .5)
                marker = min(markers, key=lambda w: w['xMin'])
                match = re.match(r'([0-9]+)(.*)', marker['text'])
                if not match:
                    raise ValueError(f'Missing section number at page {page}, y={y}')
                name_high = events[index + 1][0] - 7.5 if index + 1 < len(events) else 800
                name_words = [w for w in select(words, 436, 493.5, y - 7.5, name_high) if w is not marker]
                if match[2]:
                    name_words.append({**marker, 'text': match[2], 'xMin': marker['xMin'] + 4.5 * len(match[1])})
                row = {}
                for level in ('款', '項', '目'):
                    row.update({level + '_' + k: v for k, v in current[level].items() if k != 'level'})
                row.update({'区分_番号': match[1], '区分_名称': text(name_words),
                            '金額': cell(words, y, (493.5, 559)),
                            **{key: cell(words, y, edge) for key, edge in zip(EXECUTED, EXECUTED_EDGES)},
                            '備考': text(select(words, 953, 1180, y - 7.5, note_high)),
                            **location(page, y, markers)})
                sections.append(row)
    if total_count != 1:
        raise ValueError('Expected one printed detail expenditure total')
    return sections, parents


def metadata(columns):
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
    note = '法定節が原典の最細明細。所属する款・項・目の予算現額5列と支出済額・繰越3列・不用額・備考を反復。節の金額は予算現額、節の支出済額は執行実績。同じ欄の名称折り返しは改行、単語間の印字間隔は空白で保持。備考は各印字行の欄へ対応し、節への推定配賦を行わない。'
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': amounts}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}}],
            'column_contexts': contexts}


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Meguro general settlement requires one original')
    source = inputs[0]
    if (source['target']['jurisdiction'] != '131105' or source['target']['document_kind'] != 'settlement'
            or source['direction'] != 'expenditure' or source['format'] != 'pdf' or source['pdf_type'] != 'text'):
        raise ValueError('This measured layout is Meguro text settlement expenditure only')
    selected = [p for scope in source['scope'] if scope['account'] == '一般会計'
                for first, last in scope['pages'] for p in range(first, last + 1)]
    if sorted(selected) != [8, 9, 10, *range(42, 92)]:
        raise ValueError('Measured scope is general expenditure physical pages 8–10 and 42–91')
    destination = Path(destination)
    observations = destination / 'meguro-observations'
    observations.mkdir()
    sections, parents = detail(observe(source['path'], 42, 91, observations / 'detail-bbox.html'))
    (observations / 'parents.json').write_text(json.dumps({'detail': parents}, ensure_ascii=False, indent=2) + '\n')
    table_id = options['table_id']
    columns = tuple(ParquetColumn(k, 'BIGINT' if k.endswith('物理頁') else 'DOUBLE' if k.endswith(('上端', '下端')) else 'VARCHAR') for k in sections[0])
    output = write_conversion(destination / (table_id + '.parquet'), sections, columns=columns,
                              context=ConversionContext(source['sha256'], table_id, __file__))
    return {table_id: {'path': Path(output.path), 'metadata': metadata(list(sections[0]))}}
