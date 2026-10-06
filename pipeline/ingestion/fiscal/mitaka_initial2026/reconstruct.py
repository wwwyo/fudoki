"""Native occurrence observations for the fixed FY2026 book (2).

Numeric spans are on the original layout line, not indexes in the legacy
integer payload. A numeric token is money only with a printed currency or
monetary column context; unresolved tokens remain explicit unknowns. Native
word geometry is read from the original PDF on every extraction.
"""
import hashlib, json, re, subprocess, xml.etree.ElementTree as ET
from pathlib import Path
DIRECTORY = Path(__file__).resolve().parent
F25 = ['source_key','fiscal_year','document_kind','account','amendment','direction',
 'row_type','grain','name','printed_text','printed_amounts','amount_semantics','phase',
 'page','line','indent','col_context','table_index','section','sec_i','ordinal',
 'kan_amount','row_label','cells','extra']
GRAIN = {'kou':'kou','kan':'kan','total':'total','ordinance_total':'total'}
ZEN = str.maketrans('０１２３４５６７８９','0123456789')
NUMBER = r'(?:[△▲−-]\s*)?\d[\d,，]*(?:[.．]\d+)?'
TOKEN = re.compile(NUMBER)
SPACE = re.compile(r'\s')
NS = {'x':'http://www.w3.org/1999/xhtml'}


def compact(text):
    return SPACE.sub('', text).translate(ZEN)


def value(text):
    v=compact(text).replace('，',',').replace('．','.').replace(',','')
    v=v.replace('△','-').replace('▲','-').replace('−','-')
    return v if '.' in v else int(v)


def config():
    return json.loads((DIRECTORY/'config.json').read_bytes())


def verify_origin(c, objects):
    e=c['edition']
    for p in [Path(objects)/'inputs/origin/sha256'/e['sha256'], Path(objects)/e['sha256']]:
        if p.exists():
            body=p.read_bytes()
            if hashlib.sha256(body).hexdigest()!=e['sha256'] or len(body)!=e['bytes']:
                raise ValueError('origin identity differs')
            return p
    raise FileNotFoundError(e['sha256'])


def native_groups(pdf):
    body=subprocess.run(['pdftotext','-bbox-layout',str(pdf),'-'],check=True,capture_output=True).stdout
    pages=ET.fromstring(body).findall('.//x:page',NS)
    result={}
    for pno,page in enumerate(pages,1):
        groups=[]
        for index,w in enumerate(page.findall('.//x:word',NS)):
            bbox=[float(w.get(n)) for n in ['xMin','yMin','xMax','yMax']]
            y=(bbox[1]+bbox[3])/2
            group=next((g for g in groups if abs(g['y']-y)<2),None)
            if group is None:
                group={'y':y,'words':[]};groups.append(group)
            group['words'].append({'index':index,'text':w.text or '', 'bbox':bbox})
        for g in groups:
            g['words'].sort(key=lambda w:w['bbox'][0])
            chars=[];owners=[]
            for w in g['words']:
                part=compact(w['text']);chars.extend(part);owners.extend([w]*len(part))
            g.update(text=''.join(chars),owners=owners)
        result[pno]=sorted(groups,key=lambda g:g['y'])
    return result


def locate(text, groups, after_y):
    key=compact(text)
    matches=[g for g in groups if g['text']==key and g['y']>after_y]
    if matches:return matches[0], 'exact-row'
    # Some PDF overprinted labels or separately aligned multi-line cells do
    # not reconstruct the same row. They are not guessed into monetary cells.
    return None, 'unresolved-row'


def occurrence_bbox(text, span, group):
    if group is None:return None
    a=len(compact(text[:span[0]]));b=len(compact(text[:span[1]]))
    words={w['index']:w for w in group['owners'][a:b]}
    if not words:return None
    boxes=[w['bbox'] for w in words.values()]
    return {'bbox_pdf_points':[min(b[0] for b in boxes),min(b[1] for b in boxes),
                              max(b[2] for b in boxes),max(b[3] for b in boxes)],
            'native_word_indices':list(words)}


