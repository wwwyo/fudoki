"""Observe monetary-table cell membership from original vector ruling lines."""
from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

FLOAT = r'[-+\d.eE]+'
SEGMENT = re.compile(r'M\s+(' + FLOAT + r')\s+(' + FLOAT + r')\s+L\s+(' + FLOAT + r')\s+(' + FLOAT + r')')


def segments(svg: Path) -> tuple[list[tuple], list[tuple]]:
    vertical, horizontal = [], []
    for element in ET.parse(svg).getroot().iter():
        if not element.tag.endswith('path') or element.get('fill') != 'none':
            continue
        transform = re.search(r'matrix\(([^)]+)\)', element.get('transform', ''))
        matrix = [float(n) for n in re.split(r'[,\s]+', transform[1].strip())] if transform else [1, 0, 0, 1, 0, 0]
        a, b, c, d, e, f = matrix
        for match in SEGMENT.finditer(element.get('d', '')):
            x, y, x2, y2 = map(float, match.groups())
            x, y, x2, y2 = a*x+c*y+e, b*x+d*y+f, a*x2+c*y2+e, b*x2+d*y2+f
            if abs(x-x2) < .2:
                vertical.append(((x+x2)/2, min(y, y2), max(y, y2)))
            elif abs(y-y2) < .2:
                horizontal.append(((y+y2)/2, min(x, x2), max(x, x2)))
    return vertical, horizontal


def observe_cells(pdf: Path, observation: dict, output: Path) -> list[dict]:
    result = []
    for page_number in sorted({h['page'] for h in observation['monetary_table_headers'] if h['page'] != 112}):
        svg = output / f'cells-{page_number}.svg'
        subprocess.run(['pdftocairo', '-f', str(page_number), '-l', str(page_number), '-svg', str(pdf), str(svg)], check=True)
        vertical, horizontal = segments(svg)
        page = next(p for p in observation['pages'] if p['page'] == page_number)
        for header in [h for h in observation['monetary_table_headers'] if h['page'] == page_number]:
            header_words = sorted([w for w in page['words'] if header['pane']+20 < w['x0'] < header['pane']+524
                                   and abs(w['y1']-(header['y']+9)) < 2], key=lambda w: w['x0'])
            xs = sorted({round(x, 1) for x, lo, hi in vertical if lo-.5 < header['y']+4 < hi+.5
                         and header['pane']+20 < x < header['pane']+524})
            fields = []
            for lo, hi in zip(xs, xs[1:]):
                words = [w for w in header_words if lo-.5 < (w['x0']+w['x1'])/2 < hi+.5]
                name = ''.join(w['text'] for w in words).replace(' ', '')
                if name:
                    fields.append((name, lo, hi))
            for money in [r for r in observation['monetary_rows'] if r['page'] == page_number
                          and r['table_y'] == header['y'] and not r['is_total']]:
                money_y = money['y']+4.5
                money_field = next(f for f in fields if f[0] == header.get('amount_header', '金額'))
                money_center = (money_field[1]+money_field[2])/2
                money_cuts = sorted({round(yy, 1) for yy, lo, hi in horizontal if lo-.5 < money_center < hi+.5})
                money_top = max(yy for yy in money_cuts if yy < money_y)
                money_bottom = min(yy for yy in money_cuts if yy > money_y)
                row_cuts = sorted({money_top, money_bottom} | {
                    round(yy, 1) for yy, lo, hi in horizontal
                    if money_top < yy < money_bottom and any(
                        field != money_field[0] and lo-.5 < (left+right)/2 < hi+.5
                        for field, left, right in fields)})
                for row_top, row_bottom in zip(row_cuts, row_cuts[1:]):
                    y = (row_top+row_bottom)/2
                    values, cell_boxes = {}, {}
                    for field, lo_x, hi_x in fields:
                        cuts = sorted({round(x, 1) for x, lo, hi in vertical if lo-.5 < y < hi+.5
                                       and lo_x-.5 <= x <= hi_x+.5})
                        collected, boxes = {}, []
                        for left, right in zip(cuts, cuts[1:]):
                            center = (left+right)/2
                            ys = sorted({round(yy, 1) for yy, lo, hi in horizontal if lo-.5 < center < hi+.5})
                            above = [yy for yy in ys if yy < y]
                            below = [yy for yy in ys if yy > y]
                            if not above or not below:
                                continue
                            top, bottom = max(above), min(below)
                            boxes.append([left, top, right, bottom])
                            for index, word in enumerate(page['words']):
                                if left-.5 < (word['x0']+word['x1'])/2 < right+.5 and top-.5 < (word['y0']+word['y1'])/2 < bottom+.5:
                                    # The benefit tables print the column unit
                                    # inside the first ruled body cell, above
                                    # the first data baseline; it is a header
                                    # fact rather than part of the leaf value.
                                    if header.get('amount_header') == '給付額' and word['text'] in ('円', '件'):
                                        continue
                                    collected[index] = word
                        values[field] = ''.join(w['text'] for w in sorted(collected.values(), key=lambda w:(w['y0'],w['x0'])))
                        cell_boxes[field] = boxes
                    result.append({'page': page_number, 'y': money['y'], 'amount': money['amount'],
                                   'fields': values, 'boxes': cell_boxes, 'row_bounds': [row_top, row_bottom]})
    (output / 'cells.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result
