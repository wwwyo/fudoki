"""Read ruled enterprise statements; preserve printed strings and parent context."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn
from ingestion.lib.pdf_table import (Box, Column, Placement, RowBand, TableLayout,
                                    assemble_table, place_tokens, tokens_from_bbox_layout)

AMOUNT = re.compile(r'[0-9][0-9,]*')
RECTANGLE = re.compile(r'M ([0-9.]+) ([0-9.]+) L ([0-9.]+) ([0-9.]+) L ([0-9.]+) ([0-9.]+) L ([0-9.]+) ([0-9.]+) Z')
POSITION_COLUMNS = ('物理頁', '印刷頁', '原典位置_上端', '原典位置_下端')


def text(tokens):
    """Restore line order within wrapped cells without inserting inferred spaces."""
    rows = []
    for token in sorted(tokens, key=lambda t: (t.bbox.top, t.bbox.left)):
        if not rows or token.bbox.top - rows[-1][0].bbox.top > 1:
            rows.append([])
        rows[-1].append(token)
    return ''.join(t.raw_text for row in rows for t in sorted(row, key=lambda t: t.bbox.left)) or None


def observe(pdf, page, origin, directory):
    xml = subprocess.check_output(['pdftotext', '-bbox-layout', '-f', str(page), '-l', str(page), str(pdf), '-'])
    (directory / f'p{page}.bbox.xml').write_bytes(xml)
    tokens = tokens_from_bbox_layout(xml, origin_id=origin, first_page=page)
    with tempfile.TemporaryDirectory() as tmp:
        svg_path = Path(tmp) / 'page.svg'
        subprocess.run(['pdftocairo', '-svg', '-f', str(page), '-l', str(page), str(pdf), str(svg_path)], check=True)
        svg = svg_path.read_text()
    (directory / f'p{page}.svg').write_text(svg)
    # Glyph outlines are in <defs>; only direct page paths are table rules.
    rectangles = []
    for node in ET.fromstring(svg):
        if node.tag.rsplit('}', 1)[-1] != 'path':
            continue
        for match in RECTANGLE.finditer(node.get('d', '')):
            pairs = list(zip(*[iter(map(float, match.groups()))] * 2))
            xs, ys = zip(*pairs)
            rectangles.append((min(xs), min(ys), max(xs), max(ys)))
    horizontal = [b for b in rectangles if b[3] - b[1] < 3 and b[2] - b[0] > 10]
    (directory / f'p{page}.words.json').write_text(json.dumps([asdict(t) for t in tokens], ensure_ascii=False, indent=2) + '\n')
    return tokens, horizontal


def bands_at(rules, x, top, bottom):
    edges = sorted({round((a[1] + a[3]) / 2, 4) for a in rules if a[0] < x < a[2] and top < a[1] < bottom})
    if len(edges) < 2:
        raise ValueError('No complete ruled table at the measured amount column')
    return tuple(RowBand(a, b) for a, b in zip(edges, edges[1:]))


def cells(tokens, page, columns, bands):
    placed = place_tokens(tokens, {(t.origin_id, page): Placement(str(page)) for t in tokens})
    result = assemble_table(placed, TableLayout(tuple(columns), row_bands=bands))
    records = []
    for band, row in zip(bands, result.rows, strict=True):
        record = {c.column: text([w.token for w in c.tokens]) for c in row.cells}
        record['_tokens'] = {c.column: [w.token for w in c.tokens] for c in row.cells}
        record['_band'] = band
        records.append(record)
    return records


def printed_page(tokens):
    value = text([t for t in tokens if t.bbox.top > 800])
    if not value or not re.fullmatch(r'-[0-9]+-', value):
        raise ValueError('Printed page footer differs')
    return value


def position(page, footer, band):
    return {'物理頁': page, '印刷頁': footer, '原典位置_上端': band.top, '原典位置_下端': band.bottom}


def detail(pdf, pages, origin, directory):
    output, observations = [], []
    context = {}
    for index, page in enumerate(pages):
        tokens, rules = observe(pdf, page, origin, directory)
        if text([t for t in tokens if '消費税' in t.raw_text]) != '（消費税抜き）':
            raise ValueError('Expense detail tax heading differs')
        header = [t for t in tokens if 90 < t.bbox.top < 145 and t.raw_text in ('款項', '目', '節', '金', '額（円）', '備', '考')]
        if set(t.raw_text for t in header) != {'款項', '目', '節', '金', '額（円）', '備', '考'}:
            raise ValueError('Missing expense detail headers')
        offset = next(t.bbox.left for t in tokens if t.raw_text == '額（円）') - 302.302121
        border = 177.4 + offset
        split = []
        for token in tokens:
            if token.bbox.left < border < token.bbox.right and token.bbox.top > 115:
                # Poppler merges the final moku glyph with the first section glyph
                # on continuation pages. Split only this two-glyph boundary case.
                if len(token.raw_text) != 2 or token.raw_text[0] != '費':
                    raise ValueError(f'Unmeasured word crossing name/section rule: {token.id}')
                width = token.bbox.bottom - token.bbox.top
                split.extend((replace(token, id=token.id + ':left', raw_text=token.raw_text[0],
                                      bbox=Box(token.bbox.left, token.bbox.top, token.bbox.left + width, token.bbox.bottom), parent_id=token.id),
                              replace(token, id=token.id + ':right', raw_text=token.raw_text[1],
                                      bbox=Box(token.bbox.right - width, token.bbox.top, token.bbox.right, token.bbox.bottom), parent_id=token.id)))
            else:
                split.append(token)
        tokens = split
        bands = bands_at(rules, 300 + offset, 140 if index == 0 else 110, 795)
        columns = [Column('名称', 50, border, anchor='left'), Column('節', border, 260.1 + offset, anchor='left'),
                   Column('金額（円）', 260.1 + offset, 343 + offset, anchor='left'), Column('備考', 343 + offset, 550, anchor='left')]
        for record in cells(tokens, page, columns, bands):
            label, section, amount = record['名称'], record['節'], record['金額（円）']
            if label:
                names = record['_tokens']['名称']
                numbering = [t for t in names if t.bbox.left < 95 + offset and re.fullmatch('[０-９]+', t.raw_text)]
                if numbering:
                    label = (text(numbering) or '') + (text([t for t in names if t not in numbering]) or '')
            if amount is None or not AMOUNT.fullmatch(amount):
                raise ValueError(f'Missing/unrecognized detail amount on p{page}: {record}')
            band = record['_band']
            if label and not section:
                left = min(t.bbox.left for t in record['_tokens']['名称']) - offset
                level = '款' if left < 62 else '項' if left < 76 else '目'
                lower = ('款', '項', '目')
                for key in lower[lower.index(level):]:
                    context.pop(key, None)
                    context.pop(key + '_金額', None)
                context.update({level: label, level + '_金額': amount})
                observations.append({'page': page, 'kind': level, 'name': label, 'amount': amount, 'top': band.top, 'bottom': band.bottom})
                continue
            if not section or not all(key in context for key in ('款', '項', '目')):
                raise ValueError(f'Expense section lacks full source hierarchy on p{page}')
            if label and label != context['目']:
                raise ValueError(f'Continuation moku differs on p{page}: {label}')
            remarks = record['_tokens']['備考']
            remark_lines = []
            for t in sorted(remarks, key=lambda t: (t.bbox.top, t.bbox.left)):
                if not remark_lines or t.bbox.top - remark_lines[-1][0].bbox.top > 1:
                    remark_lines.append([])
                remark_lines[-1].append(t)
            budget, leaves = None, []
            for line in remark_lines:
                amounts = [t for t in line if AMOUNT.fullmatch(t.raw_text)]
                names = [t for t in line if t not in amounts]
                if len(amounts) != 1 or not names:
                    raise ValueError(f'Unmeasured expense remark line on p{page}')
                name, value = text(names), text(amounts)
                if name == '予算額':
                    if budget is not None:
                        raise ValueError('Repeated remark budget')
                    budget = value
                else:
                    leaves.append((name, value))
            observations.append({'page': page, 'kind': '節', 'name': section, 'amount': amount,
                                 'context': dict(context), 'budget': budget, 'remarks': leaves,
                                 'top': band.top, 'bottom': band.bottom})
            for name, value in leaves or [(None, None)]:
                output.append({**context, '節': section, '金額（円）': amount, '備考_予算額': budget,
                               '備考_名称': name, '備考_金額': value,
                               **position(page, printed_page(tokens), band)})
    return output, observations


REVENUE_LEFT = [Column('区分', 40, 170, 'left'), Column('当初予算額', 170, 247, 'right'),
                Column('補正予算額', 247, 328, 'right'), Column('予備費支出額', 328, 403, 'right'),
                Column('流用増減額', 403, 479, 'right'),
                Column('地方公営企業法第24条第3項の規定による支出額', 479, 550, 'right')]
REVENUE_RIGHT = [Column('小計', 45, 125, 'right'),
                 Column('地方公営企業法第26条第２項の規定による繰越額', 125, 181, 'right'),
                 Column('合計', 181, 256, 'right'), Column('決算額', 256, 332, 'right'),
                 Column('地方公営企業法第26条第2項の規定による繰越額', 332, 402, 'right'),
                 Column('不用額', 402, 483, 'right'), Column('備考', 483, 550, 'left')]
CAPITAL_LEFT = [Column('区分', 30, 155, 'left'), Column('当初予算額', 155, 228, 'right'),
               Column('補正予算額', 228, 304, 'right'), Column('予備費支出額', 304, 368, 'right'),
               Column('流用増減額', 368, 408, 'right'), Column('小計', 408, 487, 'right'),
               Column('地方公営企業法第26条の規定による前年度繰越額', 487, 562, 'right')]
CAPITAL_RIGHT = [Column('継続費逓次繰越額', 30, 97, 'right'), Column('合計', 97, 172, 'right'),
                Column('決算額', 172, 251, 'right'),
                Column('地方公営企業法第26条の規定による繰越額', 251, 313, 'right'),
                Column('翌年度繰越額_継続費逓次繰越額', 313, 364, 'right'),
                Column('翌年度繰越額_合計', 364, 431, 'right'), Column('不用額', 431, 505, 'right'),
                Column('備考', 505, 568, 'left')]


def report(pdf, pages, origin, directory, capital):
    left_page, right_page = pages
    lt, lr = observe(pdf, left_page, origin, directory)
    rt, rr = observe(pdf, right_page, origin, directory)
    lc, rc = (CAPITAL_LEFT, CAPITAL_RIGHT) if capital else (REVENUE_LEFT, REVENUE_RIGHT)
    top, bottom = (535, 740) if capital else (460, 674)
    lb, rb = bands_at(lr, 200, top, bottom), bands_at(rr, 220, top, bottom)
    if len(lb) != 5 or len(rb) != 5 or any(abs(a.top - b.top) > 1 for a, b in zip(lb, rb)):
        raise ValueError('Report spread rows do not align by original horizontal rules')
    tax = text([t for t in rt if 380 < t.bbox.top < 490 and (t.raw_text.startswith('（消費税') or '単位：円' in t.raw_text)])
    if tax != '（消費税込み単位：円）':
        raise ValueError('Report tax/unit heading differs')
    header_top = 505 if capital else 425
    header_alias = {'翌年度繰越額_継続費逓次繰越額': '継続費逓次繰越額', '翌年度繰越額_合計': '合計'}
    for page, tokens, columns, bands in [(left_page, lt, lc, lb), (right_page, rt, rc, rb)]:
        observed_header = cells(tokens, page, columns, (RowBand(header_top, bands[0].top),))[0]
        for column in columns:
            if observed_header[column.name] != header_alias.get(column.name, column.name):
                raise ValueError(f'Report column heading differs on p{page}: {column.name}: {observed_header[column.name]}')
    records = []
    for left, right in zip(cells(lt, left_page, lc, lb), cells(rt, right_page, rc, rb), strict=True):
        numbering = [t for t in left['_tokens']['区分'] if re.fullmatch('第[０-９]+[款項]', t.raw_text)]
        if len(numbering) != 1:
            raise ValueError('Missing report printed classification number')
        left['区分'] = text(numbering) + (text([t for t in left['_tokens']['区分'] if t not in numbering]) or '')
        right.pop('備考')
        remark_tokens = right['_tokens']['備考']
        numbers = [t for t in remark_tokens if AMOUNT.fullmatch(t.raw_text)]
        name = text([t for t in remark_tokens if t not in numbers])
        if name != 'うち仮払消費税' or len(numbers) != 1:
            raise ValueError('Report input-tax remark differs')
        values = {**{c.name: left[c.name] for c in lc}, **{c.name: right[c.name] for c in rc if c.name != '備考'},
                  '備考_名称': name, '備考_金額': text(numbers)}
        if any(not AMOUNT.fullmatch(v or '') for k, v in values.items() if k not in ('区分', '備考_名称')):
            raise ValueError('Missing/unrecognized report amount')
        records.append({**values, **position(left_page, printed_page(lt), left['_band']),
                        '右物理頁': right_page, '右印刷頁': printed_page(rt)})
    parent, *children = records
    if not parent['区分'].startswith('第１款') or any(not r['区分'].startswith('第') or '項' not in r['区分'] for r in children):
        raise ValueError('Report hierarchy differs')
    result = []
    for child in children:
        result.append({'区分_款': parent['区分'], '区分_項': child['区分'],
                       **{'区分_款_' + k: v for k, v in parent.items() if k != '区分'},
                       **{k: v for k, v in child.items() if k != '区分'}})
    return result, records


def metadata(rows, detail_table, capital):
    amounts = [k for k, v in rows[0].items() if isinstance(v, str) and AMOUNT.fullmatch(v)]
    if detail_table:
        amounts = ['款_金額', '項_金額', '目_金額', '金額（円）', '備考_予算額', '備考_金額']
    contexts = []
    if detail_table:
        for level, grain in [('款', ['款']), ('項', ['款', '項']), ('目', ['款', '項', '目'])]:
            contexts.append({'columns': [level, level + '_金額'], 'header_path': ['款' if level == '款' else level, '金額（円）'], 'grain_columns': grain})
        contexts += [{'columns': ['節', '金額（円）'], 'header_path': ['節', '金額（円）'], 'grain_columns': ['款', '項', '目', '節']},
                     {'columns': ['備考_予算額'], 'header_path': ['備考', '予算額'], 'grain_columns': ['款', '項', '目', '節']},
                     {'columns': ['備考_名称', '備考_金額'], 'header_path': ['備考'], 'grain_columns': ['款', '項', '目', '節', '備考_名称']}]
        note = '（消費税抜き）。金額（円）は決算の節額。備考の予算額は同じ節の予算、備考のその他の金額は決算内訳。原典に備考内訳がある節はその末端を行にし、款・項・目・節額と備考予算額を所属する末端へ反復。原典の節は企業会計の区分であり一般会計の法定節へ変換していない。'
    else:
        note = '（消費税込み 単位：円）。区分の項を一行とし、款の原典値を区分_款_補助列へ反復する。予算額の各欄と決算額・繰越額・不用額、備考うち仮払消費税は独立した原典の欄である。'
        budget_columns = {c.name for c in (CAPITAL_LEFT if capital else REVENUE_LEFT) if c.name != '区分'}
        budget_columns |= {'合計', '継続費逓次繰越額'}
        if not capital:
            budget_columns |= {'小計', '地方公営企業法第26条第２項の規定による繰越額'}
        for k in rows[0]:
            base = k.removeprefix('区分_款_')
            if base in (*POSITION_COLUMNS, '右物理頁', '右印刷頁') or k in ('区分_款', '区分_項'):
                continue
            path = ['翌年度繰越額'] if base.startswith('翌年度繰越額_') else ['備考'] if base.startswith('備考_') else ['予算額'] if base in budget_columns else []
            grain = ['区分_款'] if k.startswith('区分_款_') else ['区分_款', '区分_項']
            contexts.append({'columns': [k], 'header_path': path, 'grain_columns': grain})
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': amounts}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}}], 'column_contexts': contexts}


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Enterprise statement requires one selected original')
    source = inputs[0]
    if source['format'] != 'pdf' or source['direction'] != 'expenditure' or source['target']['jurisdiction'] != '132071':
        raise ValueError('This measured layout requires Akishima PDF expenditure')
    scope = source['scope']
    if len(scope) != 1 or scope[0]['account'] != '下水道事業会計':
        raise ValueError('Measured enterprise account scope differs')
    requested = options['report_pages'] + options['revenue_expense_pages'] + options['capital_expense_pages']
    selected = [p for first, last in scope[0]['pages'] for p in range(first, last + 1)]
    if sorted(requested) != sorted(selected) or len(set(requested)) != len(requested):
        raise ValueError('Layout pages must cover the complete supplied expenditure scope exactly')
    destination = Path(destination)
    observations = destination / 'enterprise-observations'
    observations.mkdir()
    pdf, origin = source['path'], source['sha256']
    jobs = [('revenue-report', False, False, options['report_pages'][:2]),
            ('capital-report', False, True, options['report_pages'][2:]),
            ('revenue-detail', True, False, options['revenue_expense_pages']),
            ('capital-detail', True, True, options['capital_expense_pages'])]
    result = {}
    for suffix, is_detail, capital, pages in jobs:
        rows, observed = detail(pdf, pages, origin, observations) if is_detail else report(pdf, pages, origin, observations, capital)
        table_id = options['table_prefix'] + '-' + suffix
        (observations / (suffix + '.json')).write_text(json.dumps(observed, ensure_ascii=False, indent=2) + '\n')
        columns = tuple(ParquetColumn(k, 'BIGINT' if k.endswith('物理頁') else 'DOUBLE' if k.endswith(('上端', '下端')) else 'VARCHAR') for k in rows[0])
        info = write_conversion(destination / (table_id + '.parquet'), rows, columns=columns,
                                context=ConversionContext(origin, table_id, __file__))
        result[table_id] = {'path': Path(info.path), 'metadata': metadata(rows, is_detail, capital)}
    return result
