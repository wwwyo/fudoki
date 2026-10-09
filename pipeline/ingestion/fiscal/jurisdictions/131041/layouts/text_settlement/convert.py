"""Read Shinjuku's measured landscape settlement tables with Poppler words.

The statutory section and remarks columns are independent decompositions of a
moku. Their vertical placement never establishes a section/project relation.
"""
from pathlib import Path
import json
import re
import subprocess
import xml.etree.ElementTree as ET

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

AMOUNT = re.compile(r"(?:△)?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")
PARENT_AMOUNTS = ['当初予算額', '補正予算額', '継続費及び繰越事業費繰越額',
                  '予備費支出及び流用増減', '計', '支出済額', '翌年度繰越額', '不用額']
DETAIL_EDGES = [(96, 169), (169, 238), (238, 305), (305, 365), (365, 445),
                (575, 715), (715, 790), (790, 865)]
SUMMARY_AMOUNTS = PARENT_AMOUNTS[:6] + ['継続費逓次繰越', '繰越明許費', '事故繰越し', '不用額']
CARRY_AMOUNTS = ['継続費逓次繰越', '繰越明許費', '事故繰越し']
SUMMARY_EDGES = [(99, 192), (192, 278), (278, 362), (362, 446), (446, 544),
                 (544, 732), (732, 813), (813, 895), (895, 976), (976, 1058)]


def observe(pdf, first, last, output):
    subprocess.run(['pdftotext', '-f', str(first), '-l', str(last), '-bbox-layout',
                    str(pdf), str(output)], check=True)
    pages = []
    for number, page in enumerate(ET.parse(output).findall('.//{*}page'), first):
        if abs(float(page.get('width')) - 1190.4) > 1:
            raise ValueError('Unmeasured PDF page dimensions')
        words = [dict(text=w.text or '', **{k: float(v) for k, v in w.attrib.items()})
                 for w in page.findall('.//{*}word')]
        pages.append((number, sorted(words, key=lambda w: (w['yMin'], w['xMin']))))
    if len(pages) != last - first + 1:
        raise ValueError('Poppler returned incomplete page range')
    return pages


def string(words):
    """Keep printed line breaks and spaces between separated words."""
    lines = []
    for word in sorted(words, key=lambda w: (round(w['yMin'], 1), w['xMin'])):
        if not lines or abs(lines[-1][0]['yMin'] - word['yMin']) > .8:
            lines.append([word])
        else:
            lines[-1].append(word)
    return '\n'.join(' '.join(w['text'] for w in sorted(line, key=lambda w: w['xMin']))
                     for line in lines) or None


def same_line(words, y, left, right):
    return [w for w in words if left <= w['xMin'] and w['xMax'] < right
            and abs(w['yMin'] - y) < .8]


def amount(words, y, bounds, sign_bounds=None):
    left, right = bounds
    sign_left, sign_right = bounds if sign_bounds is None else sign_bounds
    values = [w for w in same_line(words, y, left, right) if AMOUNT.fullmatch(w['text'])]
    if len(values) != 1:
        raise ValueError(f'Amount cell {y}/{bounds} has {len(values)} values')
    signs = [w for w in words if sign_left <= w['xMin'] and w['xMax'] < sign_right
             and y - 12 <= w['yMin'] <= y + .8 and w['text'] == '△']
    if len(signs) > 1:
        raise ValueError('Repeated amount sign')
    return ('△' if signs else '') + values[0]['text']


def position(page, words):
    return {'物理頁': page, '上端': min(w['yMin'] for w in words),
            '下端': max(w['yMax'] for w in words)}


def summary(pages, expected_rows=13):
    page, words = pages[0]
    markers = [w for w in words if w['yMin'] > 220 and w['xMax'] < 41
               and re.fullmatch(r'[0-9]+', w['text'])]
    markers.sort(key=lambda w: w['yMin'])
    starts = [w['yMin'] for w in markers]
    totals = [w for w in words if w['xMin'] > 99 and abs(w['xMax'] - 189.06) < 1
              and w['yMin'] > max(starts) + 15 and AMOUNT.fullmatch(w['text'])]
    if len(markers) != expected_rows or len(totals) != 1:
        raise ValueError('Summary row count differs')
    starts.append(totals[0]['yMin'])
    result = []
    for i, y in enumerate(starts):
        previous = starts[i-1] if i else 220
        end = (y + starts[i+1]) / 2 if i + 1 < len(starts) else 740
        name_words = [w for w in words if w['xMin'] >= 44 and w['xMax'] < 99
                      and (previous + y) / 2 < w['yMin'] < end]
        row = {'款_番号': markers[i]['text'] if i < len(markers) else None,
               '款_名称': string(name_words) if i < len(markers) else string([w for w in words if w['xMax'] < 99 and y-1 < w['yMin'] < y+5]),
               **{k: amount(words, y, b) for k, b in zip(SUMMARY_AMOUNTS, SUMMARY_EDGES)},
               '備考': string([w for w in words if w['xMin'] >= 1058 and y-1 <= w['yMin'] < end]),
               **position(page, same_line(words, y, 99, 1058))}
        result.append(row)
    return result