def layout_native_correspondence(lines, groups):
    """Exact-text occurrence bijection, bounded by unique neighboring rows.

    Repeats are paired in layout/native vertical order only when the whole
    text has equal occurrence counts and unique preceding/following anchors
    support the candidate. Missing counts/anchors or crossed anchors remain
    unresolved; no page/row/value override is used.
    """
    layout_by_text = {}
    native_by_text = {}
    for n, line in enumerate(lines, 1):
        key = compact(line)
        if key:
            layout_by_text.setdefault(key, []).append(n)
    for group in groups:
        native_by_text.setdefault(group['text'], []).append(group)
    for matches in native_by_text.values():
        matches.sort(key=lambda group: group['y'])
    anchors = {}
    for text, positions in layout_by_text.items():
        matches = native_by_text.get(text, [])
        if len(positions) == len(matches) == 1:
            anchors[positions[0]] = matches[0]['y']
    anchor_lines = sorted(anchors)
    result = {}
    for text, positions in layout_by_text.items():
        matches = native_by_text.get(text, [])
        for index, line in enumerate(positions):
            item = {'group': None, 'status': 'unresolved-occurrence-count',
                    'layout_occurrence': index,
                    'native_candidate_count': len(matches)}
            if len(positions) == len(matches) == 1:
                item.update(group=matches[0], status='exact-unique-row')
            elif len(positions) == len(matches) and matches:
                previous = [n for n in anchor_lines if n < line]
                following = [n for n in anchor_lines if n > line]
                item['status'] = 'unresolved-order-context'
                ordered = all(a['y'] < b['y'] for a, b in zip(matches, matches[1:]))
                if previous and following and ordered:
                    low, high = anchors[previous[-1]], anchors[following[0]]
                    candidate = matches[index]
                    if low < candidate['y'] < high:
                        item.update(group=candidate,
                                    status='exact-ordered-occurrence')
            result[line] = item
    return result


def page_context(lines, groups):
    bindings = layout_native_correspondence(lines, groups)
    headers = []
    for n, line in enumerate(lines, 1):
        text = line.strip()
        s = compact(text)
        if (re.search(r'単位|金額|予定額|予算額|限度額|構成比|利率|職員数|年間支給率', s)
            or '本年度' in s and '前年度' in s
            or re.fullmatch(r'[（(]?(?:(?:千円)+|[%％])[）)]?', s)):
            binding = bindings[n]
            group = binding['group']
            header = {'line': n, 'printed_text': text, 'observed_columns': [],
                      'native_mapping_status': binding['status'],
                      'layout_occurrence': binding['layout_occurrence'],
                      'native_candidate_count': binding['native_candidate_count'],
                      'native_row_y': group['y'] if group is not None else None}
            # Compact indices are distinct from spans in the retained printed text.
            positions = [i for i, char in enumerate(text) if not char.isspace()]
            for label in ['金額', '予定額', '予算額', '限度額', '本年度', '前年度',
                          '比較', '構成比', '利率', '職員数', '年間支給率', '千円', '％']:
                for occurrence, match in enumerate(re.finditer(re.escape(label), s)):
                    start, end = match.span()
                    column = {'printed_label': label, 'occurrence': occurrence,
                              'span_compact': [start, end],
                              'span': [positions[start], positions[end - 1] + 1],
                              'native_mapping_status': binding['status'],
                              'bbox_pdf_points': None, 'native_word_indices': []}
                    if group is not None:
                        words = {w['index']: w for w in group['owners'][start:end]}
                        boxes = [w['bbox'] for w in words.values()]
                        if boxes:
                            column.update(
                                bbox_pdf_points=[min(b[0] for b in boxes),
                                                 min(b[1] for b in boxes),
                                                 max(b[2] for b in boxes),
                                                 max(b[3] for b in boxes)],
                                native_word_indices=list(words))
                    header['observed_columns'].append(column)
            headers.append(header)
    return headers

