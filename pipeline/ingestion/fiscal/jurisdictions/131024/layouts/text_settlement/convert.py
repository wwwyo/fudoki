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


def grid_table(words, header, headers, lines, page):
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
            cells = {}
            cell_locations = {}
            kept = []
            for item, (lower, upper) in zip(headers, column_bounds, strict=True):
                selected = []
                for w in words:
                    wx = (w['x'] + w['xe']) / 2
                    wy = (w['y'] + w['ye']) / 2
                    if not (lower < wx < upper and header_bottom < wy < end):
                        continue
                    cell_lines = sorted(set(y for x1, x2, y in horizontal if x1 - .2 <= wx <= x2 + .2))
                    cell_top = max((y for y in cell_lines if y < wy), default=header_bottom)
                    cell_bottom = min((y for y in cell_lines if y > wy), default=end)
                    if cell_top < row_bottom - .3 and cell_bottom > row_top + .3:
                        selected.append(w)
                cells['内表_' + item['name']] = '\n'.join(text(r) for r in rows(selected))
                cell_locations['内表_' + item['name']] = coordinates(selected, page) if selected else None
                kept.extend(selected)
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


def assemble(pages, first, last, *, source, destination, reserve_kan='11', personnel_breakdown=False,
             unexplained_section_detail=False):
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
    reserve_pending = []

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
                        continue
                if '目' not in parents:
                    continue
                if min(w['y'] for w in row) < skip_until:
                    continue
                value = text(row)
                stripped = compact(value)
                if parents['款']['番号'] == reserve_kan:
                    # Reserve appropriations are a distinct explanation, not
                    # executed business detail under the zero-expense reserve.
                    payment = money(row)
                    if not payment:
                        reserve_pending.append(value)
                        continue
                    title = text(payment['name_words'])
                    if '充用した科目' in compact(title):
                        reserve_total = payment['value']
                        reserve_pending = []
                        continue
                    if reserve_pending and re.match(r'^第\s*[0-9]+\s*[款項目]', reserve_pending[0]):
                        title = '\n'.join([*reserve_pending, title])
                    match = re.match(r'^第\s*([0-9]+)\s*([款項目])\s*(.*)$', title, re.DOTALL)
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
                                            'money_location': item['money_location']})
                        record = {**node_context(owner), **item['cells'], **item['location'],
                                  **{amount_column + '_' + k: v for k, v in item['money_location'].items()}}
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
                            count = re.fullmatch(r'(.+職\s*員)\s*([0-9]+)\s*人', value)
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
                    if current and value.startswith('［') and min(w['x'] for w in row) > offset + 395:
                        project = current.get(0)
                        if project:
                            project['department'] = (project['department'] or '') + '\n' + value
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
                if number and not number.startswith('(') and names[0]['x'] - offset < 52:
                    rank = 0
                elif number and number.startswith('('):
                    rank = 1
                else:
                    right = payment['circle']['x'] - offset
                    rank = 3 if right < 220 else (2 if right < 290 else 1)
                    if names and names[0]['x'] - offset >= 55:
                        rank = max(rank, 2)
                for depth in list(current):
                    if depth >= rank:
                        current.pop(depth)
                parent_node = current[max(current)] if current else None
                if rank and parent_node is None:
                    raise ValueError(f'Orphan monetary detail on page {page}: {name_text}')
                if parent_node:
                    parent_node['has_children'] = True
                node = {'rank': rank, 'number': number, 'name': name, 'amount': payment['value'],
                        'department': department, 'location': coordinates([*row, *names], page), 'parent': parent_node,
                        'context': context(parents), 'has_children': False, 'annual_rows': []}
                nodes.append(node)
                current[rank] = node
                pending = []
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
        group = [c for c in columns if c.startswith(level + '_')]
        result['column_contexts'].append({'columns': group, 'header_path': ['科目', level],
                                         'grain_columns': [level + '_番号', level + '_原典物理頁', level + '_原典yMin']})
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
        result['column_contexts'].append({'columns': [c for c in inner if c not in money_columns],
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
                                                      unexplained_section_detail=options.get('unexplained_section_detail', False))
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