def detail(pages, edges=DETAIL_EDGES, note_bounds=(1090, 1176), sign_edges=None):
    sign_edges = edges if sign_edges is None else sign_edges
    parents, sections, remarks, moku_list = [], [], [], []
    current = {}
    for page, words in pages:
        body = [w for w in words if w['yMin'] > 145]
        total_labels = [w for w in body if w['text'] == '歳' and w['xMin'] < 40]
        if total_labels:
            if len(total_labels) != 1:
                raise ValueError('Ambiguous expenditure total boundary')
            # This printed aggregate repeats the summary, not the last moku name.
            body = [w for w in body if w['yMin'] < total_labels[0]['yMin'] - 5]
        markers = [w for w in body if w['xMax'] < 60 and re.fullmatch(r'[0-9]+', w['text'])]
        section_markers = [w for w in body if 442 < w['xMin'] and w['xMax'] < 461 and re.fullmatch(r'[0-9]+', w['text'])]
        remark_markers = [w for w in body if 867 < w['xMin'] < 884 and re.fullmatch(r'[0-9]{3}', w['text'])]
        transfer_notes = [w for w in body if 867 < w['xMin'] < 884 and w['text'].endswith('流用')]
        events = sorted([(w['yMin'], 'parent', w) for w in markers] +
                        [(w['yMin'], 'section', w) for w in section_markers] +
                        [(w['yMin'], 'remark', w) for w in remark_markers] +
                        [(w['yMin'], 'transfer', w) for w in transfer_notes], key=lambda x: x[0])
        for y, kind, marker in events:
            if kind == 'parent':
                level = '款' if marker['xMax'] < 29 else '項' if marker['xMax'] < 45 else '目'
                next_y = min([w['yMin'] for w in markers if w['yMin'] > y+.8] + [820])
                names = [w for w in body if w['xMin'] > marker['xMax'] and w['xMax'] < 96 and y-.8 <= w['yMin'] < next_y]
                first_child = min([w['yMin'] for w in section_markers + remark_markers if w['yMin'] > y+.8] + [next_y])
                note_words = [w for w in body if w['xMin'] >= 867 and y-.8 <= w['yMin'] < min(first_child, next_y)]
                annotations = [w for w in note_words if w['text'] == '前年度繰越事業費不用額']
                if len(annotations) > 1:
                    raise ValueError('Multiple previous-year carry unused notes at one parent')
                annotation_amount = None
                if annotations:
                    annotation_amount = amount(body, annotations[0]['yMin'], note_bounds)
                record = {'level': level, '番号': marker['text'], '名称': string(names),
                          **{k: amount(body, y, b, sb) for k, b, sb in zip(PARENT_AMOUNTS, edges, sign_edges)},
                          '備考': string(note_words),
                          '備考_注記名称': annotations[0]['text'] if annotations else None,
                          '備考_注記金額': annotation_amount,
                          '備考_流用注記名称': None, '備考_流用注記金額': None,
                          '翌年度繰越額_区分': string([w for w in body if 715 <= w['xMin'] and w['xMax'] < 790
                                                     and y-12 <= w['yMin'] < y and not AMOUNT.fullmatch(w['text'])]),
                          **position(page, [marker])}
                current[level] = record
                if level == '款':
                    current.pop('項', None)
                    current.pop('目', None)
                elif level == '項':
                    current.pop('目', None)
                if level == '目':
                    record['path'] = current.copy()
                    moku_list.append(record)
                parents.append(record)
            else:
                if set(current) != {'款', '項', '目'}:
                    raise ValueError(f'Missing printed moku path at page {page}, y {y}')
                moku = current['目']
                if kind == 'transfer':
                    if moku['備考_流用注記名称'] is not None:
                        raise ValueError('Multiple printed transfer notes at one moku')
                    moku['備考_流用注記名称'] = marker['text']
                    moku['備考_流用注記金額'] = amount(body, y, note_bounds)
                    note = string(same_line(body, y, 867, note_bounds[1]))
                    moku['備考'] = '\n'.join(x for x in [moku['備考'], note] if x)
                elif kind == 'section':
                    next_y = min([w['yMin'] for w in section_markers + markers if w['yMin'] > y+.8] + [820])
                    names = [w for w in body if w['xMin'] > marker['xMax'] and w['xMax'] < 516 and y-.8 <= w['yMin'] < next_y]
                    values = {'区分_番号': marker['text'], '区分_名称': string(names),
                              '金額': amount(body, y, (490, 572)),
                              **{k: amount(body, y, b, sb) for k, b, sb in zip(PARENT_AMOUNTS[-3:], edges[-3:], sign_edges[-3:])},
                              '翌年度繰越額_区分': string([w for w in body if 715 <= w['xMin'] and w['xMax'] < 790
                                                         and y-12 <= w['yMin'] < y and not AMOUNT.fullmatch(w['text'])]),
                              **position(page, [marker])}
                    sections.append((moku, values))
                else:
                    next_y = min([w['yMin'] for w in remark_markers + markers if w['yMin'] > y+.8] + [820])
                    money = [w for w in body if w['xMin'] >= 1090 and y-.8 <= w['yMin'] < next_y and AMOUNT.fullmatch(w['text'])]
                    if len(money) != 1:
                        raise ValueError(f'Remark amount page {page}, {marker["text"]}: {len(money)}')
                    names = [w for w in body if w['xMin'] > marker['xMax'] and w['xMax'] < 1176
                             and y-.8 <= w['yMin'] < next_y and w not in money]
                    values = {'備考_番号': marker['text'], '備考_名称': string(names), '備考_金額': money[0]['text'],
                              **position(page, [marker] + names + money)}
                    remarks.append((moku, values))
    section_keys = ['区分_番号', '区分_名称', '金額', '支出済額', '翌年度繰越額', '不用額', '翌年度繰越額_区分']
    remark_keys = ['備考_番号', '備考_名称', '備考_金額']
    for moku in moku_list:
        for records, keys in [(sections, section_keys), (remarks, remark_keys)]:
            if not any(parent is moku for parent, _ in records):
                records.append((moku, {**dict.fromkeys(keys), **{k: moku[k] for k in ('物理頁', '上端', '下端')}}))
    def flatten(records):
        rows = []
        for moku, values in records:
            row = {}
            for level in ['款', '項', '目']:
                parent = moku['path'][level]
                row.update({level + '_' + k: parent[k] for k in ['番号', '名称', *PARENT_AMOUNTS, '備考', '備考_注記名称', '備考_注記金額', '備考_流用注記名称', '備考_流用注記金額', '翌年度繰越額_区分', '物理頁', '上端', '下端']})
            rows.append({**row, **values})
        return sorted(rows, key=lambda r: (r['物理頁'], r['上端']))
    observed_parents = [{k: v for k, v in parent.items() if k != 'path'} for parent in parents]
    return flatten(sections), flatten(remarks), observed_parents


