"""Read Musashino's measured settlement detail pages with Poppler words.

Scope: 132039 settlement expenditure, 後期高齢者医療会計 (3 physical pages,
each a rotated A3 spread of two printed pages, no summary page).

The statutory 節 list and the 備考 column are independent decompositions of a
目: 備考 lines carry no serial numbers and nest (e.g. 委託料 contains
システム改修 and システム保守), so no pin height or name alone turns them
into rows. The raw grain is the 節 where printed, else the 目 (予備費).
"""
from pathlib import Path
import json
import re
import subprocess
import xml.etree.ElementTree as ET

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

ACCOUNT = '後期高齢者医療会計'
TOTAL_LABEL = ('歳', '出', '合', '計')
PARENT_AMOUNTS = ['当初予算額', '補正予算額', '継続費及び繰越事業費繰越額',
                  '予備費支出及び流用増減', '計', '支出済額', '翌年度繰越額', '不用額']
# Measured amount bands: (left, right) in rotated-landscape points.
AMOUNT_EDGES = [(142, 216), (218, 290), (290, 350), (350, 413),
                (415, 482), (728, 792), (794, 862), (864, 925)]
SETSU_AMOUNT_EDGE = (640, 722)
SETSU_NAME_ZONE = (480, 600)
SETSU_EVENT_X = (480, 550)
KAN_NAME_X = (40, 66)
KOU_NAME_X = (60, 80)
MOKU_NAME_X = (88, 150)
NOTE_LEFT = 925
BODY_TOP, BODY_BOTTOM = 150, 770
AMOUNT = re.compile(r'△?(?:[0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)')
SETSU_SPLIT = re.compile(r'([0-9]+)(.+)')
TOTAL_CARRY_LABELS = ('繰越明許費', '事故繰越し', '継続費逓次繰越')


def physical_pages(ranges):
    pages = []
    for first, last in ranges:
        if first > last or (pages and first <= pages[-1]):
            raise ValueError('Physical page ranges must be ordered and disjoint')
        pages.extend(range(first, last + 1))
    return pages


def observe(pdf, first, last, output):
    subprocess.run(['pdftotext', '-f', str(first), '-l', str(last), '-bbox-layout',
                    str(pdf), str(output)], check=True)
    pages = []
    for number, page in enumerate(ET.parse(output).findall('.//{*}page'), first):
        words = [dict(text=w.text or '', **{k: float(v) for k, v in w.attrib.items()})
                 for w in page.findall('.//{*}word')]
        pages.append((number, sorted(words, key=lambda w: (w['yMin'], w['xMin']))))
    if len(pages) != last - first + 1:
        raise ValueError('Poppler returned incomplete page range')
    widest = max((w['xMax'] for _, words in pages for w in words), default=0)
    if widest < 1100:
        raise ValueError('Unmeasured Musashino page space')
    return pages


def words_of(pages, page):
    return next(words for pageno, words in pages if pageno == page)


def same_line(words, y, left, right):
    return [w for w in words if left <= w['xMin'] and w['xMax'] < right
            and abs(w['yMin'] - y) < 1.2]


def joined(words):
    return ''.join(w['text'] for w in sorted(words, key=lambda w: (round(w['yMin'], 1), w['xMin'])))


def cell_amount(words, y, bounds):
    text = joined(same_line(words, y, *bounds)).replace(' ', '').replace('　', '')
    if not AMOUNT.fullmatch(text):
        raise ValueError(f'Amount cell y={y} bounds={bounds} reads {text!r}')
    return text


def events_on(pages):
    found = []
    for page, words in pages:
        for w in words:
            if not (BODY_TOP < w['yMin'] < BODY_BOTTOM):
                continue
            if re.fullmatch(r'[0-9]+', w['text']):
                if w['xMax'] < 60:
                    kind = '款'
                elif 60 <= w['xMin'] and w['xMax'] < 80:
                    kind = '項'
                elif 80 <= w['xMin'] and w['xMax'] < 92:
                    kind = '目'
                elif SETSU_EVENT_X[0] <= w['xMin'] and w['xMax'] < SETSU_EVENT_X[1]:
                    kind = '節'
                else:
                    continue
            elif (re.match(r'[0-9]', w['text']) and SETSU_EVENT_X[0] <= w['xMin']
                    and w['xMax'] < SETSU_EVENT_X[1]):
                # Setsu numbers merge with the name head (1報, 10需, 13使用料及び).
                kind = '節'
            else:
                continue
            found.append({'page': page, 'y': w['yMin'], 'x': w['xMin'], 'kind': kind, 'word': w})
    found.sort(key=lambda e: (e['page'], e['y'], e['x']))
    merged = []
    for event in found:
        if (event['kind'] == '節' and merged and merged[-1]['kind'] == '節'
                and merged[-1]['page'] == event['page']
                and abs(merged[-1]['y'] - event['y']) < 1.2):
            # One 節 number split across words (2 + 7繰 + 出 + 金).
            continue
        merged.append(event)
    return merged


