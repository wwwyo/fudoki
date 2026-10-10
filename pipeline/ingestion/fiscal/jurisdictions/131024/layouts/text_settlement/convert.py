"""Restore Chuo's text settlement business hierarchy, independently of sections."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

import duckdb

from ingestion.lib.pdf_table import tokens_from_bbox_layout


AMOUNT = re.compile(r'^(?:[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|－|−|―|\（[0-9.]+\）)$')
FINANCIAL = ['当初予算額', '補正予算額', '繰越事業費繰越額', '予備費支出', '流用増減',
             '予算現額計', '支出済額', '翌年度繰越額', '不用額', '執行率']
LEVELS = ['事業', '内訳1', '内訳2', '内訳3', '内訳4']
INNER_HEADERS = [
    ['種別', '数量', '金額'], ['区分', '件数', '金額'],
    ['種別', '扶助内容', '対象者数等', '金額'], ['種目', '件数', '金額'],
    ['区分', '月額', '児童数（延）', '金額'], ['種別', '接種者数等', '金額'],
    ['助成基準', '施工数', '金額'],
    ['区分', '件数', '給付額'],
]

# Measured original table regions. Values come from glyphs, never these bounds.
# Duplicate leaf headings retain their printed upper headings in the column key.
AUXILIARY_TABLES = [
    (96, 0, 342, 360, 462, '議員の報酬等', ['区分', '人数'], [62, 150, 285], (), True),
    (96, 0, 468, 486, 517, '定例会・臨時会運営', ['区分', '回数'], [62, 150, 330], (), True),
    (96, 0, 541, 576, 681, '開会回数', ['委員会区分', '委員会名', '回数'], [58.64, 130.61, 264.70, 309.69], ('回',), False),
    (105, 0, 519, 537, 585, '選挙管理委員会運営事業', ['区分', '人数'], [65, 150, 300], (), True),
    (106, 0, 599, 617, 665, '監査事務', ['区分', '人数'], [65, 150, 300], (), True),
    (107, 0, 323, 355, 369, '戸籍数及び戸籍人口', ['戸籍数', '戸籍人口'], [45.21, 175.56, 305.90], ('戸籍', '人'), False),
    (107, 0, 397, 429, 459, '住民基本台帳による世帯と人口', ['区分', '京橋', '日本橋', '月島', '計'], [45.21, 121.72, 198.23, 274.73, 351.24, 427.75], ('世帯', '人'), False),
    (110, 0, 351, 366, 525, '区民館の管理運営', ['施設名', '利用件数'], [45.21, 135.89, 189.72], ('件',), False),
    (110, 0, 351, 366, 525, '区民館の管理運営', ['施設名', '利用件数'], [189.72, 280.40, 334.24], ('件',), False),
    (110, 1, 709, 724, 740, '中央会館「銀座ブロッサム」の管理運営', ['区分', 'ホール', '結婚式場', '集会室'], [682.31, 765.90, 832.49, 899.08, 965.66], ('件',), False),
    (123, 1, 531, 546, 616, '巡回型ホームヘルプサービス', ['区分', '派遣世帯（延）', '派遣回数（延）'], [688.68, 787.86, 855.86, 923.87], ('世帯', '回'), False),
    (128, 1, 111, 161, 465, '保育園の園児数及び職員数', ['保育所名', '園児数_3歳未満', '園児数_3歳以上', '園児数_計', '職員数_保育士', '職員数_技術・技能', '職員数_計'], [695.77, 777.94, 834.61, 891.29, 947.96, 1004.63, 1061.30, 1117.97], ('人',), False),
    (131, 0, 145, 178, 348, '利用状況', ['児童館名', '乳幼児', '小学生', '中学生', '高校生', '保護者', '計'], [51.37, 164.71, 218.55, 272.38, 326.22, 380.06, 433.90, 487.73], ('人',), False),
    (134, 0, 545, 565, 700, '一般健康診査', ['健康診査等内訳', '対象者', '人数'], [42.63, 161.64, 323.15, 377.13], ('人',), False),
    (136, 1, 217, 277, 353, '内科・小児科診療', ['区分', '昼間診療_初療受診者数', '昼間診療_入院者数', '昼間診療_実施回数', '準夜間診療_初療受診者数', '準夜間診療_実施回数', '土曜準夜間診療_初療受診者数', '土曜準夜間診療_実施回数'], [686.48, 794.43, 845.41, 896.39, 947.38, 998.36, 1049.34, 1100.32, 1151.30], ('人', '回'), False),
    (136, 1, 389, 407, 462, '歯科診療（休日）', ['区分', '受診者数', '実施回数'], [686.48, 802.43, 856.41, 910.39], ('人', '回'), False),
    (136, 1, 497, 534, 589, '調剤（休日，土曜準夜間）', ['区分', '昼間調剤_初療調剤数', '昼間調剤_実施回数', '準夜間調剤_初療調剤数', '準夜間調剤_実施回数', '土曜準夜間調剤_初療調剤数', '土曜準夜間調剤_実施回数'], [686.48, 812.43, 864.41, 916.39, 968.37, 1020.35, 1072.33, 1124.31], ('人', '回'), False),
    (137, 0, 115, 143, 157, '認定状況', ['特級', '1級', '2級', '3級', '級外', '計'], [41.92, 79.91, 117.89, 155.88, 193.86, 231.85, 269.84], ('人',), False),
    (147, 0, 188, 203, 407, '道路維持補修', ['施工', '工種', '実績'], [53.96, 96.46, 331.65, 410.62], (), False),
    (148, 0, 461, 476, 579, '掘削道路復旧工事', ['施工', '工種', '実績'], [53.25, 95.76, 330.95, 409.91], (), False),
    (148, 0, 624, 639, 691, '特定道路舗装工事', ['工種', '助成基準', '件数', '規模'], [53.25, 197.39, 268.23, 339.07, 409.91], ('％', '件', '㎡'), False),
    (153, 0, 384, 402, 451, '教育委員会運営', ['区分', '人数'], [65, 150, 325], (), True),
    (154, 0, 169, 203, 216, '区立小学校の学級数・児童数及び教員数', ['学校数', '学級数', '児童数', '教員数'], [63.17, 145.34, 227.52, 309.69, 391.87], ('校', '学級', '人'), False),
    (155, 1, 89, 121, 134, '宇佐美学園の学級数・児童数及び教員数', ['学級数', '児童数', '教員数'], [698.98, 783.99, 869.00, 954.00], ('学級', '人'), False),
    (155, 1, 201, 233, 246, '区立中学校の学級数・生徒数及び教員数', ['学校数', '学級数', '生徒数', '教員数'], [698.98, 783.99, 869.00, 954.00, 1039.01], ('校', '学級', '人'), False),
    (156, 0, 361, 393, 406, '区立幼稚園の学級数・園児数及び教員数', ['園数', '学級数', '園児数', '教員数'], [63.88, 146.05, 228.23, 310.40, 392.57], ('園', '学級', '人'), False),
    (159, 0, 173, 203, 288, '区立図書館の現況', ['区分', '個人貸出者数', '購入図書数', '蔵書数'], [53.32, 135.29, 217.26, 299.23, 381.20], ('人', '冊'), False),
    (180, 0, 218.3, 234.5, 343.8, '療養の給付', ['区分', '件数'], [58.1, 165.9, 211.4], ('件',), False),
    (180, 0, 453.4, 469.5, 534.8, '療養費の支給', ['区分', '件数'], [58.1, 165.9, 211.4], ('件',), False),
    (184, 0, 204.5, 221.8, 308.0, '特定健康診査等', ['内訳', '対象者', '人数'], [57.7, 202.4, 362.3, 407.8], ('人',), False),
]

# Independently confirmed original prose lines whose text lacks the keyword or
# count pattern, including unnumbered headings and name wrap lines. Positions
# are measured from the original; glyphs and fiscal subjects are read from the
# words there, never from these bounds.
PROSE_LINES = [
    (100, 0, 472.58), (109, 0, 528.33), (111, 0, 200.39), (128, 0, 376.69),
    (129, 1, 353.94), (134, 0, 287.77), (136, 0, 753.53), (140, 0, 644.09),
    (141, 0, 283.64), (141, 0, 332.14), (141, 0, 429.14), (141, 0, 531.64),
    (143, 0, 172.10), (147, 0, 536.67), (147, 0, 583.17), (147, 0, 683.68),
    (147, 0, 730.18), (148, 0, 113.96), (148, 0, 160.46), (148, 0, 224.96),
    (148, 0, 271.47), (148, 0, 335.97), (148, 0, 400.47), (148, 1, 270.95),
    (148, 1, 306.95), (148, 1, 342.95), (155, 1, 486.62), (158, 0, 343.51),
    (227, 0, 335.20),
]

# Independently confirmed original office/department headings printed directly
# under a moku heading. Each starts a scope that runs in original reading order
# until the next office or moku heading; inside a moku the same business
# number/name may repeat, so the scalar is repeated by origin position, not by
# business. Positions are measured; glyphs are read from the words there.
OFFICE_HEADINGS = [
    (134, 0, 287.77), (138, 0, 127.39), (139, 0, 288.86), (139, 1, 182.37),
]


def text(words):
    return ' '.join(w['text'] for w in sorted(words, key=lambda w: w['x']) if w['text'])


def compact(value):
    return re.sub(r'\s+', '', value)


def rows(words, *, tolerance=4.1):
    result = []
    for word in sorted(words, key=lambda w: (w['y'], w['x'])):
        if not result or word['y'] - result[-1][0]['y'] > tolerance:
            result.append([])
        result[-1].append(word)
    return [sorted(row, key=lambda w: w['x']) for row in result]


def coordinates(words, page):
    return {'原典物理頁': page, '原典xMin': min(w['x'] for w in words),
            '原典yMin': min(w['y'] for w in words), '原典xMax': max(w['xe'] for w in words),
            '原典yMax': max(w['ye'] for w in words)}


def parent_event(row, page, page_words=None):
    left = [w for w in row if w['x'] < 142 and (w['x'] < 60 or not AMOUNT.fullmatch(w['text']))]
    match = re.match(r'^（([款項目])）\s*([0-9]+)\s*(.*)$', text(left))
    if not match:
        return None
    values = []
    sign = ''
    for w in row:
        if w['x'] < 130 or w['x'] > 1025:
            continue
        # Poppler sometimes joins the last 0 in one cell to the next cell's △.
        for part in re.findall(r'△|[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|（[0-9.]+）|\([0-9.]+\)', w['text']):
            if part == '△':
                sign = part
            else:
                values.append((sign + part) if sign else part)
                sign = ''
    if len(values) != len(FINANCIAL):
        raise ValueError(f'Parent monetary columns are incomplete: page={page}, {text(row)}, values={values}')
    name = match[3]
    name_words = []
    if page_words:
        center = (min(w['y'] for w in left) + max(w['ye'] for w in left)) / 2
        name_words = [w for w in page_words if 55 < w['x'] < 142
                      and abs((w['y'] + w['ye']) / 2 - center) < 11
                      and (not AMOUNT.fullmatch(w['text']) or w['xe'] < 130)
                      and w['text'] not in ('円', '％')]
        if name_words:
            name = '\n'.join(text(r) for r in rows(name_words))
    return {'level': match[1], '番号': match[2], '名称': name,
            **dict(zip(FINANCIAL, values, strict=True)), **coordinates([*row, *name_words], page)}


def annual_header(row):
    headers = []
    active = []
    for w in row:
        if w['text'].startswith(('令和', '平成')):
            active = [w]
        elif active:
            active.append(w)
        if active and '年度' in w['text']:
            headers.append({'name': text(active), 'x': (active[0]['x'] + active[-1]['xe']) / 2})
            active = []
        elif w['text'] == '計' and not active:
            headers.append({'name': '計', 'x': (w['x'] + w['xe']) / 2})
    return headers


def annual_row(row, headers):
    numbers = [w for w in row if AMOUNT.fullmatch(w['text'].removesuffix('円'))]
    if not numbers or len(numbers) != len(headers):
        return None
    first = min(w['x'] for w in numbers)
    name = text([w for w in row if w['xe'] < first - 1])
    if not name:
        return None
    cells = {}
    for idx, (header, number) in enumerate(zip(headers, numbers, strict=True)):
        end = numbers[idx + 1]['x'] if idx + 1 < len(numbers) else float('inf')
        suffix = [w for w in row if w['text'] == '円' and number['xe'] <= w['x'] < end]
        cells[header['name']] = number['text'] + (' 円' if suffix and not number['text'].endswith('円') else '')
    return name, cells


def money(row):
    # The rightmost currency is the actual business amount. Earlier currencies
    # can be per-person rates printed inside the business name.
    for idx, w in reversed(list(enumerate(row))):
        if w['text'].endswith('円') and AMOUNT.fullmatch(w['text'][:-1]):
            return {'value': w['text'], 'name_words': row[:idx], 'circle': w, 'number': w}
    circles = [(idx, w) for idx, w in enumerate(row) if w['text'] == '円']
    for idx, circle in reversed(circles):
        if idx:
            word = row[idx - 1]
            matched = re.search(r'[0-9]+(?:,[0-9]{3})*$', word['text'])
            if not matched:
                continue
            number = {**word, 'text': matched[0]}
            prefix = word['text'][:matched.start()]
            name_words = [*row[:idx - 1], *([{**word, 'text': prefix}] if prefix else [])]
            return {'value': number['text'] + ' 円', 'name_words': name_words,
                    'circle': circle, 'number': number}
    return None


def grid_lines(source, destination, page):
    svg = destination / f'page-{page}-grid.svg'
    subprocess.run(['pdftocairo', '-f', str(page), '-l', str(page), '-svg', str(source), str(svg)], check=True)
    horizontal, vertical = [], []
    root = ET.parse(svg).getroot()
    for path in root.findall('./{*}path'):
        if path.get('fill') != 'none':
            continue
        points = re.findall(r'[ML]\s+([-0-9.eE]+)\s+([-0-9.eE]+)', path.get('d', ''))
        transform = re.search(r'matrix\(([^)]+)\)', path.get('transform', ''))
        if len(points) != 2 or not transform:
            continue
        a, b, c, d, e, f = [float(v) for v in transform[1].split(',')]
        transformed = [(a * float(x) + c * float(y) + e, b * float(x) + d * float(y) + f) for x, y in points]
        (x1, y1), (x2, y2) = transformed
        if abs(y1 - y2) < .2:
            horizontal.append((min(x1, x2), max(x1, x2), (y1 + y2) / 2))
        if abs(x1 - x2) < .2:
            vertical.append(((x1 + x2) / 2, min(y1, y2), max(y1, y2)))
    return horizontal, vertical


def inner_header(row):
    joined = compact(text(row))
    profile = next((p for p in INNER_HEADERS if joined == ''.join(p)), None)
    if not profile:
        return None
    characters = []
    for w in row:
        for char in compact(w['text']):
            characters.append((char, w))
    headers = []
    at = 0
    for label in profile:
        selected = [pair[1] for pair in characters[at:at + len(label)]]
        headers.append({'name': label, 'x': (selected[0]['x'] + selected[-1]['xe']) / 2})
        at += len(label)
    return headers


def table_cells(words, headers, bounds, lines, page, top, bottom, start, end, *, unruled_rows=False):
    cells, locations, kept = {}, {}, []
    for item, (lower, upper) in zip(headers, bounds, strict=True):
        selected = []
        for word in words:
            x, y = (word['x'] + word['xe']) / 2, (word['y'] + word['ye']) / 2
            if not (lower < x < upper and start < y < end):
                continue
            rules = sorted({ry for x1, x2, ry in lines if x1 - .2 <= x <= x2 + .2})
            before = [ry for ry in rules if ry < y]
            after = [ry for ry in rules if ry > y]
            cell_top = max(before) if before else (top if unruled_rows else start)
            cell_bottom = min(after) if after else (bottom if unruled_rows else end)
            if cell_top < bottom - .3 and cell_bottom > top + .3 and (not unruled_rows or rules or top < y < bottom):
                selected.append(word)
        key = item.get('column', '内表_' + item['name'])
        cells[key] = '\n'.join(text(row) for row in rows(selected))
        locations[key] = coordinates(selected, page) if selected else None
        kept.extend(selected)
    return cells, locations, kept


def grid_table(words, header, headers, lines, page, *, column_bounds=None, body_rows=None,
               shared_units=(), unit_columns=()):
    if column_bounds is not None:
        words = [word for word in words if not (word['text'] in shared_units
                 and any(column_bounds[index][0] < (word['x'] + word['xe']) / 2 < column_bounds[index][1]
                         for index in unit_columns))]
        horizontal, vertical = lines
        start, end = body_rows[0][0], body_rows[-1][1]
        result = []
        for top, bottom in body_rows:
            cells, locations, kept = table_cells(words, headers, column_bounds, horizontal, page,
                                                  top, bottom, start, end, unruled_rows=True)
            if horizontal:
                groups = [[0]]
                center = (top + bottom) / 2
                for index in range(1, len(headers)):
                    boundary = column_bounds[index][0]
                    if any(abs(x - boundary) < .2 and first <= center <= last for x, first, last in vertical):
                        groups.append([index])
                    else:
                        groups[-1].append(index)
                for group in groups:
                    if len(group) == 1:
                        continue
                    final = group[-1]
                    merged, merged_locations, _ = table_cells(words, [headers[final]],
                        [(column_bounds[group[0]][0], column_bounds[final][1])], horizontal, page,
                        top, bottom, start, end, unruled_rows=True)
                    for index in group[:-1]:
                        key = headers[index]['column']
                        cells[key], locations[key] = '', None
                    cells.update(merged)
                    locations.update(merged_locations)
            if kept:
                result.append({'cells': cells, 'cell_locations': locations,
                               'location': coordinates(kept, page),
                               'row_bounds': {'原典物理頁': page, '原典xMin': column_bounds[0][0],
                                              '原典xMax': column_bounds[-1][1],
                                              '原典yMin': top, '原典yMax': bottom}})
        return result, end
    # This profile prints shared units above the first data glyphs inside the
    # first ruled body cell. They describe columns, not that first leaf alone.
    if headers[-1]['name'] == '給付額':
        words = [w for w in words if w['text'] not in ('件', '円')]
    horizontal, vertical = lines
    header_y = (min(w['y'] for w in header) + max(w['ye'] for w in header)) / 2
    xs = sorted(set(round(x, 2) for x, top, bottom in vertical if top - .2 <= header_y <= bottom + .2))
    if len(xs) < len(headers) + 1:
        bounds = [-float('inf'), *[(a['x'] + b['x']) / 2 for a, b in zip(headers, headers[1:])],
                  headers[-1]['x'] + 75]
        result = []
        for row in rows([w for w in words if w['y'] > max(w['ye'] for w in header)]):
            cells = {('内表_' + h['name']): text([w for w in row if bounds[idx] <= (w['x'] + w['xe']) / 2 < bounds[idx + 1]])
                     for idx, h in enumerate(headers)}
            nums = [w for w in row if bounds[-2] <= (w['x'] + w['xe']) / 2 < bounds[-1] and AMOUNT.fullmatch(w['text'])]
            if nums:
                kept = [w for w in row if w['x'] < bounds[-1]]
                result.append({'cells': cells, 'location': coordinates(kept, page),
                               'money_location': coordinates(nums[-1:], page)})
                if compact(cells['内表_' + headers[0]['name']]) == '計':
                    return result, max(w['ye'] for w in row)
        raise ValueError(f'Unruled monetary table has no total on page {page}')
    column_bounds = []
    for item in headers:
        lower = max(x for x in xs if x < item['x'])
        upper = min(x for x in xs if x > item['x'])
        column_bounds.append((lower, upper))
    left, right = column_bounds[0][0], column_bounds[-1][1]
    # Follow the outside rule through adjacent stroke segments to the table end.
    outer = sorted((top, bottom) for x, top, bottom in vertical if abs(x - right) < .2)
    end = header_y
    for top, bottom in outer:
        if top <= end + .3 and bottom > end:
            end = bottom
    header_bottom = min(y for x1, x2, y in horizontal if x1 < headers[-1]['x'] < x2 and y > header_y)
    money_left, money_right = column_bounds[-1]
    monetary = [w for w in words if money_left < (w['x'] + w['xe']) / 2 < money_right
                and header_bottom < (w['y'] + w['ye']) / 2 < end
                and AMOUNT.fullmatch(w['text'])]
    result = []
    for number in sorted(monetary, key=lambda w: w['y']):
        center = (number['x'] + number['xe']) / 2
        ycenter = (number['y'] + number['ye']) / 2
        ys = sorted(set(y for x1, x2, y in horizontal if x1 - .2 <= center <= x2 + .2))
        top = max(y for y in ys if y < ycenter)
        bottom = min(y for y in ys if y > ycenter)
        # A printed monetary cell can span finer quantity/phase rows. Preserve
        # those rows, repeating the original monetary glyph and its bbox.
        quantity_center = sum(column_bounds[-2]) / 2
        cuts = sorted({top, bottom, *(y for x1, x2, y in horizontal
                       if x1 - .2 <= quantity_center <= x2 + .2 and top + .3 < y < bottom - .3)})
        for row_top, row_bottom in zip(cuts, cuts[1:]):
            cells, cell_locations, kept = table_cells(words, headers, column_bounds, horizontal, page,
                                                       row_top, row_bottom, header_bottom, end)
            result.append({'cells': cells, 'location': coordinates(kept, page),
                           'money_location': coordinates([number], page), 'cell_locations': cell_locations,
                           'row_bounds': {'原典物理頁': page, '原典xMin': left, '原典xMax': right,
                                          '原典yMin': row_top, '原典yMax': row_bottom}})
    return result, end


def write_parquet(path, records):
    if not records:
        raise ValueError(f'No rows for {path}')
    columns = list(dict.fromkeys(key for record in records for key in record))
    types = {}
    for col in columns:
        if col.endswith('物理頁'):
            types[col] = 'INTEGER'
        elif re.search(r'(?:xMin|xMax|yMin|yMax)$', col):
            types[col] = 'DOUBLE'
        else:
            types[col] = 'VARCHAR'
    quote = lambda value: '"' + value.replace('"', '""') + '"'
    with duckdb.connect() as con:
        con.execute('create table raw (' + ', '.join(quote(c) + ' ' + types[c] for c in columns) + ')')
        con.executemany('insert into raw values (' + ','.join('?' for _ in columns) + ')',
                        [[record.get(c) for c in columns] for record in records])
        con.execute('copy raw to ? (format parquet, compression zstd)', [str(path)])
        readback = con.execute('select * from read_parquet(?, hive_partitioning=false)', [str(path)]).fetchall()
    expected = [tuple(record.get(c) for c in columns) for record in records]
    if readback != expected:
        raise ValueError('Parquet readback differs from the assembled original cells')
    return columns


def context(parents):
    result = {}
    for level in ['款', '項', '目']:
        parent = parents.get(level)
        if parent:
            for key, value in parent.items():
                if key != 'level':
                    result[level + '_' + key] = value
    return result


def node_context(node):
    chain = []
    at = node
    while at:
        chain.append(at)
        at = at['parent']
    result = dict(node['context'])
    for at in reversed(chain):
        prefix = LEVELS[at['rank']]
        result[prefix + '_番号'] = at['number']
        result[prefix + '_名称'] = at['name']
        result[prefix + '_金額'] = at['amount']
        for key, value in at['location'].items():
            result[prefix + '_' + key] = value
        result[prefix + '_所属'] = at['department']
    return result


def unexplained_sections(pages, parent, following, last):
    records = []
    start_page = parent['原典物理頁']
    end_page = following['原典物理頁'] if following else last
    for page in range(start_page, end_page + 1):
        lower = parent['原典yMax'] if page == start_page else 60
        upper = following['原典yMin'] if following and page == end_page else 790
        words = [w for w in pages[page] if lower < w['y'] < upper]
        numbers = [w for w in words if 650 < w['x'] < 680 and re.fullmatch(r'[0-9]+', w['text'])]
        for number in numbers:
            y = number['y']
            name_words = [w for w in words if 680 < w['x'] < 735 and abs(w['y'] - y) < 11]
            values = sorted([w for w in words if 735 < w['x'] < 990 and abs(w['y'] - y) < 4.1
                             and AMOUNT.fullmatch(w['text'])], key=lambda w: w['x'])
            if len(values) != 4 or not name_words:
                raise ValueError(f'Incomplete unexplained section: page={page}, number={number["text"]}')
            department = [w for w in words if 390 < w['x'] < 650 and abs(w['y'] - y) < 4.1]
            location = coordinates([number, *name_words, *values], page)
            records.append({**parent['parents'], '節_番号': number['text'],
                            '節_名称': '\n'.join(text(r) for r in rows(name_words)),
                            **dict(zip(['節_金額', '節_支出済額', '節_翌年度繰越額', '節_不用額'],
                                       [w['text'] for w in values], strict=True)),
                            '節_所属': text(department) or None,
                            **{'節_' + key: value for key, value in location.items()}, **location})
    return records


def reading_position(location):
    return location['原典物理頁'], int(location['原典xMin'] >= 650), location['原典yMin']


def nonfinancial_facts(pages, nodes, source, destination, grids, handled, all_parents):
    controls, observations, regions, office_headings = [], [], [], []
    ordered = sorted(nodes, key=lambda node: reading_position(node['location']))
    mokus = [p for p in all_parents if p['level'] == '目']

    def owner_at(page, pane, y):
        key = (page, pane, y)
        available = [node for node in ordered if reading_position(node['location']) <= key]
        if not available:
            raise ValueError(f'Nonfinancial original fact has no source heading: page={page}, y={y}')
        return available[-1]

    def governing_moku(page, pane, y):
        governing = [p for p in mokus
                     if (p['原典物理頁'], 0, p['原典yMin']) < (page, pane, y)]
        if not governing:
            raise ValueError(f'Measured prose has no fiscal subject: page={page}, y={y}')
        moku = max(governing, key=lambda p: (p['原典物理頁'], p['原典yMin']))
        return tuple(moku['parents'].get(level + '_番号') for level in ('款', '項', '目'))

    def measured_owner(page, pane, y):
        # The fiscal subject is the original moku in force at the measured
        # position, never the nearest preceding amount under another moku.
        wanted = governing_moku(page, pane, y)
        candidates = [node for node in ordered
                      if tuple(node['context'].get(level + '_番号')
                               for level in ('款', '項', '目')) == wanted]
        before = [node for node in candidates if reading_position(node['location']) <= (page, pane, y)]
        if before:
            return before[-1], None
        if candidates:
            # The line precedes every business of its moku, like an office or
            # department heading: it belongs to the moku's own context, not
            # to the coming first business.
            return None, wanted
        raise ValueError(f'Measured prose has no business under its fiscal subject: page={page}, y={y}')

    for page, pane, header_y, data_y, end, title, fields, xs, units, unruled in AUXILIARY_TABLES:
        if page not in pages:
            continue
        words = [word for word in pages[page] if int(word['x'] >= 650) == pane]
        body = [word for word in words if data_y - 7 < word['y'] < end
                and xs[0] < (word['x'] + word['xe']) / 2 < xs[-1]]
        if page not in grids:
            grids[page] = grid_lines(source, destination, page)
        horizontal = [] if unruled else grids[page][0]
        anchors = [word for word in body if xs[-2] < (word['x'] + word['xe']) / 2 < xs[-1]
                   and re.search(r'[0-9]|－', word['text']) and word['y'] >= data_y - 1]
        body_rows = []
        for line in rows(anchors):
            center = (min(word['y'] for word in line) + max(word['ye'] for word in line)) / 2
            x = (line[0]['x'] + line[0]['xe']) / 2
            rules = sorted({y for x1, x2, y in horizontal if x1 - .2 <= x <= x2 + .2})
            before, after = [y for y in rules if y < center], [y for y in rules if y > center]
            top = max(before) if before else min(word['y'] for word in line) - .5
            bottom = min(after) if after else max(word['ye'] for word in line) + .5
            interval = (max(top, data_y - 7), min(bottom, end))
            if interval not in body_rows:
                body_rows.append(interval)
        if not body_rows:
            raise ValueError(f'No original quantity rows in measured table: page={page}, title={title}')
        headers = [{'name': field, 'column': '数量表_' + title + '_' + field} for field in fields]
        items, _ = grid_table(body, [], headers, (horizontal, grids[page][1]), page,
                              column_bounds=list(zip(xs, xs[1:])), body_rows=body_rows, shared_units=units,
                              unit_columns=[index for index, field in enumerate(fields)
                                            if field not in ('区分', '施設名', '保育所名', '児童館名',
                                                             '健康診査等内訳', '対象者', '委員会区分',
                                                             '委員会名', '施工', '工種')])
        owner = owner_at(page, pane, data_y)
        heading_words = [word for word in words if header_y - 1 <= word['y'] < data_y - 7
                         and xs[0] < (word['x'] + word['xe']) / 2 < xs[-1]]
        heading = '\n'.join(text(row) for row in rows(heading_words)) or None
        records = []
        date = None
        for item in items:
            if any(compact(value) == '計' for value in item['cells'].values()):
                controls.append({**node_context(owner), **item['cells'], **item['location']})
                match = re.search(r'（[^）]*）', '\n'.join(item['cells'].values()))
                if match:
                    date = match[0]
                continue
            record = {**node_context(owner), **item['cells'], '数量表_見出し': heading,
                      '数量表_現在日': None, **item['row_bounds']}
            for column, location in item['cell_locations'].items():
                if location:
                    record.update({column + '_' + key: value for key, value in location.items()})
            records.append(record)
            observations.append(item)
        if date is None and heading:
            match = re.search(r'（[^）]*[0-9][^）]*）', heading)
            date = match[0] if match else None
        for record in records:
            record['数量表_現在日'] = date
        owner['annual_rows'].extend(records)
        owner['has_children'] = True
        regions.append((page, pane, header_y - 1, end, xs[0], xs[-1]))

    # These are original prose rows within the current printed monetary heading,
    # not allocation or a join to the independent legal section column.
    for page, words in pages.items():
        statement = any('当初予算額' in word['text'] for word in words)
        for pane in range(1 if statement else 2):
            for line in rows([word for word in words if int(word['x'] >= 650) == pane
                              and 60 < word['y'] < 790]):
                value = text(line)
                joined = compact(value)
                measured = any(p == page and pn == pane
                               and abs(min(w['y'] for w in line) - y) < 2.5
                               for p, pn, y in PROSE_LINES)
                office = any(p == page and pn == pane
                             and abs(min(w['y'] for w in line) - y) < 2.5
                             for p, pn, y in OFFICE_HEADINGS)
                if not (measured or office):
                    if money(line) or joined.startswith(('計', '（款）', '（項）', '（目）', '令和', '平成')):
                        continue
                    if not (re.match(r'^(所在地|場所|規模|完成|完了|工事延長|区域|区間|［備考］|※|（)', joined)
                            or re.search(r'[0-9][^円]*?(人|件|回|園|事業所|事業主|クラブ|世帯|基|㎡|ｍ|km|番|号|箇所|公園|児童遊園)', joined)):
                        continue
                location = coordinates(line, page)
                if office:
                    # An office/department heading is a native moku-level
                    # scalar whose scope runs in reading order to the next
                    # office or moku heading: assembly repeats it on the finest
                    # rows inside that scope by origin position.
                    office_headings.append({'moku_path': governing_moku(page, pane, location['原典yMin']),
                                            'pos': (page, pane, location['原典yMin']),
                                            'text': value, 'location': location})
                    continue
                center = (location['原典yMin'] + location['原典yMax']) / 2
                if any(pg == page and half == pane and top <= center <= bottom
                       for pg, half, top, bottom, *_ in [*regions, *handled]):
                    continue
                if measured:
                    owner, moku_path = measured_owner(page, pane, location['原典yMin'])
                    if owner is None:
                        # A measured line preceding every business of its moku
                        # is handled by the same office-heading mechanism.
                        office_headings.append({'moku_path': moku_path,
                                                'pos': (page, pane, location['原典yMin']),
                                                'text': value, 'location': location})
                        continue
                else:
                    owner = owner_at(page, pane, location['原典yMin'])
                if '給与費' in compact(owner['name']) and re.fullmatch(r'.+\s*[0-9]+\s*人\s*(（[^）]*）)?', value):
                    continue
                # A prose line is annotation, not a decomposition of the
                # printed amount: the monetary parent row stays a leaf and
                # is preserved once while the line repeats its context.
                owner['annual_rows'].append({**node_context(owner), '補足_本文': value, **location})
    return controls, observations, office_headings


def assemble(pages, first, last, *, source, destination, reserve_kan='11', personnel_breakdown=False,
             unexplained_section_detail=False, nonfinancial_breakdown=False, remark_column=False,
             remark_min_x=1024):
    parents = {}
    nodes = []
    current = {}
    all_parents = []
    totals = []
    annual_controls = []
    annual_names = set()
    inner_controls = []
    inner_cells = []
    personnel_controls = []
    lending = []
    grids = {}
    reserve = []
    reserve_path = {}
    reserve_total = None
    annual = None
    awaiting_header = False
    pending = []
    pending_department = []
    reserve_pending = []
    handled = []

    for page in range(first, last + 1):
        words = pages[page]
        # A financial statement spread has section/budget columns on the right;
        # a continuation spread instead uses both halves for business details.
        has_statement = any('当初予算額' in compact(text(row)) for row in rows(words))
        halves = [([w for w in words if w['x'] < 650], 0)]
        if not has_statement:
            halves.append(([w for w in words if w['x'] >= 650], 646))
        for half_words, offset in halves:
            skip_until = 0
            for row in rows(half_words):
                if min(w['y'] for w in row) < 60 or min(w['y'] for w in row) > 790:
                    continue
                if offset == 0:
                    full_row = [w for w in words if abs(w['y'] - row[0]['y']) <= 4.1]
                    parent = parent_event(sorted(full_row, key=lambda w: w['x']), page, words)
                    if parent:
                        level = parent['level']
                        if level in ('款', '項'):
                            for child in (['項', '目'] if level == '款' else ['目']):
                                parents.pop(child, None)
                        parents[level] = parent
                        all_parents.append(parent | {'parents': context(parents)})
                        if level == '目':
                            current = {}
                            annual = None
                            awaiting_header = False
                        pending = []
                        pending_department = []
                        continue
                if '目' not in parents:
                    if parents.get('款', {}).get('番号') == reserve_kan:
                        handled.append((page, int(offset != 0),
                                        min(w['y'] for w in row), max(w['ye'] for w in row)))
                    continue
                if min(w['y'] for w in row) < skip_until:
                    continue
                value = text(row)
                stripped = compact(value)
                if parents['款']['番号'] == reserve_kan:
                    # Reserve appropriations are a distinct explanation, not
                    # executed business detail under the zero-expense reserve.
                    # The main prose pass must not borrow these lines either;
                    # they are already retained in the reserve transfer table.
                    handled.append((page, int(offset != 0),
                                    min(w['y'] for w in row), max(w['ye'] for w in row)))
                    payment = money(row)
                    if not payment:
                        reserve_pending.append(value)
                        continue
                    title = text(payment['name_words'])
                    if '充用した科目' in compact(title):
                        reserve_total = payment['value']
                        reserve_pending = []
                        continue
                    if reserve_pending and re.match(r'^第\s*[0-9０-９]+\s*[款項目]', reserve_pending[0]):
                        title = '\n'.join([*reserve_pending, title])
                    match = re.match(r'^第\s*([0-9０-９]+)\s*([款項目])\s*(.*)$', title, re.DOTALL)
                    if match:
                        lev = match[2]
                        if lev in ('款', '項'):
                            for child in (['項', '目'] if lev == '款' else ['目']):
                                for k in list(reserve_path):
                                    if k.startswith(child + '_'):
                                        reserve_path.pop(k)
                        reserve_path.update({lev + '_番号': match[1], lev + '_名称': match[3],
                                             lev + '_金額': payment['value']})
                    elif reserve_path and (title or reserve_pending):
                        reserve.append({**context(parents), '充用した科目（事業）及び金額': reserve_total,
                                        **{'充用先_' + k: v for k, v in reserve_path.items()},
                                        '充用先_事業': '\n'.join(reserve_pending + ([title] if title else [])),
                                        '充用先_金額': payment['value'], **coordinates(row, page)})
                    reserve_pending = []
                    continue
                headers = inner_header(row)
                if headers:
                    if page not in grids:
                        grids[page] = grid_lines(source, destination, page)
                    items, skip_until = grid_table(half_words, row, headers, grids[page], page)
                    if not current:
                        raise ValueError(f'Monetary inner table without owner on page {page}')
                    is_lending = [h['name'] for h in headers] == ['区分', '件数', '金額']
                    handled_top = min(word['y'] for word in row)
                    title_rows = []
                    if is_lending:
                        # The ［備考］ caption is retained in the lending status
                        # table itself, not in the preceding business detail.
                        captions = [min(w['y'] for w in r) for r in pending
                                    if '［備考］' in compact(text(r))]
                        if captions:
                            handled_top = min(handled_top, *captions)
                    else:
                        # A measured original caption line directly above a
                        # monetary inner table is that table's title or
                        # eligibility note: hold it as scalar on the table's
                        # own rows, never as normal-benefit prose.
                        title_rows = [r for r in pending
                                      if any(p == page and pn == int(offset != 0)
                                             and abs(min(w['y'] for w in r) - y) < 2.5
                                             for p, pn, y in PROSE_LINES)]
                        if title_rows:
                            handled_top = min(handled_top,
                                              min(min(w['y'] for w in r) for r in title_rows))
                    handled.append((page, int(offset != 0), handled_top, skip_until))
                    title = '\n'.join(text(r) for r in title_rows) or None
                    title_location = (coordinates([w for r in title_rows for w in r], page)
                                      if title_rows else None)
                    amount_column = '内表_' + headers[-1]['name']
                    if is_lending:
                        owner = current.get(1, current[max(current)])
                    else:
                        owner = current[max(current)]
                        owner['has_children'] = True
                    for item in items:
                        inner_cells.append({'cells': item['cells'], 'location': item['location'],
                                            'cell_locations': item.get('cell_locations'),
                                            'row_bounds': item.get('row_bounds'),
                                            'money_location': item['money_location'],
                                            'title': title})
                        record = {**node_context(owner), **item['cells'], **item['location'],
                                  **{amount_column + '_' + k: v for k, v in item['money_location'].items()}}
                        if title:
                            # The caption's own measured position travels with
                            # the inner table's finest rows as a native title.
                            record['内表_表題'] = title
                            record.update({'内表_表題_' + k: v
                                           for k, v in title_location.items()})
                        non_amount = ''.join(compact(v) for k, v in item['cells'].items() if k != amount_column)
                        if '計' in non_amount and not any(c for c in non_amount.replace('計', '') if not c.isdigit() and c not in ',－件人'):
                            inner_controls.append(record)
                        elif is_lending:
                            lending.append(record)
                        else:
                            owner['annual_rows'].append(record)
                    pending = []
                    continue
                year_headers = annual_header(row)
                if (year_headers and any('年度' in h['name'] for h in year_headers)
                        and ('区分' in stripped) and not awaiting_header):
                    awaiting_header = True
                if '施工概要' in stripped:
                    awaiting_header = True
                    annual = None
                    pending = []
                    continue
                if awaiting_header:
                    headers = year_headers
                    if headers and any('年度' in h['name'] for h in headers):
                        if not current:
                            raise ValueError(f'施工概要 without a business parent on page {page}')
                        owner = current[max(current)]
                        owner['has_children'] = True
                        annual = {'headers': headers, 'owner': owner}
                        annual['source_start'] = (page, int(offset != 0), min(word['y'] for word in row))
                        annual_names.update(h['name'] for h in headers)
                        awaiting_header = False
                    continue
                if annual:
                    item = annual_row(row, annual['headers'])
                    if item:
                        name, cells = item
                        record = {**node_context(annual['owner']), '施工概要_区分': name,
                                  **{'施工概要_' + key: val for key, val in cells.items()},
                                  **coordinates(row, page)}
                        if compact(name) == '計':
                            annual_controls.append(record)
                            start_page, half, top = annual['source_start']
                            if start_page == page:
                                handled.append((page, half, top, max(word['ye'] for word in row)))
                            annual = None
                        else:
                            annual['owner']['annual_rows'].append(record)
                        continue
                    if not money(row):
                        continue
                    annual = None
                payment = money(row)
                if not payment:
                    if personnel_breakdown and current:
                        owner = current[max(current)]
                        if '給与費' in compact(owner['name']):
                            count = re.fullmatch(r'(.+?)\s*([0-9]+)\s*人', value)
                            if count:
                                owner['has_children'] = True
                                owner['annual_rows'].append({**node_context(owner), '職員_区分': count[1].rstrip(),
                                                             '職員_人数': value[count.start(2):],
                                                             '職員_現在日': None, **coordinates(row, page)})
                                pending = []
                                continue
                            total = re.fullmatch(r'計\s*([0-9]+)\s*人\s*(（.*）)', value)
                            if total and owner['annual_rows']:
                                for record in owner['annual_rows']:
                                    record['職員_現在日'] = total[2]
                                personnel_controls.append({'parents': node_context(owner), 'value': value,
                                                           **coordinates(row, page)})
                                pending = []
                                continue
                            dated = re.fullmatch(r'(?!計)(.+?)\s*([0-9]+)\s*人\s*(（[^）]*）)', value)
                            if dated:
                                owner['has_children'] = True
                                owner['annual_rows'].append({**node_context(owner), '職員_区分': dated[1].rstrip(),
                                                             '職員_人数': dated[2] + ' 人',
                                                             '職員_現在日': dated[3], **coordinates(row, page)})
                                pending = []
                                continue
                    if value.startswith('［') and min(w['x'] for w in row) > offset + 395:
                        project = current.get(0)
                        if project:
                            project['department'] = (project['department'] or '') + '\n' + value
                        else:
                            pending_department.append({'page': page,
                                                       'y': min(w['y'] for w in row), 'value': value})
                        continue
                    if (current and current[max(current)]['number']
                            and current[max(current)]['number'].startswith('(')
                            and not pending and value.startswith(('「', 'の'))
                            and min(w['x'] for w in row) < offset + 125):
                        active = current[max(current)]
                        active['name'] += '\n' + value
                        active['location'] = {**active['location'], '原典yMax': max(active['location']['原典yMax'], max(w['ye'] for w in row))}
                        continue
                    if value and not set(stripped) <= {'円', '％'}:
                        pending.append(row)
                    continue
                names = payment['name_words']
                name_text = text(names)
                if compact(name_text) == '計':
                    totals.append({'parents': context(parents), 'value': payment['value'], **coordinates(row, page)})
                    pending = []
                    continue
                # Names can precede a standalone monetary line or wrap below a
                # numbered heading. Do not borrow unrelated staffing/count rows.
                pending_marker = [r for r in pending if re.match(r'^\([0-9]+\)\s+', text(r))]
                if pending_marker and compact(name_text).startswith(('所在地', '完了', '完成')):
                    names = pending_marker[-1]
                    name_text = text(names)
                elif not name_text or len(compact(name_text)) < 3:
                    relevant = [r for r in pending if min(w['x'] for w in r) < payment['number']['x']
                                and len(compact(text(r))) >= 3
                                and not any(w['text'] == '円' for w in r)
                                and (('（' in text(r) or '(' in text(r))
                                     or not any(w['text'] in ('人', '件', '学級', '個', '基', '㎡', '回', 'ｍ') for w in r))]
                    if relevant:
                        last_left = min(w['x'] for w in relevant[-1])
                        relevant = [r for r in relevant if min(w['x'] for w in r) <= last_left + 10]
                        names = [*sum(relevant[-2:], []), *names]
                        name_text = '\n'.join(text(r) for r in relevant[-2:]) + ('\n' + name_text if name_text else '')
                marker = re.match(r'^([0-9]+|\([0-9]+\))\s+(.*)$', name_text, re.DOTALL)
                number = marker[1] if marker else None
                department = text([w for w in row if w['x'] > payment['circle']['xe'] and ('［' in w['text'] or '］' in w['text'] or w['x'] < offset + 650)]) or None
                name = marker[2] if marker else name_text
                name_x = payment['name_words'][0]['x'] - offset if payment['name_words'] else None
                if number and not number.startswith('(') and names[0]['x'] - offset < 52:
                    rank = 0
                elif number and number.startswith('('):
                    rank = 1
                else:
                    right = payment['circle']['x'] - offset
                    rank = 3 if right < 220 else (2 if right < 290 else 1)
                    if names and names[0]['x'] - offset >= 55:
                        rank = max(rank, 2)
                    if name_x is not None and current:
                        deepest = current[max(current)]
                        dn = deepest.get('name_x')
                        # Indent is relative: a row printed deeper than the open
                        # detail is its child, and a row at the same indent is a
                        # sibling at that same level regardless of the absolute
                        # amount column thresholds above.
                        if dn is not None:
                            if name_x > dn + 6:
                                rank = max(rank, deepest['rank'] + 1)
                            elif rank < deepest['rank'] and name_x >= dn - 4:
                                rank = deepest['rank']
                for depth in list(current):
                    if depth >= rank:
                        current.pop(depth)
                parent_node = current[max(current)] if current else None
                if rank and parent_node is None:
                    raise ValueError(f'Orphan monetary detail on page {page}: {name_text}')
                if parent_node:
                    parent_node['has_children'] = True
                node = {'rank': rank, 'number': number, 'name': name, 'amount': payment['value'],
                        'department': department, 'name_x': name_x,
                        'location': coordinates([*row, *names], page), 'parent': parent_node,
                        'context': context(parents), 'has_children': False, 'annual_rows': []}
                if pending_department and rank == 0:
                    # A department mark can print one line above the business
                    # row it belongs to (same ruled band); it is not a section
                    # department and never crosses a page or a subject heading.
                    near = [d for d in pending_department
                            if d['page'] == page and node['location']['原典yMin'] - 25 < d['y'] < node['location']['原典yMax'] + 10]
                    if near:
                        node['department'] = '\n'.join([*[d['value'] for d in near],
                                                        *([department] if department else [])])
                    pending_department = []
                nodes.append(node)
                current[rank] = node
                pending = []
    quantity_controls, quantity_cells, office_headings = (
        nonfinancial_facts(pages, nodes, source, destination, grids, handled, all_parents)
        if nonfinancial_breakdown else ([], [], []))
    records = []
    for node in nodes:
        records.extend(node['annual_rows'])
        if not node['has_children']:
            records.append({**node_context(node), '明細金額': node['amount'], **node['location']})
    # No business expenditure is printed for the reserve; retain its finest
    # available printed moku row, including the actual zero and all budget cells.
    represented_moku = {(n['context']['目_原典物理頁'], n['context']['目_原典yMin']) for n in nodes}
    for index, parent in enumerate(all_parents):
        if parent['level'] == '目' and (parent['原典物理頁'], parent['原典yMin']) not in represented_moku:
            if unexplained_section_detail:
                following = all_parents[index + 1] if index + 1 < len(all_parents) else None
                sections = unexplained_sections(pages, parent, following, last)
                if sections:
                    records.extend(sections)
                    continue
            records.append({**parent['parents'], **{k: parent[k] for k in coordinates_keys()}})
    # An office/department heading is handed to its rows at construction time:
    # every finest row inside its reading-order scope — from the heading to the
    # next office or moku heading within the same moku — carries the scalar and
    # the heading's own origin position, so no downstream pass has to re-derive
    # the correspondence and repeated business names cannot misplace it.
    for record in records:
        path = tuple(record.get(level + '_番号') for level in ('款', '項', '目'))
        pos = (record.get('原典物理頁'), int((record.get('原典xMin') or 0) >= 650),
               record.get('原典yMin'))
        applicable = [h for h in office_headings
                      if h['moku_path'] == path and h['pos'] <= pos]
        if applicable:
            heading = max(applicable, key=lambda h: h['pos'])
            record.update({'目_機関部署見出し': heading['text'],
                           **{'目_機関部署見出し_' + k: v
                              for k, v in heading['location'].items()}})
    if remark_column:
        # The printed remark column (備考, x>1024) is an independent scalar of
        # the fiscal row whose ruled band contains the line: row boundaries are
        # the horizontal rules spanning the whole fiscal table, while inner
        # quantity tables rule only their own fragments and never reach both
        # edges. Each remark line must resolve to exactly one printed row.
        remarks = {}
        entities = [(p['level'], p, p) for p in all_parents]
        entities += [(LEVELS[n['rank']], n['location'], n) for n in nodes]
        for page, words in pages.items():
            marks = [w for w in words if w['x'] > remark_min_x and 60 < w['y'] < 790]
            lines = [line for line in rows(marks) if compact(text(line)) not in ('備', '考', '備考')]
            if not lines:
                continue
            if page not in grids:
                grids[page] = grid_lines(source, destination, page)
            coverage = defaultdict(list)
            for x1, x2, y in grids[page][0]:
                coverage[round(y, 1)].append((x1, x2))
            edges = sorted(y for y, seg in coverage.items()
                           if min(x1 for x1, _ in seg) < 45 and max(x2 for _, x2 in seg) > 480)
            for line in lines:
                center = (min(w['y'] for w in line) + max(w['ye'] for w in line)) / 2
                hits = []
                for level, loc, entity in entities:
                    if loc['原典物理頁'] != page:
                        continue
                    middle = (loc['原典yMin'] + loc['原典yMax']) / 2
                    lower = max((y for y in edges if y < middle), default=60)
                    upper = min((y for y in edges if y > middle), default=790)
                    if lower < center < upper:
                        hits.append((level, loc, entity))
                if len(hits) != 1:
                    raise ValueError(f'Remark line has {len(hits)} owning rows: page={page}, {text(line)}')
                level, loc, _ = hits[0]
                key = (level, page, round(loc['原典yMin'], 1))
                remarks.setdefault(key, []).append(text(line))
        for record in [*records, *reserve, *lending]:
            for level in ['款', '項', '目', *LEVELS]:
                page = record.get(level + '_原典物理頁')
                top = record.get(level + '_原典yMin')
                if page is None or top is None:
                    continue
                found = remarks.get((level, page, round(top, 1)))
                if found:
                    record[level + '_備考'] = '\n'.join(found)
    for record in records:
        for key in sorted(annual_names):
            record.setdefault('施工概要_' + key, None)
    observations = {'parents': all_parents, 'business_nodes': [
        {k: v for k, v in node.items() if k not in ('parent', 'annual_rows')} |
        {'parent_location': node['parent']['location'] if node['parent'] else None}
        for node in nodes], 'business_totals': totals, 'annual_totals': annual_controls, 'inner_totals': inner_controls,
        'inner_cells': inner_cells,
        'coordinate_system': 'Poppler bbox-layout, upright top-left origin, pt; physical pages'}
    if personnel_breakdown:
        observations['personnel_totals'] = personnel_controls
    if nonfinancial_breakdown:
        observations['quantity_totals'] = quantity_controls
        observations['quantity_cells'] = quantity_cells
    return records, reserve, lending, observations


def coordinates_keys():
    return ['原典物理頁', '原典xMin', '原典yMin', '原典xMax', '原典yMax']


def metadata(columns, *, reserve=False, lending=False):
    monetary = [c for c in columns if any(c.endswith('_' + f) for f in FINANCIAL[:-1])
                or c.endswith('_金額') or c == '明細金額' or c.startswith('施工概要_') and c != '施工概要_区分'
                or c in ('充用した科目（事業）及び金額', '内表_金額', '内表_給付額', '内表_月額')]
    result = {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': monetary}}],
              'notes': [{'text': '事業説明と法定節一覧は独立の分解であり、同じ高さの節を事業に対応付けない。名称内の字間はPopplerの単語を空白で連結し、折り返しは改行で保持。XML構文を壊す印字外の制御文字だけを解析用コピーから除去し、原XMLを観測として保持。',
                         'scope': {'kind': 'table'}}], 'column_contexts': []}
    for level in ('款', '項', '目'):
        group = [c for c in columns if c.startswith(level + '_')
                 and not c.startswith('目_機関部署見出し')]
        result['column_contexts'].append({'columns': group, 'header_path': ['科目', level],
                                         'grain_columns': [level + '_番号', level + '_原典物理頁', level + '_原典yMin']})
    office = [c for c in columns if c.startswith('目_機関部署見出し')]
    if office:
        result['column_contexts'].append({'columns': office, 'header_path': ['科目', '目', '機関部署見出し'],
                                         'grain_columns': ['目_機関部署見出し_' + k for k in coordinates_keys()]})
        result['notes'].append({'text': '目の直下に印字される機関・部署の見出しはその目自身のscalarであり、特定の事業・内訳の補足ではない。原印字の文字と位置を、原典見出しの開始から次の機関または目見出しまでの最細行へ反復し、支出の分解や事業への付与とは扱わない。', 'scope': {'kind': 'table'}})
    for level in LEVELS:
        group = [c for c in columns if c.startswith(level + '_')]
        if group:
            result['column_contexts'].append({'columns': group, 'header_path': ['科目', '事業説明'],
                                             'grain_columns': [level + '_原典物理頁', level + '_原典yMin'],
                                             'semantic_role': 'project'})
    annual = [c for c in columns if c.startswith('施工概要_')]
    if annual:
        result['column_contexts'].append({'columns': annual, 'header_path': ['施工概要'],
                                         'grain_columns': ['原典物理頁', '原典yMin', '施工概要_区分']})
    inner = [c for c in columns if c.startswith('内表_')]
    if inner:
        money_columns = []
        for label in ('金額', '給付額'):
            prefix = '内表_' + label
            group = [c for c in inner if c == prefix or c.startswith(prefix + '_')]
            if group:
                money_columns.extend(group)
                result['column_contexts'].append({'columns': group, 'header_path': ['事業説明', '内表', label],
                                                 'grain_columns': [prefix + '_' + key for key in coordinates_keys()]})
        title_columns = [c for c in inner if c == '内表_表題' or c.startswith('内表_表題_')]
        if title_columns:
            result['column_contexts'].append({'columns': title_columns,
                                             'header_path': ['事業説明', '内表', '表題'],
                                             'grain_columns': ['内表_表題_' + k for k in coordinates_keys()]})
            result['notes'].append({'text': '金額内表の直上に印字された表題・資格区分の行は、その内表自身の表題であり通常給付側や事業の補足ではない。原印字の文字と位置を内表_表題としてその内表の最細行へ保持する。', 'scope': {'kind': 'table'}})
        result['column_contexts'].append({'columns': [c for c in inner if c not in money_columns + title_columns],
                                         'header_path': ['事業説明', '内表'],
                                         'grain_columns': ['原典物理頁', '原典yMin', '原典yMax']})
        result['notes'].append({'text': '金額を持つ内表は罫線のセル範囲で文字・複数行・結合セルの所属を復元。印字された数量・対象者数・月額・施工数などを原見出しに対応するscalar補助列で保持。金額セルが期別など複数の最細行に縦結合される場合、印字共通金額と同一金額bboxを各行へ反復し、期別配分額とは解釈しない。集計では原典頁・親経路・金額列・金額bboxで同一原典セルを識別し、反復値の一致確認後に一度だけ数える。SUM(DISTINCT 金額)は用いない。内表の計行は検算用観測に保持。', 'scope': {'kind': 'table'}})
    if '内表_給付額' in columns:
        result['units'].append({'text': '件', 'scope': {'kind': 'columns', 'columns': ['内表_件数']}})
        result['notes'].append({'text': '区分・件数・給付額の内表は最細区分行を保持。最初のデータ行上部の独立した件・円の印字は各列共通の単位であり、最初の行だけの値に含めない。', 'scope': {'kind': 'table'}})
    personnel = [c for c in columns if c.startswith('職員_')]
    if personnel:
        result['units'].append({'text': '人', 'scope': {'kind': 'columns', 'columns': ['職員_人数']}})
        result['column_contexts'].append({'columns': personnel, 'header_path': ['事業説明', '職員の給与費'],
                                         'grain_columns': ['原典物理頁', '原典yMin']})
        result['notes'].append({'text': '職員人数の最細区分行は給与費の事業親に属する独立した人数内訳。共通の給与費額と事業の原典位置を各人数行に反復するが、人数区分ごとの支出配分額は印字されていないため明細金額を付与しない。現在日は人数の計行から保持。給与費額を集計する際は同一親経路・原典位置の反復値の一致を確認して一度だけ数える。人数の計行は検算用観測に保持。', 'scope': {'kind': 'table'}})
    quantity = [column for column in columns if column.startswith('数量表_')]
    if quantity:
        declared = set()
        for _, _, _, _, _, title, fields, _, _, _ in AUXILIARY_TABLES:
            for field in fields:
                prefix = '数量表_' + title + '_' + field
                group = [column for column in quantity if column == prefix or column.startswith(prefix + '_原典')]
                if not group or prefix in declared:
                    continue
                declared.add(prefix)
                result['column_contexts'].append({'columns': group,
                    'header_path': ['事業説明', title, *field.split('_')],
                    'grain_columns': [prefix + '_' + key for key in coordinates_keys()
                                      if prefix + '_' + key in columns]})
                unit = None
                if ('園児数_' in field or '職員数_' in field or field in ('人数', '戸籍人口', '児童数', '教員数', '生徒数',
                        '園児数', '個人貸出者数', '乳幼児', '小学生', '中学生', '高校生', '保護者')
                        or field.endswith(('受診者数', '入院者数', '調剤数'))
                        or title in ('利用状況', '認定状況') and field != '児童館名'):
                    unit = '人'
                elif field.endswith(('回数', '回数（延）')):
                    unit = '回'
                elif field in ('利用件数', '件数'):
                    unit = '件'
                elif field == '派遣世帯（延）':
                    unit = '世帯'
                elif field in ('購入図書数', '蔵書数'):
                    unit = '冊'
                elif field in ('学校数', '園数', '学級数', '戸籍数', '助成基準', '規模'):
                    unit = {'学校数': '校', '園数': '園', '学級数': '学級', '戸籍数': '戸籍',
                            '助成基準': '％', '規模': '㎡'}[field]
                if unit:
                    result['units'].append({'text': unit, 'scope': {'kind': 'columns', 'columns': [prefix]}})
        general = [column for column in ('数量表_見出し', '数量表_現在日') if column in columns]
        result['column_contexts'].append({'columns': general, 'header_path': ['事業説明', '数量表'],
                                         'grain_columns': ['原典物理頁', '原典yMin', '原典yMax']})
        result['notes'].append({'text': '数量表は原典の最細区分行・欄・結合セル・印字位置を保持する独立した非金額の内訳。共通の給与費・事業費などは所属する親の印字金額と位置を反復し、数量行へ配賦した明細金額は付与しない。複数段見出しや重複した計・受診者数等は原見出しの経路で区別。計行はローカル検算用観測。住民基本台帳の京橋・日本橋・月島・計の欄は、区分が世帯数の行は世帯、人口の行は人。道路工種実績の単位は印字された数量セル内の㎡・ｍ・個を保持。回数の括弧内の延日数は同じ原典セルの原文として保持。',
                                 'scope': {'kind': 'table'}})
    if '補足_本文' in columns:
        result['column_contexts'].append({'columns': ['補足_本文'], 'header_path': ['事業説明', '補足'],
                                         'grain_columns': ['原典物理頁', '原典yMin', '原典yMax']})
        result['notes'].append({'text': '所在地・完成予定・件数等の原典補足は印字行の文字と位置をscalarで保持。所属する事業・内訳の共通印字金額と位置は反復し、補足行に支出配分額を付与しない。', 'scope': {'kind': 'table'}})
    section = [c for c in columns if c.startswith('節_')]
    if section:
        result['column_contexts'].append({'columns': section, 'header_path': ['節'],
                                         'grain_columns': ['目_原典物理頁', '目_原典yMin', '節_番号',
                                                           '節_原典物理頁', '節_原典yMin']})
        result['notes'].append({'text': '事業説明の印字がない目だけは、原典の最細法定節行を保持。節の金額は予算現額、支出済額・翌年度繰越額・不用額は同じ節の印字額。事業説明を持つ他の目へ法定節を対応付けず、別軸の節一覧を事業葉行に重ねない。法定節がない予備費は目粒度を保持。', 'scope': {'kind': 'table'}})
    result['notes'].append({'text': ('予備費の「充用した科目（事業）及び金額」の説明。各充用先の金額を保持し、通常事業の支出済額とは異なる。' if reserve else
        '款・項・目の予算列・繰越・不用額・執行率は原典の親項目粒度で反復。事業・内訳金額と明細金額は支出済額の説明。施工概要は全印字年度と計の列を保持し、通常明細金額は空欄。施工概要の区分行を末端として改修親額を反復、計行は検算用観測へ保存。予備費は目粒度の印字0支出済額を保持。'),
                             'scope': {'kind': 'table'}})
    rates = [c for c in columns if c.endswith('_執行率')]
    if rates:
        result['units'].append({'text': '％', 'scope': {'kind': 'columns', 'columns': rates}})
    if lending:
        result['units'] = [u for u in result['units'] if u['text'] != '円']
        result['units'].extend([{'text': '円', 'scope': {'kind': 'columns', 'columns': [c for c in monetary if c != '内表_金額']}},
                               {'text': '千円', 'scope': {'kind': 'columns', 'columns': ['内表_金額']}}])
        result['notes'].append({'text': '［備考］貸付状況。原文「区分」「件数」「金額」の最細印字行であり、商工業融資の支出内訳とは異なる実績の表。', 'scope': {'kind': 'table'}})
    return result


def convert(inputs, destination, options):
    if len(inputs) != 1 or inputs[0]['format'] != 'pdf' or inputs[0]['pdf_type'] != 'text':
        raise ValueError('This layout requires one selected text PDF')
    source = inputs[0]
    if source['target']['jurisdiction'] != '131024' or source['direction'] != 'expenditure':
        raise ValueError('This measured layout is Chuo expenditure only')
    first, last = options['detail_pages']
    scope = next(s for s in source['scope'] if s['account'] == options['account'])
    if not any(start <= first <= last <= end for start, end in scope['pages']):
        raise ValueError('Requested pages are outside selected account scope')
    destination = Path(destination)
    origin = destination / 'origin-bbox.html'
    subprocess.run(['pdftotext', '-f', str(first), '-l', str(last), '-bbox-layout', str(source['path']), str(origin)], check=True)
    xml = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', origin.read_text())
    tokens = tokens_from_bbox_layout(xml, origin_id=source['sha256'], first_page=first)
    pages = defaultdict(list)
    for token in tokens:
        if token.raw_text:
            box = token.bbox
            pages[token.page].append({'text': token.raw_text, 'x': box.left, 'xe': box.right,
                                       'y': box.top, 'ye': box.bottom})
    records, reserve, lending, observations = assemble(pages, first, last, source=source['path'], destination=destination,
                                                      reserve_kan=options.get('reserve_kan', '11'),
                                                      personnel_breakdown=options.get('personnel_breakdown', False),
                                                      unexplained_section_detail=options.get('unexplained_section_detail', False),
                                                      nonfinancial_breakdown=options.get('nonfinancial_breakdown', False),
                                                      remark_column=options.get('remark_column', False),
                                                      remark_min_x=options.get('remark_min_x', 1024))
    (destination / 'builder-observations.json').write_text(json.dumps(observations, ensure_ascii=False, indent=2) + '\n')
    result = {}
    available = {'detail': (records, False, False), 'reserve': (reserve, True, False),
                 'lending': (lending, False, True)}
    role = options.get('output_role')
    if role:
        outputs = [(options['table_id'], *available[role])]
    else:
        outputs = [(options['table_id'], *available['detail'])]
        for name in ('reserve', 'lending'):
            table_id = options.get(name + '_table_id')
            data, is_reserve, is_lending = available[name]
            if not table_id:
                if data:
                    raise ValueError(f'Nonempty {name} explanation requires a declared table ID or output_role')
                continue
            outputs.append((table_id, data, is_reserve, is_lending))
    for table_id, data, is_reserve, is_lending in outputs:
        output = destination / (table_id + '.parquet')
        columns = write_parquet(output, data)
        result[table_id] = {'path': output, 'metadata': metadata(columns, reserve=is_reserve, lending=is_lending)}
    return result