def expenditure_detail(remark_rows, summary_rows):
    """Retain summary-only printed facts on the same numbered kan parent."""
    summary_by_kan = {row['款_番号']: row for row in summary_rows if row['款_番号'] is not None}
    if len(summary_by_kan) != len(summary_rows) - 1:
        raise ValueError('Repeated summary kan number')
    if set(summary_by_kan) != {row['款_番号'] for row in remark_rows}:
        raise ValueError('Summary and detail kan coverage differs')
    rows = []
    for detail_row in remark_rows:
        parent = summary_by_kan[detail_row['款_番号']]
        if re.sub(r'\s+', '', parent['款_名称']) != re.sub(r'\s+', '', detail_row['款_名称']):
            raise ValueError('Summary and detail printed kan names differ')
        rows.append({**detail_row,
                     **{'款_' + column: parent[column] for column in CARRY_AMOUNTS},
                     **{'款_総括_' + column: parent[column] for column in ('物理頁', '上端', '下端')}})
    return rows


def metadata(rows, suffix):
    amounts = [k for k in rows[0] if any(k == v or k.endswith('_' + v) for v in set(PARENT_AMOUNTS + SUMMARY_AMOUNTS + ['金額', '備考_金額', '備考_注記金額', '備考_流用注記金額']))]
    contexts = []
    if suffix != 'summary':
        for level in ['款', '項', '目']:
            columns = [k for k in rows[0] if k.startswith(level + '_') and not k.endswith(('物理頁', '上端', '下端'))]
            contexts.append({'columns': columns, 'header_path': ['科目', level],
                             'grain_columns': [x + '_番号' for x in ['款', '項', '目'][:['款', '項', '目'].index(level)+1]]})
        columns = ['区分_番号', '区分_名称', '金額', '支出済額', '翌年度繰越額', '不用額', '翌年度繰越額_区分'] if suffix == 'setsu' else ['備考_番号', '備考_名称', '備考_金額']
        contexts.append({'columns': columns, 'header_path': ['節', '区分', '金額'] if suffix == 'setsu' else ['備考'],
                         'grain_columns': ['款_番号', '項_番号', '目_番号', columns[0]],
                         'semantic_role': 'setsu' if suffix == 'setsu' else 'project'})
        if suffix == 'expenditure-detail':
            contexts[0]['columns'] = [k for k in contexts[0]['columns'] if k not in ['款_' + x for x in CARRY_AMOUNTS]]
            contexts.append({'columns': ['款_' + x for x in CARRY_AMOUNTS],
                             'header_path': ['歳出総括', '翌年度繰越額'],
                             'grain_columns': ['款_番号']})
    note = ('一般会計歳出総括。歳出合計は款番号が空欄の印字合計行。' if suffix == 'summary' else
            '款・項・目の印字欄を所属する葉へ反復。節一覧と備考は同じ目の独立した分解であり相互の対応を推定していない。葉の欄が印字されない目は目の粒度で残し、葉の番号・名称・金額をNULLとする。備考_注記名称・備考_注記金額は親欄に印字された前年度繰越事業費不用額、備考_流用注記名称・備考_流用注記金額は目の備考欄の流用注記であり、いずれも支出済額の内訳ではない。金額は円の原表記である。')
    if suffix == 'expenditure-detail':
        note += ('正式rawは備考の最細説明・事業明細であり、法定節一覧・総括表は独立したローカル検算観測に残す。'
                 '款_継続費逓次繰越・款_繰越明許費・款_事故繰越しは、総括の同じ印字款番号・名称への所属を確認して反復した親金額。'
                 '款_総括_物理頁・上端・下端はその総括行の原典位置。これらの繰越額と反復親金額は備考_金額へ加算しない。')
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': amounts}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}}], 'column_contexts': contexts}


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Measured Shinjuku settlement uses one original')
    source = inputs[0]
    if source['target']['jurisdiction'] != '131041' or source['target']['document_kind'] != 'settlement' or source['direction'] != 'expenditure':
        raise ValueError('Measured Shinjuku settlement expenditure required')
    selected = [p for s in source['scope'] if s['account'] == '一般会計' for a, b in s['pages'] for p in range(a, b+1)]
    if sorted(selected) != [3, *range(65, 148)]:
        raise ValueError('Measured scope differs from general account p3 and p65–147')
    destination = Path(destination)
    observations = destination / 'shinjuku-observations'
    observations.mkdir()
    summary_rows = summary(observe(source['path'], 3, 3, observations / 'summary-bbox.html'))
    section_rows, remark_rows, parents = detail(observe(source['path'], 65, 147, observations / 'detail-bbox.html'))
    (observations / 'parents.json').write_text(json.dumps(parents, ensure_ascii=False, indent=2) + '\n')
    detail_rows = expenditure_detail(remark_rows, summary_rows)
    results = {}
    for suffix, rows in [('summary', summary_rows), ('setsu', section_rows), ('expenditure-detail', detail_rows)]:
        table_id = options['table_prefix'] + '-' + suffix
        columns = tuple(ParquetColumn(k, 'BIGINT' if k.endswith('物理頁') else 'DOUBLE' if k.endswith(('上端', '下端')) else 'VARCHAR') for k in rows[0])
        table_destination = destination if suffix == 'expenditure-detail' else observations
        result = write_conversion(table_destination / (table_id + '.parquet'), rows, columns=columns,
                                  context=ConversionContext(source['sha256'], table_id, __file__))
        if suffix == 'expenditure-detail':
            results[table_id] = {'path': Path(result.path), 'metadata': metadata(rows, suffix)}
    return results
