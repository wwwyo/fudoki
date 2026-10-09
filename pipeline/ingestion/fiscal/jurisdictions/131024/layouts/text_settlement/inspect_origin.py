"""Independently observe Chuo's printed settlement controls and text positions.

No conversion module is imported. Observations are local, reproducible inspection
inputs rather than fiscal raw tables.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {'h': 'http://www.w3.org/1999/xhtml'}
MONEY = re.compile(r'^(?:△)?\d[\d,]*$')
FIELDS = ('当初予算額', '補正予算額', '繰越事業費繰越額', '予備費支出',
          '流用増減', '予算現額計', '支出済額', '翌年度繰越額', '不用額', '執行率')
BOUNDS = ((130, 198), (198, 263), (263, 328), (328, 393), (393, 458),
          (458, 524), (798, 861), (861, 924), (924, 987), (987, 1028))


def number(value: str) -> int:
    return int(re.sub(r'[\s,円]', '', value).replace('△', '-'))


def observe(pdf: Path, sha: str, output: Path, pages_range=(96, 163), reserve_page=163,
            personnel_breakdown=False, terminal_sections=False) -> dict:
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != sha:
        raise ValueError('Origin SHA mismatch')
    output.mkdir(parents=True, exist_ok=False)
    xml = output / 'origin.xml'
    start, end = pages_range
    subprocess.run(['pdftotext', '-f', str(start), '-l', str(end), '-bbox-layout', str(pdf), str(xml)], check=True)
    original = xml.read_bytes()
    # InDesign embeds backspace / substitute control characters. Retain the
    # original byte observation; strip XML-illegal controls only for parsing.
    clean = re.sub(rb'[\x00-\x08\x0b\x0c\x0e-\x1f]', b'', original)
    root = ET.fromstring(clean)
    pages, controls, sections, anomalies = [], [], [], []
    context = {}
    for index, page in enumerate(root.findall('.//h:page', NS), start):
        words = [{'text': w.text or '', 'x0': float(w.get('xMin')), 'x1': float(w.get('xMax')),
                  'y0': float(w.get('yMin')), 'y1': float(w.get('yMax'))}
                 for w in page.findall('.//h:word', NS)]
        words.sort(key=lambda w: (w['y0'], w['x0']))
        lines = []
        for word in words:
            # Poppler's separate flows split visual table rows. Group their
            # baseline positions independently of its paragraph segmentation.
            match = next((line for line in reversed(lines) if abs(line['y'] - word['y0']) < 2), None)
            if match is None:
                match = {'y': word['y0'], 'words': []}
                lines.append(match)
            match['words'].append(word)
        for line in lines:
            row = sorted(line['words'], key=lambda w: w['x0'])
            # A single Poppler word straddles two ruled cells on page 127.
            # The source prints reserve transfer 0, then a negative flow amount.
            if index == 127:
                split = []
                for word in row:
                    if word['text'] == '0△' and 386 < word['x0'] < 389:
                        split.extend([{**word, 'text': '0', 'x1': word['x0'] + 4.5},
                                      {**word, 'text': '△', 'x0': 393.1}])
                    else:
                        split.append(word)
                row = split
            label = ''.join(w['text'] for w in row if w['x0'] < 130)
            marker = re.search(r'（([款項目])）\s*(\d+)', label)
            is_total = label.replace(' ', '') == '歳出合計'
            if marker or is_total:
                row = sorted(row + [w for w in words if w['text'] == '△' and w not in row
                                    and abs(w['y1'] - (line['y'] + 9)) < 2], key=lambda w: w['x0'])
                level = marker[1] if marker else '合計'
                code = marker[2] if marker else None
                if marker:
                    context[level] = code
                    for child in {'款': ('項', '目'), '項': ('目',), '目': ()}[level]:
                        context.pop(child, None)
                values = {}
                for field, (lo, hi) in zip(FIELDS, BOUNDS):
                    tokens = [w['text'] for w in row if lo <= w['x0'] and w['x1'] <= hi + .8]
                    values[field] = ''.join(tokens)
                if not all(values.values()):
                    anomalies.append({'page': index, 'y': line['y'], 'kind': 'missing control cell', 'values': values})
                name = ''.join(w['text'] for w in sorted(words, key=lambda w: (w['y0'], w['x0']))
                               if 55 <= w['x0'] < 130 and abs(w['y0'] - line['y']) < 16)
                controls.append({'page': index, 'y': line['y'], 'level': level, 'code': code,
                                 'name': name, 'path': dict(context), 'values': values})
            # Right-side legal section rows have their printed number in a
            # dedicated column, unlike the left explanatory numbering.
            codes = [w for w in row if 665 < w['x0'] < 682 and re.fullmatch(r'\d+', w['text'])]
            if codes and 70 < line['y'] < 770:
                values = {}
                for field, lo, hi in [('予算現額計', 733, 799), ('支出済額', 798, 861),
                                      ('翌年度繰越額', 861, 924), ('不用額', 924, 987)]:
                    tokens = [w['text'] for w in row if lo <= w['x0'] and w['x1'] <= hi + .8 and MONEY.fullmatch(w['text'])]
                    values[field] = ''.join(tokens)
                if all(values.values()):
                    sections.append({'page': index, 'y': line['y'], 'code': codes[0]['text'],
                                     'name': ''.join(w['text'] for w in sorted(words,key=lambda w:(w['y0'],w['x0']))
                                                     if 681 <= w['x0'] < 733 and abs(w['y0']-line['y'])<8),
                                     'department': ''.join(w['text'] for w in sorted(words,key=lambda w:(w['y0'],w['x0']))
                                                           if 400 < w['x0'] < 524 and abs(w['y0']-line['y'])<8),
                                     'path': dict(context), 'values': values})
        pages.append({'page': index, 'width': float(page.get('width')), 'height': float(page.get('height')),
                      'words': words})
    construction_tables = []
    monetary_headers = []
    active = None
    for page in pages:
        for pane in (0, 646):
            pane_words = [w for w in page['words'] if pane + 20 < w['x0'] < pane + 524 and 55 < w['y0'] < 780]
            pane_lines = []
            for word in pane_words:
                line = next((q for q in pane_lines if abs(q['bottom'] - word['y1']) < 2), None)
                if line is None:
                    line = {'bottom': word['y1'], 'words': []}
                    pane_lines.append(line)
                line['words'].append(word)
            for line in sorted(pane_lines, key=lambda q: q['bottom']):
                line['words'].sort(key=lambda w: w['x0'])
                text = ''.join(w['text'] for w in line['words']).replace(' ', '')
                if active is not None and re.match(r'^\(\d+\)', text):
                    active['closed'] = True
                    active['without_printed_total'] = True
                    active = None
                if text == '施工概要':
                    if active is not None:
                        anomalies.append({'kind': 'unclosed construction table', 'page': page['page']})
                    active = {'page': page['page'], 'pane': pane, 'y': line['bottom'] - 9, 'lines': []}
                    construction_tables.append(active)
                    continue
                if text.startswith('区分') and '年度' in text and active is None:
                    active = {'page': page['page'], 'pane': pane, 'y': line['bottom'] - 9,
                              'without_construction_heading': True, 'lines': []}
                    construction_tables.append(active)
                if ('金額' in text or '給付額' in text) and not text.startswith('区分金額B') and page['page'] != reserve_page:
                    monetary_headers.append({'page': page['page'], 'pane': pane, 'y': line['bottom'] - 9,
                                             'text': text, 'amount_header': '給付額' if '給付額' in text else '金額'})
                if active is not None:
                    has_amount = any(re.fullmatch(r'(?:△)?\d[\d,]*|－', w['text']) for w in line['words'])
                    if has_amount and not text.startswith('区分') and not re.match(
                            r'^(?:計|調査|設計|工事|移転|移設|事務|備品)', text):
                        active['closed'] = True
                        active['without_printed_total'] = True
                        active = None
                        continue
                    active['lines'].append({'page': page['page'], 'pane': pane, **line})
                    if re.match(r'^計[\d,－△円]+$', text):
                        active['closed'] = True
                        active = None
    if active is not None:
        anomalies.append({'kind': 'unclosed construction table at scope end', 'page': active['page']})
    annual_rows = []
    for table in construction_tables:
        headers = []
        for line in table['lines']:
            row_words = line['words']
            text = ''.join(w['text'] for w in row_words).replace(' ', '')
            if text.startswith('区分') and '年度' in text:
                group = []
                for word in row_words:
                    if '令和' in word['text'] or '平成' in word['text'] or group:
                        group.append(word)
                    if group and '年度' in word['text']:
                        headers.append({'name': ''.join(w['text'] for w in group).replace(' ', ''),
                                        'x': word['x1'] - line['pane']})
                        group = []
                    if not group and word['text'] == '計':
                        headers.append({'name': '計', 'x': word['x1'] - line['pane']})
                continue
            if not headers:
                continue
            amount_words = [w for w in row_words if re.fullmatch(r'(?:△)?\d[\d,]*|－', w['text'])]
            if not amount_words:
                continue
            first_amount_x = min(w['x0'] for w in amount_words)
            label_words = [w for w in row_words if w['x0'] < first_amount_x and w not in amount_words
                           and w['text'] != '円']
            label = ''.join(w['text'] for w in label_words).replace(' ', '')
            values = {}
            for word in amount_words:
                header = min(headers, key=lambda h: abs(h['x'] - (word['x1'] - line['pane'])))
                values[header['name']] = word['text']
            if label:
                annual_rows.append({'table_page': table['page'], 'table_y': table['y'], 'page': line['page'],
                                    'pane': line['pane'], 'y': line['bottom'] - 9, 'name': label, 'values': values,
                                    'is_total': label == '計'})
    monetary_rows = []
    for header in monetary_headers:
        words = [w for w in next(p['words'] for p in pages if p['page'] == header['page'])
                 if header['pane'] + 20 < w['x0'] < header['pane'] + 524]
        line_words = [w for w in words if abs(w['y1'] - (header['y'] + 9)) < 2]
        amount_header = header.get('amount_header', '金額')
        money_start = min(w['x0'] for w in line_words if w['text'] == amount_header[0])
        money_end = max(w['x1'] for w in line_words if w['text'] == '額')
        money_middle = (money_start + money_end) / 2
        candidates = [w for w in words if re.fullmatch(r'\d[\d,]*', w['text'])
                      and w['x1'] >= money_middle and w['x1'] <= money_end + 45
                      and header['y'] + 10 < w['y0'] < 780]
        for word in sorted(candidates, key=lambda w: w['y0']):
            row_words = sorted([w for w in words if abs(w['y1'] - word['y1']) < 2], key=lambda w: w['x0'])
            row_text = ''.join(w['text'] for w in row_words).replace(' ', '')
            if re.match(r'^\(\d+\)', row_text) or (row_words and row_words[-1]['text'] == '円'):
                break
            labels = ''.join(w['text'] for w in row_words if w['x0'] < money_start
                             and not re.fullmatch(r'\d[\d,]*', w['text'])).replace(' ', '')
            total = labels == '計' or labels.startswith('計')
            monetary_rows.append({'page': header['page'], 'pane': header['pane'], 'table_y': header['y'],
                                  'y': word['y0'], 'amount': word['text'], 'x0': word['x0'], 'x1': word['x1'],
                                  'is_total': total, 'line_text': row_text,
                                  'unit': '千円' if header['page'] == 112 else '円', 'amount_header': amount_header})
            if total:
                break
    observation = {'sha256': sha, 'page_range': [start, end], 'reserve_page': reserve_page,
                   'pages': pages, 'controls': controls, 'sections': sections,
                   'construction_tables': construction_tables,
                   'annual_rows': annual_rows, 'monetary_table_headers': monetary_headers,
                   'monetary_rows': monetary_rows,
                   'anomalies': anomalies, 'xml_illegal_controls': len(original) - len(clean)}
    if personnel_breakdown:
        personnel = []
        for page in pages:
            lines = []
            for word in page['words']:
                if not (20 < word['x0'] < 524 and 100 < word['y0'] < 780):
                    continue
                line = next((q for q in reversed(lines) if abs(q['bottom']-word['y1']) < 1), None)
                if line is None:
                    line = {'bottom': word['y1'], 'words': []}
                    lines.append(line)
                line['words'].append(word)
            active = False
            for line in sorted(lines, key=lambda q: q['bottom']):
                words = sorted(line['words'], key=lambda w: w['x0'])
                compact = re.sub(r'\s+', '', ''.join(w['text'] for w in words))
                if '職員の給与費' in compact and '円' in compact:
                    active = True
                    continue
                if not active:
                    continue
                left = [w for w in words if w['x0'] < 310]
                count = next((i for i,w in enumerate(left) if re.match(r'^\d+',w['text'])), None)
                if count is None:
                    continue
                label = ''.join(w['text'] for w in left[:count])
                value = ''.join(w['text'] for w in left[count:])
                if not re.fullmatch(r'\d[\d,]*人(?:（[^）]+）)?', value):
                    continue
                item = max((c for c in controls if c['level']=='目' and (c['page'],c['y'])
                            < (page['page'],left[count]['y0'])),key=lambda c:(c['page'],c['y']))
                total = label.replace(' ','')=='計'
                personnel.append({'page':page['page'],'y':left[count]['y0'],'name':label,'value':value,
                                  'path':item['path'],'is_total':total})
                if total:
                    active = False
        observation['personnel_rows'] = personnel
    if terminal_sections:
        terminal = []
        ordered = sorted(controls,key=lambda c:(c['page'],c['y']))
        for index,control in enumerate(ordered):
            if control['level'] != '目':
                continue
            location=(control['page'],control['y'])
            end_location=(ordered[index+1]['page'],ordered[index+1]['y']) if index+1<len(ordered) else (end+1,0)
            explanatory_amounts=[w for page in pages for w in page['words'] if 20<w['x0']<524
                                 and location < (page['page'],w['y0']) < end_location
                                 and w['y0']>100
                                 and (page['page']!=control['page'] or w['y0']>control['y']+16)
                                 and '円' in w['text']]
            if not explanatory_amounts:
                terminal.extend(section for section in sections if section['path']==control['path'])
        observation['terminal_sections'] = terminal
    from inspect_cells import observe_cells
    observation['cell_values'] = observe_cells(pdf, observation, output)
    (output / 'observations.json').write_text(json.dumps(observation, ensure_ascii=False, indent=2))
    summary = {'pages': len(pages), 'controls': len(controls), 'sections': len(sections),
               'construction_tables': len(construction_tables),
               'annual_rows': len(annual_rows), 'monetary_table_headers': len(monetary_headers),
               'monetary_rows': len(monetary_rows),
               'anomalies': len(anomalies), 'xml_illegal_controls': observation['xml_illegal_controls']}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pages', type=int, nargs=2, default=(96, 163))
    parser.add_argument('--reserve-page', type=int, default=163)
    parser.add_argument('--personnel-breakdown', action='store_true')
    parser.add_argument('--terminal-sections', action='store_true')
    args = parser.parse_args()
    print(json.dumps(observe(args.pdf, args.sha256, args.output, args.pages, args.reserve_page,
                             args.personnel_breakdown,args.terminal_sections), ensure_ascii=False))


if __name__ == '__main__':
    main()
