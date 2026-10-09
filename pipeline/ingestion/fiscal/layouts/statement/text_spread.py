"""Build measured text-PDF observations and one raw table of scoped detail rows.

The confirmed section level in the explanation is matched within its moku.
Statutory totals and funding never become allocated detail amounts.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn
from ingestion.lib.pdf_table import (
    Box, Column, Placement, RowBand, TableLayout, TableRow, assemble_table,
    join_wrapped_rows, place_tokens, tokens_from_bbox_layout,
)


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


FIELD_KEYS = {
    'moku': {k+'_raw': k for k in ('moku','current','previous','difference','national','loan','other','general')},
    'funding': {'name_raw':'other', 'amount_raw':'other'},
    'setsu': {'code_raw':'setsu_code', 'name_raw':'setsu_name', 'amount_raw':'setsu_amount'},
    'explanation': {'name_raw':'explanation_name', 'amount_raw':'explanation_amount'},
}


def inside(box, bounds):
    left, top, right, bottom = bounds
    return left <= box.left < box.right <= right and top <= box.top < box.bottom <= bottom


def original_words(xml, pages):
    """Read the XML independently of the table-building adapter."""
    nodes = ET.fromstring(xml).findall('.//{*}page')
    if len(nodes) != len(pages):
        raise ValueError('The requested spread is incomplete')
    return {f'p{page}:w{i}': {
        'page': page, 'raw_text': ''.join(word.itertext()),
        'bbox': [float(word.attrib[k]) for k in ('xMin', 'yMin', 'xMax', 'yMax')],
    } for page, node in zip(pages, nodes, strict=True)
       for i, word in enumerate(node.findall('.//{*}word'))}


@dataclass
class Spread:
    tables: dict[str, list[dict]]
    bindings: dict[str, dict]
    profile: dict
    pages: tuple[int, int]
    origin_id: str


def build_spread(xml: bytes, *, origin_id: str, pages: tuple[int, int], profile: dict) -> Spread:
    """Build headers, context, moku, funding, statutory setsu and explanation."""
    if len(pages) != 2 or pages[1] != pages[0] + 1:
        raise ValueError('Choose two consecutive physical pages')
    tokens = tokens_from_bbox_layout(xml, origin_id=origin_id, first_page=pages[0])
    original_words(xml, pages)
    regions = {r['id']: r for r in profile['regions']}
    if len(regions) != len(profile['regions']):
        raise ValueError('Region IDs must be unique')
    headers, context, body, observations = [], [], [], []
    for t in tokens:
        is_body = profile['body_top'] <= t.bbox.y('center') < profile['body_bottom']
        matches = [r for r in regions.values() if pages[r['page_side']] == t.page and inside(t.bbox, r['bbox'])]
        if (is_body and matches) or (not is_body and len(matches) != 1):
            raise ValueError(f'Unknown/ambiguous original region: {t.id}')
        if is_body:
            body.append(t)
        observations.append({'token_id': t.id, 'page': t.page, 'raw_text': t.raw_text,
            'bbox': encoded([t.bbox.left,t.bbox.top,t.bbox.right,t.bbox.bottom]),
            'region': 'body' if is_body else matches[0]['id']})
    for r in regions.values():
        words = sorted((t for t in tokens if pages[r['page_side']] == t.page and inside(t.bbox, r['bbox'])),
                       key=lambda t: (t.bbox.top, t.bbox.left, t.id))
        text = ''.join(t.raw_text for t in words)
        if not words or (r['expected'] is not None and text != r['expected']):
            raise ValueError(f'Header/context differs: {r["id"]}, {text!r}')
        row = {'region_id': r['id'], 'parent_id': r['parent'], 'kind': r['kind'], 'raw_text': text,
            'page': pages[r['page_side']], 'bbox': encoded(r['bbox']), 'token_ids': encoded([t.id for t in words])}
        if r['kind'] in ('header','unit'):
            headers.append(row)
        else:
            printed = re.fullmatch(r'－([0-9]+)－', text) if r['kind']=='printed_page' else None
            if r['kind']=='printed_page' and printed is None:
                raise ValueError('Unrecognized printed page number')
            row['printed_page'] = int(printed.group(1)) if printed else None
            context.append(row)
    by_region = {r['region_id']: r for r in [*headers, *context]}
    if 'repeated_kan' in by_region and '第'+by_region['repeated_kan']['raw_text'] != by_region['kan']['raw_text']:
        raise ValueError('Repeated kan heading differs from the original context')
    for r in headers:
        if r['parent_id'] is not None:
            parent = by_region[r['parent_id']]
            a, b = json.loads(r['bbox']), json.loads(parent['bbox'])
            if parent['kind'] != 'header' or r['page'] != parent['page'] or not b[0] <= a[0] < a[2] <= b[2]:
                raise ValueError('Header child is outside its parent span')

    def header_path(region_id):
        r = by_region[region_id]
        return [*header_path(r['parent_id']), region_id] if r['parent_id'] else [region_id]

    bindings = {c['key']: {'header_ids': header_path(c['header']),
        'header_texts': [by_region[i]['raw_text'] for i in header_path(c['header'])],
        'component': c['component'],
        'unit': next((r['raw_text'] for r in headers if r['kind'] == 'unit' and r['parent_id'] == c['header']), None),
    } for c in profile['columns']}
    for c in profile['columns']:
        header = by_region[c['header']]
        bounds = json.loads(header['bbox'])
        if header['kind'] != 'header' or header['page'] != pages[c['page_side']] or not bounds[0] <= c['left'] < c['right'] <= bounds[2]:
            raise ValueError('Body column is outside its original header span')
    placement = {(origin_id, page): Placement('spread', offset_x=profile['right_page_offset'] * side)
                 for side, page in enumerate(pages)}
    columns = tuple(Column(c['key'], c['left'] + profile['right_page_offset'] * c['page_side'],
        c['right'] + profile['right_page_offset'] * c['page_side']) for c in profile['columns'])
    bands = tuple(RowBand(profile['body_top'] + i * profile['row_height'],
        profile['body_top'] + (i+1) * profile['row_height']) for i in range(profile['printed_rows']))
    grid = assemble_table(place_tokens(body, placement), TableLayout(columns, row_bands=bands))
    if grid.unassigned:
        raise ValueError('There are unassigned body words')
    for row in grid.rows:
        for cell in row.cells:
            col = next(c for c in profile['columns'] if c['key'] == cell.column)
            for w in cell.tokens:
                if not inside(w.token.bbox, [col['left'], bands[row.source_rows[0]-1].top,
                        col['right'], bands[row.source_rows[0]-1].bottom]):
                    raise ValueError('A word crosses its declared body cell')
    moku_starts = [row for row in grid.rows if row.cell('moku').tokens]
    if len(moku_starts) != 1 or moku_starts[0].source_rows != (1,):
        raise ValueError('This measured profile requires one moku starting in the spread')
    first = moku_starts[0]
    moku_id = f'p{pages[0]}:moku:1'
    shared = {'origin_id': origin_id, 'moku_id': moku_id,
        'kan_raw': by_region['kan']['raw_text'], 'kou_raw': by_region['kou']['raw_text']}

    def record(row_id, rows, cells, extra=None):
        return {**shared, 'row_id': row_id,
            **{field: cell.text for field, cell in cells.items()}, **(extra or {}),
            'source_rows': encoded(sorted({i for row in rows for i in row.source_rows})),
            'cell_token_ids': encoded({field: [w.token.id for w in cell.tokens] for field,cell in cells.items()}),
            'header_bindings': encoded({field: bindings[cell.column] for field,cell in cells.items()})}

    keys = ('moku','current','previous','difference','national','loan','other','general')
    moku = [record(moku_id, [first], {k+'_raw':first.cell(k) for k in keys})]
    remainder = [row for row in grid.rows[1:] if row.cell('other').tokens]
    funding = []
    if remainder:
        if len(remainder) != 2 or re.fullmatch(r'[0-9][0-9,]*', remainder[0].cell('other').text or '') or not re.fullmatch(r'[0-9][0-9,]*', remainder[1].cell('other').text or ''):
            raise ValueError('Unrecognized funding annotation; do not discard it')
        funding.append(record('funding:1', remainder, {'name_raw':remainder[0].cell('other'),
            'amount_raw':remainder[1].cell('other')}))
    setsu, active = [], []

    def close_setsu():
        if not active:
            return
        projected = [TableRow(tuple(row.cell(k) for k in
            ('setsu_code', 'setsu_name', 'setsu_amount')), row.source_rows) for row in active]
        merged = join_wrapped_rows(projected, columns=('setsu_name',))
        setsu.append(record(f'setsu:{len(setsu)+1}', active,
            {'code_raw':merged.cell('setsu_code'), 'name_raw':merged.cell('setsu_name'),
             'amount_raw':merged.cell('setsu_amount')}))
        active.clear()

    for row in grid.rows:
        code, name, amount = (row.cell(k) for k in ('setsu_code','setsu_name','setsu_amount'))
        if code.tokens:
            close_setsu()
            if not re.fullmatch(r'[0-9]{2}', code.text) or not name.tokens or not amount.tokens:
                raise ValueError('Incomplete statutory setsu')
            active.append(row)
        elif name.tokens:
            if not active or amount.tokens or row.source_rows[0] != active[-1].source_rows[-1]+1:
                raise ValueError('Unconfirmed setsu name continuation')
            active.append(row)
        elif amount.tokens:
            raise ValueError('Setsu amount without a declared category')
    close_setsu()
    explanation, stack = [], []
    tolerance = profile['geometry_tolerance']
    for row in grid.rows:
        name, amount = row.cell('explanation_name'), row.cell('explanation_amount')
        if not name.tokens and not amount.tokens:
            continue
        if not name.tokens or not amount.tokens:
            raise ValueError('Unconfirmed explanation continuation')
        left = min(w.token.bbox.left for w in name.tokens)
        right = max(w.token.bbox.right for w in amount.tokens)
        levels = [i for i, lv in enumerate(profile['explanation_levels'])
            if abs(left-lv['name_left']) <= tolerance and abs(right-lv['amount_right']) <= tolerance]
        if len(levels) != 1:
            raise ValueError('Explanation indentation and amount alignment disagree')
        depth = levels[0]
        while len(stack) > depth:
            stack.pop()['closure'] = 'closed_in_scope'
        if len(stack) != depth:
            raise ValueError('Explanation hierarchy has no observed parent')
        ident = f'explanation:{len(explanation)+1}'
        item = record(ident, [row], {'name_raw':name, 'amount_raw':amount},
            {'depth':depth, 'role':profile['explanation_levels'][depth]['name'],
             'parent_id':stack[-1]['row_id'] if stack else None, 'closure':'open_at_scope_end',
             'path_raw':encoded([n['name_raw'] for n in stack]+[name.text])})
        explanation.append(item)
        stack.append(item)
    return Spread({'headers':headers,'context':context,'moku':moku,'funding':funding,
        'setsu':setsu,'explanation':explanation,'words':observations}, bindings, profile, pages, origin_id)


def verify_spread(tables: dict[str, list[dict]], *, xml: bytes, spread: Spread) -> dict:
    """Check raw values, original word ownership and semantic separation."""
    if set(tables) != set(spread.tables):
        raise ValueError('Raw table set differs')
    for name, rows in tables.items():
        expected_fields = {field for row in spread.tables[name] for field in row}
        if any(set(row) != expected_fields for row in rows):
            raise ValueError('Raw table columns differ; target metadata and normalized fields do not belong here')
    expected = original_words(xml, spread.pages)
    words = tables['words']
    if len(words) != len(expected) or len({w['token_id'] for w in words}) != len(expected):
        raise ValueError('Original word identity/count differs')
    for w in words:
        e=expected[w['token_id']]
        if (w['page'],w['raw_text'],json.loads(w['bbox'])) != (e['page'],e['raw_text'],e['bbox']):
            raise ValueError('Original text/position differs')
    owners = Counter()
    by_region = {r['region_id']:r for t in ('headers','context') for r in tables[t]}
    if len(by_region) != len(spread.profile['regions']):
        raise ValueError('Header/context region set differs')
    for r in spread.profile['regions']:
        saved = by_region[r['id']]
        ids=json.loads(saved['token_ids'])
        region_ids = [i for i,w in expected.items() if w['page']==spread.pages[r['page_side']] and inside(Box(*w['bbox']),r['bbox'])]
        region_ids.sort(key=lambda i:(expected[i]['bbox'][1],expected[i]['bbox'][0],i))
        text=''.join(expected[i]['raw_text'] for i in region_ids)
        if (ids,saved['raw_text'],saved['parent_id'],saved['kind'],saved['page'],json.loads(saved['bbox'])) != (region_ids,text,r['parent'],r['kind'],spread.pages[r['page_side']],r['bbox']):
            raise ValueError('Header text/span/parent differs')
        if r['kind']=='printed_page' and saved['printed_page']!=int(re.fullmatch(r'－([0-9]+)－',text).group(1)):
            raise ValueError('Printed page differs')
        owners.update(ids)
    col_by_key = {c['key']:c for c in spread.profile['columns']}
    records = {r['row_id']:r for t in ('moku','funding','setsu','explanation') for r in tables[t]}
    if len(records) != sum(len(tables[t]) for t in ('moku','funding','setsu','explanation')):
        raise ValueError('Duplicate raw row ID')
    if len(tables['moku']) != 1:
        raise ValueError('Moku scope differs')
    moku_id=tables['moku'][0]['row_id']
    for table_name in ('moku','funding','setsu','explanation'):
        row_starts=[json.loads(r['source_rows'])[0] for r in tables[table_name]]
        if row_starts!=sorted(set(row_starts)):
            raise ValueError('Original row order differs')
        if table_name=='setsu' and any('parent_id' in r or 'explanation_id' in r for r in tables[table_name]):
            raise ValueError('Statutory setsu must be independent of explanation')
        for row in tables[table_name]:
            if row['origin_id']!=spread.origin_id or row['moku_id']!=moku_id or row['kan_raw']!=by_region['kan']['raw_text'] or row['kou_raw']!=by_region['kou']['raw_text']:
                raise ValueError('Inherited original context differs')
            refs=json.loads(row['cell_token_ids'])
            binding=json.loads(row['header_bindings'])
            source_rows=json.loads(row['source_rows'])
            observed_rows=set()
            if set(refs)!=set(binding) or set(refs)!=set(FIELD_KEYS[table_name]):
                raise ValueError('Cell/header fields differ')
            for field,ids in refs.items():
                key = FIELD_KEYS[table_name][field]
                if binding[field] != spread.bindings[key]:
                    raise ValueError('Original header binding differs')
                col=col_by_key[key]
                for ident in ids:
                    w=expected[ident]
                    band=next((i+1 for i in range(spread.profile['printed_rows'])
                        if inside(Box(*w['bbox']),[col['left'],spread.profile['body_top']+i*spread.profile['row_height'],col['right'],spread.profile['body_top']+(i+1)*spread.profile['row_height']])),None)
                    if w['page']!=spread.pages[col['page_side']] or band not in source_rows:
                        raise ValueError('Word assigned to the wrong original column/row')
                    observed_rows.add(band)
                ordered=sorted(ids,key=lambda i:(expected[i]['bbox'][1],expected[i]['bbox'][0],i))
                if ids!=ordered or row[field] != (''.join(expected[i]['raw_text'] for i in ordered) if ids else None):
                    raise ValueError('Raw cell text/order differs')
                owners.update(ids)
            if source_rows!=sorted(observed_rows):
                raise ValueError('Original row span differs')
            if table_name=='explanation':
                if 'setsu_id' in row or 'setsu_code_raw' in row:
                    raise ValueError('Explanation cannot inherit statutory setsu')
                depth=row['depth']; lv=spread.profile['explanation_levels'][depth]
                if abs(min(expected[i]['bbox'][0] for i in refs['name_raw'])-lv['name_left'])>spread.profile['geometry_tolerance'] or abs(max(expected[i]['bbox'][2] for i in refs['amount_raw'])-lv['amount_right'])>spread.profile['geometry_tolerance'] or row['role']!=lv['name']:
                    raise ValueError('Explanation depth differs from the original geometry')
                parent=records.get(row['parent_id'])
                preceding=[r for r in tables['explanation'] if json.loads(r['source_rows'])[0]<source_rows[0] and r['depth']<depth]
                last_parent=preceding[-1] if preceding else None
                if (depth==0 and parent is not None) or (depth>0 and (parent is None or parent!=last_parent or parent['depth']!=depth-1)):
                    raise ValueError('Wrong explanation parent')
                path=json.loads(parent['path_raw']) if parent else []
                if json.loads(row['path_raw'])!=path+[row['name_raw']]:
                    raise ValueError('Explanation path differs')
                later=[r for r in tables['explanation'] if json.loads(r['source_rows'])[0]>source_rows[0] and r['depth']<=depth]
                if row['closure']!=('closed_in_scope' if later else 'open_at_scope_end'):
                    raise ValueError('Explanation scope-end state differs')
    if owners != Counter(expected.keys()):
        raise ValueError('Missing or duplicate original word ownership')
    return {'status':'passed','original_words':len(expected),'body_words':sum(w['region']=='body' for w in words),
        'header_words':sum(len(json.loads(r['token_ids'])) for r in tables['headers']),
        'context_words':sum(len(json.loads(r['token_ids'])) for r in tables['context']),
        'tables':{k:len(v) for k,v in tables.items()},'unassigned_words':0,'duplicate_word_uses':0}


def project_raw_tables(tables):
    """Keep printed headings; represent components under a shared heading as structs."""
    result = {}
    for name, fields in FIELD_KEYS.items():
        rows = []
        for record in tables[name]:
            bindings = json.loads(record['header_bindings'])
            row = {}
            for field in fields:
                binding = bindings[field]
                label = binding['header_texts'][-1]
                component = binding['component']
                if component is None and name == 'funding':
                    component = 'name' if field == 'name_raw' else 'amount'
                if component is None:
                    if label in row:
                        raise ValueError('Ambiguous original column heading')
                    row[label] = record[field]
                else:
                    key = {'code': '_code', 'name': '_text', 'amount': '_amount'}[component]
                    row.setdefault(label, {})[key] = record[field]
            row['_source_row_id'] = record['row_id']
            rows.append(row)
        result[name] = rows
    return result


def verify_raw_tables(raw_tables, *, tables, xml, spread):
    preservation = verify_spread(tables, xml=xml, spread=spread)
    if raw_tables != project_raw_tables(tables):
        raise ValueError('Original fields, headings, row order or source references differ')
    return preservation


def explanation_paths(tables):
    """Restore observed parent paths; match the confirmed section level in this layout."""
    sections = {}
    for section in tables['setsu']:
        if section['name_raw'] in sections:
            raise ValueError('Ambiguous statutory section name in this moku')
        sections[section['name_raw']] = section
    nodes = {node['row_id']: node for node in tables['explanation']}
    parents = {node['parent_id'] for node in nodes.values()}
    paths = []
    for node in nodes.values():
        if node['row_id'] in parents:
            continue
        path, active = [], node
        while active is not None:
            if active in path:
                raise ValueError('Cyclic explanation hierarchy')
            path.append(active)
            active = nodes[active['parent_id']] if active['parent_id'] else None
        path.reverse()
        section_nodes = [part for part in path if part['role'] == 'setsu']
        if len(section_nodes) > 1:
            raise ValueError('Ambiguous explanation section level')
        section = None
        if section_nodes:
            section = sections.get(section_nodes[0]['name_raw'])
            if section is None:
                raise ValueError('Explanation section is not in the observed statutory list')
        elif node['closure'] != 'open_at_scope_end':
            raise ValueError('Completed explanation detail has no observed section')
        paths.append((node, path, section))
    return paths


def raw_component_columns(tables):
    """Name scalar components without assigning new semantic names to source levels."""
    def heading(table, field):
        return json.loads(tables[table][0]['header_bindings'])[field]['header_texts'][-1]

    explanation = heading('explanation', 'name_raw')
    other = heading('moku', 'other_raw')
    levels = max(node['depth'] for node in tables['explanation']) + 1
    return {
        'explanation': [(f'{explanation}{i}_名称', f'{explanation}{i}_金額')
                        for i in range(1, levels + 1)],
        'funding': [(f'{other}_内訳{i}_名称', f'{other}_内訳{i}_金額')
                    for i in range(1, len(tables['funding']) + 1)],
    }


def assemble_raw_expenditure(tables):
    """One flat raw row per confirmed terminal explanation item.

    Parent values repeat at their original scope. Funding annotations occupy
    separate scalar columns, so they neither multiply detail rows nor allocate money.
    """
    raw = project_raw_tables(tables)
    if len(raw['moku']) != 1:
        raise ValueError('Choose the measured one-moku scope')
    source = tables['moku'][0]
    columns = raw_component_columns(tables)
    moku = {'款': source['kan_raw'], '項': source['kou_raw'],
            **{k: v for k, v in raw['moku'][0].items() if k != '_source_row_id'}}
    for names, record in zip(columns['funding'], tables['funding'], strict=True):
        moku.update(zip(names, (record['name_raw'], record['amount_raw']), strict=True))

    rows = []
    for node, path, section in explanation_paths(tables):
        if node['closure'] != 'closed_in_scope':
            continue
        row = dict(moku)
        for depth, names in enumerate(columns['explanation']):
            part = next((part for part in path if part['depth'] == depth), None)
            values = (part['name_raw'], part['amount_raw']) if part else (None, None)
            row.update(zip(names, values, strict=True))
        rows.append(row)
    if not rows:
        raise ValueError('No confirmed terminal explanation items in the requested scope')
    return rows


def raw_expenditure_schema(rows):
    """All raw components are original strings or NULL, never nested values."""
    return tuple(ParquetColumn(name) for name in rows[0])


def raw_expenditure_metadata(tables):
    """Describe source headers, units and the scope of each flattened component."""
    columns = raw_component_columns(tables)
    grain = ['款', '項', '目']
    units, contexts = [], []

    def context(table, field, names, keys, *, components=False):
        binding = json.loads(tables[table][0]['header_bindings'])[field]
        contexts.append({'columns': list(names),
                         'header_path': binding['header_texts'] if components else binding['header_texts'][:-1],
                         'grain_columns': keys})
        return binding

    for field in FIELD_KEYS['moku']:
        binding = json.loads(tables['moku'][0]['header_bindings'])[field]
        label = binding['header_texts'][-1]
        context('moku', field, [label], grain)
        if binding['unit'] is not None:
            units.append({'text': binding['unit'], 'scope': {'kind': 'columns', 'columns': [label]}})
    for table, component_names in [('explanation', columns['explanation']), ('funding', columns['funding'])]:
        for i, names in enumerate(component_names, 1):
            keys = [*grain, *[level[0] for level in component_names[:i]]] if table == 'explanation' else [*grain, names[0]]
            context(table, 'name_raw', names, keys, components=True)
            if table == 'explanation':
                roles = {n['role'] for n in tables[table] if n['depth'] == i - 1}
                if len(roles) == 1 and roles <= {'project', 'setsu'}:
                    contexts[-1]['semantic_role'] = next(iter(roles))
            binding = json.loads(tables[table][0]['header_bindings'])['amount_raw']
            if binding['unit'] is not None:
                units.append({'text': binding['unit'], 'scope': {'kind': 'columns', 'columns': [names[1]]}})
    return {'units': units, 'notes': [], 'column_contexts': contexts}


def verify_raw_expenditure(rows, *, tables, xml, spread, metadata=None):
    preservation = verify_spread(tables, xml=xml, spread=spread)
    if rows != assemble_raw_expenditure(tables):
        raise ValueError('Assembled original fields, section ownership or hierarchy differ')
    if metadata is not None:
        from ingestion.fiscal.manifest import validate_metadata
        validate_metadata(metadata, list(rows[0]))
        if metadata != raw_expenditure_metadata(tables):
            raise ValueError('Original units, header paths or grain references differ')
    return preservation


def reconcile(tables):
    """Compare independent printed amounts without changing stored raw strings."""
    def number(text):
        if not isinstance(text,str) or not re.fullmatch(r'-?[0-9][0-9,]*',text):
            raise ValueError('Unsupported printed amount for reconciliation')
        return Decimal(text.replace(',',''))
    checks=[]
    def compare(kind, ident, observed, total):
        checks.append({'kind':kind,'row_id':ident,'status':'passed' if observed==total else 'mismatch',
            'printed':str(observed),'computed':str(total)})
    m=tables['moku'][0]
    compare('year_difference',m['row_id'],number(m['difference_raw']),number(m['current_raw'])-number(m['previous_raw']))
    compare('funding_total',m['row_id'],number(m['current_raw']),sum(number(m[k]) for k in ('national_raw','loan_raw','other_raw','general_raw') if m[k] is not None))
    compare('statutory_setsu_total',m['row_id'],number(m['current_raw']),sum(number(r['amount_raw']) for r in tables['setsu']))
    for f in tables['funding']:
        compare('funding_breakdown',f['row_id'],number(m['other_raw']),number(f['amount_raw']))
    for node in tables['explanation']:
        children=[r for r in tables['explanation'] if r['parent_id']==node['row_id']]
        if node['closure']=='open_at_scope_end':
            checks.append({'kind':'explanation_children','row_id':node['row_id'],'status':'deferred_scope_end'})
        elif children:
            compare('explanation_children',node['row_id'],number(node['amount_raw']),sum(number(c['amount_raw']) for c in children))
    return checks


def schema(table, rows):
    fixed={'headers':('region_id','parent_id','kind','raw_text','page','bbox','token_ids'),
        'context':('region_id','parent_id','kind','raw_text','page','bbox','token_ids'),
        'words':('token_id','page','raw_text','bbox','region')}
    empty_funding=('origin_id','moku_id','kan_raw','kou_raw','row_id','name_raw','amount_raw','source_rows','cell_token_ids','header_bindings')
    names=tuple(rows[0]) if rows else fixed.get(table,empty_funding)
    return tuple(ParquetColumn(n,'INTEGER' if n in ('page','printed_page','depth') else 'VARCHAR') for n in names)


def read_tables(destination, names):
    import duckdb
    result={}
    with duckdb.connect(config={'threads':1}) as c:
        for name in names:
            cursor=c.execute('SELECT * FROM read_parquet(?, hive_partitioning=false)',[str(destination/f'{name}.parquet')])
            fields=[v[0] for v in cursor.description]
            result[name]=[dict(zip(fields,row,strict=True)) for row in cursor.fetchall()]
    return result


def convert_spread(source: Path, destination: Path, *, origin_sha256: str,
                   profile_path: Path, pages: tuple[int,int]) -> dict:
    """Convert a supplied spread and verify all saved raw tables."""
    def digest():
        with source.open('rb') as f:
            return hashlib.file_digest(f,'sha256').hexdigest()
    if digest()!=origin_sha256:
        raise ValueError('Original SHA differs')
    destination.mkdir(parents=True,exist_ok=False)
    xml_path=destination/'words.xhtml'
    subprocess.run(['pdftotext','-f',str(pages[0]),'-l',str(pages[1]),'-bbox-layout',str(source),str(xml_path)],check=True)
    xml=xml_path.read_bytes()
    spread=build_spread(xml,origin_id=origin_sha256,pages=pages,profile=json.loads(profile_path.read_text()))
    verify_spread(spread.tables,xml=xml,spread=spread)
    results={}
    raw_result=None
    try:
        for name,rows in spread.tables.items():
            context=ConversionContext(origin_sha256,f'spread-{pages[0]}-{pages[1]}-{name}',
                'ingestion.fiscal.layouts.statement.text_spread',layout_ref=str(profile_path))
            results[name]=write_conversion(destination/f'{name}.parquet',rows,columns=schema(name,rows),context=context)
        saved=read_tables(destination,spread.tables)
        checks=verify_spread(saved,xml=xml,spread=spread)
        amounts=reconcile(saved)
        rows=assemble_raw_expenditure(saved)
        metadata=raw_expenditure_metadata(saved)
        raw_result=write_conversion(destination/'expenditure.parquet',rows,
            columns=raw_expenditure_schema(rows),context=ConversionContext(
                origin_sha256,f'spread-{pages[0]}-{pages[1]}-expenditure',
                'ingestion.fiscal.layouts.statement.text_spread',layout_ref=str(profile_path)))
        readback=read_tables(destination,('expenditure',))['expenditure']
        raw_checks=verify_raw_expenditure(readback,tables=saved,xml=xml,spread=spread,metadata=metadata)
        if digest()!=origin_sha256:
            raise ValueError('Original changed during conversion')
    except BaseException:
        for result in results.values():
            Path(result.path).unlink(missing_ok=True)
        if raw_result is not None:
            Path(raw_result.path).unlink(missing_ok=True)
        raise
    report={'scope':{'pages':list(pages),'current_selection_adopted':False},'preservation':checks,
        'reconciliation':amounts,'conversion':{name:asdict(r) for name,r in results.items()},
        'raw':{'conversion':asdict(raw_result),'metadata':metadata,'preservation':raw_checks,
            'pending_terminal_items':[{'source_row_id':node['row_id'],'text':node['name_raw'],
                'amount':node['amount_raw'],'reason':node['closure']}
                for node,path,section in explanation_paths(saved) if node['closure']!='closed_in_scope']}}
    (destination/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--profile',type=Path,required=True)
    p.add_argument('--pages',type=int,nargs=2,required=True)
    p.add_argument('--origin-sha256',required=True)
    a=p.parse_args()
    report=convert_spread(a.source,a.output,origin_sha256=a.origin_sha256,profile_path=a.profile,pages=tuple(a.pages))
    print(encoded(report['preservation'] | {'reconciliation':dict(Counter(c['status'] for c in report['reconciliation'])),
        'report':str(a.output/'checks.json')}))


if __name__=='__main__':
    main()