def total_row(pages):
    for page, words in pages:
        by_y = {}
        for w in words:
            if w['xMax'] >= 150 or not (BODY_TOP < w['yMin'] < BODY_BOTTOM):
                continue
            if w['text'] in TOTAL_LABEL:
                by_y.setdefault(round(w['yMin'], 1), []).append(w['text'])
        for y, texts in by_y.items():
            if all(t in texts for t in TOTAL_LABEL):
                return {page: y}
    raise ValueError('Expenditure total row not found')


def level_end(page, y, events, kinds):
    later = [(e['page'], e['y']) for e in events
             if e['kind'] in kinds and (e['page'], e['y']) > (page, y + 0.8)]
    return min(later) if later else (page, BODY_BOTTOM + 1)


def names_in(pages, level, page, y, end, total_pos):
    zone = {'款': KAN_NAME_X, '項': KOU_NAME_X, '目': MOKU_NAME_X}[level]
    got = []
    for pageno, words in pages:
        for w in words:
            if not (zone[0] <= w['xMin'] and w['xMax'] < zone[1]):
                continue
            if not (BODY_TOP < w['yMin'] < BODY_BOTTOM):
                continue
            if pageno in total_pos and w['yMin'] >= total_pos[pageno] - 1.2:
                continue
            if (pageno, w['yMin']) < (page, y - 1.2) or (pageno, w['yMin']) >= (end[0], end[1] - 1.2):
                continue
            if re.fullmatch(r'[0-9]+', w['text']):
                continue
            got.append(w)
    return joined(got) or None