def separate_monthly_description_cell(text, end, group, geometry, row, headers):
    """A monetary 金額 cell ends before a distinct native 月額 description cell.

    This uses native WORD positions and the printed 金額 header, not row ids,
    a numeric threshold, or the presence of a monetary page elsewhere.
    """
    label = re.match(r'\s*(月額)', text[end:])
    if label is None or geometry is None or group is None:
        return False
    start = end + label.start(1)
    description = occurrence_bbox(text, (start, end + label.end(1)), group)
    if description is None:
        return False
    amount_box = geometry['bbox_pdf_points']
    description_box = description['bbox_pdf_points']
    for h in reversed([h for h in headers if h['line'] < row['line']]):
        for c in h['observed_columns']:
            if c['printed_label'] != '金額':
                continue
            header_box = c['bbox_pdf_points']
            if header_box is None:
                continue  # unresolved printed header does not establish a money cell
            return (header_box[0] <= amount_box[0]
                    and amount_box[2] < description_box[0]
                    and header_box[2] < description_box[0])
    return False


def printed_account_sections(pages):
    """Read split printed cover/header titles before any retained numeric row."""
    sections = {}; current = None
    for pno, page in enumerate(pages, 1):
        lines = page.splitlines()[:5]
        title = compact(''.join(lines))
        match = re.search(r'三鷹市(?:の)?([^。]{1,40}?会計)(?:の)?予算', title)
        if match:
            current = {'account': match.group(1), 'physical_page': pno,
                       'original_title_lines': lines}
        if current is not None:
            sections[pno] = current
    return sections


def classify(text, match, row, headers, geometry, following_line, group):
    start,end=match.span();pre,post=text[:start],text[end:];n=value(match.group())
    if re.fullmatch(r'-\d+-',compact(text)):
        return 'page_label','printed-footer',None
    if not pre.strip() and re.match(r'\s*歳\s*[入出]\s*$', post):
        return 'ordinal', 'printed-section-heading', None
    if re.search(r'第\s*$', pre) and re.match(r'\s*号', post):
        return 'ordinal', 'printed-numbered-category', None
    if not pre.strip() and re.match(r'\s*の\s*' + NUMBER + r'\s*[%％]', post):
        return 'unknown', 'printed-calculation-base-role-unconfirmed', None
    if separate_monthly_description_cell(text, end, group, geometry, row, headers):
        unit = '千円' if any('千円' in compact(h['printed_text'])
                          for h in headers if h['line'] < row['line']) else None
        return 'amount', 'printed-money-cell-before-separate-monthly-label', unit
    for m in re.finditer(NUMBER+r'\s*[～〜~]\s*'+NUMBER+r'\s*(年|月|日|歳|[%％])',text.translate(ZEN)):
        if m.start()<=start<end<=m.end():
            return ('rate' if m.group(1) in ['%','％'] else 'period'), 'printed-range-unit',None
    if re.match(r'\s*[%％]',post):return 'rate','inline-percent',None
    if re.match(r'\s*(年度|年|ヶ月|か月|ヵ月|月|日|歳)',post):return 'period','inline-period',None
    if re.match(r'\s*[人名件台個戸軒]',post):return 'count','inline-count',None
    if re.search(r'(?:第|条の)\s*$',pre) or re.match(r'\s*[条章]',post):
        return ('ordinal' if re.match(r'\s*[款項目表]',post) else 'article'),'printed-numbered-reference',None
    if re.match(r'\s*[款項目表号級]',post):return 'ordinal','printed-numbered-reference',None
    if re.match(r'[.．](?!\d)',post):return 'ordinal','printed-number-separator',None
    if re.search(r'[（(]\s*$',pre) and re.match(r'\s*[）)]',post):
        return 'ordinal','parenthesized-number',None
    if re.match(r'\s*(千円|円)',post) or (re.match(r'\s*千$',post) and following_line.lstrip().startswith('円')):
        return 'amount','inline-currency', '千円' if re.match(r'\s*千',post) else '円'
    if not pre.strip() and isinstance(n,int) and re.match(r'\s*[^\d,，.．△▲−\s-]',post):
        return 'ordinal','numbered-heading',None
    # The decoder retains only the financial payload on these rows. Align it
    # to the final exact occurrence, NEVER to the leading article/ordinal.
    if row['type'] in ['kan','kou','ordinance_total','total']:
        tokens=list(TOKEN.finditer(text.translate(ZEN)))
        if match.span()==tokens[-1].span() and n==row['amounts'][-1]:
            return 'amount','exact-retained-payload', '千円' if any('千円' in compact(h['printed_text']) for h in headers if h['line']<row['line']) else None
    prior=[h for h in headers if h['line']<row['line']]
    htext=' '.join(compact(h['printed_text']) for h in prior)
    if isinstance(n,str):
        return ('rate' if any(v in htext for v in ['構成比','利率']) else 'unknown'),'decimal-header-context' if any(v in htext for v in ['構成比','利率']) else 'unresolved-decimal-context',None
    if geometry is None:return 'unknown','unresolved-native-row',None
    # Mixed personnel/period tables require a cell-specific mapping; a page
    # containing monetary columns is not evidence that every number is money.
    if any(s in htext for s in ['職員数','年間支給率','月分','（人）','(人)']):
        return 'unknown','mixed-quantity-columns-unresolved',None
    if any(s in htext for s in ['金額','予定額','予算額','限度額','千円']):
        return 'amount','printed-monetary-table-context','千円' if '千円' in htext else None
    return 'unknown','no-confirmed-monetary-column',None


