"""Read configured scan settlement spreads from supplied local PDF bytes."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
PIPELINE = BASE.parents[5]
sys.path.insert(0, str(PIPELINE))
from ingestion.lib.scan_ocr import PaddleConfig, PaddleOcr, OcrRegion
from ingestion.lib.paddle_ocr import _render_pdf, _observations, _replace, _crop_box
from ingestion.lib.pdf_table import (Column, Placement, RowBand, TableLayout,
    assemble_table, place_tokens, tokens_from_ocr)
from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn
from ingestion.fiscal.manifest import validate_metadata
from ingestion.lib.ocr_names import load_name_dictionary, correct_name_preserving_layout

LEVELS = ['款', '項', '目']
BUDGET = ['当初予算額', '補正予算額', '継続費及び繰越事業費繰越額', '予備費支出及び流用増減', '計']
EXECUTED = ['支出済額', '翌年度繰越額', '不用額']
PARENT_MONEY = BUDGET + EXECUTED


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def observe(source, pages, cache, expected_sha, layout):
    source, cache = Path(source), Path(cache)
    if digest(source) != expected_sha:
        raise ValueError('Origin SHA differs from supplied saved reference')
    cache.mkdir(parents=True, exist_ok=True)
    config = PaddleConfig(**layout.get('ocr_config', {}))
    images = cache / 'images'
    images.mkdir(exist_ok=True)
    rendered = cache / 'render.json'
    if not rendered.exists():
        save(rendered, _render_pdf(source, pages, config, images))
    render = json.loads(rendered.read_text())
    if [p['page_number'] for p in render['pages']] != pages:
        raise ValueError('Rendered page scope differs')
    retries = {int(p): [OcrRegion(v['id'], tuple(v['bbox'])) for v in values]
               for p, values in layout.get('retry_regions', {}).items()}
    identity = {'origin_sha256': expected_sha, 'pages': pages, 'config': asdict(config),
                'retry_regions': layout.get('retry_regions', {}),
                'ocr_code_sha256': digest(PIPELINE/'ingestion/lib/paddle_ocr.py'),
                'model_manifest_sha256': digest(PIPELINE/'ingestion/lib/paddle_ocr_models.json'),
                'renderer_code_sha256': digest(PIPELINE/'ingestion/lib/pdf_render.swift'),
                'package_versions': {p:importlib.metadata.version(p) for p in ['paddleocr','paddlex','paddlepaddle']}}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    saved = cache / f'ocr-{key}.json'
    if not saved.exists():
        with PaddleOcr(config) as engine:
            result = engine.recognize_pdf(source, pages=pages, retry_regions=retries)
        save(saved, result)
        save(cache / f'ocr-{key}.request.json', identity)
    result = json.loads(saved.read_text())
    if (result['origin']['sha256'] != expected_sha
            or [p['page_number'] for p in result['pages']] != pages
            or result['engine']['config'] != asdict(config)
            or result['engine']['driver_sha256'] != identity['ocr_code_sha256']
            or result['engine']['model_manifest']['sha256'] != identity['model_manifest_sha256']
            or result['renderer']['backend_sha256'] != identity['renderer_code_sha256']):
        raise ValueError('Cached observations differ from origin/scope/config')
    for record, page in zip(render['pages'], result['pages'], strict=True):
        if digest(record['image_path']) != page['rendered_png_sha256']:
            raise ValueError('Cached inspection image differs from OCR rendering')
    if layout.get('cell_retry_regions'):
        return retry_cells(result, saved, render, cache, config, layout['cell_retry_regions'])
    return result, saved


def retry_cells(base, base_path, render, cache, config, declarations):
    """Reread declared cells from fixed PNGs; retain each immutable native input."""
    pages={p['page_number']:p for p in base['pages']}
    images={p['page_number']:Path(p['image_path']) for p in render['pages']}
    raw_results=[]
    with PaddleOcr(config) as engine:
        for number,regions in declarations.items():
            number=int(number)
            page=pages[number]
            image=images[number]
            image_sha=digest(image)
            if image_sha!=page['rendered_png_sha256']:
                raise ValueError('Cell reread PNG differs from original OCR rendering')
            for region in regions:
                identity={'image_path':str(image.resolve()),'image_sha256':image_sha,
                    'origin_sha256':base['origin']['sha256'],'physical_page':number,
                    'region':region,'config':asdict(config),
                    'driver_sha256':base['engine']['driver_sha256'],
                    'model_manifest_sha256':base['engine']['model_manifest']['sha256'],
                    'package_versions':base['engine']['versions']}
                key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
                path=cache/f'crop-{key}.json'
                if not path.exists():
                    crop=OcrRegion(region['id'],tuple(region['bbox']))
                    retry=OcrRegion(region['id']+'-retry',tuple(region['bbox']))
                    raw=engine.recognize_image(image,regions=[crop],retry_regions=[retry])
                    save(path,raw)
                    save(cache/f'crop-{key}.request.json',identity)
                raw=json.loads(path.read_text())
                if (raw['origin']['sha256']!=image_sha or raw['engine']['config']!=asdict(config)
                        or raw['engine']['driver_sha256']!=base['engine']['driver_sha256']
                        or raw['engine']['model_manifest']['sha256']!=base['engine']['model_manifest']['sha256']
                        or raw['engine']['versions']!=base['engine']['versions']
                        or raw['pages'][0]['rendered_rgb_pixel_sha256']!=page['rendered_rgb_pixel_sha256']
                        or raw['pages'][0]['regions'][0]['id']!=region['id']
                        or raw['pages'][0]['regions'][0]['crop_bbox_px']!=_crop_box(
                            OcrRegion(region['id'],tuple(region['bbox'])),page['image_width'],page['image_height'])
                        or digest(image)!=image_sha):
                    raise ValueError('Cell reread native input identity differs')
                raw_results.append((number,region,path,raw))
    binding={'base_path':str(base_path.resolve()),'base_sha256':digest(base_path),
        'crop_inputs':[{'path':str(path.resolve()),'sha256':digest(path),'physical_page':number,
                       'region':region} for number,region,path,_ in raw_results],
        'projection_code_sha256':digest(Path(__file__))}
    key=hashlib.sha256(json.dumps(binding,sort_keys=True).encode()).hexdigest()
    saved=cache/f'augmented-{key}.json'
    combined=json.loads(base_path.read_text())
    targets={p['page_number']:p for p in combined['pages']}
    projection=[]
    for number,region,path,raw in raw_results:
        target=targets[number]
        raw_page=raw['pages'][0]
        projected={}
        for attempt in raw_page['attempts']:
            attempt_id='p'+str(number)+attempt['id'][2:]
            observed=_observations(attempt['native'],attempt['crop_bbox_px'],target,attempt_id)
            projected.update({old['id']:new for old,new in zip(attempt['observations'],observed,strict=True)})
            target['attempts'].append({**attempt,'id':attempt_id,'observations':observed,
                'supplemental_native_path':str(path.resolve()),'native_attempt_id':attempt['id']})
            projection.append({'physical_page':number,'native_path':str(path.resolve()),
                'native_sha256':digest(path),'native_attempt_id':attempt['id'],
                'projected_attempt_id':attempt_id,
                'source_observation_ids':[v['id'] for v in attempt['observations']],
                'projected_observation_ids':[v['id'] for v in observed],
                'image_size_px':[target['image_width'],target['image_height']],
                'displayed_pdf_size_pt':target['displayed_pdf_size_pt']})
        active=next(v for v in target['regions'] if v['id']=='full-page')
        raw_region=raw_page['regions'][0]
        replacements=[projected[v['id']] for v in raw_region['observations']]
        active['observations'],removed=_replace(active['observations'],replacements,raw_region['crop_bbox_px'])
        active['attempt_ids'].extend('p'+str(number)+v[2:] for v in raw_region['attempt_ids'])
        projection[-1]['superseded_base_observation_ids']=removed
    combined['native_inputs']=binding
    combined['crop_projection_bindings']=projection
    if saved.exists():
        if json.loads(saved.read_text())!=combined:
            raise ValueError('Cached active observations differ from immutable native projection')
    else:
        save(saved,combined)
    return combined,saved


class Builder:
    def __init__(self, result, layout):
        self.layout = layout
        self.sha = result['origin']['sha256']
        self.tokens = tokens_from_ocr(result, kind='region', region_ids=['full-page'], unit='pt')
        self.page_data = {p['page_number']: p for p in result['pages']}
        self.printed = {}
        self.maps, self.unknowns = [], []
        self.corrections = layout.get('name_corrections', [])
        self.applied_corrections = set()
        self.dictionary_corrections = []
        self.dictionaries = {role:(PIPELINE / ref, load_name_dictionary(PIPELINE / ref))
            for role,ref in layout.get('name_dictionaries',{}).items()}
        for number in self.page_data:
            footer = self.select(number, [0, .92, 1, .98])
            self.printed[number] = self.text(footer)
            if not self.printed[number]:
                self.unknowns.append({'physical_page': number, 'field':'印刷頁', 'reason':'footer unobserved'})

    def select(self, number, bbox):
        page = self.page_data[number]
        width, height = page['displayed_pdf_size_pt']
        x1, y1, x2, y2 = bbox
        return tuple(t for t in self.tokens if t.page == number and t.bbox
            and x1 <= t.bbox.x('center') / width < x2
            and y1 <= t.bbox.y('center') / height < y2)

    @staticmethod
    def text(tokens):
        return '\n'.join(t.raw_text for t in sorted(tokens, key=lambda t:(t.bbox.top,t.bbox.left))) or None

    def field(self, table, row_id, name, tokens, *, required=False, location=None):
        text = self.text(tokens)
        for token in tokens:
            self.maps.append({'table_id':table,'row_id':row_id,'field':name,
                'physical_page':token.page,'printed_page':self.printed[token.page],
                'observation_id':token.id,'observed_text':token.raw_text,
                'left_pt':token.bbox.left,'top_pt':token.bbox.top,
                'right_pt':token.bbox.right,'bottom_pt':token.bbox.bottom})
        if text is None and required:
            self.unknowns.append({'table_id':table,'row_id':row_id,'field':name,
                                  'reason':'no OCR observation; blank not inferred', 'location':location})
        declarations = [v for v in self.corrections if (v['table_id'],v['row_id'],v['field']) == (table,row_id,name)]
        if len(declarations)>1:
            raise ValueError('Multiple corrections for one observed name cell')
        if declarations:
            item=declarations[0]
            if name not in [*LEVELS,'区分','印字','備考']:
                raise ValueError('Local corrections are restricted to observed names')
            if (item['origin_sha256']!=self.sha or item['before_text']!=text
                    or item['observation_ids']!=[t.id for t in tokens]
                    or any(t.page!=item['physical_page'] for t in tokens)
                    or item['observation_boxes_pt']!=[[t.bbox.left,t.bbox.top,t.bbox.right,t.bbox.bottom] for t in tokens]):
                raise ValueError('Local correction origin/native observation identity differs')
            if name=='備考' and re.findall(r'[△▲+−-]?[0-9０-９][0-9０-９,，]*',text)!=re.findall(
                    r'[△▲+−-]?[0-9０-９][0-9０-９,，]*',item['confirmed_original_text']):
                raise ValueError('Local note name corrections must preserve printed amounts')
            self.applied_corrections.add(item['id'])
            return item['confirmed_original_text']
        return self.correct_dictionary_name(table, row_id, name, tokens, text)

    def correct_dictionary_name(self, table, row_id, name, tokens, text):
        role='subject' if table in ['parents','summary'] and name in LEVELS else 'setsu' if table=='details' and name=='区分' else None
        if text is None or role not in self.dictionaries:
            return text
        # Only these source-confirmed numbered hierarchy/section fields separate a prefix.
        numbered=re.fullmatch(r'(\s*[0-9０-９]+\s*)([^0-9０-９\s][\s\S]*)',text)
        if not numbered:
            return text
        prefix,logical=numbered.groups()
        path,dictionary=self.dictionaries[role]
        corrected=correct_name_preserving_layout(logical,dictionary)
        if not corrected['rule_id']:
            return text
        after=prefix+corrected['corrected_name']
        item={'id':f'dictionary:{table}:{row_id}:{name}',
            'origin_sha256':self.sha,'table_id':table,'row_id':row_id,'field':name,
            'physical_page':tokens[0].page,'printed_page':self.printed[tokens[0].page],
            'observation_ids':[t.id for t in tokens],
            'observation_boxes_pt':[[t.bbox.left,t.bbox.top,t.bbox.right,t.bbox.bottom] for t in tokens],
            'before_text':text,'confirmed_original_text':after,
            'dictionary_path':str(path.resolve()),'dictionary_sha256':dictionary.sha256,
            'rule_id':corrected['rule_id'],'reason':corrected['reason'],
            'raw_number_prefix':prefix,'raw_logical_name':logical,
            'corrected_logical_name':corrected['corrected_name'],
            'matching_normalization':corrected['normalization'],
            'layout_policy':corrected['layout_policy'],
            'application_condition':'whole logical name after source-confirmed numbered subject/setsu field separation'}
        if any(v['id']==item['id'] for v in self.dictionary_corrections):
            raise ValueError('Repeated dictionary application to one original name cell')
        self.dictionary_corrections.append(item)
        return after

    def spread(self, spec, columns):
        left, right = spec['left_page'], spec['right_page']
        placements = {}
        for number in [left, right]:
            width, height = self.page_data[number]['displayed_pdf_size_pt']
            placements[(self.sha,number)] = Placement('spread', scale_x=1000/width,
                scale_y=1000/height, offset_x=0 if number==left else 1000,
                offset_y=spec['left_y_offset']*1000 if number==left else 0)
        chosen = tuple(t for t in self.tokens if t.page in [left,right])
        placed = place_tokens(chosen, placements)
        cols = tuple(Column(side+'_'+name,(x1+(side=='右'))*1000,(x2+(side=='右'))*1000)
            for side,key in [('左','left'),('右','right')] for name,x1,x2 in columns[key])
        layout = TableLayout(columns=cols, row_bands=tuple(RowBand(a*1000,b*1000)
            for a,b in zip(spec['row_edges'],spec['row_edges'][1:])))
        return assemble_table(placed, layout)

    def row_field(self, table, row_id, row, side, name, required=False):
        return self.field(table,row_id,name,tuple(t.token for t in row.cell(side+'_'+name).tokens),required=required)

    def amount_field(self, table, row_id, row, name, record):
        declaration = self.layout.get('amount_labels', {}).get(name)
        if not declaration:
            return self.row_field(table, row_id, row, '右', name, True)
        tokens = tuple(t.token for t in row.cell('右_'+name).tokens)
        labels = tuple(t for t in tokens if t.raw_text in declaration['confirmed_labels'])
        amounts = tuple(t for t in tokens if t not in labels)
        record[declaration['label_column']] = self.field(table, row_id,
            declaration['label_column'], labels)
        if any(not re.fullmatch(r'[△▲+−-]?\s*[0-9０-９][0-9０-９,，\s]*', t.raw_text) for t in amounts):
            self.unknowns.append({'table_id':table, 'row_id':row_id, 'field':name,
                'reason':'amount/label separation contains unconfirmed text'})
        return self.field(table, row_id, name, amounts, required=True)

    def moku_remarks(self, regions, row_id):
        tokens = tuple(t for region in regions for t in self.select(region['page'],region['bbox']))
        return self.field('details',row_id,'備考',tokens,required=True) if regions else None

    def remarks(self, parents):
        owners = {p['row_id']:p for p in parents if p['printed_hierarchy_field']=='目'}
        records = []
        for region in self.layout.get('remarks_regions', []):
            owner = owners[region['owner_row_id']]
            for index, item in enumerate(region['items']):
                row_id=f"remarks:{region['page']}:{index}"
                record={'row_id':row_id, 'physical_page':region['page'],
                    'printed_page':self.printed[region['page']],
                    **{level:owner[level] for level in LEVELS}, '目_row_id':owner['row_id']}
                for name,bbox in item.items():
                    record[name]=self.field('remarks',row_id,name,
                        self.select(region['page'],bbox),required=True,location=bbox)
                records.append(record)
        return records

    def parent_name(self, spec, row_index, level, row_id):
        roles = {int(k):v for k,v in spec['roles'].items()}
        rank = LEVELS.index(level)
        end = next((i for i in range(row_index+1,len(spec['row_edges'])-1)
                    if roles.get(i) in LEVELS[:rank+1] or roles.get(i)=='歳出合計'), len(spec['row_edges'])-1)
        bounds = next(c[1:] for c in self.layout['detail_columns']['left'] if c[0]==level)
        bbox = [*bounds[:1],spec['row_edges'][row_index]-spec['left_y_offset'],
                bounds[1],spec['row_edges'][end]-spec['left_y_offset']]
        return self.field('parents',row_id,level,self.select(spec['left_page'],bbox),required=True,location=bbox)

    def details(self):
        parents, details, totals = [], [], []
        current = {level:None for level in LEVELS}
        for spec in self.layout['detail_spreads']:
            assembled = self.spread(spec,self.layout['detail_columns'])
            roles = {int(k):v for k,v in spec['roles'].items()}
            for index,row in enumerate(assembled.rows):
                role = roles.get(index)
                row_id = f"spread-{spec['left_page']}-{spec['right_page']}:band-{index}"
                if role in LEVELS or role == '歳出合計':
                    record = {'row_id':row_id,'printed_hierarchy_field':role,
                              'left_physical_page':spec['left_page'], 'right_physical_page':spec['right_page'],
                              'left_printed_page':self.printed[spec['left_page']], 'right_printed_page':self.printed[spec['right_page']],
                              'source_band_top':spec['row_edges'][index], 'source_band_bottom':spec['row_edges'][index+1]}
                    for level in LEVELS:
                        record[level] = current[level][level] if role in LEVELS and current[level] else None
                    if role in LEVELS:
                        for deeper in LEVELS[LEVELS.index(role)+1:]:
                            current[deeper] = None
                            record[deeper] = None
                        record[role] = self.parent_name(spec,index,role,row_id)
                    else:
                        record['歳出合計'] = self.field('detail_totals',row_id,'歳出合計',
                            self.select(spec['left_page'],[self.layout['detail_columns']['left'][0][1],spec['row_edges'][index]-spec['left_y_offset'],self.layout['detail_columns']['left'][2][2],spec['row_edges'][index+1]-spec['left_y_offset']]),required=True)
                    for name in BUDGET:
                        record[name] = self.row_field('parents' if role in LEVELS else 'detail_totals',row_id,row,'左',name,True)
                    for name in EXECUTED:
                        record[name] = self.amount_field('parents' if role in LEVELS else 'detail_totals',row_id,row,name,record)
                    if role in LEVELS:
                        current[role] = record
                        parents.append(record)
                        if index not in spec.get('moku_without_setsu',[]):
                            continue
                    else:
                        totals.append(record)
                        continue
                if not current['目']:
                    self.unknowns.append({'row_id':row_id,'reason':'detail without observed moku context'})
                detail = {'row_id':row_id,'left_physical_page':spec['left_page'], 'right_physical_page':spec['right_page'],
                          'left_printed_page':self.printed[spec['left_page']], 'right_printed_page':self.printed[spec['right_page']],
                          'source_band_top':spec['row_edges'][index], 'source_band_bottom':spec['row_edges'][index+1]}
                no_setsu = index in spec.get('moku_without_setsu',[])
                for level in LEVELS:
                    parent = current[level]
                    detail[level] = parent[level] if parent else None
                    detail[level+'_row_id'] = parent['row_id'] if parent else None
                    for name in PARENT_MONEY:
                        detail[level+'_'+name] = parent[name] if parent else None
                    for declaration in self.layout.get('amount_labels',{}).values():
                        label=declaration['label_column']
                        detail[level+'_'+label] = parent[label] if parent else None
                for name in ['区分','金額',*EXECUTED]:
                    detail[name] = (self.amount_field('details',row_id,row,name,detail)
                        if name in self.layout.get('amount_labels',{}) else
                        self.row_field('details',row_id,row,'右',name,not no_setsu or name in EXECUTED))
                # Empty source rectangles are explicitly confirmed in the layout; no OCR absence-to-zero rule.
                remarks_regions = [v for v in self.layout.get('remarks_regions',[])
                    if current['目'] and v['owner_row_id']==current['目']['row_id']]
                detail['備考'] = (self.moku_remarks(remarks_regions,row_id) if remarks_regions else
                    self.row_field('details',row_id,row,'右','備考'))
                if detail['備考'] is None:
                    column=next(v for v in self.layout['detail_columns']['right'] if v[0]=='備考')
                    interior=[column[1]+.004,spec['row_edges'][index]+.004,column[2]-.004,spec['row_edges'][index+1]-.004]
                    if any(v['page']==spec['right_page'] and v['field']=='備考'
                           and v['bbox'][0]<=interior[0] and v['bbox'][1]<=interior[1]
                           and interior[2]<=v['bbox'][2] and interior[3]<=v['bbox'][3]
                           for v in self.layout['verified_blank_regions']):
                        detail['備考'] = ''
                    else:
                        self.unknowns.append({'row_id':row_id,'field':'備考','reason':'unobserved; blank unconfirmed'})
                details.append(detail)
        return parents, details, totals

    def summary(self):
        spec = self.layout['summary']
        table = self.spread(spec,spec['columns'])
        output = []
        current_kan = None
        for index,row in enumerate(table.rows):
            row_id=f"summary-{spec['left_page']}-{spec['right_page']}:band-{index}"
            role=spec['roles'][index]
            name_field='項' if role=='項' else '款'
            # The total label spans both hierarchy columns.
            if role=='歳出合計':
                tokens = tuple(t.token for f in ['左_款','左_項'] for t in row.cell(f).tokens)
                name=self.field('summary',row_id,'歳出合計',tokens,required=True)
            else:
                bbox_bounds = next(c[1:] for c in spec['columns']['left'] if c[0]==name_field)
                end=index+1
                if role=='款':
                    end=next((i for i in range(index+1,len(spec['roles'])) if spec['roles'][i]!='項'),len(spec['roles']))
                name=self.field('summary',row_id,name_field,self.select(spec['left_page'],
                    [bbox_bounds[0],spec['row_edges'][index]-spec['left_y_offset'],bbox_bounds[1],spec['row_edges'][end]-spec['left_y_offset']]),required=True)
            if role=='款': current_kan=name
            record={'row_id':row_id,'printed_hierarchy_field':role,'款':current_kan if role!='歳出合計' else None,
                    '項':name if role=='項' else None,'歳出合計':name if role=='歳出合計' else None,
                    'left_physical_page':spec['left_page'],'right_physical_page':spec['right_page'],
                    'left_printed_page':self.printed[spec['left_page']], 'right_printed_page':self.printed[spec['right_page']],
                    'source_band_top':spec['row_edges'][index], 'source_band_bottom':spec['row_edges'][index+1]}
            record['予算現額(A)']=self.row_field('summary',row_id,row,'左','予算現額(A)',True)
            for name,_,_ in spec['columns']['right']:
                record[name]=self.row_field('summary',row_id,row,'右',name,True)
            output.append(record)
        return output

    def marginalia(self):
        records=[]
        for page_text,regions in self.layout['marginalia_regions'].items():
            page=int(page_text)
            selected={t.id:t for bbox in regions for t in self.select(page,bbox)}
            for token in selected.values():
                row_id=f'marginalia:{token.id}'
                records.append({'row_id':row_id,'physical_page':page,'printed_page':self.printed[page],
                    '印字':self.field('marginalia',row_id,'印字',(token,))})
        return records


def columns_for(rows):
    if not rows:
        raise ValueError('Expected nonempty output table')
    integer={'left_physical_page','right_physical_page','physical_page'}
    floating={'source_band_top','source_band_bottom','left_pt','top_pt','right_pt','bottom_pt'}
    return [ParquetColumn(name,'BIGINT' if name in integer else 'DOUBLE' if name in floating else 'VARCHAR')
            for name in rows[0]]


def table_metadata(layout):
    """Describe confirmed printed columns and their source grain in the manager schema."""
    def note(text, columns=None):
        return {'text':text,'scope':{'kind':'columns','columns':columns} if columns else {'kind':'table'}}
    def context(columns, header, grain, role=None):
        value={'columns':columns,'header_path':header,'grain_columns':grain}
        if role: value['semantic_role']=role
        return value
    def money_unit(columns):
        return [note(layout['confirmed_unit_text'],columns)]
    metadata={name:{'notes':[],'column_contexts':[]} for name in
              ['details','parents','detail_totals','summary','marginalia','cell_observations']}
    detail_money=['金額',*EXECUTED,*[level+'_'+name for level in LEVELS for name in PARENT_MONEY]]
    details=metadata['details']
    details['units']=money_unit(detail_money)
    has_remarks = bool(layout.get('remarks_regions'))
    details['notes']=[note('原典の法定節一覧を一行ずつ保持する。備考は確認済みの目枠に属する独立した流用注記であり、法定節一覧と同じ高さの行に結び付けない。' if has_remarks else '原典の法定節一覧を一行ずつ保持する。説明欄に金額の印字はない。節の掲載のない予備費は目の一行。'),
        note('金額を持つ備考の各注記文と印字額はremarks表に独立して保持する。detailsの備考は目枠の全文を同じ目の節へ反復したもので、当該節の明細や支出済額ではない。' if has_remarks else '予備費は原典の節欄が印字されていないため区分・金額はNULL。未観測値を0へ補わない。',['備考'] if has_remarks else ['区分','金額']),
        note('備考の空文字はverified_blank_regionsの原典枠に印字なしと構築AIが画像確認した結果。独立検査は別途行い、人間確認ではない。' if has_remarks else '備考の空文字は、layoutのverified_blank_regionsに固定した物理頁と原典枠の全域を親AIが画像確認し、印字がないと確認した結果。人間の確認ではない。',['備考']),
        note('名称欄の折り返しは改行を保持する。親の名称・金額は、原典の款・項・目に属する欄を末端行へ展開したもので、末端と同じ粒度の金額ではない。'),
        note('原典ヘッダーと本文列の結合は原典罫線と配置で確認した。header_pathは原典確認文字、native OCRのヘッダー字形はmarginaliaとcell_observationsに未訂正で保持する。')]
    details['column_contexts']=[context(['区分'],['節','区分'],['款','項','目','区分'],'setsu'),
        context(['金額'],['節','金額'],['款','項','目','区分'],'setsu'),
        *[context([name],[name],['款','項','目','区分']) for name in EXECUTED],
        context(['備考'],['備考'],['款','項','目'])]
    for index,level in enumerate(LEVELS):
        grain=LEVELS[:index+1]
        details['column_contexts'].append(context([level],[level],grain))
        for name in PARENT_MONEY:
            header=['予算現額',name] if name in BUDGET else [name]
            details['column_contexts'].append(context([level+'_'+name],header,grain))
        details['notes'].append(note(level+'の金額は原典の'+level+'の一セルを同じ所属の末端行に反復したもの。原典親の粒度は'+ '・'.join(grain)+'。', [level+'_'+name for name in PARENT_MONEY]))
    for table,grain in [('parents',LEVELS),('detail_totals',['歳出合計'])]:
        value=metadata[table]
        value['units']=money_unit(PARENT_MONEY)
        value['column_contexts']=[context([name],['予算現額',name] if name in BUDGET else [name],grain) for name in PARENT_MONEY]
        value['notes']=[note('原典事項別明細書の印字小計。printed_hierarchy_fieldは金額が属する原典欄を示す。款行では款、項行では款・項、目行では款・項・目が原典の粒度。' if table=='parents' else '原典事項別明細書末尾に印字された歳出合計。款・項・目・節の印字小計とは別の原典欄。'),
            note('原典確認ヘッダーはcolumn_contexts、OCRヘッダーの未訂正の字形はmarginaliaとcell_observationsに保持する。')]
    summary=metadata['summary']
    summary_names=[name for side in ['left','right'] for name,_,_ in layout['summary']['columns'][side] if name not in LEVELS]
    summary['units']=money_unit(summary_names)
    summary['column_contexts']=[context([name],[name],['款','項','歳出合計']) for name in summary_names]
    summary['notes']=[note('原典歳出決算総括表の款・項・歳出合計を独立して保持する。各行の原典粒度はprinted_hierarchy_fieldによる。'),
        note('不用額の欄には(A)−(B)−(C)、予算現額と支出済額との比較(E)の欄には(A)−(B)が印字されている。原典の式と数字を改変しない。'),
        note('歳入総括表は歳出表から除外。対象頁全体の確認範囲と除外理由はreceiptのpage_dispositionに保持する。')]
    metadata['marginalia']['notes']=[note('原典の表紙、年度、会計、資料名、表外の見出し、単位、注記、印刷頁のnative観測文字を保持する。' if has_remarks else '原典の表紙、年度、会計、資料名、表外の見出し、単位、注記、印刷頁の観測。native観測文字を保持する。表紙の齡は原典の旧字で、齢に置き換えない。'),
        note('単位のOCR括弧はASCII、原典の括弧は全角。nativeの字形を上書きせず、金額列のunitsには原典の'+layout['confirmed_unit_text']+'を記載する。'),
        note('字形・原典ヘッダーの確認は親AIの原典画像照合であり、人間の確認ではない。')]
    metadata['cell_observations']['notes']=[note('表/行/fieldからnative OCR観測id・元の文字・原典位置へ対応する。文字訂正後もobserved_textはnativeの訂正前文字列で、receiptのdictionary_name_correctionsに辞書path・SHA・rule ID・番号付き原文・論理名称・適用条件・折り返し保持方針・原典観測bindingを残す。旧局所宣言の確認根拠はcorrections.jsonに保持する。'),
        note('left_pt/top_pt/right_pt/bottom_ptは原典の表示CropBox上のpt座標。物理頁と原典の印刷頁を別列で保持する。')]
    if layout.get('remarks_regions'):
        metadata['remarks']={'units':money_unit(['備考_金額']),
            'notes':[note('原典の備考枠の流用注記。目への所属は罫線枠で確認し、法定節の同y行との関係や節別の支出とは解釈しない。へ/からと相手科目は備考の原文に保持する。'),
                     note('備考_金額は同じ原典注記項目の印字金額を独立欄へ展開した補助列であり、支出済額ではない。')],
            'column_contexts':[context(['備考','備考_金額'],['備考'],LEVELS),
                *[context([level],[level],LEVELS[:i+1]) for i,level in enumerate(LEVELS)]]}
    for name,declaration in layout.get('amount_labels',{}).items():
        label=declaration['label_column']
        for table in ['details','parents','detail_totals']:
            grain=LEVELS+['区分'] if table=='details' else LEVELS if table=='parents' else ['歳出合計']
            metadata[table]['column_contexts'].append(context([label],[name],grain))
            metadata[table]['notes'].append(note(name+'欄に印字された区分と金額を分離する。'+label+'は原典区分の補助列で、'+name+'には同じ欄の原文数字だけを保持する。区分の印字のない0では区分はNULL。',[name,label]))
        for i,level in enumerate(LEVELS):
            details['column_contexts'].append(context([level+'_'+label],[name],LEVELS[:i+1]))
            details['notes'].append(note(level+'の'+label+'は同じ原典親セルの区分を、親金額と同じ粒度で末端へ反復したもの。',[level+'_'+label]))
    for correction in layout.get('name_corrections',[]):
        metadata[correction['table_id']]['notes'].append(note('局所名称訂正 '+correction['id']+'。原典SHA・頁・native観測ID・位置・訂正前後・根拠は'+layout.get('corrections_ref','corrections.json')+'に固定。原典画像確認であり人間確認ではない。'))
    for correction in layout.get('dictionary_name_corrections',[]):
        metadata[correction['table_id']]['notes'].append(note('名称全体の共有辞書訂正 '+correction['rule_id']+'、辞書 '+correction['dictionary_path']+'、SHA '+correction['dictionary_sha256']+'。確認済み番号付き欄の数字prefixを分離し、NFKCと空白除去は照合だけに使う。'+correction['layout_policy']+'。元文字と原典位置はreceipt/native観測に保持する。'))
    return metadata


def convert(inputs: list[dict], destination: Path, options: dict) -> dict[str, dict]:
    """Convert one selected PDF; target/account information remains caller-owned metadata."""
    if len(inputs)!=1 or inputs[0]['format']!='pdf' or len(inputs[0]['scope'])!=1:
        raise ValueError('Supply one PDF and one account scope')
    source=inputs[0]
    pages=[p for first,last in source['scope'][0]['pages'] for p in range(first,last+1)]
    layout_path=Path(options.get('layout_path',BASE/'layout.json')).resolve()
    layout=json.loads(layout_path.read_text())
    corrections_path=layout_path.parent/layout['corrections_ref'] if layout.get('corrections_ref') else None
    if corrections_path:
        declarations=json.loads(corrections_path.read_text())
        layout['name_corrections']=declarations['corrections']
        layout['correction_review_history']=declarations.get('review_history',[])
        layout['archived_local_corrections']=declarations.get('archived_local_corrections',[])
    if set(pages)!={int(p) for p in layout['page_disposition']}:
        raise ValueError('Supplied page scope differs from measured layout coverage')
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    if any(destination.iterdir()):
        raise FileExistsError('Candidate destination must be empty and unused')
    ocr_started=time.perf_counter()
    cache=Path(options['cache_dir'])
    existing_observations=set(cache.glob('*.json'))
    existing_paths={p.resolve() for p in existing_observations}
    result, observation_path=observe(source['path'],pages,cache,source['sha256'],layout)
    ocr_wall_seconds=time.perf_counter()-ocr_started
    table_started=time.perf_counter()
    builder=Builder(result,layout)
    parents,details,totals=builder.details()
    summary=builder.summary()
    marginalia=builder.marginalia()
    tables={'details':details,'parents':parents,'detail_totals':totals,'summary':summary,
            'marginalia':marginalia,'cell_observations':builder.maps}
    if layout.get('remarks_regions'):
        tables['remarks']=builder.remarks(parents)
    if builder.applied_corrections != {v['id'] for v in builder.corrections}:
        raise ValueError('Declared name corrections were not applied exactly once to their source cells')
    layout['dictionary_name_corrections']=builder.dictionary_corrections
    metadata=table_metadata(layout)
    table_seconds=time.perf_counter()-table_started
    write_started=time.perf_counter()
    output={}
    receipts={}
    for name,rows in tables.items():
        path=destination/f'{name}.parquet'
        context=ConversionContext(source['sha256'],name,str(Path(__file__).resolve()),str(layout_path))
        columns=columns_for(rows)
        written=write_conversion(path,rows,columns=columns,context=context)
        import duckdb
        with duckdb.connect() as con:
            schema=con.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(path)]).fetchall()
            count=con.execute('SELECT COUNT(*) FROM read_parquet(?)',[str(path)]).fetchone()[0]
            saved_rows=con.execute('SELECT * FROM read_parquet(?)',[str(path)]).fetchall()
        if count!=written.row_count: raise ValueError('Saved readback row count differs')
        if saved_rows!=[tuple(row[c.name] for c in columns) for row in rows]:
            raise ValueError('Saved readback cells/order/nulls differ')
        validate_metadata(metadata[name], [r[0] for r in schema])
        output[name]={'path':path,'metadata':metadata[name]}
        receipts[name]={**asdict(written),'columns':[{'name':r[0],'type':r[1]} for r in schema],'metadata':metadata[name]}
    save(destination/'unknowns.json',builder.unknowns)
    tracked=[Path(__file__),layout_path,BASE/'options.schema.json',BASE/'README.md',
             PIPELINE/'ingestion/lib/scan_ocr.py',PIPELINE/'ingestion/lib/paddle_ocr.py',
             PIPELINE/'ingestion/lib/pdf_table.py',PIPELINE/'ingestion/lib/parquet.py',
             PIPELINE/'ingestion/lib/conversion.py',PIPELINE/'ingestion/lib/pdf_render.swift',
             PIPELINE/'ingestion/lib/paddle_ocr_models.json']
    tracked.extend([PIPELINE/'ingestion/fiscal/manifest.py',PIPELINE/'ingestion/fiscal/manifest.schema.json'])
    if corrections_path: tracked.append(corrections_path)
    tracked.extend([PIPELINE/'ingestion/lib/ocr_names.py',PIPELINE/'ingestion/lib/ocr_vocabulary.json'])
    for path,dictionary in builder.dictionaries.values():
        if digest(path)!=dictionary.sha256:
            raise ValueError('Name dictionary changed during conversion')
        tracked.append(path)
    save(destination/'receipt.json',{'origin':result['origin'],'scope':source['scope'],
        'conversion_inputs':inputs,'conversion_options':options,
        'target':source.get('target'),'direction':source.get('direction'),
        'tables':receipts,'table_metadata':metadata,'unknown_count':len(builder.unknowns),
        'page_disposition':layout['page_disposition'],'ocr_observations':str(observation_path.resolve()),
        'ocr_observations_sha256':digest(observation_path),
        'native_inputs':result.get('native_inputs'),
        'crop_projection_bindings':result.get('crop_projection_bindings',[]),
        'processing_times':{'ocr_cache_reused':observation_path in existing_observations,
            'base_ocr_cache_reused':Path(result.get('native_inputs',{}).get('base_path',observation_path)).resolve() in existing_paths,
            'native_cache_reused':(Path(result.get('native_inputs',{}).get('base_path',observation_path)).resolve() in existing_paths
                and all(Path(v['path']).resolve() in existing_paths for v in result.get('native_inputs',{}).get('crop_inputs',[]))),
            'ocr_call_wall_seconds':ocr_wall_seconds,
            'original_ocr_render_seconds':result['render_seconds'],
            'original_ocr_initialization_seconds':result['engine']['init_seconds'],
            'original_ocr_inference_seconds':sum(a['inference_seconds'] for p in result['pages'] for a in p['attempts'] if a['retry_region_id'] is None and not a.get('supplemental_native_path')),
            'original_ocr_retry_seconds':sum(a['inference_seconds'] for p in result['pages'] for a in p['attempts'] if a['retry_region_id'] is not None or a.get('supplemental_native_path')),
            'table_seconds':table_seconds,'write_readback_seconds':time.perf_counter()-write_started},
        'code_state':{str(p.resolve()):digest(p) for p in tracked},
        'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=PIPELINE,text=True).strip(),
        'git_status':subprocess.check_output(['git','status','--short'],cwd=PIPELINE,text=True).splitlines(),
        'local_name_corrections':builder.corrections,'dictionary_name_corrections':builder.dictionary_corrections,
        'name_dictionary_refs':{role:{'path':str(path.resolve()),'sha256':dictionary.sha256} for role,(path,dictionary) in builder.dictionaries.items()},
        'archived_local_corrections':layout.get('archived_local_corrections',[]),'correction_review_history':layout.get('correction_review_history',[]),'reproduce_command':options.get('reproduce_command')})
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',required=True,type=Path)
    parser.add_argument('--options',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    output=convert(json.loads(args.inputs.read_text()),args.output,json.loads(args.options.read_text()))
    print(json.dumps({'tables':{name:{'path':str(value['path']),'metadata':value['metadata']} for name,value in output.items()}},ensure_ascii=False))

if __name__=='__main__':
    main()