def detail(pages):
    events = events_on(pages)
    total_pos = total_row(pages)
    total_page, total_y = next(iter(total_pos.items()))
    parents, setsu_rows, moku_list = [], [], []
    current = {}
    for event in events:
        page, y, kind = event['page'], event['y'], event['kind']
        words = words_of(pages, page)
        if kind == '節':
            if set(current) != {'款', '項', '目'}:
                raise ValueError(f'Missing printed moku path at page {page}, y {y}')
            end = level_end(page, y, events, ('款', '項', '目', '節'))
            name_words = [w for pageno, ws in pages for w in ws
                          if (pageno, w['yMin']) >= (page, y - 1.2)
                          and (pageno, w['yMin']) < (end[0], end[1] - 1.2)
                          and SETSU_NAME_ZONE[0] <= w['xMin'] and w['xMax'] < SETSU_NAME_ZONE[1]]
            matched = SETSU_SPLIT.fullmatch(joined(name_words))
            if matched is None:
                raise ValueError(f"Setsu name at page {page}, y {y} reads {joined(name_words)!r}")
            values = {'区分_番号': matched.group(1), '区分_名称': matched.group(2),
                      '金額': cell_amount(words, y, SETSU_AMOUNT_EDGE),
                      '支出済額': cell_amount(words, y, AMOUNT_EDGES[5]),
                      '翌年度繰越額': cell_amount(words, y, AMOUNT_EDGES[6]),
                      '不用額': cell_amount(words, y, AMOUNT_EDGES[7]),
                      '物理頁': page, '上端': event['word']['yMin'],
                      '下端': max(w['yMax'] for w in name_words)}
            setsu_rows.append((current['目'], values))
            continue
        shared = {e['kind'] for e in events if e is not event and e['page'] == page
                  and abs(e['y'] - y) < 1.2 and e['kind'] in ('款', '項', '目')}
        if kind == '項' and shared == {'款'}:
            shared = set()
        elif shared:
            if not (kind == '款' and shared == {'項'}):
                raise ValueError(f'Unmeasured shared heading line at page {page}, y {y}')
        if kind == '款' and shared == {'項'}:
            # A continued spread reprints the bare kan number on the kou row;
            # the printed amounts belong to the kou.
            if event['word']['text'] != current.get('款', {}).get('番号'):
                raise ValueError(f'Unmeasured shared kan/kou line at page {page}, y {y}')
            record = {'level': kind, '番号': event['word']['text'],
                      **{k: current['款'][k] for k in PARENT_AMOUNTS},
                      '物理頁': page, '上端': event['word']['yMin'], '下端': event['word']['yMax']}
            current.pop('項', None)
            current.pop('目', None)
            current[kind] = record
            parents.append(record)
            continue
        record = {'level': kind, '番号': event['word']['text'],
                  **{k: cell_amount(words, y, b) for k, b in zip(PARENT_AMOUNTS, AMOUNT_EDGES)},
                  '物理頁': page, '上端': event['word']['yMin'], '下端': event['word']['yMax']}
        if kind == '目':
            record['ref'] = {'款': current['款'], '項': current['項']}
            current['目'] = record
            moku_list.append(record)
        else:
            if kind == '項':
                record['ref'] = {'款': current['款']}
            old = current.get(kind)
            if old is not None and old['番号'] == record['番号']:
                for key in PARENT_AMOUNTS:
                    if old[key] != record[key]:
                        raise ValueError(f'Reprinted {kind} amounts differ')
            if kind == '款':
                current.pop('項', None)
                current.pop('目', None)
            else:
                current.pop('目', None)
            current[kind] = record
        parents.append(record)
    # Hierarchy spans keep reprinted headings from swallowing names.
    for record in parents:
        kinds = {'款': ('款',), '項': ('款', '項'), '目': ('款', '項', '目')}[record['level']]
        end = level_end(record['物理頁'], record['上端'], events, kinds)
        record['名称'] = names_in(pages, record['level'], record['物理頁'], record['上端'], end,
                                  total_pos)
    # A continued spread reprints the heading row with identical amounts but
    # without the vertical name. Share the printed name within one identity.
    groups = {}
    for record in parents:
        if record['level'] == '目':
            ref = record['ref']
            key = ('目', ref['款']['番号'], ref['項']['番号'], record['番号'],
                   tuple(record[k] for k in PARENT_AMOUNTS))
        elif record['level'] == '項':
            key = ('項', record['ref']['款']['番号'], record['番号'],
                   tuple(record[k] for k in PARENT_AMOUNTS))
        else:
            key = ('款', record['番号'], tuple(record[k] for k in PARENT_AMOUNTS))
        groups.setdefault(key, []).append(record)
    for members in groups.values():
        names = {m['名称'] for m in members if m['名称']}
        if len(names) > 1:
            raise ValueError('Reprinted parent names differ')
        if names:
            for member in members:
                member['名称'] = next(iter(names))
    rows = []
    for moku in moku_list:
        end = level_end(moku['物理頁'], moku['上端'], events, ('款', '項', '目'))
        limit = end if end[0] == moku['物理頁'] else (moku['物理頁'], BODY_BOTTOM + 1)
        children = [(m, v) for m, v in setsu_rows if m is moku]
        if not children:
            children = [(moku, {'区分_番号': None, '区分_名称': None, '金額': None,
                                '支出済額': None, '翌年度繰越額': None, '不用額': None,
                                '物理頁': moku['物理頁'], '上端': moku['上端'], '下端': moku['下端']})]
        note = note_of(pages, moku['物理頁'], moku['上端'], limit)
        for _, values in children:
            row = {}
            for level in ('款', '項', '目'):
                parent = moku['ref'][level] if level in moku['ref'] else moku
                row.update({level + '_' + k: parent.get(k) for k in
                            ['番号', '名称', *PARENT_AMOUNTS, '物理頁', '上端', '下端']})
            row['目_備考'] = note
            rows.append({**row, **values})
    rows.sort(key=lambda r: (r['物理頁'], r['上端']))
    words = words_of(pages, total_page)
    total = {k: cell_amount(words, total_y, b)
             for k, b in zip(PARENT_AMOUNTS, AMOUNT_EDGES) if k != '翌年度繰越額'}
    zone = [w for w in words if 780 <= w['xMin'] and w['xMax'] < 870
            and total_y - 12 <= w['yMin'] <= total_y + 60]
    bands = {}
    for w in zone:
        bands.setdefault(round(w['yMin'], 1), []).append(w)
    lines = [(y, joined(ws)) for y, ws in sorted(bands.items())]
    carry = []
    for label in TOTAL_CARRY_LABELS:
        hit = [(y, text) for y, text in lines if label in text]
        if len(hit) != 1:
            raise ValueError(f'Total carryover label {label} unresolved')
        zeros = [w for w in words if 840 <= w['xMin'] and w['xMax'] < 868
                 and hit[0][0] - 1.2 <= w['yMin'] <= hit[0][0] + 12
                 and w['text'] == '0']
        if len(zeros) != 1:
            raise ValueError(f'Total carryover amount for {label} unresolved')
        carry.append({'区分': label, '金額': '0'})
    total = {'物理頁': total_page, '上端': total_y, **total,
             '翌年度繰越額_内訳': carry}
    observed = [{k: v for k, v in record.items() if k != 'ref'} for record in parents]
    return rows, observed, total


