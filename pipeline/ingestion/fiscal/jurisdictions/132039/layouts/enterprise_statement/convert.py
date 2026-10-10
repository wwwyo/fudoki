"""Measured enterprise statement grids, spreads and ruled expense hierarchies.

Reads immutable native OCR observations; all source-specific geometry and
corrections are supplied separately. No selection, storage or dbt mutation.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn
from ingestion.lib.pdf_table import (Box, Column, Heading, HierarchyContext,
    Placement, RowBand, TableLayout, assemble_table, place_tokens, tokens_from_ocr)
from ingestion.fiscal.layouts.statement.text_spread import encoded, inside


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_native(spec, source_sha):
    path = Path(spec['path'])
    if sha(path) != spec['sha256']:
        raise ValueError('Native observation SHA differs')
    native = json.loads(path.read_text())
    if native['origin']['sha256'] != source_sha:
        raise ValueError('Native observations belong to another original')
    return native, tokens_from_ocr(native, kind='region', region_ids=['full-page'], unit='pt')


def cell_text(cell, separator):
    """Join cell tokens in print order: lines top-to-bottom, tokens left-to-right.

    Tokens whose center-y is within 4pt are the same printed line; `separator`
    joins lines, never same-line fragments."""
    if not cell.tokens:
        return None
    lines = []
    for word in sorted(cell.tokens, key=lambda t: (t.bbox.y('center'), t.bbox.left, t.token.id)):
        y = word.bbox.y('center')
        if lines and y - lines[-1][0] <= 4:
            lines[-1][1].append(word)
        else:
            lines.append([y, [word]])
    return separator.join(''.join(w.token.raw_text for w in sorted(ws, key=lambda t: (t.bbox.left, t.token.id)))
                          for _, ws in lines)


def note_text(tokens):
    """Join note tokens like cell_text: one line per 4pt y-group, no separator
    inside a line, newline between lines."""
    if not tokens:
        return ''
    lines = []
    for t in sorted(tokens, key=lambda t: (t.bbox.y('center'), t.bbox.left, t.id)):
        y = t.bbox.y('center')
        if lines and y - lines[-1][0] <= 4:
            lines[-1][1].append(t)
        else:
            lines.append([y, [t]])
    return '\n'.join(''.join(t.raw_text for t in sorted(ws, key=lambda t: (t.bbox.left, t.id)))
                     for _, ws in lines)


def apply_correction(corrections, key, ids, box, text, native_bindings, layout, used):
    correction = corrections.get(key)
    if not correction:
        return text
    if (correction['source_sha256'] != layout['source_sha256'] or
            correction['native_sha256'] != layout['native_sha256'] or
            correction['observation_ids'] != ids or correction['bbox'] != box or
            correction['before'] != text or correction['native_observations'] !=
            [{'id': ident, 'sha256': native_bindings[ident]} for ident in ids]):
        raise ValueError(f'Correction binding differs: {key}')
    used.append(correction)
    return correction['after']


def build(native, tokens, layout, native_bindings=None):
    pages = {p['page_number']: p for p in native['pages']}
    by_page = {p: [t for t in tokens if t.page == p] for p in pages}
    claimed = set()
    bindings = []
    missing = []
    corrections_used = []
    corrections = {(c['page'], c['table'], c['row'], c['column']): c
                   for c in layout.get('corrections', [])}
    native_bindings = native_bindings or {t.id: layout['native_sha256'] for t in tokens}
    by_id = {t.id: t for t in tokens}
    header_bindings = []
    for header in layout.get('header_bindings', []):
        if header['source_sha256'] != layout['source_sha256'] or header['native_sha256'] != layout['native_sha256']:
            raise ValueError('Header origin/native identity differs')
        for part in header['parts']:
            observed = [by_id[i] for i in part['observation_ids']]
            if any(t.page != part['page'] or not t.bbox or not inside(t.bbox, part['bbox']) for t in observed):
                raise ValueError('Header observation position differs')
            if ''.join(t.raw_text for t in observed) != part['native_text']:
                raise ValueError('Header native text differs')
            claimed.update(part['observation_ids'])
        context = next(c for c in layout['metadata'][header['table']]['column_contexts']
                       if c['columns'] == header['columns'])
        if context['header_path'] != header['header_path']:
            raise ValueError('Metadata/header binding differs')
        header_bindings.append(header)

    def grid(spec):
        page = spec['page']
        bands = tuple(RowBand(*b) for b in spec['bands'])
        bounds = (spec['columns'][0]['left'], bands[0].top,
                  spec['columns'][-1]['right'], bands[-1].bottom)
        chosen = [t for t in by_page[page] if t.bbox and
                  bounds[0] <= t.bbox.x('center') <= bounds[2] and
                  bounds[1] <= t.bbox.y('center') < bounds[3]]
        result = assemble_table(place_tokens(chosen, {
            (layout['source_sha256'], page): Placement(str(page))}),
            TableLayout(tuple(Column(c['name'], c['left'], c['right'],
                c.get('anchor', 'center'), c.get('separator', '')) for c in spec['columns']),
                row_bands=bands))
        out = []
        for i, row in enumerate(result.rows):
            values = {}
            refs = {}
            for col, cell in zip(spec['columns'], row.cells, strict=True):
                ids = [p.token.id for p in cell.tokens]
                box = [col['left'], bands[i].top, col['right'], bands[i].bottom]
                key = (page, spec['table'], i + 1, col['name'])
                raw = cell_text(cell, col.get('separator', ''))
                text = apply_correction(corrections, key, ids, box, raw,
                                        native_bindings, layout, corrections_used)
                if text is None and col['name'] in spec.get('required_cells', []):
                    missing.append({'page': page, 'table': spec['table'], 'row': i + 1,
                                    'column': col['name'], 'bbox': box, 'observation_ids': ids})
                values[col['name']] = text
                refs[col['name']] = ids
                claimed.update(ids)
                bindings.append({'table': spec['table'], 'row': i + 1, 'column': col['name'],
                    'page': page, 'bbox': box, 'observation_ids': ids, 'native_text': raw,
                    'value': text, 'source_sha256': layout['source_sha256'],
                    'native_sha256': layout['native_sha256']})
            out.append((values, refs))
        return out

    tables = {}
    for book in layout['detail_books']:
        printed_rows = []
        details = []
        hierarchy = HierarchyContext(['款', '項', '目'])
        hierarchy_amounts = {k: None for k in hierarchy.levels}
        hierarchy_refs = {k: {} for k in hierarchy.levels}
        for spec in book['pages']:
            for i, (fields, refs) in enumerate(grid(spec)):
                observed = [k for k in ['款', '項', '目', '節'] if fields[k] is not None]
                total = i + 1 in spec.get('total_rows', [])
                if len(observed) != 1 and not total:
                    raise ValueError(f'Expense hierarchy ambiguous: page {spec["page"]} row {i + 1}')
                level = observed[0] if observed else None
                label = fields[level] if level else None
                if total:
                    hierarchy.reset()
                    hierarchy_amounts = {k: None for k in hierarchy.levels}
                    hierarchy_refs = {k: {} for k in hierarchy.levels}
                elif level in hierarchy.levels:
                    hierarchy.update(level, Heading(label, tuple(refs[level])))
                    idx = hierarchy.levels.index(level)
                    for lower in hierarchy.levels[idx:]:
                        hierarchy_amounts[lower] = None
                        hierarchy_refs[lower] = {}
                    hierarchy_amounts[level] = fields['金額']
                    hierarchy_refs[level] = {'page': spec['page'], 'row': i + 1,
                                            'name': refs[level], 'amount': refs['金額']}
                snapshot = hierarchy.snapshot()
                row = {'印字区分': level, '印字名称': label, '金額': fields['金額'],
                       '節': fields['節'] if not total else None,
                       'physical_page': spec['page'], 'printed_page': str(spec['printed_page']),
                       'source_row': i + 1, 'cell_refs': encoded(refs)}
                for k in hierarchy.levels:
                    row[k] = snapshot[k].value if snapshot[k] else None
                    row[k + '_金額'] = hierarchy_amounts[k]
                printed_rows.append(row)
                if level == '節' and not total:
                    details.append({**row, 'hierarchy_refs': encoded(hierarchy_refs)})
        tables[book['id']] = printed_rows
        tables[book['id'] + '_details'] = details

    for spread in layout['spreads']:
        left = grid(spread['left'])
        right = grid(spread['right'])
        if len(left) != len(right):
            raise ValueError('Spread row bands differ')
        rows = []
        parent = None
        parent_refs = None
        item = None
        for i, ((a, ar), (b, br)) in enumerate(zip(left, right, strict=True)):
            label = a['区分']
            if label and re.match(r'第\s*[0-9０-９]+\s*款', label):
                level = '款'
                parent = label
                parent_refs = {'page': spread['left']['page'], 'row': i + 1, 'ids': ar['区分']}
                item = None
            elif label and re.match(r'第\s*[0-9０-９]+\s*項', label):
                level = '項'
                item = label
            elif label == '計':
                level = '計'
                parent = None
                parent_refs = None
                item = None
            else:
                raise ValueError(f'Unresolved statement hierarchy: {label!r}')
            row = {**a, **b, '印字区分': level, '款': parent, '項': item,
                   'physical_page': spread['left']['page'],
                   'right_page': spread['right']['page'],
                   'printed_page': str(spread['left']['printed_page']),
                   'source_row': i + 1, 'cell_refs': encoded({'left': ar, 'right': br}),
                   'hierarchy_refs': encoded(parent_refs)}
            rows.append(row)
        tables[spread['id']] = rows

    note_rows = []
    for i, note in enumerate(layout.get('notes', [])):
        selected = [t for t in by_page[note['page']] if t.bbox and inside(t.bbox, note['bbox'])]
        selected.sort(key=lambda t: (t.bbox.top, t.bbox.left, t.id))
        if any(t.id in claimed for t in selected):
            raise ValueError(f'Note region covers claimed cells: {note}')
        ids = [t.id for t in selected]
        text = apply_correction(corrections, (note['page'], 'statement_notes', i + 1, '注記'),
                                ids, note['bbox'], note_text(selected),
                                native_bindings, layout, corrections_used)
        note_rows.append({'種別': note['kind'], '注記': text,
                         'physical_page': note['page'], 'printed_page': str(note['printed_page']),
                         'cell_refs': encoded(ids)})
        claimed.update(ids)
    tables['statement_notes'] = note_rows
    if len(corrections_used) != len(corrections):
        raise ValueError('Unused source correction')

    exclusions = layout.get('exclusion_regions', [])
    excluded = []
    unassigned = []
    for t in tokens:
        if t.id in claimed:
            continue
        hit = next((r for r in exclusions if r['page'] == t.page and t.bbox and
                    r['bbox'][0] <= t.bbox.x('center') <= r['bbox'][2] and
                    r['bbox'][1] <= t.bbox.y('center') < r['bbox'][3]), None)
        if hit:
            excluded.append({'id': t.id, 'page': t.page, 'region': hit['region'],
                             'reason': hit['reason']})
        else:
            unassigned.append(asdict(t))
    for region in exclusions:
        overlapped = [t.id for t in tokens if t.id in claimed and t.bbox and
                      t.page == region['page'] and
                      region['bbox'][0] <= t.bbox.x('center') <= region['bbox'][2] and
                      region['bbox'][1] <= t.bbox.y('center') < region['bbox'][3]]
        if overlapped:
            raise ValueError(f'Exclusion region covers claimed cells: {region["region"]}')
    return tables, {'bindings': bindings, 'missing': missing, 'unassigned': unassigned,
                    'excluded': excluded, 'corrections_used': corrections_used,
                    'header_bindings': header_bindings}


def convert(inputs: list[dict], destination: Path, options: dict) -> dict:
    if len(inputs) != 1 or inputs[0]['format'] != 'pdf' or inputs[0]['direction'] != 'expenditure':
        raise ValueError('One selected expenditure PDF required')
    source = inputs[0]
    layout_path = Path(options['layout'])
    if sha(layout_path) != options['layout_sha256']:
        raise ValueError('Layout SHA differs')
    layout = json.loads(layout_path.read_text())
    if sha(source['path']) != layout['source_sha256']:
        raise ValueError('Original SHA differs')
    scope = source['scope']
    if len(scope) != 1 or scope[0]['account'] != layout['account'] or scope[0]['pages'] != layout['scope']:
        raise ValueError('Supplied source scope differs')
    native, tokens = read_native(options['native'], layout['source_sha256'])
    native_bindings = {t.id: options['native']['sha256'] for t in tokens}
    for supplement in options.get('supplemental_native', []):
        path = Path(supplement['path'])
        if sha(path) != supplement['sha256']:
            raise ValueError('Supplemental native SHA differs')
        result = json.loads(path.read_text())
        if result['origin']['sha256'] != layout['source_sha256']:
            raise ValueError('Supplemental native original differs')
        extra = tokens_from_ocr(result, kind='region', region_ids=supplement['regions'], unit='pt')
        if any(t.id in native_bindings for t in extra):
            raise ValueError('Supplemental observation ID collision')
        native_bindings.update({t.id: supplement['sha256'] for t in extra})
        tokens += extra
    if options['native']['sha256'] != layout['native_sha256']:
        raise ValueError('Layout/native binding differs')
    if sorted(p['page_number'] for p in native['pages']) != sorted(layout['pages']):
        raise ValueError('Native page coverage differs')
    tables, observations = build(native, tokens, layout, native_bindings)
    observations['native_bindings'] = native_bindings
    destination.mkdir(parents=True, exist_ok=True)
    # The formal runner shares one candidate dir across conversions; refuse only our own files.
    planned = ['observations.json', 'conversion.json', *(t + '.parquet' for t in tables)]
    if any((destination / name).exists() for name in planned):
        raise FileExistsError(f'Candidate output already exists in {destination}')
    (destination / 'observations.json').write_text(json.dumps(observations, ensure_ascii=False, indent=2) + '\n')
    results = {}
    summary = {}
    for table_id, rows in tables.items():
        if not rows:
            raise ValueError('Unexpected empty source table')
        columns = [ParquetColumn(k, 'BIGINT' if k in ('physical_page', 'right_page', 'source_row') else 'VARCHAR')
                   for k in rows[0]]
        context = ConversionContext(layout['source_sha256'], table_id, __file__, str(layout_path))
        info = write_conversion(destination / (table_id + '.parquet'), rows, columns=columns, context=context)
        metadata = layout['metadata'][table_id]
        results[table_id] = {'path': destination / (table_id + '.parquet'), 'metadata': metadata}
        summary[table_id] = {**asdict(info), 'schema': [asdict(c) for c in columns],
                             'metadata': metadata, 'amount_columns': layout['amount_columns'][table_id]}
    (destination / 'conversion.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    result = convert(request['inputs'], args.output, request['options'])
    print(json.dumps({k: str(v['path']) for k, v in result.items()}))


if __name__ == '__main__':
    main()
