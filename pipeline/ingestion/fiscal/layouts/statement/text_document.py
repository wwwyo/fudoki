"""Assemble a complete measured text-PDF statement across continuation spreads."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import subprocess

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn
from ingestion.lib.pdf_table import tokens_from_bbox_layout
from ingestion.fiscal.layouts.statement.text_spread import encoded, inside, read_tables


AMOUNT = re.compile(r'(?:△|-)?[0-9][0-9,]*')
MOKU_FIELDS = ('moku', 'current', 'previous', 'difference', 'national', 'loan', 'other', 'general')


def lines(tokens, tolerance=1):
    """Group physical baselines, including the half-point numeric font offset."""
    result = []
    for token in sorted(tokens, key=lambda t: (t.bbox.top, t.bbox.left, t.id)):
        if not result or abs(token.bbox.top - result[-1][0].bbox.top) > tolerance:
            result.append([])
        result[-1].append(token)
    return [sorted(row, key=lambda t: (t.bbox.left, t.id)) for row in result]


def cell_text(tokens):
    return ''.join(t.raw_text for t in tokens) if tokens else None


def build_document(xml, *, origin_id, pages, profile):
    """Use independent printed columns; only the moku span crosses the spread."""
    if pages[0] % 2 or pages[1] % 2 != 1:
        raise ValueError('The measured statement starts on a left page and ends on a right page')
    tokens = tokens_from_bbox_layout(xml, origin_id=origin_id, first_page=pages[0])
    if {t.page for t in tokens} != set(range(pages[0], pages[1] + 1)):
        raise ValueError('Requested physical page coverage differs')
    by_page = {p: [t for t in tokens if t.page == p] for p in range(pages[0], pages[1] + 1)}
    tables = {name: [] for name in ('headers', 'context', 'moku', 'moku_occurrences', 'funding',
                                  'setsu', 'explanation', 'totals', 'words', 'detail_index')}
    owners = {}
    bindings = {}
    moku_by_key = {}
    stacks = {}
    pending = {}
    active_setsu = {}
    funding_pending = {}
    column_by_key = {c['key']: c for c in profile['columns']}

    def claim(words, row, field):
        for t in words:
            if t.id in owners:
                raise ValueError(f'Duplicate word ownership: {t.id}')
            owners[t.id] = (row['row_id'], field)

    def record(table, fields, *, moku=None, extra=None):
        ident = f'{table}:{len(tables[table]) + 1}'
        all_words = [t for v in fields.values() for t in v]
        row = {'row_id': ident, 'moku_id': moku['row_id'] if moku else None,
               'page': all_words[0].page if all_words else None,
               'printed_page': all_words[0].page - 4 if all_words else None,
               **{name: cell_text(v) for name, v in fields.items()},
               'cell_token_ids': encoded({name: [t.id for t in v] for name, v in fields.items()}),
               'bbox': encoded([min(t.bbox.left for t in all_words), min(t.bbox.top for t in all_words),
                                max(t.bbox.right for t in all_words), max(t.bbox.bottom for t in all_words)]) if all_words else None,
               **(extra or {})}
        for field, words in fields.items():
            claim(words, row, field)
        tables[table].append(row)
        return row

    def append(row, field, words):
        refs = json.loads(row['cell_token_ids'])
        refs.setdefault(field, []).extend(t.id for t in words)
        row[field] = (row[field] or '') + (cell_text(words) or '')
        row['cell_token_ids'] = encoded(refs)
        claim(words, row, field)
        box = json.loads(row['bbox'])
        if words and words[0].page == row['page']:
            box = [min(box[0], min(t.bbox.left for t in words)), min(box[1], min(t.bbox.top for t in words)),
                   max(box[2], max(t.bbox.right for t in words)), max(box[3], max(t.bbox.bottom for t in words))]
            row['bbox'] = encoded(box)

    def cells(row, keys):
        result = {k: [] for k in keys}
        for t in row:
            matching = [k for k in keys if column_by_key[k]['left'] <= t.bbox.left < column_by_key[k]['right']]
            if len(matching) != 1:
                raise ValueError(f'Unknown column: {t.id}')
            result[matching[0]].append(t)
        return result

    def close_moku(moku):
        if moku['row_id'] in pending:
            raise ValueError(f'Unresolved explanation continuation at moku boundary: {moku["row_id"]}')
        for node in stacks.get(moku['row_id'], []):
            node['closure'] = 'closed_in_scope'
        stacks[moku['row_id']] = []

    def annotations(moku, cs):
        funding_open = funding_pending.setdefault(moku['row_id'], {})
        for key in ('national', 'loan', 'other'):
            words = cs[key]
            if not words:
                continue
            text = cell_text(words)
            if AMOUNT.fullmatch(text):
                entry = funding_open.pop(key, None)
                if entry is None:
                    raise ValueError(f'Funding amount without name: {words[0].id}')
                append(entry, 'amount_raw', words)
            elif key in funding_open:
                append(funding_open[key], 'name_raw', words)
            else:
                funding_open[key] = record('funding', {'name_raw': words, 'amount_raw': []}, moku=moku,
                                           extra={'column_key': key})

    def add_explanation(moku, names, amounts):
        levels = profile['explanation_levels']
        left = min(t.bbox.left for t in names)
        matches = [i for i, level in enumerate(levels) if abs(left - level['name_left']) <= profile['geometry_tolerance']]
        if len(matches) != 1:
            raise ValueError(f'Unknown explanation indentation: {names[0].id}')
        depth = matches[0]
        if amounts and abs(max(t.bbox.right for t in amounts) - levels[depth]['amount_right']) > profile['geometry_tolerance']:
            raise ValueError(f'Explanation name/amount alignment differs: {names[0].id}')
        stack = stacks.setdefault(moku['row_id'], [])
        while len(stack) > depth:
            stack.pop()['closure'] = 'closed_in_scope'
        if len(stack) != depth:
            raise ValueError(f'Explanation has no observed parent: {names[0].id}')
        node = record('explanation', {'name_raw': names, 'amount_raw': amounts}, moku=moku,
                      extra={'depth': depth, 'role': levels[depth]['name'],
                             'parent_id': stack[-1]['row_id'] if stack else None,
                             'closure': 'open_at_scope_end'})
        stack.append(node)
        if not amounts:
            pending[moku['row_id']] = node

    current = None
    for left_page in range(pages[0], pages[1] + 1, 2):
        pair = (left_page, left_page + 1)
        pair_words = [*by_page[pair[0]], *by_page[pair[1]]]
        context_values = {}
        for region in profile['regions']:
            bounds = list(region['bbox'])
            if region['id'] in ('kan', 'kou'):
                bounds[2] = 538
            elif region['id'] == 'repeated_kan':
                bounds[0], bounds[2] = 56, 545
            words = [t for t in by_page[pair[region['page_side']]] if inside(t.bbox, bounds)]
            words = [t for row in lines(words) for t in row]
            text = cell_text(words)
            # Direction occurs once; footer may list several kan on the last spread.
            required = region['kind'] in ('header', 'unit', 'printed_page') or region['id'] in ('kan', 'kou')
            if required and not words:
                raise ValueError(f'Missing measured header: {left_page}, {region["id"]}')
            if words and region['expected'] is not None and text != region['expected']:
                raise ValueError(f'Original heading differs: {left_page}, {region["id"]}, {text}')
            if words:
                table = 'headers' if region['kind'] in ('header', 'unit') else 'context'
                r = record(table, {'raw_text': words}, extra={'region_id': region['id'],
                           'parent_id': region['parent'], 'kind': region['kind']})
                context_values[region['id']] = text
                if region['kind'] == 'printed_page':
                    matched = re.fullmatch(r'－([0-9]+)－', text)
                    if not matched or int(matched.group(1)) != r['printed_page']:
                        raise ValueError('Physical/printed page relation differs')
        if not bindings:
            regions = {r['id']: r for r in profile['regions']}
            def header_path(ident):
                parent = regions[ident]['parent']
                return [*header_path(parent), context_values[ident]] if parent else [context_values[ident]]
            bindings = {c['key']: {'header_path': header_path(c['header']),
                        'unit': next((context_values[r['id']] for r in profile['regions']
                                     if r['kind'] == 'unit' and r['parent'] == c['header']), None)}
                        for c in profile['columns']}
        kan, kou = context_values['kan'], context_values['kou']
        body = {p: [t for t in by_page[p] if t.id not in owners and
                    profile['body_top'] <= t.bbox.top < profile['body_bottom']] for p in pair}
        spans = []
        occurrence = None
        for row in lines(body[left_page]):
            y = min(t.bbox.top for t in row)
            raw_text = cell_text(row)
            if raw_text.startswith('第') and any(t.raw_text == '款' for t in row):
                kan = raw_text
                record('context', {'raw_text': row}, extra={'region_id': 'kan', 'parent_id': None, 'kind': 'context'})
                continue
            if raw_text.startswith('第') and any(t.raw_text == '項' for t in row):
                kou = raw_text
                record('context', {'raw_text': row}, extra={'region_id': 'kou', 'parent_id': None, 'kind': 'context'})
                continue
            cs = cells(row, MOKU_FIELDS)
            label = cell_text(cs['moku'])
            if label == '計':
                record('totals', {k + '_raw': v for k, v in cs.items()}, extra={'kan_raw': kan, 'kou_raw': kou})
                continue
            number = next((t for t in cs['moku'] if t.bbox.left < 72 and re.fullmatch('[0-9]+', t.raw_text)), None)
            if number or (cs['moku'] and cs['current']):
                code = number.raw_text if number else None
                key = (kan, kou, code if code is not None else label)
                if cs['current']:
                    if key in moku_by_key:
                        raise ValueError(f'Repeated moku amount: {key}')
                    current = record('moku', {k + '_raw': v for k, v in cs.items()},
                                     extra={'kan_raw': kan, 'kou_raw': kou, 'code_raw': code})
                    current['moku_id'] = current['row_id']
                    moku_by_key[key] = current
                    occurrence = None
                else:
                    current = moku_by_key.get(key)
                    if current is None:
                        raise ValueError(f'Continuation moku has no initial amount: {key}')
                    occurrence = record('moku_occurrences', {'moku_raw': cs['moku']}, moku=current,
                                        extra={'kan_raw': kan, 'kou_raw': kou})
                    if any(cs[k] for k in ('previous', 'difference', 'general')):
                        raise ValueError('Unexpected continuation budget values')
                    annotations(current, cs)
                spans.append((y, current))
                continue
            if current is None:
                raise ValueError(f'Body before moku: {row[0].id}')
            if cs['moku']:
                append(occurrence or current, 'moku_raw', cs['moku'])
            if any(cs[k] for k in ('current', 'previous', 'difference', 'general')):
                raise ValueError(f'Unexpected unlabelled amount row: {row[0].id}')
            annotations(current, cs)
        if not spans:
            raise ValueError(f'No moku in spread: {left_page}')
        for row in lines(body[pair[1]]):
            y = min(t.bbox.top for t in row)
            matches = [m for start, m in spans if start <= y + 1]
            if not matches:
                raise ValueError(f'Right-page body before moku: {row[0].id}')
            moku = matches[-1]
            if tables['explanation'] and tables['explanation'][-1]['moku_id'] != moku['row_id']:
                previous = next(m for m in tables['moku'] if m['row_id'] == tables['explanation'][-1]['moku_id'])
                close_moku(previous)
            statutory = [t for t in row if t.bbox.left < column_by_key['explanation_name']['left']]
            explanation = [t for t in row if t not in statutory]
            if statutory:
                cs = cells(statutory, ('setsu_code', 'setsu_name', 'setsu_amount'))
                if cs['setsu_code']:
                    if not cs['setsu_name'] or not cs['setsu_amount']:
                        raise ValueError(f'Incomplete statutory section: {statutory[0].id}')
                    entry = record('setsu', {'code_raw': cs['setsu_code'], 'name_raw': cs['setsu_name'],
                                             'amount_raw': cs['setsu_amount']}, moku=moku)
                    active_setsu[moku['row_id']] = entry
                elif cs['setsu_name'] and not cs['setsu_amount']:
                    entry = active_setsu.get(moku['row_id'])
                    if entry is None:
                        raise ValueError('Statutory name continuation has no preceding section')
                    append(entry, 'name_raw', cs['setsu_name'])
                else:
                    raise ValueError(f'Unconfirmed statutory continuation: {statutory[0].id}')
            if explanation:
                amounts = [t for t in explanation if AMOUNT.fullmatch(t.raw_text) and any(
                           abs(t.bbox.right - lv['amount_right']) <= profile['geometry_tolerance']
                           for lv in profile['explanation_levels'])]
                names = [t for t in explanation if t not in amounts]
                waiting = pending.get(moku['row_id'])
                if waiting:
                    if amounts and abs(max(t.bbox.right for t in amounts) -
                                       profile['explanation_levels'][waiting['depth']]['amount_right']) > profile['geometry_tolerance']:
                        raise ValueError(f'Continuation amount indentation differs: {explanation[0].id}')
                    if names and abs(min(t.bbox.left for t in names) -
                                     profile['explanation_levels'][waiting['depth']]['name_left']) > profile['geometry_tolerance']:
                        raise ValueError(f'Continuation name indentation differs: {explanation[0].id}')
                    if names:
                        append(waiting, 'name_raw', names)
                    if amounts:
                        append(waiting, 'amount_raw', amounts)
                        pending.pop(moku['row_id'])
                elif names:
                    add_explanation(moku, names, amounts)
                else:
                    raise ValueError(f'Amount-only explanation without name: {explanation[0].id}')
        for t in pair_words:
            if t.id not in owners:
                raise ValueError(f'Unassigned original word: {t.id}, {t.raw_text!r}')
    for moku in tables['moku']:
        close_moku(moku)
    if any(funding_pending.values()):
        raise ValueError('Unresolved funding continuation at document end')
    for t in tokens:
        owner, field = owners[t.id]
        tables['words'].append({'token_id': t.id, 'page': t.page, 'printed_page': t.page - 4,
                                'raw_text': t.raw_text,
                                'bbox': encoded([t.bbox.left, t.bbox.top, t.bbox.right, t.bbox.bottom]),
                                'owner_id': owner, 'field': field})
    return tables, bindings


def assemble_document(tables, bindings):
    """Flatten observed parent paths and independent moku funding annotations."""
    nodes = {n['row_id']: n for n in tables['explanation']}
    parents = {n['parent_id'] for n in nodes.values()}
    funding_keys = ('national', 'loan', 'other')
    counts = {key: max((sum(f['moku_id'] == m['row_id'] and f['column_key'] == key for f in tables['funding'])
                        for m in tables['moku']), default=0) for key in funding_keys}
    max_depth = max((n['depth'] for n in nodes.values()), default=-1) + 1
    fields = ['款', '項', *[bindings[k]['header_path'][-1] for k in MOKU_FIELDS]]
    for key in funding_keys:
        label = bindings[key]['header_path'][-1]
        for i in range(1, counts[key] + 1):
            fields.extend([f'{label}_内訳{i}_名称', f'{label}_内訳{i}_金額'])
    for i in range(1, max_depth + 1):
        fields.extend([f'説明{i}_名称', f'説明{i}_金額'])
    rows, index, no_explanation = [], [], []
    for moku in tables['moku']:
        base = dict.fromkeys(fields)
        base.update({'款': moku['kan_raw'], '項': moku['kou_raw']})
        base.update({bindings[k]['header_path'][-1]: moku[k + '_raw'] for k in MOKU_FIELDS})
        for key in funding_keys:
            label = bindings[key]['header_path'][-1]
            for i, f in enumerate((f for f in tables['funding'] if f['moku_id'] == moku['row_id'] and f['column_key'] == key), 1):
                base[f'{label}_内訳{i}_名称'] = f['name_raw']
                base[f'{label}_内訳{i}_金額'] = f['amount_raw']
        terminals = [n for n in nodes.values() if n['moku_id'] == moku['row_id'] and n['row_id'] not in parents]
        if not terminals:
            rows.append(base)
            no_explanation.append(moku['row_id'])
            index.append({'raw_row': len(rows), 'moku_id': moku['row_id'], 'explanation_id': None,
                          'setsu_id': None, 'path_ids': encoded([]), 'grain': 'moku_without_explanation'})
            continue
        statutory = {}
        for s in tables['setsu']:
            if s['moku_id'] == moku['row_id']:
                if s['name_raw'] in statutory:
                    raise ValueError('Ambiguous statutory name within moku')
                statutory[s['name_raw']] = s
        for terminal in terminals:
            if terminal['closure'] != 'closed_in_scope':
                raise ValueError('Explanation leaf is still open at scope end')
            path, active = [], terminal
            while active is not None:
                path.append(active)
                active = nodes[active['parent_id']] if active['parent_id'] else None
            path.reverse()
            section_nodes = [n for n in path if n['role'] == 'setsu']
            if len(section_nodes) != 1 or section_nodes[0]['name_raw'] not in statutory:
                raise ValueError(f'Explanation section not independently observed: {terminal["row_id"]}')
            row = dict(base)
            for n in path:
                row[f'説明{n["depth"] + 1}_名称'] = n['name_raw']
                row[f'説明{n["depth"] + 1}_金額'] = n['amount_raw']
            rows.append(row)
            index.append({'raw_row': len(rows), 'moku_id': moku['row_id'], 'explanation_id': terminal['row_id'],
                          'setsu_id': statutory[section_nodes[0]['name_raw']]['row_id'],
                          'path_ids': encoded([n['row_id'] for n in path]), 'grain': 'explanation_terminal'})
    tables['detail_index'] = index
    units, contexts = [], []
    grain = ['款', '項', '目']
    for key in MOKU_FIELDS:
        label = bindings[key]['header_path'][-1]
        contexts.append({'columns': [label], 'header_path': bindings[key]['header_path'][:-1], 'grain_columns': grain})
        if bindings[key]['unit']:
            units.append({'text': bindings[key]['unit'], 'scope': {'kind': 'columns', 'columns': [label]}})
    for key in funding_keys:
        label = bindings[key]['header_path'][-1]
        for i in range(1, counts[key] + 1):
            name, amount = f'{label}_内訳{i}_名称', f'{label}_内訳{i}_金額'
            contexts.append({'columns': [name, amount], 'header_path': bindings[key]['header_path'],
                             'grain_columns': [*grain, name]})
            units.append({'text': bindings[key]['unit'], 'scope': {'kind': 'columns', 'columns': [amount]}})
    for depth in range(max_depth):
        name, amount = f'説明{depth + 1}_名称', f'説明{depth + 1}_金額'
        ctx = {'columns': [name, amount], 'header_path': bindings['explanation_name']['header_path'],
               'grain_columns': [*grain, *[f'説明{i + 1}_名称' for i in range(depth + 1)]]}
        roles = {n['role'] for n in nodes.values() if n['depth'] == depth}
        if len(roles) == 1 and roles <= {'project', 'setsu'}:
            ctx['semantic_role'] = next(iter(roles))
        contexts.append(ctx)
        units.append({'text': bindings['explanation_amount']['unit'], 'scope': {'kind': 'columns', 'columns': [amount]}})
    notes = [{'text': '目と説明内の親金額、財源内訳は所属する末端明細に反復する。財源内訳を説明明細へ配賦していない。',
              'scope': {'kind': 'table'}}]
    if no_explanation:
        descriptions = ['／'.join((m['kan_raw'], m['kou_raw'], m['moku_raw'])) for m in tables['moku'] if m['row_id'] in no_explanation]
        notes.append({'text': '説明欄に文字・金額がない目は、原典で確認できる最小粒度である目を1行に保持し、説明列はNULLとする。対象: ' + '、'.join(descriptions),
                      'scope': {'kind': 'table'}})
    return rows, {'units': units, 'notes': notes, 'column_contexts': contexts}


def convert_document(source, destination, *, origin_sha256, profile_path, pages, table_id='expenditure', observation_ranges=()):
    """Create a new candidate and compare every saved original word and raw row."""
    def digest():
        with source.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest() != origin_sha256:
        raise ValueError('Original SHA differs')
    destination.mkdir(parents=True, exist_ok=False)
    xml_path = destination / 'words.xhtml'
    subprocess.run(['pdftotext', '-f', str(pages[0]), '-l', str(pages[1]), '-bbox-layout', str(source), str(xml_path)], check=True)
    xml = xml_path.read_bytes()
    profile = json.loads(profile_path.read_text())
    tables, bindings = build_document(xml, origin_id=origin_sha256, pages=pages, profile=profile)
    rows, metadata = assemble_document(tables, bindings)
    if observation_ranges:
        controls = []
        for first, last in observation_ranges:
            if first <= pages[1] and last >= pages[0]:
                raise ValueError('Independent control pages overlap detail pages')
            control_path = destination / f'control-{first}-{last}.xhtml'
            subprocess.run(['pdftotext', '-f', str(first), '-l', str(last), '-bbox-layout', str(source), str(control_path)], check=True)
            for t in tokens_from_bbox_layout(control_path.read_bytes(), origin_id=origin_sha256, first_page=first):
                controls.append({'token_id': t.id, 'page': t.page, 'printed_page': t.page - 4,
                                 'raw_text': t.raw_text,
                                 'bbox': encoded([t.bbox.left, t.bbox.top, t.bbox.right, t.bbox.bottom])})
        tables['control_words'] = controls
    from ingestion.fiscal.manifest import validate_metadata
    validate_metadata(metadata, list(rows[0]))
    outputs = {}
    for name, records in tables.items():
        fields = list(dict.fromkeys(field for r in records for field in r))
        if not fields:
            fields = ['row_id']
        numeric = {'page', 'printed_page', 'depth', 'raw_row'}
        normalized = [{key: r.get(key) for key in fields} for r in records]
        outputs[name] = write_conversion(destination / (name + '.parquet'), normalized,
                       columns=[ParquetColumn(k, 'INTEGER' if k in numeric else 'VARCHAR') for k in fields],
                       context=ConversionContext(origin_sha256, name, 'ingestion.fiscal.layouts.statement.text_document',
                                                 layout_ref=str(profile_path)))
    raw = write_conversion(destination / (table_id + '.parquet'), rows,
                           columns=[ParquetColumn(k) for k in rows[0]],
                           context=ConversionContext(origin_sha256, table_id, 'ingestion.fiscal.layouts.statement.text_document',
                                                     layout_ref=str(profile_path)))
    saved = read_tables(destination, [*tables, table_id])
    for name, records in tables.items():
        fields = list(dict.fromkeys(field for r in records for field in r)) or ['row_id']
        if saved[name] != [{key: r.get(key) for key in fields} for r in records]:
            raise ValueError(f'Saved original observation differs: {name}')
    if saved[table_id] != rows:
        raise ValueError('Saved raw table differs from assembled original values')
    rebuilt_tables, rebuilt_bindings = build_document(xml, origin_id=origin_sha256, pages=pages, profile=profile)
    rebuilt_rows, rebuilt_metadata = assemble_document(rebuilt_tables, rebuilt_bindings)
    if rebuilt_rows != saved[table_id] or rebuilt_metadata != metadata:
        raise ValueError('Saved original hierarchy differs')
    if saved['words'] != rebuilt_tables['words'] or len({w['token_id'] for w in saved['words']}) != len(saved['words']):
        raise ValueError('Saved original word identity/text/position differs')
    if digest() != origin_sha256:
        raise ValueError('Original changed during conversion')
    report = {'scope': {'physical_pages': list(pages), 'processed_pages': list(range(pages[0], pages[1] + 1)),
                        'unprocessed_pages': [], 'direction': 'expenditure'},
              'preservation': {'original_words': len(saved['words']), 'unassigned_words': 0, 'duplicate_word_uses': 0,
                               'readback_rows_equal': True, 'observation_readback_equal': True},
              'observations': {k: asdict(v) for k, v in outputs.items()},
              'raw': {'conversion': asdict(raw), 'metadata': metadata, 'columns': list(rows[0])},
              'grain_counts': dict(Counter(r['grain'] for r in tables['detail_index'])),
              'pending': [], 'content_validation': 'parent_agent_required'}
    (destination / 'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def convert(inputs, destination, options):
    """Existing ingestion management converter contract; no registry or storage writes."""
    if len(inputs) != 1 or inputs[0]['format'] != 'pdf' or inputs[0]['direction'] != 'expenditure':
        raise ValueError('Measured document needs one expenditure PDF')
    source = inputs[0]
    if len(source['scope']) != 1 or source['pdf_type'] != 'text':
        raise ValueError('Measured document needs one account text scope')
    ranges = source['scope'][0]['pages']
    detail_pages = options.get('detail_pages')
    if detail_pages is None:
        if len(ranges) != 1:
            raise ValueError('Noncontinuous scope requires explicit detail_pages')
        detail_pages = ranges[0]
    if detail_pages not in ranges:
        raise ValueError('Detail pages must be an explicit supplied scope range')
    from ingestion.fiscal.manifest import code_path
    report = convert_document(source['path'], destination / options['table_id'], origin_sha256=source['sha256'],
                              profile_path=code_path(options['profile']), pages=tuple(detail_pages),
                              table_id=options['table_id'], observation_ranges=[r for r in ranges if r != detail_pages])
    return {options['table_id']: {'path': Path(report['raw']['conversion']['path']), 'metadata': report['raw']['metadata']}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--pages', type=int, nargs=2, required=True)
    parser.add_argument('--observation-pages', type=int, nargs=2, action='append', default=[])
    parser.add_argument('--origin-sha256', required=True)
    args = parser.parse_args()
    report = convert_document(args.source, args.output, origin_sha256=args.origin_sha256,
                              profile_path=args.profile, pages=tuple(args.pages), observation_ranges=args.observation_pages)
    print(encoded({'rows': report['raw']['conversion']['row_count'], 'columns': len(report['raw']['columns']),
                   'pages': len(report['scope']['processed_pages']), 'observations': {k: v['row_count'] for k, v in report['observations'].items()},
                   'report': str(args.output / 'checks.json')}))


if __name__ == '__main__':
    main()
