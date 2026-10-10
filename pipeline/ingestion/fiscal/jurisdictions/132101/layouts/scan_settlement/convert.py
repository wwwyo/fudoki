"""Reconstruct 132101 settlement-3 council tables from frozen scan observations.

Single landscape sheet per physical page carries BOTH the left 科目/予算現額/節
table and the right 支出/繰越/不用/備考 table. Explanation hierarchy is
project -> setsu -> leaf with printed number+name correspondence between the
bikou setsu headings and the statutory 節一覧. This converter never starts OCR,
downloads inputs, or changes a managed manifest.
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
import unicodedata

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
DETAIL_COLUMNS = (
    tuple(n for level in LEVELS for n in (level + '番号', level + '名称'))
    + tuple(level + '_' + field for level in LEVELS for field in MONEY)
    + ('備考_事業番号', '備考_事業名称', '備考_事業部署', '備考_事業金額',
       '備考_節番号', '備考_節名称', '備考_節金額',
       '備考_費目名称', '備考_費目金額', '備考_末端金額',
       '原典頁', '原典終頁', '印字頁', '印字終頁')
)
NAMES = DETAIL_COLUMNS
# Printed setsu subtotals wrap the amount in （ ）; OCR keeps the closing mark on
# the amount token while the opening mark may split off or drop. Leaf/project
# amounts never carry the closing mark.
HEADER_ZONE_BOTTOM = 130.0  # build_layout.py と同じ見出し帯の下端
MONEY_TOKEN = re.compile(r'[+\-△▲]?\s*\d[\d,\s]*\s*[）)]?\Z')
KNOWN_CLASSIFICATIONS = (
    'bound-source-cell',
    'bikou-paren-fragment-not-a-cell',
    'unit-glyph-in-body',
    'superseded-crop-observation',
    'unused-crop-owner-strip-observation',
    'unused-crop-observation',
    'page-title-header-unit-or-footer',
    'child-of-bound-source-cell',
    'child-of-marginalia',
    'marginalia-child-observation',
    'unassigned-body-observation',
)
NULL_REASONS = {
    '印字頁': 'source absence: this book prints no page numbers; NULL is not an unread amount',
    '印字終頁': 'source absence: this book prints no page numbers; NULL is not an unread amount',
}
PAREN_OPEN_TAIL = re.compile(r'[（(ＣC]+$')
PAREN_CLOSE_TAIL = re.compile(r'\s*[）)]$')
CONTROL_LABEL = re.compile(r'(\d+)\s*(.+)')
SETSU_LABEL = re.compile(r'(\d+)\s*(.+)')
PROJECT_LABEL = re.compile(r'(\d+)\s*(.+?)\s*[（(]\s*(.+?)\s*[）)]')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class Reader:
    def __init__(self, source, native_refs, corrections, layout, declarations=None):
        self.source_sha = digest(source)
        self.layout = layout
        self.declarations = declarations or {}
        self.refs, self.by_id, self.all_tokens = {}, {}, []
        self.bindings, self.used, self.corrected = {}, set(), []
        self.native_inventory = []
        self.observations = []
        self.crop_by_alias = {}
        self.crop_ref_ids = set()
        self.crop_bindings = {}
        self.restorations = {}
        for ref in native_refs:
            path = Path(ref['path'])
            if digest(path) != ref['sha256']:
                raise ValueError('Frozen native SHA differs')
            result = json.loads(path.read_text())
            if ref['kind'] == 'pdf':
                if result['origin']['sha256'] != self.source_sha:
                    raise ValueError('Native origin differs from selected PDF')
                pages = [p.get('page_number') or i + 1 for i, p in enumerate(result['pages'])]
                if ref.get('page_scope', 'full') == 'full':
                    if pages != layout['physical_pages']:
                        raise ValueError('Native PDF page scope differs')
                elif not pages or any(p not in layout['physical_pages'] for p in pages):
                    raise ValueError('Crop native page outside selected scope')
            else:
                image = Path(ref['image_path'])
                if digest(image) != result['origin']['sha256']:
                    raise ValueError('Crop native image SHA differs')
            region_ids = ref['regions']
            unit = 'pt' if ref['kind'] == 'pdf' else 'px'
            raw_tokens = tokens_from_ocr(result, kind='region', region_ids=region_ids, unit=unit)
            # Every observation level is retained with parent/role so that no
            # observation is silently dropped from the partition (F04).
            for kind in ('region', 'word', 'number'):
                if kind == 'region':
                    continue
                self.observations.extend(self._observation_records(
                    result, tokens_from_ocr(result, kind=kind, region_ids=region_ids, unit=unit),
                    ref, unit))
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
                self.by_id[alias] = mapped
                self.refs[alias] = {'native_sha256': ref['sha256'], 'native_path': str(path),
                                    'native_observation_id': token.id, 'raw_text': token.raw_text,
                                    'physical_page': page, 'bbox_pdf_pt': asdict(box) if box else None,
                                    'native_bbox': asdict(token.bbox) if token.bbox else None,
                                    'native_unit': unit, 'native_origin_sha256': result['origin']['sha256']}
                record = {'alias': alias, 'native_ref_id': ref['id'],
                          'native_sha256': ref['sha256'], 'native_path': str(path),
                          'observation_id': token.id, 'kind': 'region', 'parent_id': None,
                          'raw_text': token.raw_text, 'page': page,
                          'bbox_pdf_pt': asdict(box) if box else None,
                          'attempt_id': self._attempt_of(result, token.id),
                          'confidence': token.confidence}
                self.observations.append(record)
                if ref.get('page_scope', 'full') == 'crop':
                    # Crop observations are candidate re-reads; they never join the
                    # body pool on their own, only a declared binding adopts one.
                    self.crop_by_alias[alias] = mapped
                    self.crop_ref_ids.add(ref['id'])
                else:
                    self.all_tokens.append(mapped)
            if ref.get('page_scope', 'full') == 'crop':
                # Superseded owner-strip observations stay in the immutable native
                # attempts; keep them in the partition instead of dropping them.
                self.observations.extend(self._crop_attempt_records(result, ref))
            self.native_inventory.append({'id': ref['id'], 'path': str(path), 'sha256': ref['sha256'],
                                          'region_count': len(region_ids),
                                          'page_scope': ref.get('page_scope', 'full'),
                                          'observation_levels': 'region/word/number; parent ids retained in immutable native'})
        self.body_tokens = list(self.all_tokens)
        # Every observation level gets a ref record so the partition can cite it.
        for record in self.observations:
            if record['alias'] not in self.refs:
                self.refs[record['alias']] = {
                    'native_sha256': record['native_sha256'], 'native_path': record['native_path'],
                    'native_observation_id': record['observation_id'],
                    'raw_text': record['raw_text'], 'physical_page': record['page'],
                    'bbox_pdf_pt': record['bbox_pdf_pt'],
                    'native_bbox': record['bbox_pdf_pt'], 'native_unit': record['bbox_pdf_pt'] and 'pt' or None,
                    'native_origin_sha256': self.source_sha,
                    'observation_kind': record['kind'],
                    'parent_observation_id': record['parent_id'],
                    'attempt_id': record['attempt_id']}
        self._register_declarations()
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
    def _attempt_of(result, observation_id):
        for page in result['pages']:
            for attempt in page.get('attempts', []):
                if observation_id.startswith(attempt['id'] + ':'):
                    return attempt['id']
        return None

    def _crop_attempt_records(self, result, ref):
        records = []
        seen = {(r['alias'], r['attempt_id']) for r in self.observations}
        for page in result['pages']:
            superseded = set()
            for attempt in page.get('attempts', []):
                superseded.update(attempt.get('superseded_observation_ids') or [])
            for attempt in page.get('attempts', []):
                for item in attempt.get('observations', []):
                    bbox = item.get('bbox_pdf_pt')
                    if ref['kind'] == 'pdf' and bbox is None:
                        continue
                    if bbox is None:
                        box = None
                    elif isinstance(bbox, dict):
                        box = Box(bbox['left'], bbox['top'], bbox['right'], bbox['bottom'])
                    else:
                        box = Box(*bbox)
                    key = (ref['id'] + '|' + item['id'], attempt['id'])
                    if key in seen:
                        continue
                    seen.add(key)
                    records.append({'alias': key[0],
                                    'native_ref_id': ref['id'], 'native_sha256': ref['sha256'],
                                    'native_path': str(ref['path']), 'observation_id': item['id'],
                                    'kind': item['kind'], 'parent_id': item.get('parent_id'),
                                    'raw_text': item['raw_text'], 'page': page.get('page_number'),
                                    'bbox_pdf_pt': asdict(box) if box else None,
                                    'attempt_id': attempt['id'],
                                    'confidence': item.get('confidence'),
                                    'superseded': item['id'] in superseded})
        return records

    def _observation_records(self, result, tokens, ref, unit):
        records = []
        for token in tokens:
            page = token.page if ref['kind'] == 'pdf' else ref['physical_page']
            records.append({'alias': ref['id'] + '|' + token.id, 'native_ref_id': ref['id'],
                            'native_sha256': ref['sha256'], 'native_path': str(ref['path']),
                            'observation_id': token.id, 'kind': token.kind, 'parent_id': token.parent_id,
                            'raw_text': token.raw_text, 'page': page,
                            'bbox_pdf_pt': asdict(token.bbox) if token.bbox else None,
                            'attempt_id': self._attempt_of(result, token.id),
                            'confidence': token.confidence})
        return records

    def _register_declarations(self):
        declared = self.declarations.get('crop_cell_bindings', []) + \
            self.declarations.get('continuation_crop_bindings', [])
        for entry in declared:
            alias = entry['native_ref_id'] + '|' + entry['native_observation_id']
            token = self.crop_by_alias.get(alias)
            if token is None:
                raise ValueError(f'Declared crop binding is not a loaded crop observation: {alias}')
            if entry['kind'] not in ('money', 'name'):
                raise ValueError('Declared crop binding kind unsupported')
            actual = self.refs[alias]
            if entry['page'] != actual['physical_page'] or entry['raw_text'] != actual['raw_text']:
                raise ValueError('Declared crop binding page/raw differs from the observation')
            attempt = self._attempt_of(json.loads(Path(actual['native_path']).read_text()),
                                      entry['native_observation_id'])
            if entry.get('attempt_id') and entry['attempt_id'] != attempt:
                raise ValueError('Declared crop binding attempt differs from the observation')
            if not attempt or ':a0:' in attempt:
                raise ValueError('Declared crop binding must come from a retry attempt, not the owner strip')
            box = Box(*entry['source_cell_bbox_pdf_pt'])
            native_box = Box(actual['bbox_pdf_pt']['left'], actual['bbox_pdf_pt']['top'],
                             actual['bbox_pdf_pt']['right'], actual['bbox_pdf_pt']['bottom'])
            if not self.inside(native_box, box):
                raise ValueError('Declared crop observation center is outside the declared source cell')
            if entry['cell_key'] in self.crop_bindings:
                raise ValueError('Duplicate declared crop binding for a cell')
            entry = dict(entry, alias=alias, attempt_id=attempt, native_bbox=actual['native_bbox'])
            self.crop_bindings[entry['cell_key']] = entry
        for entry in self.declarations.get('logical_name_restorations', []):
            if entry['cell_key'] in self.restorations:
                raise ValueError('Duplicate declared logical name restoration')
            self.restorations[entry['cell_key']] = entry

    @staticmethod
    def inside(box, bounds):
        return box is not None and bounds.left <= box.x('center') < bounds.right and bounds.top <= box.y('center') < bounds.bottom

    def cell(self, key, page, bbox, kind, *, native_id=None, confirmed_text=None):
        bounds = Box(*bbox)
        pool = self.all_tokens if native_id else self.body_tokens
        tokens = [t for t in pool if t.page == page and self.inside(t.bbox, bounds)
                  and (native_id is None or t.id.startswith(native_id + '|'))]
        if kind == 'money':
            tokens = [t for t in tokens if MONEY_TOKEN.fullmatch(t.raw_text)]
        elif kind == 'name':
            tokens = [t for t in tokens if not MONEY_TOKEN.fullmatch(t.raw_text)]
        elif kind == 'label':
            pass
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
        if kind == 'label' and len(tokens) > 1:
            raise ValueError(f'Multiple observations in label cell {key}')
        value = observed
        if kind == 'name' and value is not None:
            value = re.sub(r'\s+', '', value)
        if confirmed_text is not None:
            if not tokens:
                raise ValueError('Source-confirmed text requires real native binding')
            value = confirmed_text
        crop_source = None
        binding = self.crop_bindings.get(key)
        if binding is not None:
            if tokens:
                raise ValueError(f'Cell {key} has full-native observations and a declared crop binding')
            if binding['page'] != page:
                raise ValueError(f'Declared crop binding page differs for {key}')
            if binding['kind'] != kind and not (kind == 'label' and binding['kind'] == 'name'):
                raise ValueError(f'Declared crop binding kind differs for {key}')
            capture = Box(*bbox)
            native_box = Box(*[self.refs[binding['alias']]['bbox_pdf_pt'][k] for k in ('left', 'top', 'right', 'bottom')])
            if not self.inside(native_box, capture):
                raise ValueError(f'Crop observation for {key} falls outside the capture ROI')
            value = binding['raw_text']
            self.used.add(binding['alias'])
            crop_source = {'native_ref_id': binding['native_ref_id'],
                           'native_sha256': self.refs[binding['alias']]['native_sha256'],
                           'native_path': self.refs[binding['alias']]['native_path'],
                           'native_observation_id': binding['native_observation_id'],
                           'attempt_id': binding['attempt_id'],
                           'source_cell_bbox_pdf_pt': binding['source_cell_bbox_pdf_pt'],
                           'source_bbox_px': binding.get('source_bbox_px'),
                           'native_bbox_pdf_pt': self.refs[binding['alias']]['native_bbox'],
                           'raw_text': binding['raw_text'], 'before': binding.get('before'),
                           'after': binding.get('after'),
                           'reason': binding.get('reason')}
        restoration = self.restorations.get(key)
        if restoration is not None:
            if (restoration['page'] != page or [t.id for t in tokens] !=
                    [restoration['native_ref_id'] + '|' + i for i in restoration['observation_ids']]):
                raise ValueError(f'Logical restoration observation binding differs for {key}')
            if restoration['native_joined'] != re.sub(r'\s+', '', observed or ''):
                raise ValueError(f'Logical restoration before-text differs for {key}')
            if '\n'.join(restoration['native_lines']) != observed:
                raise ValueError(f'Logical restoration native line breaks differ for {key}')
            value = restoration['source_observed_logical']
        status = 'observed' if tokens else ('crop-observed' if crop_source else 'unread')
        self.bindings[key] = {'physical_page': page, 'bbox_pdf_pt': bbox, 'kind': kind,
                              'observed_text': observed, 'value': value, 'status': status,
                              'native_refs': [self.refs[t.id] for t in tokens],
                              'aliases': [t.id for t in tokens],
                              'source_confirmed_text': confirmed_text,
                              'crop_source': crop_source,
                              'logical_restoration': (
                                  {'native_lines': restoration['native_lines'],
                                   'native_joined': restoration['native_joined'],
                                   'source_observed_logical': restoration['source_observed_logical'],
                                   'changed_positions': restoration['changed_positions'],
                                   'author_unicode_proven': restoration['author_unicode_proven'],
                                   'reason': restoration['reason']} if restoration is not None
                                  else ('join typeset name fragments and original wraps; native unchanged'
                                        if kind == 'name' else None))}
        self.used.update(t.id for t in tokens)
        return value


def strip_parens(text):
    return PAREN_CLOSE_TAIL.sub('', text).strip()


def build_null_reasons(row, reader):
    """Per-column NULL reason (F06): printed-page absence and unread money stay distinct."""
    reasons = {}
    for column, value in row.items():
        if value is not None:
            continue
        if column in NULL_REASONS:
            reasons[column] = NULL_REASONS[column]
            continue
        cell_key = None
        for level in LEVELS:
            if column.startswith(level + '_'):
                cell_key = 'control-0:' + column[len(level) + 1:]
                break
        cell = reader.bindings.get(cell_key) if cell_key else None
        if cell is None:
            reasons[column] = 'no source cell declared for this column'
        elif cell['status'] == 'crop-observed' and cell.get('crop_source'):
            reasons[column] = ('full-native unread; resolved by declared crop observation '
                               + cell['crop_source']['native_observation_id'])
        else:
            reasons[column] = 'native observation absent for the printed cell (unread); not zero and not a blank'
    return reasons


def metadata(layout):
    money_columns = [level + '_' + field for level in LEVELS for field in MONEY] + [
        '備考_事業金額', '備考_節金額', '備考_費目金額', '備考_末端金額']
    contexts = []
    for index, level in enumerate(LEVELS):
        grain = [ancestor + '番号' for ancestor in LEVELS[:index + 1]]
        for field in MONEY:
            contexts.append({'columns': [level + '_' + field],
                             'header_path': ['予算現額', field] if field in BUDGET else
                             (['翌年度繰越額', field] if field in RIGHT[1:4] else [field]),
                             'grain_columns': grain})
    for columns, grain in [
        (['備考_事業番号', '備考_事業名称', '備考_事業部署', '備考_事業金額'],
         ['款番号', '項番号', '目番号', '備考_事業番号']),
        (['備考_節番号', '備考_節名称', '備考_節金額'],
         ['款番号', '項番号', '目番号', '備考_事業番号', '備考_節番号']),
        (['備考_費目名称', '備考_費目金額'],
         ['款番号', '項番号', '目番号', '備考_事業番号', '備考_節番号', '備考_費目名称']),
        (['備考_末端金額'],
         ['款番号', '項番号', '目番号', '備考_事業番号', '備考_節番号', '備考_費目名称', '原典頁']),
    ]:
        contexts.append({'columns': columns, 'header_path': ['備考'], 'grain_columns': grain, 'semantic_role': 'project'})
    return {'units': [{'text': '円', 'scope': {'kind': 'columns', 'columns': money_columns}}],
            'notes': [{'text': note, 'scope': {'kind': 'table'}} for note in layout['metadata_notes']],
            'column_contexts': contexts}


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
    declarations_path = Path(options['declarations_path'])
    if digest(declarations_path) != options['declarations_sha256']:
        raise ValueError('Source declarations SHA differs')
    declarations = json.loads(declarations_path.read_text())
    reader = Reader(source['path'], options['native_refs'], json.loads(corrections_path.read_text()),
                    layout, declarations)

    budget_cols = layout['budget_columns']
    right_cols = layout['right_amount_columns']
    controls = []
    for spec in layout['parent_controls']:
        name = reader.cell(spec['id'] + ':label', spec['page'], spec['label_bbox'], 'name')
        match = CONTROL_LABEL.fullmatch(name or '')
        if not match:
            raise ValueError('Numbered parent heading is unreadable')
        values = {'number': match.group(1), 'name': match.group(2)}
        top, bottom = spec['row_band']
        for field, (x0, x1) in zip(BUDGET, budget_cols, strict=True):
            values[field] = reader.cell(spec['id'] + ':' + field, spec['page'],
                                        [x0, top, x1, bottom], 'money')
        for field, (x0, x1) in zip(RIGHT, right_cols, strict=True):
            values[field] = reader.cell(spec['id'] + ':' + field, spec['page'],
                                        [x0, top, x1, bottom], 'money')
        controls.append({'id': spec['id'], 'record_role': 'independent-printed-parent-control',
                         'level': spec['level'], 'values': values,
                         'cell_keys': [spec['id'] + ':label'] + [spec['id'] + ':' + f for f in MONEY]})

    sections = []
    for spec in layout['statutory_sections']:
        raw_label = reader.cell(spec['id'] + ':区分', 1, spec['label_bbox'], 'name')
        if raw_label is None:
            raise ValueError(f"Statutory label unreadable: {spec['id']}")
        match = SETSU_LABEL.fullmatch(raw_label)
        if not match:
            raise ValueError(f"Statutory label has no number: {spec['id']}")
        if match.group(1) != spec['number']:
            raise ValueError(f"Statutory number differs: {spec['id']}")
        record = {'id': spec['id'], 'record_role': 'statutory-section-check-only',
                  'source_order': spec['order'],
                  'parent_path': [c['values']['number'] for c in controls],
                  '区分': match.group(1) + ' ' + match.group(2)}
        record['金額'] = reader.cell(spec['id'] + ':金額', 1, spec['amount_bbox'], 'money')
        top, bottom = spec['row_band']
        for field, (x0, x1) in zip(RIGHT, right_cols, strict=True):
            record[field] = reader.cell(spec['id'] + ':' + field, 1, [x0, top, x1, bottom], 'money')
        sections.append(record)

    nodes = []
    for spec in layout['explanation_nodes']:
        raw_name = reader.cell(spec['id'] + ':name', spec['page'], spec['name_bbox'], 'name')
        raw_amount = reader.cell(spec['id'] + ':amount', spec['page'], spec['amount_bbox'], 'money')
        if raw_name is None or raw_amount is None:
            raise ValueError(f"Explanation field unreadable: {spec['id']}")
        clean_name = PAREN_OPEN_TAIL.sub('', raw_name)
        amount = strip_parens(raw_amount)
        node = dict(spec, raw_name=raw_name, amount=amount, record_role='explanation-' + spec['role'])
        node['cell_keys'] = [spec['id'] + ':name', spec['id'] + ':amount']
        if spec['role'] == 'project':
            match = PROJECT_LABEL.fullmatch(raw_name)
            if not match:
                raise ValueError('Project heading and department cannot be separated')
            node.update(number=match.group(1), name=match.group(2), department=match.group(3))
        elif spec['role'] == 'setsu':
            match = SETSU_LABEL.fullmatch(clean_name)
            if not match:
                raise ValueError('Setsu heading has no number')
            node.update(number=match.group(1), name=match.group(2))
        else:
            node.update(name=clean_name)
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
        if [n['role'] for n in chain] != ['project', 'setsu', 'leaf']:
            raise ValueError('Undeclared explanation hierarchy')
        project, setsu, leaf = chain
        row = {name: None for name in NAMES}
        cells = {}
        for control in controls:
            level, values = control['level'], control['values']
            row[level + '番号'], row[level + '名称'] = values['number'], values['name']
            cells[level + '番号'] = cells[level + '名称'] = control['id'] + ':label'
            for field in MONEY:
                row[level + '_' + field] = values[field]
                cells[level + '_' + field] = control['id'] + ':' + field
        row.update({'備考_事業番号': project['number'], '備考_事業名称': project['name'],
                    '備考_事業部署': project['department'], '備考_事業金額': project['amount'],
                    '備考_節番号': setsu['number'], '備考_節名称': setsu['name'],
                    '備考_節金額': setsu['amount'],
                    '備考_費目名称': leaf['name'], '備考_費目金額': leaf['amount'],
                    '備考_末端金額': leaf['amount'],
                    '原典頁': leaf['page'], '印字頁': None,
                    '原典終頁': leaf['page'], '印字終頁': None})
        for suffix in ('番号', '名称', '部署'):
            cells['備考_事業' + suffix] = project['id'] + ':name'
        cells['備考_事業金額'] = project['id'] + ':amount'
        cells['備考_節番号'] = cells['備考_節名称'] = setsu['id'] + ':name'
        cells['備考_節金額'] = setsu['id'] + ':amount'
        cells['備考_費目名称'], cells['備考_費目金額'] = leaf['id'] + ':name', leaf['id'] + ':amount'
        cells['備考_末端金額'] = leaf['id'] + ':amount'
        row_bindings.append({'row_index': len(rows), 'leaf_node': leaf['id'],
                             'ancestor_nodes': [n['id'] for n in chain], 'cells': cells,
                             'null_columns': [k for k, v in row.items() if v is None],
                             'null_reasons': build_null_reasons(row, reader),
                             'page_columns': {'原典頁': leaf['page'], '印字頁': None}})
        rows.append(row)

    total_spec = layout['explanation_total']
    total_values = {}
    label = reader.cell('total:name', total_spec['page'], total_spec['name_bbox'], 'name')
    if (label or '').replace(' ', '') != '歳出合計':
        raise ValueError('歳出合計 label differs')
    top, bottom = total_spec['row_band']
    for field, (x0, x1) in zip(BUDGET, budget_cols, strict=True):
        total_values[field] = reader.cell('total:' + field, total_spec['page'],
                                          [x0, top, x1, bottom], 'money')
    for field, (x0, x1) in zip(RIGHT, right_cols, strict=True):
        total_values[field] = reader.cell('total:' + field, total_spec['page'],
                                          [x0, top, x1, bottom], 'money')
    total = {'record_role': 'printed-book-total-control', 'parent_path': [],
             'label': label, 'amounts': total_values, 'physical_page': total_spec['page'],
             'affiliation': None, 'hierarchy_path': [],
             'cell_keys': ['total:name'] + ['total:' + f for f in MONEY]}

    # The declared header cells are the per-piece cells (role + meaning); the
    # broad cluster cells are intentionally not bound, to avoid double claims.
    headers = []
    # continuation restatement cells: per level, per page
    continuations = []
    for spec in layout['continuation_cells']:
        value = reader.cell(spec['id'], spec['page'], spec['bbox_pdf_pt'], 'label')
        cell = reader.bindings[spec['id']]
        continuations.append({'id': spec['id'], 'page': spec['page'], 'level': spec['level'],
                             'bbox_pdf_pt': spec['bbox_pdf_pt'], 'value': value,
                             'native_observation_ids': cell['aliases'],
                             'status': cell['status'],
                             'declared_native_observation_ids': spec['native_observation_ids'],
                             'declared_native_detected': spec['native_detected'],
                             'crop_source': cell['crop_source'],
                             'record_role': 'continuation-restatement-cell'})
        if cell['status'] == 'unread':
            raise ValueError(f'Continuation cell {spec["id"]} stays unread after declarations')
    if [c['id'] for c in continuations] != [s['id'] for s in layout['continuation_cells']]:
        raise ValueError('Continuation cell set differs from layout')
    blank_cells = []
    for spec in layout.get('confirmed_blank_cells', []):
        value = reader.cell(spec['id'], spec['page'], spec['bbox_pdf_pt'], 'header')
        if value is not None:
            raise ValueError('Declared blank source cell contains a native observation')
        reader.bindings[spec['id']].update(status='confirmed-blank', value='')
        blank_cells.append(dict(spec, value='', record_role='source-confirmed-blank',
                                null_kind='source-confirmed-blank (printed nothing)'))
    if len(blank_cells) != len(layout.get('confirmed_blank_cells', [])):
        raise ValueError('Declared blank cell set differs from layout')
    for spec in layout['footers']:
        footer = reader.cell(spec['id'], spec['page'], spec['bbox_pdf_pt'], 'header')
        if (footer or '').replace(' ', '') != layout['running_label']:
            raise ValueError('Running footer differs from declared 款 label')
    # header pieces: role/meaning for every printed header, unit and marginalia piece
    header_pieces = []
    for spec in layout.get('header_pieces', []):
        observed = reader.cell(spec['id'], spec['page'], spec['bbox_pdf_pt'], 'header')
        cell = reader.bindings[spec['id']]
        if (observed or '') != spec['raw_text']:
            raise ValueError(f'Header piece text differs: {spec["id"]}')
        header_pieces.append({'id': spec['id'], 'page': spec['page'], 'role': spec['role'],
                              'meaning': spec['meaning'], 'raw_text': spec['raw_text'],
                              'native_observation_ids': cell['aliases'],
                              'status': cell['status']})
    if len(header_pieces) != len(layout.get('header_pieces', [])):
        raise ValueError('Header piece set differs from layout')
    word_ids_in_header = sum(1 for o in reader.observations
                             if o['kind'] != 'region' and o['page'] in layout['physical_pages']
                             and o['bbox_pdf_pt'] is not None
                             and o['bbox_pdf_pt']['bottom'] <= 130.0)

    dictionary_checks = []
    for role, path in layout['name_dictionaries'].items():
        dictionary = load_name_dictionary(Path(path))
        names = [c['values']['name'] for c in controls] if role == 'subject' else [
            re.sub(r'^\d+\s*', '', s['区分'] or '') for s in sections]
        for name in names:
            result = correct_name_preserving_layout(name, dictionary)
            if result['corrected_name'] != name:
                raise ValueError('New dictionary correction requires source-confirmed review; do not infer source spelling')
            dictionary_checks.append({'role': role, 'name': name, 'path': path,
                                      'sha256': digest(path), 'applied': False})

    # ---- Full native partition: every observation, every level (F04).
    cell_of_alias = {}
    for key, cell in reader.bindings.items():
        for alias in cell['aliases']:
            if alias in cell_of_alias:
                raise ValueError('Native region claimed by two cells')
            cell_of_alias[alias] = key
    for alias in reader.used:
        if alias.startswith('crop') and alias not in cell_of_alias:
            cell_of_alias[alias] = next(
                k for k, v in reader.crop_bindings.items() if v['alias'] == alias)
    marginalia, classification_rows = [], []
    remaining = []
    for record in reader.observations:
        ref = reader.refs[record['alias']]
        box = record['bbox_pdf_pt']
        y = (box['top'] + box['bottom']) / 2 if box else None
        raw = record['raw_text']
        kind = record['kind']
        page = record['page']
        is_crop = record['native_ref_id'] in reader.crop_ref_ids
        header_piece = next((h for h in header_pieces
                             if record['observation_id'] in h['native_observation_ids']), None)
        if record['alias'] in cell_of_alias:
            classification = 'bound-source-cell'
            detail = cell_of_alias[record['alias']]
        elif is_crop:
            if record.get('superseded'):
                classification = 'superseded-crop-observation'
                detail = (record['attempt_id'] or '') + '; replaced by a declared retry in the same region'
            elif record['attempt_id'] and record['attempt_id'].endswith(':a0'):
                classification = 'unused-crop-owner-strip-observation'
                detail = (record['attempt_id'] or '') + '; base strip observation not adopted for a cell'
            else:
                classification = 'unused-crop-observation'
                detail = (record['attempt_id'] or '') + '; crop observation not adopted for a cell'
        elif header_piece is not None:
            classification = 'bound-source-cell'
            detail = header_piece['meaning']
        elif kind == 'region' and raw in ('(', '（', 'C', 'Ｃ', ')', '）') and box is not None and (box['left'] + box['right']) / 2 >= 740:
            classification = 'bikou-paren-fragment-not-a-cell'
            detail = 'printed setsu subtotal parenthesis'
        elif kind == 'region' and raw == '円':
            classification = 'unit-glyph-in-body'
            detail = 'printed unit glyph 円 inside the table body; not a cell value'
        elif kind != 'region' and record['parent_id']:
            parent_alias = record['alias'].split('|')[0] + '|' + record['parent_id']
            parent_bound = parent_alias in cell_of_alias
            classification = 'child-of-bound-source-cell' if parent_bound else 'child-of-marginalia'
            detail = ('parent ' + parent_alias + ' ' +
                      (str(cell_of_alias[parent_alias]) if parent_bound else 'marginalia') +
                      '; numeric sub-token, never an independent amount row')
        elif kind != 'region':
            classification = 'marginalia-child-observation'
            detail = 'word/number sub-token of a marginalia region'
        elif y is not None and (box['bottom'] <= HEADER_ZONE_BOTTOM or y > 548):
            classification = 'page-title-header-unit-or-footer'
            detail = 'printed furniture'
        else:
            classification = 'unassigned-body-observation'
            detail = None
            marginalia.append(dict(ref, classification=classification))
        if classification not in KNOWN_CLASSIFICATIONS:
            raise ValueError(f'Unknown observation classification: {classification}')
        classification_rows.append({'alias': record['alias'], 'native_ref_id': record['native_ref_id'],
                                    'native_sha256': record['native_sha256'],
                                    'native_observation_id': record['observation_id'],
                                    'kind': kind, 'parent_observation_id': record['parent_id'],
                                    'raw_text': raw, 'physical_page': page,
                                    'bbox_pdf_pt': box, 'attempt_id': record['attempt_id'],
                                    'classification': classification, 'detail': detail})
    if marginalia:
        raise ValueError(f'{len(marginalia)} observations unassigned: '
                         + '; '.join(f"{m['native_observation_id']}@{m['physical_page']} "
                                     f"{m['raw_text']!r} y={(m.get('bbox_pdf_pt') or {}).get('top')}"
                                     for m in marginalia[:20]))
    for alias, ref in reader.refs.items():
        rows_for_alias = [c for c in classification_rows if c['alias'] == alias]
        ref['classifications'] = [r['classification'] for r in rows_for_alias] or ['not-classified']
        ref['binding_cells'] = [r['detail'] for r in rows_for_alias
                                if r['classification'] == 'bound-source-cell']
    observation_counts = {}
    for row in classification_rows:
        observation_counts[row['classification']] = observation_counts.get(row['classification'], 0) + 1

    # ---- width-only source-reason declarations (F09)
    width_only = []
    for row in rows:
        for column, value in row.items():
            if isinstance(value, str) and unicodedata.normalize('NFKC', value) != value:
                width_only.append({'row_index': len(width_only), 'column': column,
                                   'value': value,
                                   'nfkc': unicodedata.normalize('NFKC', value),
                                   'reason': 'full/half width or variant form read from the scan; author encoding is not determinable; no bulk normalization applied'})

    table_metadata = metadata(layout)
    applied_declarations = {}
    applied_declarations['geometry_semantics'] = layout.get('geometry_semantics')
    applied_declarations['observation_partition'] = {
        'total': len(classification_rows),
        'by_classification': observation_counts,
        'native_region_word_number': {
            'region': sum(1 for r in classification_rows if r['kind'] == 'region'),
            'word': sum(1 for r in classification_rows if r['kind'] == 'word'),
            'number': sum(1 for r in classification_rows if r['kind'] == 'number')},
        'word_number_in_header_zone': word_ids_in_header,
        'numeric_sub_tokens_are_independent_rows': False,
        'header_pieces': len(header_pieces),
        'unit_pieces': sum(1 for h in header_pieces if h['role'] == 'unit'),
        'marginalia_pieces': sum(1 for h in header_pieces if h['role'] == 'marginalia'),
        'declared_blank_source_cells': len(blank_cells),
        'continuation_cells_resolved': len(continuations),
        'crop_cells_adopted': len(set(reader.crop_bindings)),
    }
    applied_declarations['source_reason_declarations'] = {
        'width_only_differences': {'count': len(width_only), 'items': width_only,
                                   'reconciliation_note': 'values whose NFKC form differs; declared as source reason, no normalization'},
        'pending_glyph_declarations': declarations.get('pending_glyph_declarations', []),
        'logical_name_restorations': [{'cell_key': k, 'native_joined': v['native_joined'],
                                       'source_observed_logical': v['source_observed_logical'],
                                       'author_unicode_proven': v['author_unicode_proven'],
                                       'reason': v['reason']}
                                      for k, v in reader.restorations.items()],
        'header_correspondence': declarations.get('header_correspondence', []),
        'corrections_policy': 'no bulk NFKC/width normalization; no dictionary promotion for unproven glyphs; scoped declarations only',
    }
    if {c['alias'] for c in reader.corrected} != set(reader.corrections):
        raise ValueError('Unused source correction')
    if {v['alias'] for v in reader.crop_bindings.values()} - reader.used:
        raise ValueError('Unused declared crop binding')
    if set(reader.restorations) - set(reader.bindings):
        raise ValueError('Unused logical name restoration')
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
        'confirmed_blank_cells': blank_cells, 'declared_blank_source_cells': blank_cells,
        'broad_capture_zones': layout.get('broad_capture_zones', []),
        'header_pieces': header_pieces, 'headers': headers,
        'crop_cell_bindings': {k: v for k, v in reader.crop_bindings.items()},
        'marginalia': marginalia, 'unassigned': remaining})
    save(destination / 'bindings.json', {'cells': reader.bindings, 'rows': row_bindings,
        'all_region_observations': reader.refs, 'unassigned': remaining,
        'observation_partition': classification_rows})
    save(destination / 'headers.json', headers)
    save(destination / 'header-pieces.json', header_pieces)
    save(destination / 'metadata.json', table_metadata)
    save(destination / 'applied-declarations.json', applied_declarations)
    save(destination / 'receipt.json', {'source_sha256': source['sha256'], 'scope': source['scope'],
        'origin_physical_pages': layout['physical_pages'], 'printed_pages': layout['printed_pages'],
        'layout_sha256': digest(layout_path), 'converter_sha256': digest(__file__),
        'source_declarations_sha256': digest(declarations_path),
        'corrections_sha256': digest(corrections_path), 'native_inventory': reader.native_inventory,
        'table': asdict(result), 'metadata': table_metadata,
        'applied_declarations_path': 'applied-declarations.json',
        'schema': [{'name': name, 'type': 'BIGINT' if name in ('原典頁', '原典終頁') else 'VARCHAR'} for name in NAMES],
        'row_grain': 'finest bikou leaf per row; parent references repeated and nonadditive; 備考_末端金額 is the only additive column',
        'row_count': len(rows), 'rows_per_project': {p['number']: sum(r['備考_事業番号'] == p['number'] for r in rows) for p in nodes if p['role'] == 'project'},
        'local_corrections': reader.corrected, 'dictionary_checks': dictionary_checks,
        'unread': [k for k, v in reader.bindings.items() if v['status'] == 'unread'],
        'crop_observed_cells': [k for k, v in reader.bindings.items() if v['status'] == 'crop-observed'],
        'observation_partition_counts': observation_counts,
        'width_only_declaration_count': len(width_only),
        'unassigned': remaining, 'elapsed_seconds': time.perf_counter() - started, 'pid': os.getpid(),
        'ocr_executed': False, 'candidate_number': options.get('table_id', 'details'),
        'canonical_classification_applied': False})
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