def note_of(pages, page, y, limit):
    words = words_of(pages, page)
    lines = {}
    for w in words:
        if w['xMin'] < NOTE_LEFT:
            continue
        if not (y - 1.2 <= w['yMin'] < limit[1] - 1.2):
            continue
        lines.setdefault(round(w['yMin'], 1), []).append(w)
    textual = [''.join(w['text'] for w in sorted(lines[key], key=lambda w: w['xMin']))
               for key in sorted(lines)]
    return '\n'.join(textual) or None


def metadata(rows):
    amounts = [k for k in rows[0]
               if k in set(PARENT_AMOUNTS + ['金額', '支出済額', '翌年度繰越額', '不用額'])
               or any(k == v or k.endswith('_' + v) for v in PARENT_AMOUNTS)]
    contexts = []
    for index, level in enumerate(('款', '項', '目')):
        columns = [k for k in rows[0] if k.startswith(level + '_')
                   and not k.endswith(('物理頁', '上端', '下端')) and k != '目_備考']
        contexts.append({'columns': columns, 'header_path': ['科目', level],
                         'grain_columns': [x + '_番号' for x in ('款', '項', '目')[:index + 1]]})
    contexts.append({'columns': ['区分_番号', '区分_名称', '金額', '支出済額', '翌年度繰越額', '不用額'],
                     'header_path': ['節', '区分', '金額'], 'semantic_role': 'setsu',
                     'grain_columns': ['款_番号', '項_番号', '目_番号', '区分_番号']})
    contexts.append({'columns': ['目_備考'], 'header_path': ['備考'],
                     'grain_columns': ['款_番号', '項_番号', '目_番号']})
    note = ('武蔵野市後期高齢者医療会計の決算事項別明細書（歳出）。款・項・目の印字欄を所属する葉へ反復。'
            '最細は法定節（節がない予備費目は目）。節一覧と備考は同じ目の独立した分解であり相互の対応を推定していない。'
            '目_備考は目の備考欄の原文（□事業・○経費・積算）。金額は円の原表記（△は減額符号）。'
            '歳出合計はlocal観測に残しraw行にしない。')
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': amounts}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}}],
            'column_contexts': contexts}


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Measured Musashino settlement uses one original')
    source = inputs[0]
    if (source['target']['jurisdiction'] != '132039' or source['target']['document_kind'] != 'settlement'
            or source['direction'] != 'expenditure' or source['format'] != 'pdf'
            or source['pdf_type'] != 'text'):
        raise ValueError('This measured layout is Musashino text settlement expenditure only')
    wanted = physical_pages(options['detail_pages'])
    selected = [p for scope in source['scope'] if scope['account'] == options['account']
                for first, last in scope['pages'] for p in range(first, last + 1)]
    if sorted(selected) != sorted(wanted):
        raise ValueError('Configured account pages differ from selected expenditure scope')
    destination = Path(destination)
    table_id = options['table_id']
    prefix = table_id.removesuffix('-expenditure-detail')
    observations = destination / f'musashino-{prefix}-observations'
    observations.mkdir()
    pages = []
    for index, (first, last) in enumerate(options['detail_pages']):
        pages.extend(observe(source['path'], first, last,
                             observations / f'detail-{index}-bbox.xml'))
    rows, parents, total = detail(pages)
    if not rows:
        raise ValueError('Configured detail scope has no leaf rows')
    (observations / 'parents.json').write_text(
        json.dumps(parents, ensure_ascii=False, indent=2) + '\n')
    (observations / 'total.json').write_text(
        json.dumps(total, ensure_ascii=False, indent=2) + '\n')
    columns = tuple(ParquetColumn(k, 'BIGINT' if k.endswith('物理頁')
                                  else 'DOUBLE' if k.endswith(('上端', '下端')) else 'VARCHAR')
                    for k in rows[0])
    result = write_conversion(destination / (table_id + '.parquet'), rows, columns=columns,
                              context=ConversionContext(source['sha256'], table_id, __file__))
    return {table_id: {'path': Path(result.path), 'metadata': metadata(rows)}}
