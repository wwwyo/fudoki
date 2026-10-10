"""Reconstruct source-declared settlement hierarchies from frozen scan observations.

Geometry and parent relationships belong to the layout, not to year/account code.
This converter never starts OCR, downloads inputs, or changes a managed manifest.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

BASE = Path(__file__).resolve().parent
PIPELINE = BASE.parents[5]
sys.path.insert(0, str(PIPELINE))
from ingestion.lib.pdf_table import (
    Box, Column, Placement, TableLayout, assemble_table, place_tokens, tokens_from_ocr,
)
from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn
from ingestion.fiscal.manifest import validate_metadata
from ingestion.lib.ocr_names import load_name_dictionary, correct_name_preserving_layout

LEVELS = ('款', '項', '目')
BUDGET = ('当初予算額', '補正予算額', '継続費及び繰越事業費繰越額', '予備費支出及び流用増減', '計')
RIGHT = ('支出済額', '継続費逓次繰越', '繰越明許費', '事故繰越し', '不用額')
MONEY = BUDGET + RIGHT
EXPLANATION = ('備考_事業番号', '備考_事業名称', '備考_事業部署', '備考_事業金額',
               '備考_費目名称', '備考_費目金額', '備考_子名称', '備考_子金額',
               '備考_人数注記', '備考_末端金額')
PAGES = ('原典頁', '印字頁', '原典終頁', '印字終頁')
NAMES = tuple(n for level in LEVELS for n in (level + '番号', level + '名称')) + tuple(
    level + '_' + field for level in LEVELS for field in MONEY) + EXPLANATION + PAGES
NUMBER = re.compile(r'[+\-△▲]?\s*\d[\d,\s]*\Z')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class Reader:
    def __init__(self, source, native_refs, corrections, layout):
        self.source_sha = digest(source)
        self.layout = layout
        self.refs, self.by_id, self.all_tokens = {}, {}, []
        self.bindings, self.used, self.corrected = {}, set(), []
        self.native_inventory = []
        for ref in native_refs:
            path = Path(ref['path'])
            if digest(path) != ref['sha256']:
                raise ValueError('Frozen native SHA differs')
            result = json.loads(path.read_text())
            if ref['kind'] == 'pdf':
                if result['origin']['sha256'] != self.source_sha:
                    raise ValueError('Native origin differs from selected PDF')
                if [p['page_number'] for p in result['pages']] != layout['physical_pages']:
                    raise ValueError('Native PDF page scope differs')
            else:
                image = Path(ref['image_path'])
                if digest(image) != result['origin']['sha256']:
                    raise ValueError('Crop native image SHA differs')
            region_ids = ref['regions']
            unit = 'pt' if ref['kind'] == 'pdf' else 'px'
            raw_tokens = tokens_from_ocr(result, kind='region', region_ids=region_ids, unit=unit)
            for token in raw_tokens:
                page = token.page if ref['kind'] == 'pdf' else ref['physical_page']
                box = token.bbox
                if unit == 'px' and box:
                    original = result['pages'][0]
                    width, height = layout['page_sizes_pt'][str(page)]
                    box = Box(box.left * width / original['image_width'],
                              box.top * height / original['image_height'],
                              box.right * width / original['image_width'],
                              box.bottom * height / original['image_height'])
                alias = ref['id'] + '|' + token.id
                mapped = replace(token, id=alias, origin_id=self.source_sha, page=page, bbox=box, unit='pt')
                self.all_tokens.append(mapped)
                self.by_id[alias] = mapped
                self.refs[alias] = {'native_sha256': ref['sha256'], 'native_path': str(path),
                                    'native_observation_id': token.id, 'raw_text': token.raw_text,
                                    'physical_page': page, 'bbox_pdf_pt': asdict(box) if box else None,
                                    'native_bbox': asdict(token.bbox) if token.bbox else None,
                                    'native_unit': unit, 'native_origin_sha256': result['origin']['sha256']}
            self.native_inventory.append({'id': ref['id'], 'path': str(path), 'sha256': ref['sha256'],
                                          'region_count': len(region_ids), 'observation_levels': 'region; words/numbers retained in immutable native'})
        self.body_tokens = [t for t in self.all_tokens if t.id.startswith('full|')]
        for replacement in layout.get('body_replacements', []):
            page, bounds = replacement['physical_page'], Box(*replacement['bbox_pdf_pt'])
            removed = [t for t in self.body_tokens if t.page == page and self.inside(t.bbox, bounds)]
            self.body_tokens = [t for t in self.body_tokens if t not in removed]
            self.body_tokens.extend(t for t in self.all_tokens if t.id.startswith(replacement['native_id'] + '|')
                                    and replacement['region_id'] + ':' in t.id)
            for t in removed:
                self.used.add(t.id)
                self.refs[t.id]['classification'] = 'superseded-by-authorized-crop'
        self.corrections = {}
        for correction in corrections:
            alias = correction['alias']
            token = self.by_id.get(alias)
            if token is None or correction['origin_sha256'] != self.source_sha:
                raise ValueError('Correction observation/origin not found')
            actual = self.refs[alias]
            if any(correction[k] != actual[k] for k in ('native_sha256', 'native_observation_id', 'physical_page', 'bbox_pdf_pt')):
                raise ValueError('Correction native identity or geometry differs')
            if correction['before'] != token.raw_text:
                raise ValueError('Correction before-text differs')
            if alias in self.corrections:
                raise ValueError('Duplicate correction target')
            self.corrections[alias] = correction

    @staticmethod
    def inside(box, bounds):
        return box is not None and bounds.left <= box.x('center') < bounds.right and bounds.top <= box.y('center') < bounds.bottom

    def cell(self, key, page, bbox, kind, *, native_id=None, confirmed_text=None):
        bounds = Box(*bbox)
        pool = self.all_tokens if native_id else self.body_tokens
        tokens = [t for t in pool if t.page == page and self.inside(t.bbox, bounds)
                  and (native_id is None or t.id.startswith(native_id + '|'))]
        if kind == 'money':
            tokens = [t for t in tokens if NUMBER.fullmatch(t.raw_text)]
        elif kind == 'name':
            tokens = [t for t in tokens if not NUMBER.fullmatch(t.raw_text)]
        corrected_tokens = []
        for token in tokens:
            correction = self.corrections.get(token.id)
            if correction:
                corrected_tokens.append(replace(token, raw_text=correction['after']))
                if token.id not in {c['alias'] for c in self.corrected}:
                    self.corrected.append(correction)
            else:
                corrected_tokens.append(token)
        placed = place_tokens(corrected_tokens, {(self.source_sha, page): Placement('page')})
        table = assemble_table(placed, TableLayout((Column('value', bounds.left, bounds.right),), row_tolerance=3))
        if table.unassigned:
            raise ValueError('Cell has ambiguous geometry')
        lines = [row.cell('value').text for row in table.rows if row.cell('value').text is not None]
        observed = '\n'.join(lines) if lines else None
        if kind == 'money' and len(tokens) > 1:
            raise ValueError(f'Multiple observations in monetary cell {key}')
        value = observed
        if kind == 'name' and value is not None:
            value = re.sub(r'\s+', '', value)
        if confirmed_text is not None:
            if not tokens:
                raise ValueError('Source-confirmed text requires real native binding')
            value = confirmed_text
        status = 'observed' if tokens else 'unread'
        self.bindings[key] = {'physical_page': page, 'bbox_pdf_pt': bbox, 'kind': kind,
                              'observed_text': observed, 'value': value, 'status': status,
                              'native_refs': [self.refs[t.id] for t in tokens],
                              'aliases': [t.id for t in tokens],
                              'source_confirmed_text': confirmed_text,
                              'logical_restoration': 'join typeset name fragments and original wraps; native unchanged' if kind == 'name' else None}
        self.used.update(t.id for t in tokens)
        return value


def metadata(layout):
    money_columns = [level + '_' + field for level in LEVELS for field in MONEY] + [
        '備考_事業金額', '備考_費目金額', '備考_子金額', '備考_末端金額']
    contexts = []
    for index, level in enumerate(LEVELS):
        grain = [ancestor + '番号' for ancestor in LEVELS[:index + 1]]
        for field in MONEY:
            contexts.append({'columns': [level + '_' + field],
                             'header_path': ['予算現額', field] if field in BUDGET else
                             (['翌年度繰越額', field] if field in RIGHT[1:4] else [field]),
                             'grain_columns': grain})
    for role, columns, grain in [
        ('事業', ['備考_事業番号', '備考_事業名称', '備考_事業部署', '備考_事業金額'], ['款番号', '項番号', '目番号', '備考_事業番号']),
        ('費目', ['備考_費目名称', '備考_費目金額'], ['款番号', '項番号', '目番号', '備考_事業番号', '備考_費目名称']),
        ('子', ['備考_子名称', '備考_子金額', '備考_人数注記'], ['款番号', '項番号', '目番号', '備考_事業番号', '備考_費目名称', '備考_子名称']),
        ('末端', ['備考_末端金額'], ['款番号', '項番号', '目番号', '備考_事業番号', '備考_費目名称', '備考_子名称', '原典頁']),
    ]:
        contexts.append({'columns': columns, 'header_path': ['備考'], 'grain_columns': grain, 'semantic_role': 'project'})
    return {'units': [{'text': '（単位：円）', 'scope': {'kind': 'columns', 'columns': money_columns}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}} for note in layout['metadata_notes']],
            'column_contexts': contexts}


def confirm_source_cells(reader, declarations):
    """Fail closed on image-confirmed header/continuation transcription scopes."""
    confirmed = []
    for declaration in declarations:
        key = declaration['cell_key']
        cell = reader.bindings[key]
        if (declaration['origin_sha256'] != reader.source_sha
                or declaration['physical_page'] != cell['physical_page']
                or declaration['bbox_pdf_pt'] != cell['bbox_pdf_pt']
                or declaration['before'] != cell['observed_text']):
            raise ValueError('Source confirmation source/cell/before differs')
        actual = [{k: ref[k] for k in ('native_sha256', 'native_observation_id', 'bbox_pdf_pt', 'raw_text')}
                  for ref in cell['native_refs']]
        if actual != declaration['native_refs']:
            raise ValueError('Source confirmation native IDs/text/geometry differ')
        confirmed.append(declaration)
    return confirmed


def convert(inputs: list[dict], destination: Path, options: dict) -> dict:
    started = time.perf_counter()
    if len(inputs) != 1 or inputs[0]['format'] != 'pdf' or len(inputs[0]['scope']) != 1:
        raise ValueError('One selected PDF and one account scope are required')
    source = inputs[0]
    layout_path = Path(options['layout_path'])
    if digest(layout_path) != options['layout_sha256']:
        raise ValueError('Layout SHA differs')
    layout = json.loads(layout_path.read_text())
    if digest(source['path']) != source['sha256'] or source['sha256'] != layout['origin_sha256']:
        raise ValueError('Origin differs from source-specific layout')
    scope_pages = [p for start, end in source['scope'][0]['pages'] for p in range(start, end + 1)]
    if scope_pages != layout['physical_pages']:
        raise ValueError('Selected scope differs from layout')
    corrections_path = Path(options['corrections_path'])
    if digest(corrections_path) != options['corrections_sha256']:
        raise ValueError('Corrections SHA differs')
    reader = Reader(source['path'], options['native_refs'], json.loads(corrections_path.read_text()), layout)
    # Reconstruct independent print cells, then inherit their source-confirmed context.
    controls = []
    for spec in layout['parent_controls']:
        name = reader.cell(spec['id'] + ':label', spec['left_page'], spec['label_bbox'], 'name')
        match = re.fullmatch(r'(\d+)(.+)', name or '')
        if not match:
            raise ValueError('Numbered parent heading is unreadable')
        values = {'number': match[1], 'name': match[2]}
        for field, bbox in zip(BUDGET, layout['budget_columns'], strict=True):
            values[field] = reader.cell(spec['id'] + ':' + field, spec['left_page'],
                                       [bbox[0], *spec['row_band'][:1], bbox[1], spec['row_band'][1]], 'money')
        for field, bbox in zip(RIGHT, layout['right_columns'], strict=True):
            values[field] = reader.cell(spec['id'] + ':' + field, spec['right_page'],
                                       [bbox[0], spec['row_band'][0], bbox[1], spec['row_band'][1]], 'money')
        controls.append({'id': spec['id'], 'record_role': 'independent-printed-parent-control', 'level': spec['level'],
                         'values': values, 'cell_keys': [spec['id'] + ':label'] + [spec['id'] + ':' + f for f in MONEY]})
    nodes = []
    for spec in layout['explanation_nodes']:
        name = reader.cell(spec['id'] + ':name', spec['page'], spec['name_bbox'], 'name', native_id=spec.get('native_id'))
        amount = reader.cell(spec['id'] + ':amount', spec['page'], spec['amount_bbox'], 'money')
        if name is None or amount is None:
            raise ValueError(f'Explanation field unreadable: {spec["id"]}')
        node = dict(spec, name=name, amount=amount, record_role='explanation-' + spec['role'])
        node['cell_keys'] = [spec['id'] + ':name', spec['id'] + ':amount']
        if spec['role'] == 'project':
            match = re.fullmatch(r'(\d+)(.+?)[（(](.+)[）)]', name)
            if not match:
                raise ValueError('Project heading and department cannot be separated')
            node.update(number=match[1], name=match[2], department=match[3])
        if spec.get('personnel_pattern'):
            match = re.fullmatch(spec['personnel_pattern'], name)
            if not match:
                raise ValueError('Personnel annotation differs from source-declared structure')
            node.update(name=match[1], personnel_note=match[2])
        nodes.append(node)
    by_id = {node['id']: node for node in nodes}
    children = {node['parent'] for node in nodes if node['parent'] is not None}
    rows, row_bindings = [], []
    for node in nodes:
        if node['id'] in children or node['role'] == 'project':
            continue
        chain, cursor = [], node
        while cursor is not None:
            if cursor['id'] in {n['id'] for n in chain}:
                raise ValueError('Cyclic explanation hierarchy')
            chain.append(cursor)
            cursor = by_id[cursor['parent']] if cursor['parent'] else None
        chain.reverse()
        if [n['role'] for n in chain] not in (['project', 'expense'], ['project', 'expense', 'child']):
            raise ValueError('Undeclared explanation hierarchy')
        row = {name: None for name in NAMES}
        cells = {}
        for control in controls:
            level, values = control['level'], control['values']
            row[level + '番号'], row[level + '名称'] = values['number'], values['name']
            cells[level + '番号'] = cells[level + '名称'] = control['id'] + ':label'
            for field in MONEY:
                row[level + '_' + field] = values[field]
                cells[level + '_' + field] = control['id'] + ':' + field
        project, expense = chain[:2]
        row.update({'備考_事業番号': project['number'], '備考_事業名称': project['name'],
                    '備考_事業部署': project['department'], '備考_事業金額': project['amount'],
                    '備考_費目名称': expense['name'], '備考_費目金額': expense['amount'],
                    '備考_末端金額': node['amount'],
                    '原典頁': node['page'], '印字頁': layout['printed_pages'][str(node['page'])],
                    '原典終頁': node['page'], '印字終頁': layout['printed_pages'][str(node['page'])]})
        for suffix in ('番号', '名称', '部署'):
            cells['備考_事業' + suffix] = project['id'] + ':name'
        cells['備考_事業金額'] = project['id'] + ':amount'
        cells['備考_費目名称'], cells['備考_費目金額'] = expense['id'] + ':name', expense['id'] + ':amount'
        if len(chain) == 3:
            row.update({'備考_子名称': node['name'], '備考_子金額': node['amount'],
                        '備考_人数注記': node.get('personnel_note')})
            cells['備考_子名称'], cells['備考_子金額'] = node['id'] + ':name', node['id'] + ':amount'
            if node.get('personnel_note'):
                cells['備考_人数注記'] = node['id'] + ':name'
        cells['備考_末端金額'] = node['id'] + ':amount'
        row_bindings.append({'row_index': len(rows), 'leaf_node': node['id'], 'ancestor_nodes': [n['id'] for n in chain],
                             'cells': cells, 'null_columns': [k for k, v in row.items() if v is None],
                             'null_reason': 'source hierarchy has no child or personnel annotation; not zero or unread',
                             'page_columns': {'原典頁': node['page'], '印字頁': layout['printed_pages'][str(node['page'])]}})
        rows.append(row)
    sections = []
    for spec in layout['statutory_sections']:
        value = reader.cell(spec['id'] + ':区分', spec['left_page'], spec['label_bbox'], 'name')
        record = {'id': spec['id'], 'record_role': 'statutory-section-check-only', 'source_order': spec['order'],
                  'parent_path': [c['values']['number'] for c in controls], '区分': value}
        record['金額'] = reader.cell(spec['id'] + ':金額', spec['left_page'], spec['amount_bbox'], 'money')
        for field, bbox in zip(RIGHT, layout['right_columns'], strict=True):
            record[field] = reader.cell(spec['id'] + ':' + field, spec['right_page'],
                                        [bbox[0], spec['row_band'][0], bbox[1], spec['row_band'][1]], 'money')
        sections.append(record)
    total_spec = layout['explanation_total']
    total = {'record_role': 'printed-explanation-total', 'parent_path': [c['values']['number'] for c in controls],
             'project': None, 'expense': None, 'child': None,
             'label': reader.cell('total:name', total_spec['page'], total_spec['name_bbox'], 'name'),
             'amount': reader.cell('total:amount', total_spec['page'], total_spec['amount_bbox'], 'money'),
             'physical_page': total_spec['page'], 'cell_keys': ['total:name', 'total:amount']}
    headers = []
    for spec in layout['headers']:
        observed = reader.cell(spec['id'], spec['page'], spec['bbox_pdf_pt'], 'header',
                               native_id=spec.get('native_id'))
        headers.append(dict(spec, observed_text=observed, native_refs=reader.bindings[spec['id']]['native_refs']))
    continuations = []
    for spec in layout['continuations']:
        observed = reader.cell(spec['id'], spec['page'], spec['bbox_pdf_pt'], 'header')
        continuations.append(dict(spec, native_text=observed, native_refs=reader.bindings[spec['id']]['native_refs']))
    blank_cells = []
    for spec in layout.get('confirmed_blank_cells', []):
        value = reader.cell(spec['id'], spec['page'], spec['bbox_pdf_pt'], 'header')
        if value is not None:
            raise ValueError('Image-confirmed blank cell contains a native observation')
        reader.bindings[spec['id']].update(status='confirmed-blank', value='')
        blank_cells.append(dict(spec, value='', record_role='source-confirmed-continuation-blank'))
    for page in layout['physical_pages']:
        footer = reader.cell(f'footer-p{page}', page, layout['printed_page_bbox'], 'header')
        if (footer or '').strip('-–− ') != layout['printed_pages'][str(page)]:
            raise ValueError('Printed page declaration differs from actual native footer')
    confirmation_path = Path(options['confirmations_path'])
    if digest(confirmation_path) != options['confirmations_sha256']:
        raise ValueError('Source confirmations SHA differs')
    confirmations = confirm_source_cells(reader, json.loads(confirmation_path.read_text()))
    # Apply shared dictionaries only to observed, numbered source headings; no rules
    # currently match this file. Unknown source-only names remain local source names.
    dictionary_checks = []
    for role, path in layout['name_dictionaries'].items():
        dictionary = load_name_dictionary(Path(path))
        names = [c['values']['name'] for c in controls] if role == 'subject' else [
            re.sub(r'^\d+', '', s['区分'] or '') for s in sections]
        for name in names:
            result = correct_name_preserving_layout(name, dictionary)
            if result['corrected_name'] != name:
                raise ValueError('New dictionary correction requires source-confirmed review; do not infer source spelling')
            dictionary_checks.append({'role': role, 'name': name, 'path': path, 'sha256': digest(path), 'applied': False})
    remaining, marginalia = [], []
    for token in reader.all_tokens:
        if token.id in reader.used:
            continue
        ref = reader.refs[token.id]
        y = token.bbox.y('center') if token.bbox else None
        if y is not None and (y < 156 or y > 770):
            marginalia.append(dict(ref, classification='page-title-header-unit-or-footer'))
        elif not token.id.startswith('full|'):
            marginalia.append(dict(ref, classification='authorized-crop-observation-not-used-for-body'))
        else:
            remaining.append(dict(ref, classification='unassigned-body-observation'))
    if remaining:
        raise ValueError(f'{len(remaining)} body observations unassigned; preserve and resolve before candidate')
    for alias, ref in reader.refs.items():
        cells = [key for key, value in reader.bindings.items() if alias in value['aliases']]
        categories = [v['classification'] for v in marginalia + remaining
                      if v['native_sha256'] == ref['native_sha256'] and v['native_observation_id'] == ref['native_observation_id']]
        ref['binding_cells'] = cells
        ref['classifications'] = (['bound-source-cell'] if cells else []) + categories
        if ref.get('classification'):
            ref['classifications'].append(ref['classification'])
        if not ref['classifications']:
            raise ValueError('Native region silently dropped')
    table_metadata = metadata(layout)
    validate_metadata(table_metadata, list(NAMES))
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    table_id = options.get('table_id', 'details')
    result = write_conversion(destination / (table_id + '.parquet'), rows,
        columns=[ParquetColumn(name, 'BIGINT' if name in ('原典頁', '原典終頁') else 'VARCHAR') for name in NAMES],
        context=ConversionContext(source['sha256'], table_id, str(Path(__file__).resolve()), str(layout_path)))
    save(destination / 'candidate-observations.json', {'parent_controls': controls, 'statutory_sections': sections,
        'explanation_nodes': nodes, 'explanation_total': total, 'continuations': continuations,
        'confirmed_blank_cells': blank_cells, 'marginalia': marginalia, 'unassigned': remaining})
    save(destination / 'bindings.json', {'cells': reader.bindings, 'rows': row_bindings,
        'all_region_observations': reader.refs, 'unassigned': remaining})
    save(destination / 'headers.json', headers)
    save(destination / 'metadata.json', table_metadata)
    save(destination / 'receipt.json', {'source_sha256': source['sha256'], 'scope': source['scope'],
        'origin_physical_pages': layout['physical_pages'], 'printed_pages': layout['printed_pages'],
        'layout_sha256': digest(layout_path), 'converter_sha256': digest(__file__),
        'corrections_sha256': digest(corrections_path), 'native_inventory': reader.native_inventory,
        'confirmations_sha256': digest(confirmation_path), 'source_confirmations': confirmations,
        'table': asdict(result), 'metadata': table_metadata,
        'schema': [{'name': name, 'type': 'BIGINT' if name in ('原典頁', '原典終頁') else 'VARCHAR'} for name in NAMES],
        'row_grain': 'source-confirmed finest explanation item; parent references repeated and nonadditive',
        'row_count': len(rows), 'rows_per_project': {p['number']: sum(r['備考_事業番号'] == p['number'] for r in rows) for p in nodes if p['role'] == 'project'},
        'local_corrections': reader.corrected, 'dictionary_checks': dictionary_checks,
        'unread': [k for k, v in reader.bindings.items() if v['status'] == 'unread'],
        'unassigned': remaining, 'elapsed_seconds': time.perf_counter() - started, 'pid': os.getpid(),
        'ocr_executed': False, 'canonical_classification_applied': False})
    return {table_id: {'path': result.path, 'metadata': table_metadata}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--options', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = convert(json.loads(Path(args.inputs).read_text()), Path(args.output), json.loads(Path(args.options).read_text()))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
