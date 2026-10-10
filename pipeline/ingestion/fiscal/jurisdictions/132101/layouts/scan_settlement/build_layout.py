"""Derive frozen scan_settlement layout for 132101 settlement-3 from frozen native.

Reads ONLY the frozen source PDF (SHA check) and frozen native-full-001.json.
Writes layout.json + corrections.json ( whitespace-in-amount only ).
Fails closed when expected structure counts differ. No OCR is started.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
CASE = Path('pipeline/ingestion/fiscal/observations/scan-2025-devin-max-2026-10-09/132101/general/settlement-3')

ORIGIN_SHA = '0b1af0ae74a6964525621308a1390afa66d735edfd2ca534de8cd64230522b3c'
NATIVE_SHA = '1a5b1394060d54a15fbf5a336f09c166a6c8201294a7be4e30c0c45f010ac68e'
SOURCE_PDF = Path('pipeline/.cache/objects/fiscal/source-selection/132101/2025/settlement-3.pdf')
NATIVE_PATH = CASE / 'native-full-001.json'

# Display-pt column boundaries, converted from design px (x_pt=px*842/3509) and
# confirmed against native token extents (each column holds its header/amounts).
LEFT_COLS = [11.0, 20.4, 30.0, 78.2, 127.7, 177.1, 221.7, 261.6, 311.0, 355.2, 404.6]
RIGHT_COLS = [446.6, 496.1, 535.9, 576.0, 615.8, 665.2, 832.7]
BIKOU_X = 665.2
AMOUNT_X = 788.0

BUDGET = ('当初予算額', '補正予算額', '継続費及び繰越事業費繰越額', '予備費支出及び流用増減', '計')
RIGHT = ('支出済額', '継続費逓次繰越', '繰越明許費', '事故繰越し', '不用額')

# Header/unit/marginalia zone: everything printed above the first body row band.
HEADER_ZONE_BOTTOM = 130.0
# Continuation body band on p2-p4 (below the 款/項/目 restatement row, above footer).
CONTINUATION_BODY = (142.0, 525.0)
# The 13 columns that carry no printed content on continuation pages.
CONTINUATION_BLANK_COLUMNS = (
    ('目名', (30.0, 78.2)),
    ('当初予算額', (78.2, 127.7)),
    ('補正予算額', (127.7, 177.1)),
    ('継続費及び繰越事業費繰越額', (177.1, 221.7)),
    ('予備費支出及び流用増減', (221.7, 261.6)),
    ('計', (261.6, 311.0)),
    ('節_区分', (311.0, 355.2)),
    ('節_金額', (355.2, 404.6)),
    ('支出済額', (446.6, 496.1)),
    ('継続費逓次繰越', (496.1, 535.9)),
    ('繰越明許費', (535.9, 576.0)),
    ('事故繰越し', (576.0, 615.8)),
    ('不用額', (615.8, 665.2)),
)
HEADER_GROUP_CELLS = (
    ('科目前項款', (11.0, 30.0)),
    ('目', (30.0, 78.2)),
    ('予算現額', (78.2, 311.0)),
    ('節', (311.0, 404.6)),
    ('翌年度繰越額', (496.1, 615.8)),
    ('備考', (665.2, 832.7)),
)
HEADER_GROUP_MEANINGS = {
    '科目前項款': '科目 (款/項/目) group header',
    '目': '科目 (款/項/目) group header',
    '予算現額': '予算現額 group header',
    '節': '節 (区分/金額) group header',
    '翌年度繰越額': '翌年度繰越額 group header',
    '備考': '備考 group header',
}

NUMBER = re.compile(r'[+\-△▲]?\s*\d[\d,\s]*\s*[）)]?\Z')
AMOUNT_INNER = re.compile(r'[+\-△▲]?\s*\d[\d,\s]*\Z')
SETSU_HEAD = re.compile(r'(\d+)\s*(.+)')
MONEY_INPUT = re.compile(r'\d+\Z')
PROJECT_DEPTS = ('職員課', '議会事務局')


def digest(path):
    with Path(path).open('rb') as fh:
        return hashlib.file_digest(fh, 'sha256').hexdigest()


def regions(page):
    return [o for o in page['regions'][0]['observations'] if o['kind'] == 'region']


def header_meaning(raw, x, y):
    """Declare the role of every printed header/unit/marginalia piece."""
    if raw == '円':
        for name, (x0, x1) in CONTINUATION_BLANK_COLUMNS[1:]:
            if x0 <= x < x1:
                return 'unit', f'unit glyph 円 for column {name}'
        if x >= BIKOU_X:
            return 'unit', 'unit glyph 円 for 備考 amount zone'
        if 30.0 <= x < 78.2:
            return 'unit', 'unit glyph 円 for 科目 zone'
        return 'unit', 'unit glyph 円'
    if raw in ('歳', '出'):
        return 'marginalia', 'direction label 歳出 (printed table furniture, not a cell value)'
    if x < 11.0 or y < 40.0:
        return 'marginalia', 'page furniture'
    if 11.0 <= x < 30.0:
        return 'header', '科目 款/項 group header'
    if 30.0 <= x < 78.2:
        return 'header', '科目 目 group header'
    for name, (x0, x1) in HEADER_GROUP_CELLS:
        if x0 <= x < x1 and y < 90.0:
            return 'header', HEADER_GROUP_MEANINGS[name]
    for name, (x0, x1) in CONTINUATION_BLANK_COLUMNS[1:]:
        if x0 <= x < x1:
            return 'header', f'{name} column header'
    if 311.0 <= x < 404.6 and y >= 90.0:
        return 'header', '節 区分/金額 column header'
    if x >= BIKOU_X:
        return 'header', '備考 column header'
    return 'header', 'table header piece'


def center(bbox):
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def cluster(tokens, tol):
    toks = sorted(tokens, key=lambda o: ((o['bbox_pdf_pt'][1] + o['bbox_pdf_pt'][3]) / 2,
                                         o['bbox_pdf_pt'][0]))
    bands = []
    for o in toks:
        y = (o['bbox_pdf_pt'][1] + o['bbox_pdf_pt'][3]) / 2
        if bands and abs(y - bands[-1][0]) < tol:
            bands[-1][1].append(o)
        else:
            bands.append([y, [o]])
    return bands


def band_box(band, pad=1.5):
    xs = [t['bbox_pdf_pt'][0] for t in band] + [t['bbox_pdf_pt'][2] for t in band]
    ys = [t['bbox_pdf_pt'][1] for t in band] + [t['bbox_pdf_pt'][3] for t in band]
    return [round(min(xs) - pad, 1), round(min(ys) - pad, 1),
            round(max(xs) + pad, 1), round(max(ys) + pad, 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True, help='layout.json destination (must not exist)')
    ap.add_argument('--corrections', required=True, help='corrections.json destination (must not exist)')
    args = ap.parse_args()
    if digest(SOURCE_PDF) != ORIGIN_SHA:
        raise ValueError('source SHA differs')
    native = json.loads(NATIVE_PATH.read_text())
    if digest(NATIVE_PATH) != NATIVE_SHA:
        raise ValueError('native SHA differs')
    pages = native['pages']
    assert [p.get('page_number') or i + 1 for i, p in enumerate(pages)] == [1, 2, 3, 4]
    for p in pages:
        assert p['displayed_pdf_size_pt'] == [842, 595]
        assert p['image_width'] == 3509 and p['image_height'] == 2480

    corrections = []

    def correct_amount(token, page_no):
        raw = token['raw_text']
        probe = raw.strip().removesuffix(')').removesuffix('）').replace('(', '').replace('C', '').strip()
        if ' ' in raw and AMOUNT_INNER.fullmatch(probe):
            after = raw.replace(' ', '')
            if after != raw:
                corrections.append({
                    'alias': f"full|{token['id']}",
                    'origin_sha256': ORIGIN_SHA,
                    'native_sha256': NATIVE_SHA,
                    'native_observation_id': token['id'],
                    'physical_page': page_no,
                    'bbox_pdf_pt': {k: v for k, v in zip(
                        ('left', 'top', 'right', 'bottom'), token['bbox_pdf_pt'])},
                    'before': raw, 'after': after,
                    'reason': 'OCR-inserted inter-digit whitespace confirmed against rendered glyphs; digits/commas/sign unchanged, never inferred from totals.',
                })
                return after
        return raw

    # ---- left table: controls + statutory sections (page 1), total (page 4)
    p1 = [o for o in regions(pages[0])
          if o['bbox_pdf_pt'][0] < 404.6 and o['bbox_pdf_pt'][1] > 125]
    kei_bands = cluster([o for o in p1
                         if LEFT_COLS[7] <= o['bbox_pdf_pt'][0] < LEFT_COLS[10]], 8)
    # merge wrapped statutory names (band without 計 amount attaches backward)
    rows = []
    for _, band in kei_bands:
        has_amount = any((LEFT_COLS[7] <= t['bbox_pdf_pt'][0] < LEFT_COLS[8]
                            or LEFT_COLS[9] <= t['bbox_pdf_pt'][0]) for t in band)
        if not has_amount and rows:
            rows[-1][1].extend(band)
        else:
            rows.append([_, band])
    if len(rows) != 17:
        raise ValueError(f'expected 3 controls + 14 statutory rows, got {len(rows)}')
    controls, statutory = [], []
    levels = ['款', '項', '目']
    for i in range(3):
        _, band = rows[i]
        labels = []
        for t in regions(pages[0]):
            ymid = (t['bbox_pdf_pt'][1] + t['bbox_pdf_pt'][3]) / 2
            if t['bbox_pdf_pt'][0] < LEFT_COLS[3] and abs(ymid - _) < 8:
                labels.append(t)
        labels.sort(key=lambda t: t['bbox_pdf_pt'][0])
        controls.append({'band_y': _, 'band': band, 'labels': labels})
    for spec_y, band in rows[3:]:
        names = sorted([t for t in band if t['bbox_pdf_pt'][0] < LEFT_COLS[9]],
                       key=lambda t: t['bbox_pdf_pt'][0])
        amounts = sorted([t for t in band if LEFT_COLS[9] <= t['bbox_pdf_pt'][0]],
                         key=lambda t: t['bbox_pdf_pt'][0])
        statutory.append({'band_y': spec_y, 'band': band, 'names': names, 'amounts': amounts})
    if len(statutory) != 14:
        raise ValueError('statutory count differs')
    sec_numbers = []
    for s in statutory:
        text = ''.join(t['raw_text'] for t in s['names']).replace(' ', '')
        m = SETSU_HEAD.match(text)
        if not m:
            raise ValueError(f'unreadable statutory label: {text}')
        sec_numbers.append(m.group(1))
    if sec_numbers != ['1', '2', '3', '4', '5', '7', '8', '9', '10', '11', '12', '13', '17', '18']:
        raise ValueError(f'statutory numbers differ: {sec_numbers}')

    def scan_money_band(page_no, band, zones):
        top = min(t['bbox_pdf_pt'][1] for t in band) - 2
        bottom = max(t['bbox_pdf_pt'][3] for t in band) + 2
        for (x0, x1) in zones:
            for t in regions(pages[page_no - 1]):
                bb = t['bbox_pdf_pt']
                if (x0 <= (bb[0] + bb[2]) / 2 < x1 and top <= (bb[1] + bb[3]) / 2 < bottom
                        and re.fullmatch(r'[+\-△▲]?\s*\d[\d,\s]*', t['raw_text'])):
                    correct_amount(t, page_no)

    MONEY_ZONES = [tuple(LEFT_COLS[i:i + 2]) for i in range(3, 9)] + \
        [tuple(RIGHT_COLS[i:i + 2]) for i in range(5)]
    for c in controls:
        scan_money_band(1, c['band'], MONEY_ZONES)
    for s in statutory:
        scan_money_band(1, s['band'], MONEY_ZONES)

    parent_controls = []
    for i, c in enumerate(controls):
        top = min(t['bbox_pdf_pt'][1] for t in c['band']) - 2
        bottom = max(t['bbox_pdf_pt'][3] for t in c['band']) + 2
        label_bb = band_box(c['labels']) if c['labels'] else band_box(c['band'])
        parent_controls.append({
            'id': f'control-{i}', 'level': levels[i], 'page': 1,
            'label_bbox': label_bb, 'row_band': [round(top, 1), round(bottom, 1)],
        })
    statutory_specs = []
    for i, s in enumerate(statutory):
        top = min(t['bbox_pdf_pt'][1] for t in s['band']) - 2
        bottom = max(t['bbox_pdf_pt'][3] for t in s['band']) + 2
        statutory_specs.append({
            'id': f'section-{i:02d}', 'order': i,
            'label_bbox': band_box(s['names']), 'amount_bbox': band_box(s['amounts']),
            'row_band': [round(top, 1), round(bottom, 1)],
            'number': sec_numbers[i],
        })

    # ---- bikou explanation nodes across pages 1-4
    nodes = []
    current_project, current_setsu = None, None
    order = 0
    for pi, page in enumerate(pages):
        page_no = pi + 1
        toks = [o for o in regions(page) if o['bbox_pdf_pt'][0] >= BIKOU_X
                and o['bbox_pdf_pt'][1] > 130 and o['bbox_pdf_pt'][3] < 548]
        bands = cluster(toks, 5)
        # forward-join amountless bands (wrapped names) into the next band
        joined = []
        pending = []
        for _, band in bands:
            band = sorted(band, key=lambda t: t['bbox_pdf_pt'][0])
            has_amount = any(t['bbox_pdf_pt'][0] >= AMOUNT_X and NUMBER.fullmatch(t['raw_text'])
                             for t in band)
            if not has_amount:
                pending.extend(band)
            else:
                joined.append(pending + band)
                pending = []
        if pending:
            raise ValueError(f'trailing amountless bikou band on page {page_no}')
        for band in joined:
            name_toks = [t for t in band if t['bbox_pdf_pt'][0] < AMOUNT_X]
            amount_toks = [t for t in band if t['bbox_pdf_pt'][0] >= AMOUNT_X
                           and NUMBER.fullmatch(t['raw_text'])]
            if len(amount_toks) != 1:
                raise ValueError(f'bikou band without exactly one amount on p{page_no}: '
                                 + '|'.join(t['raw_text'] for t in band))
            amount_tok = amount_toks[0]
            name_text = ''.join(t['raw_text'] for t in name_toks).replace(' ', '')
            is_project = any(d in name_text for d in PROJECT_DEPTS)
            m = SETSU_HEAD.match(name_text)
            # Printed setsu subtotals wrap the amount in （ ）; OCR often drops
            # the opening mark (or reads it as C), but the closing mark on the
            # amount token survives. Leaf/project amounts never carry it.
            has_paren_amount = (amount_tok['raw_text'].rstrip().endswith(')')
                                or '(' in ''.join(t['raw_text'] for t in band
                                                 if t['bbox_pdf_pt'][0] >= 760)
                                or '（' in name_text or 'C' in [t['raw_text'] for t in band])
            if is_project:
                pm = re.fullmatch(r'(\d+)\s*(.+?)\s*[（(]\s*(.+?)\s*[）)]', name_text)
                if not pm:
                    raise ValueError(f'unreadable project heading p{page_no}: {name_text}')
                node = {'id': f'project-{len([n for n in nodes if n["role"]=="project"])+1}',
                        'page': page_no, 'source_order': order, 'role': 'project',
                        'parent': None, 'number': pm.group(1), 'dept': pm.group(3)}
                current_project = node['id']
                current_setsu = None
            elif m and has_paren_amount and len(name_text) <= 14:
                node = {'id': f'setsu-{len([n for n in nodes if n["role"]=="setsu"])+1:02d}',
                        'page': page_no, 'source_order': order, 'role': 'setsu',
                        'parent': current_project, 'number': m.group(1)}
                if current_project is None:
                    raise ValueError('setsu without project context')
                current_setsu = node['id']
            else:
                if current_setsu is None:
                    raise ValueError(f'leaf without setsu context p{page_no}: {name_text}')
                node = {'id': f'leaf-{len([n for n in nodes if n["role"]=="leaf"])+1:03d}',
                        'page': page_no, 'source_order': order, 'role': 'leaf',
                        'parent': current_setsu}
            name_bb = band_box(name_toks)
            amt_bb = band_box([amount_tok])
            node.update({'name_bbox': name_bb, 'amount_bbox': amt_bb,
                         'amount_raw': amount_tok['raw_text'],
                         'amount_id': amount_tok['id']})
            correct_amount(amount_tok, page_no)
            nodes.append(node)
            order += 1
    projects = [n for n in nodes if n['role'] == 'project']
    setsus = [n for n in nodes if n['role'] == 'setsu']
    leaves = [n for n in nodes if n['role'] == 'leaf']
    if (len(projects), len(setsus), len(leaves)) != (5, 30, 75):
        raise ValueError(f'explanation counts differ: {len(projects)}/{len(setsus)}/{len(leaves)}')

    # ---- total control row (page 4)
    p4left = [o for o in regions(pages[3]) if o['bbox_pdf_pt'][0] < 404.6
              and o['bbox_pdf_pt'][1] > 500]
    total_label = [o for o in p4left if o['bbox_pdf_pt'][0] < LEFT_COLS[3]]
    if not any('歳出合計' in o['raw_text'] for o in total_label):
        raise ValueError('歳出合計 label not found on page 4')
    total_band = cluster(p4left, 8)[0][1]
    scan_money_band(4, total_band, MONEY_ZONES)
    total_top = min(t['bbox_pdf_pt'][1] for t in total_band) - 2
    total_bottom = max(t['bbox_pdf_pt'][3] for t in total_band) + 2

    # ---- continuation restatement cells (款/項/目 on p2-p4) + confirmed blanks
    control_band = parent_controls[0]['row_band']
    continuation_cells = []
    blank_cells = []
    for pi in (1, 2, 3):
        page = pages[pi]
        page_no = pi + 1
        page_regions = regions(page)
        for level_index, level in enumerate(levels):
            x0, x1 = LEFT_COLS[level_index], LEFT_COLS[level_index + 1]
            box = [x0, control_band[0], x1, control_band[1]]
            found = [o for o in page_regions if o['bbox_pdf_pt'][0] < LEFT_COLS[3]
                     and x0 <= center(o['bbox_pdf_pt'])[0] < x1
                     and control_band[0] <= center(o['bbox_pdf_pt'])[1] < control_band[1]]
            detected = [o for o in found if MONEY_INPUT.fullmatch(o['raw_text'])]
            continuation_cells.append({
                'id': f'continuation-p{page_no}-{level}', 'page': page_no, 'level': level,
                'bbox_pdf_pt': box,
                'native_observation_ids': [o['id'] for o in detected],
                'native_detected': bool(detected)})
        # every one of the 13 amount/節 columns is blank on a continuation page
        for name, (x0, x1) in CONTINUATION_BLANK_COLUMNS:
            box = [x0, CONTINUATION_BODY[0], x1, CONTINUATION_BODY[1]]
            inside = [o for o in page_regions
                      if x0 <= center(o['bbox_pdf_pt'])[0] < x1
                      and CONTINUATION_BODY[0] <= center(o['bbox_pdf_pt'])[1] < CONTINUATION_BODY[1]]
            if inside:
                raise ValueError(f'declared blank column {name} on p{page_no} holds observations: '
                                 + '|'.join(o['raw_text'] for o in inside[:5]))
            blank_cells.append({'id': f'blank-p{page_no}-{name}', 'page': page_no,
                                'column': name, 'bbox_pdf_pt': box})
    # broad rectangles are non-authoritative capture zones, kept only for audit
    broad_zones = []
    for pi in (1, 2, 3):
        page_no = pi + 1
        for name, (x0, x1) in (('left-amount-broad', (LEFT_COLS[3], LEFT_COLS[9])),
                               ('right-amount-broad', (RIGHT_COLS[0], RIGHT_COLS[5]))):
            broad_zones.append({'id': f'broad-p{page_no}-{name}', 'page': page_no,
                                'bbox_pdf_pt': [x0, 150.0, x1, 520.0],
                                'role': 'broad-capture-zone-not-a-source-cell-boundary'})
    if len(blank_cells) != 39:
        raise ValueError(f'expected 39 declared blank source cells, got {len(blank_cells)}')

    # ---- headers (14): group + column headers from native header tokens
    headers = []
    hdr = [o for o in regions(pages[0]) if o['bbox_pdf_pt'][3] <= 125]
    groups = cluster(hdr, 12)
    for i, (_, band) in enumerate(groups):
        headers.append({'id': f'header-{i:02d}', 'page': 1, 'bbox_pdf_pt': band_box(band)})

    # ---- footer running label (all pages)
    footers = []
    for pi, page in enumerate(pages):
        page_no = pi + 1
        toks = [o for o in regions(page) if o['bbox_pdf_pt'][1] > 548
                and o['bbox_pdf_pt'][0] > 700]
        if not any('議会費' in o['raw_text'] for o in toks):
            raise ValueError(f'running footer missing on page {page_no}')
        footers.append({'id': f'footer-p{page_no}', 'page': page_no,
                        'bbox_pdf_pt': band_box(toks)})

    # ---- every printed header/unit/marginalia piece, all pages (F04)
    header_pieces = []
    for pi, page in enumerate(pages):
        page_no = pi + 1
        for o in regions(page):
            bb = o['bbox_pdf_pt']
            if bb[3] > HEADER_ZONE_BOTTOM:
                continue
            x, y = center(bb)
            role, meaning = header_meaning(o['raw_text'], x, y)
            header_pieces.append({'id': f'header-piece-p{page_no}-{o["id"]}', 'page': page_no,
                                  'native_observation_id': o['id'], 'bbox_pdf_pt': list(bb),
                                  'raw_text': o['raw_text'], 'role': role, 'meaning': meaning})
    unit_pieces = [h for h in header_pieces if h['role'] == 'unit']
    marginalia_pieces = [h for h in header_pieces if h['role'] == 'marginalia']
    if not (len(header_pieces) and unit_pieces and marginalia_pieces):
        raise ValueError('header piece classification incomplete')

    layout = {
        'origin_sha256': ORIGIN_SHA,
        'physical_pages': [1, 2, 3, 4],
        'printed_pages': {'1': None, '2': None, '3': None, '4': None},
        'running_label': '1議会費',
        'page_sizes_pt': {str(i): [842, 595] for i in (1, 2, 3, 4)},
        'left_columns': LEFT_COLS,
        'right_columns': RIGHT_COLS,
        'budget_columns': [[LEFT_COLS[i], LEFT_COLS[i + 1]] for i in range(3, 8)],
        'right_amount_columns': [[RIGHT_COLS[i], RIGHT_COLS[i + 1]] for i in range(5)],
        'setsu_label_zone': [LEFT_COLS[8], LEFT_COLS[9]],
        'setsu_amount_zone': [LEFT_COLS[9], LEFT_COLS[10]],
        'bikou_amount_x': AMOUNT_X,
        'parent_controls': parent_controls,
        'statutory_sections': statutory_specs,
        'explanation_nodes': [{k: n[k] for k in ('id', 'page', 'source_order', 'role', 'parent',
                                                 'name_bbox', 'amount_bbox')}
                               for n in nodes],
        'explanation_total': {'page': 4, 'name_bbox': band_box(total_label),
                              'row_band': [round(total_top, 1), round(total_bottom, 1)]},
        'headers': headers,
        'header_pieces': header_pieces,
        'continuation_cells': continuation_cells,
        'continuations': [],
        'confirmed_blank_cells': blank_cells,
        'broad_capture_zones': broad_zones,
        'footers': footers,
        'geometry_semantics': {
            'source_cell_bbox_pdf_pt': 'independently measured original ruled-cell extent; recorded per cell in source declarations where measured',
            'capture_bbox_pdf_pt': 'converter capture ROI: native token extent plus small padding; NOT a claim of the original ruled cell boundary',
            'native_bbox_pdf_pt': 'immutable native observation extent; never padded or rewritten',
            'membership_rule': 'strict native observation center inside the declared capture ROI; no uniform tolerance (no 2pt screen, no 0-margin extent equality demand)',
            'display_transform': 'x_pt = px * 842/3509, y_pt = px * 595/2480, top-left origin; 842x595pt display of a 595x842pt MediaBox with rotation 90',
        },
        'metadata_notes': [
            '当初予算額=approved基準額、補正予算額=補正増減、継続費及び繰越事業費繰越額=当年度繰越成分、予備費支出及び流用増減=予備費/流用増減、計=adjusted（上4列の印字合計）、支出済額=executed、継続費逓次繰越/繰越明許費/事故繰越し=翌年度繰越3内訳、不用額=unused（計−支出済額、本冊限定）。繰越3列・不用額をexecutedへ加算しない。',
            '備考金額は全て支出済額段階。備考_末端金額が唯一の加算列。款項目・事業・節の反復金額は非加算の所属参照として通常列に展開。',
            '節行の（金額）は非加算小計の印字。VARCHAR金額列には括弧内側の数字列を保持し、括弧・原文・座標はbindingsに保存。事業部署列は括弧内側の名称。',
            '印字頁/印字終頁列は保持し全行NULL。本冊に印字頁番号はなく、頁脚は全頁同一の款running label「1議会費」。原典物理頁列と区別。',
            '歳出合計は非加算control。款項目所属NULL・path[]。冊内議会費の合計であり一般会計全款の総額ではない。',
            '単位は円。法定節一覧と説明の対応は番号+名称の印字対応が確認できる節に限り保持（検証可能13節＋検証不可1節=災害補償費）。',
            'NULL理由は列別: 金額列NULL=当該cellのnative未観測（unread。宣言crop観測で解消した場合はその実IDをbindingsに保持）、印字頁/印字終頁=NULL=原典に印字頁番号が存在しない。0や空欄とは別。',
            '候補002の訂正: 6セルはnative-crop-002の実観測a1–a6、継続5セルはnative-crop-003の実観測（p2/p3款・p2/p3項・p4款）をsource/native SHA・頁・bbox・実観測IDで束縛。leaf065の中点は原典限定の論理表示復元（作者Unicodeは未証明）。leaf073のnative「閱」は論理名称で「閲」へ復元（作者Unicodeは未証明、rawは不変）。予備費支出及び流用増減のnative「流用增减」は原見出し対応を宣言しrawは不変。幅（全角/半角・増/减・閲）はNFKC等で一括正規化しない。',
        ],
        'name_dictionaries': {
            'subject': 'pipeline/ingestion/lib/fiscal_subject_name_corrections.json',
            'setsu': 'pipeline/ingestion/lib/fiscal_setsu_name_corrections.json',
        },
    }
    out = Path(args.output)
    if out.exists():
        raise FileExistsError(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(layout, ensure_ascii=False, indent=2) + '\n')
    corr = Path(args.corrections)
    if corr.exists():
        raise FileExistsError(corr)
    corr.write_text(json.dumps(corrections, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'nodes': {'project': len(projects), 'setsu': len(setsus), 'leaf': len(leaves)},
                      'statutory': len(statutory_specs), 'headers': len(headers),
                      'header_pieces': len(header_pieces),
                      'unit_pieces': len(unit_pieces),
                      'marginalia_pieces': len(marginalia_pieces),
                      'continuation_cells': len(continuation_cells),
                      'blank_cells': len(blank_cells),
                      'corrections': len(corrections), 'layout': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