def typed_rows(c, objects):
    from . import decoder
    pdf=verify_origin(c,objects)
    d=decoder.parse(str(pdf))
    pages=subprocess.run(['pdftotext','-layout',str(pdf),'-'],check=True,capture_output=True,text=True).stdout.split('\f')
    groups=native_groups(pdf);account_sections=printed_account_sections(pages);out=[];after={}
    for r in d['rows']:
        text=r['printed_text'];pno=r['page'];lines=pages[pno-1].splitlines()
        if lines[r['line']-1].strip()!=text:raise ValueError('layout row coordinate differs')
        headers=page_context(lines,groups[pno]);group,status=locate(text,groups[pno],after.get(pno,-1))
        if group is not None:after[pno]=group['y']
        tokens=[];amounts=[]
        for index,m in enumerate(TOKEN.finditer(text.translate(ZEN))):
            geo=occurrence_bbox(text,m.span(),group)
            cls,basis,unit=classify(text,m,r,headers,geo,lines[r['line']] if r['line']<len(lines) else '',group)
            tok={'occurrence':index,'raw_numeric':text[m.start():m.end()],
                 'span':[m.start(),m.end()],'value':value(m.group()),'class':cls,
                 'basis':basis,'unit':unit,'native_position':geo}
            tokens.append(tok)
            if cls=='amount':amounts.append(tok['value'])
        context={'physical_page':pno,'layout_line':r['line'],'native_row_mapping':status,
                 'headers':headers,'printed_account_section':account_sections.get(pno),'column_roles_status':'printed headers retained; cell/year/role linkage unconfirmed'}
        out.append({'source_key':c['source_key'],'fiscal_year':c['edition']['fiscal_year'],
          'document_kind':'budget','account':account_sections.get(pno,{}).get('account',r.get('account')),'amendment':None,
          'direction':{'exp':'expenditure','rev':'revenue'}.get(r.get('direction')),
          'row_type':r['type'],'grain':GRAIN.get(r['type']),'name':r.get('name'),
          'printed_text':text,'printed_amounts':amounts,
          'amount_semantics':{'version':2,'printed_amounts':amounts,'token_classes':tokens,
             'monetary_column_roles':'unconfirmed','unit_conversion_applied':False},
          'phase':None,'page':pno,'line':r['line'],'indent':r.get('indent'),
          'col_context':context,'table_index':None,'section':None,'sec_i':r.get('sec_i'),
          'ordinal':r.get('ordinal'),'kan_amount':None,'row_label':None,'cells':None,
          'extra':{'legacy_aux_integer_payload_used_for_money':False}})
    return out,d
