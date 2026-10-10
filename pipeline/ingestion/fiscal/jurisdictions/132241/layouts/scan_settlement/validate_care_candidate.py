"""Independently compare care-account scan tables against frozen original-image readings.

The reference is supplied separately by the original-image reviewer. This
module does not import the construction module or use OCR as ground truth.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from copy import deepcopy

import duckdb
from jsonschema import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[6]))
from ingestion.fiscal.manifest import validate_metadata

LEVELS = ('款', '項', '目')
BUDGET = ('当初予算額', '補正予算額', '継続費及び繰越事業費繰越額', '予備費支出及び流用増減', '計')
OUTCOMES = ('支出済額', '翌年度繰越額', '不用額')
SUMMARY = {'予算現額(A)': '予算現額(A)', '支出済額(B)': '支出済額(B)',
           '翌年度繰越額(C)': '翌年度繰越額(C)', '不用額': '不用額(A)－(B)－(C)',
           '予算現額と支出済額との比較(E)': '予算現額と支出済額との比較(E)(A)－(B)'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def compact(value):
    return re.sub(r'\s', '', value) if isinstance(value, str) else value


def label(value):
    match = re.fullmatch(r'(\d+)(.+)', compact(value) or '')
    return match.groups() if match else (None, compact(value))


def path_of(row, depth):
    return tuple(label(row.get(level))[0] for level in LEVELS[:depth])


def expected_money(field, value):
    return value.removeprefix('繰越明許費') if field == '翌年度繰越額' and isinstance(value, str) else value


def amount(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:△|-)?\d[\d,]*', compact(value)):
        return None
    text = compact(value).replace(',', '').replace('△', '-')
    return int(text)


def inspect_native_inputs(receipt, gold, before, issues, comparisons):
    """Recompute projection and active replacement from immutable native inputs."""
    native_inputs = receipt['native_inputs']
    base_path = Path(native_inputs['base_path'])
    if digest(base_path) != native_inputs['base_sha256']:
        raise ValueError('Immutable base native changed')
    before[str(base_path)] = digest(base_path)
    base = json.loads(base_path.read_text())
    merged_path = Path(receipt['ocr_observations'])
    if digest(merged_path) != receipt['ocr_observations_sha256']:
        raise ValueError('Submitted merged observations changed')
    merged = json.loads(merged_path.read_text())
    if merged['native_inputs'] != native_inputs or merged['crop_projection_bindings'] != receipt['crop_projection_bindings']:
        raise ValueError('Receipt/native composition declarations differ')
    before[str(merged_path)] = digest(merged_path)
    bp = {p['page_number']: p for p in base['pages']}
    mp = {p['page_number']: p for p in merged['pages']}
    if sorted(bp) != gold['scope']['pages'] or sorted(mp) != gold['scope']['pages']:
        issues.append({'kind': 'wrong-native-page-scope'})
    expected_active = {page: {o['id']: deepcopy(o) for r in p['regions'] for o in r['observations']} for page, p in bp.items()}
    immutable_attempts = []
    for page, p in bp.items():
        if p['rendered_png_sha256'] != gold['image_sha256'][f'page-{page}.png']:
            issues.append({'kind': 'native-origin-image-differs', 'page': page})
        for field in ('image_width', 'image_height', 'displayed_pdf_size_pt', 'crop_box_pdf_pt', 'rotation_degrees'):
            if p[field] != mp[page][field]:
                issues.append({'kind': 'altered-native-page-geometry', 'page': page, 'field': field})
        projected_attempts = {a['id']: a for a in mp[page]['attempts']}
        for a in p['attempts']:
            if projected_attempts.get(a['id']) != a:
                issues.append({'kind': 'altered-base-native-attempt', 'page': page, 'attempt': a['id']})
            immutable_attempts.append((page, p, a))
    crops = {}
    for info in native_inputs['crop_inputs']:
        path = Path(info['path'])
        if digest(path) != info['sha256']:
            raise ValueError(f'Immutable crop native changed: {path}')
        before[str(path)] = info['sha256']
        data = json.loads(path.read_text())
        page = info['physical_page']
        if data['origin']['sha256'] != gold['image_sha256'][f'page-{page}.png']:
            issues.append({'kind': 'crop-origin-image-differs', 'page': page})
        image_path = Path(data['origin']['path'])
        if digest(image_path) != data['origin']['sha256']:
            raise ValueError('Crop original image changed')
        before[str(image_path)] = digest(image_path)
        crops[str(path)] = data
        for p in data['pages']:
            for a in p['attempts']:
                immutable_attempts.append((page, p, a))
    # Native region text/boxes are independently derived from engine JSON, not
    # merely compared with a second copy of transformed observations.
    for page, p, attempt in immutable_attempts:
        obs = {o['id']: o for o in attempt['observations']}
        x0, y0, x1, y1 = attempt['crop_bbox_px']
        if attempt['input_image_size_px'] != [x1-x0, y1-y0]:
            issues.append({'kind': 'unsupported-native-input-transform', 'page': page, 'attempt': attempt['id']})
            continue
        for result_index, result in enumerate(attempt['native']):
            res = result['res']
            for row_index, (text, box) in enumerate(zip(res['rec_texts'], res['rec_boxes'])):
                key = f"{attempt['id']}:result{result_index}:r{row_index}"
                o = obs.get(key)
                expected_box = [box[0]+x0, box[1]+y0, box[2]+x0, box[3]+y0]
                comparisons['immutable-native-region'] += 1
                if not o or o['raw_text'] != text or o['bbox_px'] != expected_box:
                    issues.append({'kind': 'altered-immutable-native-region', 'page': page, 'observation_id': key})
    seen_bindings = set()
    def observation_equal(left, right):
        a=dict(left);b=dict(right)
        x=a.pop('bbox_pdf_pt',None);y=b.pop('bbox_pdf_pt',None)
        return a==b and ((x is None and y is None) or (x is not None and y is not None and len(x)==len(y) and all(abs(u-v)<1e-9 for u,v in zip(x,y))))
    for binding in receipt['crop_projection_bindings']:
        page = binding['physical_page']
        key = (page, binding['projected_attempt_id'])
        if key in seen_bindings:
            issues.append({'kind': 'duplicate-native-projection-binding', 'key': key})
        seen_bindings.add(key)
        data = crops[binding['native_path']]
        if binding['native_sha256'] != before[binding['native_path']]:
            issues.append({'kind': 'wrong-crop-native-binding-sha', 'page': page})
        source_attempt = next(a for p in data['pages'] for a in p['attempts'] if a['id'] == binding['native_attempt_id'])
        target_attempt = next(a for a in mp[page]['attempts'] if a['id'] == binding['projected_attempt_id'])
        for field, value in source_attempt.items():
            if field in ('id', 'observations'): continue
            if target_attempt.get(field) != value:
                issues.append({'kind': 'altered-projected-native-attempt', 'page': page, 'field': field})
        width, height = binding['image_size_px']
        pw, ph = binding['displayed_pdf_size_pt']
        if [width, height] != [bp[page]['image_width'], bp[page]['image_height']] or [pw, ph] != bp[page]['displayed_pdf_size_pt']:
            issues.append({'kind': 'wrong-projection-image-geometry', 'page': page})
        projected = []
        for raw in source_attempt['observations']:
            item = deepcopy(raw)
            prefix = lambda s: s.replace('p1:', f'p{page}:', 1) if s else s
            item['id'] = prefix(item['id'])
            item['parent_id'] = prefix(item['parent_id'])
            item['attempt_id'] = prefix(item['attempt_id'])
            item['page_number'] = page
            if item['bbox_px'] is not None:
                b = item['bbox_px']
                item['bbox_pdf_pt'] = [b[0]/width*pw, b[1]/height*ph, b[2]/width*pw, b[3]/height*ph]
            projected.append(item)
        comparisons['crop-projected-observation'] += len(projected)
        actual_projected=target_attempt['observations']
        if len(projected)!=len(actual_projected) or not all(observation_equal(a,b) for a,b in zip(projected,actual_projected)) or [o['id'] for o in source_attempt['observations']] != binding['source_observation_ids'] or [o['id'] for o in projected] != binding['projected_observation_ids']:
            issues.append({'kind': 'wrong-native-projection', 'page': page, 'attempt': binding['projected_attempt_id']})
        if 'superseded_base_observation_ids' in binding:
            removed = binding['superseded_base_observation_ids']
            # target_attempt superseded IDs describe crop-internal a0→a1;
            # receipt IDs separately describe immutable base→active crop.
            crop = source_attempt['crop_bbox_px']
            for oid in removed:
                raw = expected_active[page].pop(oid, None)
                if not raw:
                    issues.append({'kind': 'unknown-superseded-observation', 'observation_id': oid})
                elif raw['bbox_px'] is not None:
                    b = raw['bbox_px']; x=(b[0]+b[2])/2; y=(b[1]+b[3])/2
                    if not crop[0] <= x <= crop[2] or not crop[1] <= y <= crop[3]:
                        issues.append({'kind': 'superseded-observation-outside-crop', 'observation_id': oid})
            expected_active[page].update({o['id']: o for o in projected})
    for page, expected in expected_active.items():
        actual_list = [o for r in mp[page]['regions'] for o in r['observations']]
        actual = {o['id']: o for o in actual_list}
        if len(actual_list) != len(actual) or set(actual)!=set(expected) or not all(observation_equal(expected[k],actual[k]) for k in set(expected)&set(actual)):
            issues.append({'kind': 'wrong-active-native-composition', 'page': page})
        comparisons['active-native-composition'] += len(expected)


def validate(candidate, source, reference, rules):
    receipt_path = candidate / 'receipt.json'
    receipt = json.loads(receipt_path.read_text())
    gold = json.loads(reference.read_text())
    geometry = json.loads(rules.read_text())
    before = {str(p): digest(p) for p in [receipt_path, source, reference, rules]}
    before[str(Path(__file__).resolve())]=digest(__file__)
    for image_name, sha in gold['image_sha256'].items():
        p = reference.parent / image_name
        if digest(p) != sha: raise ValueError(f'Original image changed: {p}')
        before[str(p)] = sha
    for page, info in geometry.items():
        image=Path(info['image_path']) if 'image_path' in info else rules.parent/f'page-{page}.png'
        if digest(image)!=info['image_sha256']:
            raise ValueError(f'Independent original image changed: {image}')
        before[str(image)]=info['image_sha256']
    if before[str(source)] != gold['origin_sha256'] or receipt['origin']['sha256'] != gold['origin_sha256']:
        raise ValueError('Original identity differs from independent reference or candidate')
    for filename, sha in receipt['code_state'].items():
        if digest(filename) != sha:
            raise ValueError(f'Submitted construction code changed: {filename}')
        before[filename] = sha
    tables = {}
    schema = {}
    with duckdb.connect() as con:
        for table, info in receipt['tables'].items():
            p = candidate / f'{table}.parquet'
            if digest(p) != info['sha256'] or p.stat().st_size != info['bytes']:
                raise ValueError(f'Submitted table identity changed: {table}')
            before[str(p)] = info['sha256']
            description = con.execute('DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)', [str(p)]).fetchall()
            schema[table] = [(r[0], r[1]) for r in description]
            if schema[table] != [(r['name'], r['type']) for r in info['columns']]:
                raise ValueError(f'Submitted table schema changed: {table}')
            rows = con.execute('SELECT * FROM read_parquet(?, hive_partitioning=false)', [str(p)]).fetchall()
            tables[table] = [dict(zip([r[0] for r in description], row)) for row in rows]
            if len(rows) != info['row_count']:
                raise ValueError(f'Submitted row count changed: {table}')
    issues, arithmetic = [], []
    if receipt.get('target') != {'jurisdiction':'132241','fiscal_year':2020,'document_kind':'settlement'} or receipt.get('direction')!='expenditure':
        issues.append({'kind':'wrong-original-target'})
    if receipt.get('scope') != [{'account':'介護保険特別会計','pages':[[5,9],[20,29]]}] or set(map(int,receipt['page_disposition']))!=set(gold['scope']['pages']):
        issues.append({'kind':'wrong-original-scope'})
    if receipt['origin'].get('bytes')!=source.stat().st_size:
        issues.append({'kind':'wrong-original-bytes'})
    for table, rows in tables.items():
        if table not in ('cell_observations',):
            ids=[r['row_id'] for r in rows]
            for k,c in Counter(ids).items():
                if c>1:issues.append({'kind':'duplicate-row-id','table':table,'row_id':k,'count':c})
    for table in tables:
        if any(t in ('JSON','STRUCT','MAP') or t.endswith('[]') for _,t in schema[table]):
            issues.append({'kind':'nested-original-fields','table':table})
    comparisons = defaultdict(int)

    for table, info in receipt['tables'].items():
        metadata = info.get('metadata')
        if metadata is None:
            issues.append({'kind': 'missing-canonical-metadata', 'table': table})
            continue
        try:
            validate_metadata(metadata, [c for c, _ in schema[table]])
        except (ValueError, TypeError, ValidationError) as exc:
            issues.append({'kind': 'invalid-canonical-metadata', 'table': table, 'reason': str(exc)})
            continue
        money = [c for c, _ in schema[table] if c in (*BUDGET, *OUTCOMES, *SUMMARY, '金額') or any(c == k+'_'+m for k in LEVELS for m in (*BUDGET,*OUTCOMES))]
        for column in money:
            contexts = [c for c in metadata.get('column_contexts', []) if column in c['columns']]
            units = [u for u in metadata.get('units', []) if u['scope']['kind']=='table' or column in u['scope'].get('columns', [])]
            if len(contexts)!=1 or not units or not any(re.sub(r'[（()）\s]', '', u['text']) in ('円','単位：円','単位:円') for u in units):
                issues.append({'kind': 'missing-money-header-or-unit', 'table': table, 'field': column})
            if contexts:
                original_column = column.split('_',1)[1] if table=='details' and column.startswith(tuple(k+'_' for k in LEVELS)) else column
                header = ''.join(compact(part) for part in contexts[0]['header_path'])
                if compact(original_column) not in header:
                    issues.append({'kind':'wrong-money-header','table':table,'field':column,'header_path':contexts[0]['header_path']})
            if table=='details' and column.startswith(tuple(k+'_' for k in LEVELS)):
                level=column.split('_',1)[0]
                if contexts and contexts[0]['grain_columns'] != list(LEVELS[:LEVELS.index(level)+1]):
                    issues.append({'kind':'wrong-repeated-parent-grain','field':column})

    def compare(kind, table, row, field, actual, expected):
        comparisons[kind] += 1
        if compact(actual) != compact(expected):
            issues.append({'kind': kind, 'table': table, 'row_id': row.get('row_id'),
                           'field': field, 'actual': actual, 'expected': expected})

    def indexed(table, key):
        result = {}
        for row in tables[table]:
            k = key(row)
            if k in result:
                issues.append({'kind': 'duplicate-original-item', 'table': table, 'key': k})
            result[k] = row
        return result

    parents = indexed('parents', lambda r: path_of(r, LEVELS.index(r['printed_hierarchy_field']) + 1))
    parent_refs = {r['row_id']: r for r in tables['parents']}
    gold_parents = {tuple(r['path']): r for r in gold['detail_controls'] if r['path']}
    compare('row-count', 'parents', {}, 'count', len(tables['parents']), len(gold_parents))
    for path, expected in gold_parents.items():
        row = parents.get(path)
        if row is None:
            issues.append({'kind': 'missing-original-item', 'table': 'parents', 'path': path})
            continue
        for depth in range(1, len(path) + 1):
            compare('name-and-ancestry', 'parents', row, LEVELS[depth-1],
                    label(row.get(LEVELS[depth-1]))[1], gold_parents[path[:depth]]['name'])
        for field, value in expected['values'].items():
            compare('original-money', 'parents', row, field, row.get(field), expected_money(field, value))
        compare('physical-page', 'parents', row, 'left_physical_page', row['left_physical_page'], expected['left_page'])
        compare('physical-page', 'parents', row, 'right_physical_page', row['right_physical_page'], expected['right_page'])
    leaves = indexed('details', lambda r: (path_of(r, 3), label(r.get('区分'))[0]))
    compare('row-count', 'details', {}, 'count', len(tables['details']), len(gold['detail_leaves']))
    for expected in gold['detail_leaves']:
        key = (tuple(expected['path']), expected['setsu_number'])
        row = leaves.get(key)
        if row is None:
            issues.append({'kind': 'missing-original-item', 'table': 'details', 'key': key})
            continue
        compare('name-and-ancestry', 'details', row, '区分', label(row['区分'])[1], expected['name'])
        for field, value in expected['values'].items():
            compare('original-money', 'details', row, field, row.get(field), expected_money(field, value))
        compare('physical-page', 'details', row, 'right_physical_page', row['right_physical_page'], expected['page'])
    for row in tables['details']:
        path = path_of(row, 3)
        for depth, level in enumerate(LEVELS, 1):
            expected = gold_parents.get(path[:depth])
            if not expected:
                issues.append({'kind': 'unknown-ancestry', 'row_id': row['row_id'], 'path': path})
                continue
            compare('name-and-ancestry', 'details', row, level, label(row.get(level))[1], expected['name'])
            linked = parent_refs.get(row.get(level + '_row_id'))
            if not linked or path_of(linked, depth) != path[:depth]:
                issues.append({'kind': 'wrong-parent-reference', 'row_id': row['row_id'], 'level': level})
            for field, value in expected['values'].items():
                compare('repeated-parent-money', 'details', row, level + '_' + field, row.get(level + '_' + field), expected_money(field, value))
        remark = next((r for r in gold['remarks'] if r['path']==list(path)), None)
        compare('original-remark-text', 'details', row, '備考', row.get('備考'), remark['text'] if remark else '')
    total = next(r for r in gold['detail_controls'] if not r['path'])
    compare('row-count', 'detail_totals', {}, 'count', len(tables['detail_totals']), 1)
    for row in tables['detail_totals']:
        compare('name-and-ancestry', 'detail_totals', row, '歳出合計', row.get('歳出合計'), total['name'])
        for field in LEVELS:
            compare('unprinted-total-ancestry','detail_totals',row,field,row.get(field),None)
        for field, value in total['values'].items():
            compare('original-money', 'detail_totals', row, field, row.get(field), expected_money(field, value))
    summaries = indexed('summary', lambda r: () if r['printed_hierarchy_field']=='歳出合計' else path_of(r, 1 if r['printed_hierarchy_field']=='款' else 2))
    compare('row-count', 'summary', {}, 'count', len(tables['summary']), len(gold['summary']))
    for expected in gold['summary']:
        path = tuple(expected['path'])
        row = summaries.get(path)
        if row is None:
            issues.append({'kind':'missing-original-item','table':'summary','path':path})
            continue
        field = LEVELS[len(path)-1] if path else '歳出合計'
        compare('name-and-ancestry', 'summary', row, field, label(row.get(field))[1] if path else row.get(field), expected['name'])
        if len(path)==2:
            compare('name-and-ancestry','summary',row,'款',label(row.get('款'))[1],gold_parents[path[:1]]['name'])
        compare('physical-page','summary',row,'left_physical_page',row['left_physical_page'],expected['left_page'])
        compare('physical-page','summary',row,'right_physical_page',row['right_physical_page'],expected['right_page'])
        for field, reference_field in SUMMARY.items():
            compare('original-money', 'summary', row, field, row.get(field), expected['values'][reference_field])

    for table, rows in [('parents', tables['parents']), ('detail_totals', tables['detail_totals'])]:
        for row in rows:
            path = path_of(row, LEVELS.index(row['printed_hierarchy_field'])+1) if table=='parents' else ()
            expected = gold_parents[path] if path else total
            compare('original-band-identity',table,row,'band',int(row['row_id'].rsplit('-',1)[1]),expected['band'])
            label_expected = '繰越明許費' if expected['values']['翌年度繰越額'].startswith('繰越明許費') else None
            compare('original-carryover-label',table,row,'翌年度繰越額_区分',row.get('翌年度繰越額_区分'),label_expected)
    for expected in gold['detail_leaves']:
        row=leaves.get((tuple(expected['path']),expected['setsu_number']))
        if row:
            compare('original-band-identity','details',row,'band',int(row['row_id'].rsplit('-',1)[1]),expected['band'])
            compare('original-carryover-label','details',row,'翌年度繰越額_区分',row.get('翌年度繰越額_区分'),'繰越明許費' if expected['values']['翌年度繰越額'].startswith('繰越明許費') else None)
            for depth,level in enumerate(LEVELS,1):
                control=gold_parents[tuple(expected['path'][:depth])]
                compare('repeated-carryover-label','details',row,level+'_翌年度繰越額_区分',row.get(level+'_翌年度繰越額_区分'),'繰越明許費' if control['values']['翌年度繰越額'].startswith('繰越明許費') else None)
    for expected in gold['summary']:
        row=summaries.get(tuple(expected['path']))
        if row: compare('original-band-identity','summary',row,'band',int(row['row_id'].rsplit('-',1)[1]),expected['band'])

    for page, facts in gold['nonfinancial'].items():
        number=int(page.removeprefix('physical_'))
        text=''.join(compact(r['印字']) for r in tables['marginalia'] if r['physical_page']==number)
        for field, expected in facts.items():
            comparisons['original-nonfinancial'] += 1
            if compact(expected) not in text:
                issues.append({'kind':'missing-original-nonfinancial','page':number,'field':field,'expected':expected})

    def aggregate(kind, path, field, values, parent):
        numbers = [amount(v) for v in values]
        expected = amount(parent)
        actual = sum(numbers) if numbers and all(n is not None for n in numbers) else None
        status = 'hold' if actual is None or expected is None else 'match' if actual==expected else 'mismatch'
        entry = {'kind':kind,'path':path,'field':field,'actual':actual,'expected':expected,'status':status}
        arithmetic.append(entry)
        if status != 'match': issues.append(entry)

    for path, row in parents.items():
        children = [r for p, r in parents.items() if len(p)==len(path)+1 and p[:-1]==path]
        if children:
            for field in (*BUDGET, *OUTCOMES): aggregate('child-to-parent',path,field,[r.get(field) for r in children],row.get(field))
        if len(path)==3:
            if list(path)==gold['reserve_without_setsu_path']:
                arithmetic.append({'kind':'setsu-to-moku','path':path,'status':'not-checkable','reason':'Original prints no setsu breakdown; reserve moku retained.'})
            else:
                children=[r for (p,n),r in leaves.items() if p==path and n is not None]
                for child_field,parent_field in [('金額','計'),*[(k,k) for k in OUTCOMES]]:
                    aggregate('setsu-to-moku',path,parent_field,[r.get(child_field) for r in children],row.get(parent_field))
    if len(tables['detail_totals'])==1:
        for field in (*BUDGET,*OUTCOMES):aggregate('kan-to-account',[],field,[r.get(field) for p,r in parents.items() if len(p)==1],tables['detail_totals'][0].get(field))
    for table in ('parents','detail_totals'):
        for row in tables[table]:
            aggregate('budget-equation',row['row_id'],'計',[row.get(k) for k in BUDGET[:4]],row.get('計'))
            aggregate('settlement-equation',row['row_id'],'計',[row.get(k) for k in OUTCOMES],row.get('計'))
    for row in tables['details']:
        if label(row.get('区分'))[0]:aggregate('leaf-equation',row['row_id'],'金額',[row.get(k) for k in OUTCOMES],row.get('金額'))

    for path, row in summaries.items():
        parent=parents.get(path) if path else tables['detail_totals'][0]
        if parent:
            for sf,pf in [('予算現額(A)','計'),('支出済額(B)','支出済額'),('翌年度繰越額(C)','翌年度繰越額'),('不用額','不用額')]:
                compare('summary-detail-money','summary',row,sf,row.get(sf),parent.get(pf))

    observations = json.loads(Path(receipt['ocr_observations']).read_text())
    if observations['origin']['sha256'] != gold['origin_sha256']:
        raise ValueError('OCR observations refer to another original')
    before[receipt['ocr_observations']] = digest(receipt['ocr_observations'])
    native = {o['id']:o for p in observations['pages'] for region in p['regions'] for o in region['observations'] if o['kind']=='region'}
    mapping = defaultdict(list)
    page_sizes = {p['page_number']:p['displayed_pdf_size_pt'] for p in observations['pages']}
    for item in tables['cell_observations']:
        mapping[(item['table_id'],item['row_id'],item['field'])].append(item)
        raw = native.get(item['observation_id'])
        if not raw or raw['raw_text'] != item['observed_text'] or raw['page_number'] != item['physical_page']:
            issues.append({'kind':'altered-native-observation','observation_id':item['observation_id']})
        elif raw['bbox_pdf_pt'] != [item[k] for k in ('left_pt','top_pt','right_pt','bottom_pt')]:
            issues.append({'kind':'altered-native-coordinate','observation_id':item['observation_id']})
        compare('printed-page','cell_observations',item,'printed_page',item['printed_page'],gold['printed_pages'].get(str(item['physical_page'])))
    declarations={}
    dictionary_records = receipt.get('dictionary_name_corrections', [])
    for correction in [*receipt.get('local_name_corrections', []), *dictionary_records]:
        key=(correction['table_id'],correction['row_id'],correction['field'])
        if correction['field'] not in (*LEVELS,'区分','備考','印字'):
            issues.append({'kind':'invalid-name-correction-target','cell':key})
        if key in declarations:
            issues.append({'kind':'duplicate-name-correction','cell':key})
        declarations[key]=correction
        items=mapping[key]
        if (correction['origin_sha256']!=gold['origin_sha256']
                or [i['observation_id'] for i in items]!=correction['observation_ids']
                or [[i[k] for k in ('left_pt','top_pt','right_pt','bottom_pt')] for i in items]!=correction['observation_boxes_pt']
                or compact(''.join(i['observed_text'] for i in items))!=compact(correction['before_text'])
                or not items
                or any(i['physical_page']!=correction['physical_page']
                       or i['printed_page']!=correction.get('printed_page',gold['printed_pages'][str(correction['physical_page'])]) for i in items)):
            issues.append({'kind':'unbound-name-correction','cell':key})
    for correction in dictionary_records:
        key=(correction['table_id'],correction['row_id'],correction['field'])
        role = ('subject' if key[0] in ('parents','summary') and key[2] in LEVELS
                else 'setsu' if key[0]=='details' and key[2]=='区分' else None)
        ref=receipt.get('name_dictionary_refs',{}).get(role)
        path=Path(correction['dictionary_path'])
        sha=digest(path)
        if (role is None or not ref or ref['path']!=str(path)
                or ref['sha256']!=sha or correction['dictionary_sha256']!=sha
                or receipt['code_state'].get(str(path))!=sha
                or path.name!=f'fiscal_{role}_name_corrections.json'):
            issues.append({'kind':'unbound-name-dictionary','cell':key})
        before[str(path)]=sha
        dictionary=json.loads(path.read_text())
        normalize=lambda text: ''.join(unicodedata.normalize('NFKC',text).split())
        rules_by_id=[rule for rule in dictionary['rules'] if rule['id']==correction['rule_id']]
        numbered=re.fullmatch(r'(\s*[0-9０-９]+\s*)([^0-9０-９\s][\s\S]*)',correction['before_text'])
        if (dictionary.get('schema_version')!=1
                or dictionary.get('normalization')!='NFKC_REMOVE_WHITESPACE'
                or correction.get('matching_normalization')!=dictionary.get('normalization')
                or len(rules_by_id)!=1 or not numbered):
            issues.append({'kind':'invalid-dictionary-name-rule','cell':key})
            continue
        prefix,logical=numbered.groups()
        rule=rules_by_id[0]
        if (prefix!=correction['raw_number_prefix'] or logical!=correction['raw_logical_name']
                or normalize(logical)!=normalize(rule['observed_name'])
                or normalize(correction['corrected_logical_name'])!=normalize(rule['corrected_name'])
                or correction['confirmed_original_text']!=prefix+correction['corrected_logical_name']
                or correction['reason']!=rule['reason']):
            issues.append({'kind':'wrong-whole-name-dictionary-application','cell':key})
        comparisons['dictionary-name-rule'] += 1
    for table in ('parents','detail_totals','summary','details','marginalia'):
        for row in tables[table]:
            field = row['printed_hierarchy_field'] if table in ('parents','detail_totals','summary') else '区分' if table=='details' else '印字'
            if row.get(field) is None:
                continue
            key=(table,row['row_id'],field)
            items=mapping[key]
            correction=declarations.get(key)
            expected=correction['confirmed_original_text'] if correction else ''.join(i['observed_text'] for i in items)
            compare('native-or-declared-name',table,row,field,row[field],expected)
    compare('row-count','remarks',{},'count',len(tables['remarks']),sum(len(r['entries']) for r in gold['remarks']))
    remark_rows={r['row_id']:r for r in tables['remarks']}
    for expected in gold['remarks']:
        for index,entry in enumerate(expected['entries']):
            row=remark_rows.get(f"remarks:{expected['page']}:{index}")
            if not row:
                issues.append({'kind':'missing-original-remark','page':expected['page'],'index':index})
                continue
            for field,value in [('備考',entry['text']),('備考_金額',entry['amount']),('physical_page',expected['page']),('printed_page',gold['printed_pages'][str(expected['page'])])]:
                compare('original-remark','remarks',row,field,row.get(field),value)
            for depth,level in enumerate(LEVELS,1):
                compare('remark-ancestry','remarks',row,level,label(row.get(level))[1],gold_parents[tuple(expected['path'][:depth])]['name'])
            linked=parent_refs.get(row['目_row_id'])
            if not linked or path_of(linked,3)!=tuple(expected['path']):
                issues.append({'kind':'wrong-remark-parent-reference','table':'remarks','row_id':row['row_id']})
            for field in ('備考','備考_金額'):
                items=mapping[('remarks',row['row_id'],field)]
                correction=declarations.get(('remarks',row['row_id'],field))
                native_text=''.join(i['observed_text'] for i in items)
                compare('remark-native-or-declared','remarks',row,field,row[field],correction['confirmed_original_text'] if correction else native_text)
                if not items:issues.append({'kind':'missing-remark-native-binding','table':'remarks','row_id':row['row_id'],'field':field})
                for item in items:
                    width,height=page_sizes[item['physical_page']]
                    x=(item['left_pt']+item['right_pt'])/(2*width);y=(item['top_pt']+item['bottom_pt'])/(2*height)
                    b=expected['bbox_normalized']
                    if item['physical_page']!=expected['page'] or not b[0]-.003<=x<=b[2]+.003 or not b[1]-.003<=y<=b[3]+.003:
                        issues.append({'kind':'wrong-remark-original-position','table':'remarks','row_id':row['row_id'],'field':field,'observation_id':item['observation_id']})
    # The auxiliary label is absent (NULL) when only a numeric 0 is printed;
    # this is distinct from a source-confirmed empty monetary cell/string.
    for table in ('parents','details','summary','detail_totals','remarks'):
        for column,_ in schema[table]:
            if column.endswith('翌年度繰越額_区分'):
                contexts=[c for c in receipt['tables'][table]['metadata']['column_contexts'] if column in c['columns']]
                if len(contexts)!=1 or ''.join(compact(x) for x in contexts[0]['header_path'])!='翌年度繰越額':
                    issues.append({'kind':'wrong-carryover-label-metadata','table':table,'field':column})
    for table,column in [('details','備考'),('remarks','備考'),('remarks','備考_金額')]:
        contexts=[c for c in receipt['tables'][table]['metadata']['column_contexts'] if column in c['columns']]
        if len(contexts)!=1 or contexts[0]['header_path']!=['備考'] or contexts[0]['grain_columns']!=list(LEVELS):
            issues.append({'kind':'wrong-remark-metadata','table':table,'field':column})
    if not any(u['text'].replace('（','(').replace('）',')').replace(' ','') in ('(単位：円)','(単位:円)') and '備考_金額' in u['scope'].get('columns',[]) for u in receipt['tables']['remarks']['metadata']['units']):
        issues.append({'kind':'wrong-remark-unit','table':'remarks','field':'備考_金額'})
    inspect_native_inputs(receipt,gold,before,issues,comparisons)
    for table in ('parents','detail_totals','summary','details'):
        for row in tables[table]:
            right=int(row['right_physical_page'])
            edges=geometry[str(right)]['edges']
            band=int(row['row_id'].rsplit('-',1)[1])
            for side in ('left','right'):
                page=row[side+'_physical_page']
                compare('printed-row-page',table,row,side+'_printed_page',row[side+'_printed_page'],gold['printed_pages'].get(str(page)))
            for field,expected in [('source_band_top',edges[band]),('source_band_bottom',edges[band+1])]:
                comparisons['original-row-boundary'] += 1
                if abs(row[field]-expected)>.003:
                    issues.append({'kind':'wrong-original-row-boundary','table':table,'row_id':row['row_id'],'field':field})
            money = BUDGET+OUTCOMES if table in ('parents','detail_totals') else tuple(SUMMARY) if table=='summary' else ('金額',*OUTCOMES)
            for field in money:
                value=row.get(field)
                if value is None:continue
                items=mapping[(table,row['row_id'],field)]
                if not items:issues.append({'kind':'missing-original-field-mapping','table':table,'row_id':row['row_id'],'field':field})
                elif compact(''.join(item['observed_text'] for item in items))!=compact(value):
                    issues.append({'kind':'money-not-native-text','table':table,'row_id':row['row_id'],'field':field})
                for item in items:
                    width,height=page_sizes[item['physical_page']]
                    center=(item['top_pt']+item['bottom_pt'])/(2*height)
                    if not edges[band]-.003<=center<=edges[band+1]+.003:
                        issues.append({'kind':'wrong-original-row','table':table,'row_id':row['row_id'],'field':field,'observation_id':item['observation_id']})
                    if table=='summary':
                        expected_page = row['left_physical_page'] if field=='予算現額(A)' else right
                        column = 2 if field=='予算現額(A)' else list(SUMMARY)[1:].index(field)
                    else:
                        expected_page = row['left_physical_page'] if field in BUDGET else right
                        column = 3+BUDGET.index(field) if field in BUDGET else 1 if field=='金額' else 2+OUTCOMES.index(field)
                    compare('original-column-page',table,row,field,item['physical_page'],expected_page)
                    x=(item['left_pt']+item['right_pt'])/(2*width)
                    x_edges=geometry[str(expected_page)]['x_edges']
                    comparisons['original-column-position'] += 1
                    if not x_edges[column]-.003<=x<=x_edges[column+1]+.003:
                        issues.append({'kind':'wrong-original-column','table':table,'row_id':row['row_id'],'field':field,'observation_id':item['observation_id']})
    for table in ('parents','detail_totals','details'):
        for row in tables[table]:
            for field,value in row.items():
                if not field.endswith('翌年度繰越額_区分'):continue
                if table=='details' and field.startswith(tuple(k+'_' for k in LEVELS)):
                    level=field.split('_',1)[0];items=mapping[('parents',row[level+'_row_id'],'翌年度繰越額_区分')]
                else:items=mapping[(table,row['row_id'],field)]
                if value:
                    compare('carryover-label-native',table,row,field,value,''.join(i['observed_text'] for i in items))
                    if not items:issues.append({'kind':'missing-carryover-label-mapping','table':table,'row_id':row['row_id'],'field':field})
                elif items:issues.append({'kind':'unexpected-carryover-label-observation','table':table,'row_id':row['row_id'],'field':field})
    for key,items in mapping.items():
        counts=Counter(i['observation_id'] for i in items)
        if any(c>1 for c in counts.values()):issues.append({'kind':'duplicate-cell-native-binding','cell':key})
    for table in ('parents','detail_totals','summary','details'):
        for row in tables[table]:
            field=row['printed_hierarchy_field'] if table!='details' else '区分'
            if not row.get(field):continue
            items=mapping[(table,row['row_id'],field)]
            band=int(row['row_id'].rsplit('-',1)[1]);right=row['right_physical_page'];edges=geometry[str(right)]['edges']
            page=row['left_physical_page'] if table!='details' else right
            column=LEVELS.index(field) if field in LEVELS else 0
            bottom=edges[band+1]
            if table=='parents':
                # Left hierarchy cells span child rows; right financial bands are narrower.
                depth=LEVELS.index(field)+1
                next_bands=[r['band'] for r in gold['detail_controls'] if r['left_page']==page and r['path'] and len(r['path'])<=depth and r['band']>band]
                bottom=edges[min(next_bands)] if next_bands else edges[-1]
            for item in items:
                width,height=page_sizes[item['physical_page']]
                x=(item['left_pt']+item['right_pt'])/(2*width);y=(item['top_pt']+item['bottom_pt'])/(2*height)
                xe=geometry[str(page)]['x_edges']
                # Total label spans combined hierarchy columns.
                last=3 if field=='歳出合計' and table=='detail_totals' else 2 if field=='歳出合計' else column+1
                if item['physical_page']!=page or not xe[column]-.003<=x<=xe[last]+.003 or not edges[band]-.003<=y<=bottom+.003:
                    issues.append({'kind':'wrong-original-name-position','table':table,'row_id':row['row_id'],'field':field,'observation_id':item['observation_id']})
    for table in ('parents','detail_totals','details'):
        for row in tables[table]:
            field='翌年度繰越額_区分';items=mapping[(table,row['row_id'],field)]
            if not row.get(field):continue
            right=row['right_physical_page'];edges=geometry[str(right)]['edges'];band=int(row['row_id'].rsplit('-',1)[1]);xe=geometry[str(right)]['x_edges']
            for item in items:
                width,height=page_sizes[item['physical_page']];x=(item['left_pt']+item['right_pt'])/(2*width);y=(item['top_pt']+item['bottom_pt'])/(2*height)
                if item['physical_page']!=right or not xe[3]-.003<=x<=xe[4]+.003 or not edges[band]-.003<=y<=edges[band+1]+.003:
                    issues.append({'kind':'wrong-carryover-label-position','table':table,'row_id':row['row_id'],'observation_id':item['observation_id']})
    before[str(candidate/'unknowns.json')]=digest(candidate/'unknowns.json')
    if receipt['unknown_count'] or json.loads((candidate/'unknowns.json').read_text()):
        issues.append({'kind':'unresolved-observations','count':receipt['unknown_count']})
    for issue in issues:
        table=issue.get('table');row_id=issue.get('row_id')
        row=next((r for r in tables.get(table,[]) if r.get('row_id')==row_id),None) if row_id else None
        if row:
            issue['original_location']={k:row.get(k) for k in ('left_physical_page','right_physical_page','left_printed_page','right_printed_page','source_band_top','source_band_bottom') if k in row}
            field=issue.get('field')
            if field:
                issue['original_location']['native_boxes']=[{'page':i['physical_page'],'bbox_pdf_pt':[i[k] for k in ('left_pt','top_pt','right_pt','bottom_pt')]} for i in mapping[(table,row_id,field)]]
    for path,sha in before.items():
        if digest(path)!=sha:raise ValueError(f'Inspection input changed: {path}')
    return {'status':'passed' if not issues else 'failed','candidate':str(candidate.resolve()),
            'input_sha256':before,'row_counts':{k:len(v) for k,v in tables.items()},
            'comparison_counts':dict(comparisons),'issues':issues,'arithmetic':arithmetic,
            'distinct_original_money_cells':sum(len(row['values']) for group in ('detail_controls','detail_leaves','summary') for row in gold[group]),
            'duplicate_reserve_outcome_comparisons':0,
            'arithmetic_counts':dict(Counter(e['status'] for e in arithmetic)),
            'reference_by':gold['reference_by'],'match_rule':gold['match_rule']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('candidate','source','reference','rules','output'):parser.add_argument('--'+flag,required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    result=validate(args.candidate,args.source,args.reference,args.rules)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','row_counts','comparison_counts','arithmetic_counts')},ensure_ascii=False))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
