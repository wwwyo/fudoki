"""Parent-agent inspection of saved Parquet against independent PDF observations."""
import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import duckdb


def identity(source, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("--origin-sha256 must be 64 lowercase hexadecimal characters")
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"Original identity mismatch: expected {expected}, got {actual}")
    return actual


def fresh_output(output):
    # Never reuse a directory containing a previous passed result.
    output.mkdir(parents=True, exist_ok=False)


def run_cli():
    try:
        return main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error) or type(error).__name__}, ensure_ascii=False))
        return 2


DIGITS = str.maketrans('０１２３４５６７８９', '0123456789')
LABELS = {'moku':'目','current':'本年度予算額','previous':'前年度予算額','difference':'比較',
          'national':'国都支出金','loan':'地方債','other':'その他','general':'一般財源'}
BOUNDS = {'moku_raw':(56,125),'current_raw':(125,184),'previous_raw':(184,243),
          'difference_raw':(243,302),'national_raw':(302,361),'loan_raw':(361,420),
          'other_raw':(420,479),'general_raw':(479,538)}


def integer(value):
    return int(value.replace(',', '').replace('△', '-'))


def code(text, kind):
    return re.fullmatch(r'第([０-９0-9]+)' + kind + r'.+', text).group(1).translate(DIGITS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Original PDF (read only)')
    parser.add_argument('--origin-sha256', required=True, help='Expected original SHA-256')
    parser.add_argument('--raw', type=Path, required=True, help='Saved candidate raw Parquet (read only)')
    parser.add_argument('--observations', type=Path, required=True, help='Candidate inspection Parquet directory (read only)')
    parser.add_argument('--origin-observations', type=Path, required=True, help='inspect_origin.py output directory')
    parser.add_argument('--detail-controls', type=Path, required=True, help='inspect_detail_origin.py independent-detail-controls.json')
    parser.add_argument('--output', type=Path, required=True, help='New validation directory; must not exist')
    args = parser.parse_args()
    source_sha = identity(args.source, args.origin_sha256)
    detail = json.loads(args.detail_controls.read_text())
    controls = json.loads((args.origin_observations / 'independent-origin-controls.json').read_text())
    if controls['origin_sha256'] != source_sha or detail['origin_sha256'] != source_sha:
        raise ValueError('Independent original observation identity mismatch')
    for name in ('detail', 'totals', 'summary'):
        observed_sha = hashlib.sha256((args.origin_observations / f'origin-{name}-bbox.xhtml').read_bytes()).hexdigest()
        if observed_sha != controls['bbox_sha256'][name]:
            raise ValueError(f'Independent {name} observation identity mismatch')
        if name == 'detail' and observed_sha != detail['detail_bbox_sha256']:
            raise ValueError('Independent detail controls identity mismatch')
    required = ('words', 'control_words', 'detail_index', 'moku', 'explanation', 'setsu',
                'funding', 'headers', 'totals', 'context', 'moku_occurrences')
    for path in (args.raw, *(args.observations / f'{name}.parquet' for name in required)):
        if not path.is_file():
            raise FileNotFoundError(f'Missing inspection input: {path}')
    fresh_output(args.output)
    originals = {}
    for i, page in enumerate(ET.parse(args.origin_observations / 'origin-detail-bbox.xhtml').findall('.//{*}page')):
        for j, word in enumerate(page.findall('.//{*}word')):
            originals[f'p{108+i}:w{j}'] = {'page':108+i, 'text':''.join(word.itertext()),
                'bbox':[float(word.get(k)) for k in ('xMin','yMin','xMax','yMax')]}
    tables = {}
    with duckdb.connect() as con:
        for name, path in [('expenditure', args.raw), *((name, args.observations / f'{name}.parquet') for name in required)]:
            cur = con.execute('select * from read_parquet(?, hive_partitioning=false)', [str(path)])
            columns = [d[0] for d in cur.description]
            tables[name] = [dict(zip(columns, values)) for values in cur.fetchall()]
        schema = con.execute('describe select * from read_parquet(?, hive_partitioning=false)', [str(args.raw)]).fetchall()
    issues = []
    def problem(category, **fields):
        issues.append({'category':category, **fields})
    for hold in detail['holds']:
        problem('independent_source_hold', **hold)
    if 'control_words' in tables:
        expected_controls={}
        for first,name in [(10,'totals'),(18,'summary')]:
            for offset,page in enumerate(ET.parse(args.origin_observations/f'origin-{name}-bbox.xhtml').findall('.//{*}page')):
                for index,word in enumerate(page.findall('.//{*}word')):
                    expected_controls[f'p{first+offset}:w{index}']=(first+offset,''.join(word.itertext()),
                        [float(word.get(k)) for k in ('xMin','yMin','xMax','yMax')])
        observed_controls={w['token_id']:(w['page'],w['raw_text'],json.loads(w['bbox'])) for w in tables['control_words']}
        if observed_controls!=expected_controls or len(tables['control_words'])!=len(expected_controls):
            problem('control_word_preservation',expected=len(expected_controls),saved=len(tables['control_words']))
    raw = tables['expenditure']
    if any(row[1] != 'VARCHAR' for row in schema):
        problem('raw_type', schema=schema)
    for column in [r[0] for r in schema]:
        if column.startswith('_') or column in ('jurisdiction','fiscal_year','phase','direction','unit'):
            problem('raw_management_column', column=column)
    word_rows = tables['words']
    if len(word_rows) != len(originals) or set(w['token_id'] for w in word_rows) != set(originals):
        problem('word_inventory', observed=len(word_rows), expected=len(originals))
    for word in word_rows:
        source = originals.get(word['token_id'])
        if source is None or (word['page'], word['raw_text'], json.loads(word['bbox'])) != (
                source['page'], source['text'], source['bbox']):
            problem('word_preservation', token=word['token_id'])
        if word['printed_page'] != word['page'] - 4:
            problem('printed_page', token=word['token_id'])
    owners = Counter()
    for table, records in tables.items():
        if table in ('expenditure','words','detail_index','control_words'):
            continue
        for record in records:
            for field, refs in json.loads(record['cell_token_ids']).items():
                if any(ref not in originals for ref in refs):
                    problem('unknown_source_token', table=table, row=record['row_id'], field=field)
                    continue
                text = ''.join(originals[ref]['text'] for ref in refs) if refs else None
                if record[field] != text:
                    problem('cell_text', table=table,row=record['row_id'],field=field,printed=text,saved=record[field])
                owners.update(refs)
                for ref in refs:
                    x = originals[ref]['bbox'][0]
                    bounds = None
                    if table in ('moku','moku_occurrences','totals'):
                        bounds = BOUNDS.get(field)
                    elif table=='funding':
                        bounds = BOUNDS[record['column_key']+'_raw']
                    elif table=='setsu':
                        bounds = {'code_raw':(56,72),'name_raw':(72,132),'amount_raw':(132,195)}[field]
                    elif table=='explanation':
                        bounds = (195,470) if field=='name_raw' else None
                        # 原典の金額欄は右端で段階を区別する。8桁の印字額は
                        # x467.5から始まり、仮の区切り470をまたぐ（頁449等）。
                        if field=='amount_raw' and (not re.fullmatch(r'(?:△|-)?\d[\d,]*',originals[ref]['text'])
                            or abs(originals[ref]['bbox'][2]-[535,526,508][record['depth']])>1):
                            problem('source_amount_alignment',row=record['row_id'],token=ref)
                    if bounds and not bounds[0] <= x < bounds[1]:
                        problem('source_column',table=table,row=record['row_id'],field=field,token=ref)
    if owners != Counter(originals.keys()):
        problem('source_ownership',missing=len(set(originals)-set(owners)),duplicate=sum(n-1 for n in owners.values() if n>1))
    actual_owners = {w['token_id']:(w['owner_id'],w['field']) for w in word_rows}
    for table, records in tables.items():
        if table in ('expenditure','words','detail_index','control_words'):
            continue
        for record in records:
            for field, refs in json.loads(record['cell_token_ids']).items():
                for ref in refs:
                    if actual_owners.get(ref)!=(record['row_id'],field):
                        problem('owner_reference',token=ref)
    moku = {r['row_id']:r for r in tables['moku']}
    nodes = {r['row_id']:r for r in tables['explanation']}
    setsu = {r['row_id']:r for r in tables['setsu']}
    if len(moku)!=len(detail['moku']):
        problem('moku_inventory',saved=len(moku),expected=len(detail['moku']))
    source_moku = {}
    moku_keys = {}
    for ident,m in moku.items():
        refs = json.loads(m['cell_token_ids'])['current_raw']
        position = originals[refs[0]]
        matches = [s for s in detail['moku'] if s['page']==position['page'] and abs(s['y']-position['bbox'][1])<1]
        if len(matches)!=1:
            problem('moku_source_position',row=ident,matches=len(matches)); continue
        source=matches[0];source_moku[ident]=source;moku_keys[ident]=source['key']
        if (code(m['kan_raw'],'款'),code(m['kou_raw'],'項'),m['code_raw'],m['current_raw']) != (
                source['key'][0],source['key'][1],source['code'],source['printed']):
            problem('moku_context',row=ident,source=source)
    def check_membership(record):
        source=originals[next(iter(json.loads(record['cell_token_ids']).values()))[0]]
        matches=[s for s in detail['source_spans'] if s['page']==source['page'] and s['top']<=source['bbox'][1]<s['bottom']]
        if len(matches)!=1 or matches[0]['key'] != moku_keys.get(record['moku_id']):
            problem('moku_membership',row=record['row_id'],page=source['page'],bbox=source['bbox'],matches=matches)
    for record in [*setsu.values(),*nodes.values()]:
        check_membership(record)
    if len(setsu)!=len(detail['setsu']):
        problem('setsu_inventory',saved=len(setsu),expected=len(detail['setsu']))
    for ident,s in setsu.items():
        position=originals[json.loads(s['cell_token_ids'])['amount_raw'][0]]
        matches=[r for r in detail['setsu'] if r['page']==position['page'] and abs(r['y']-position['bbox'][1])<1 and r['code']==s['code_raw']]
        if len(matches)!=1 or matches[0]['printed']!=s['amount_raw'] or matches[0]['key']!=moku_keys.get(s['moku_id']):
            problem('statutory_source',row=ident,matches=matches)
    stacks={}
    children=defaultdict(list)
    def source_start(node):
        word=originals[json.loads(node['cell_token_ids'])['name_raw'][0]]
        return (word['page'],word['bbox'][1],word['bbox'][0])
    source_order=sorted(nodes,key=lambda ident:source_start(nodes[ident]))
    if source_order!=list(nodes):problem('explanation_source_order')
    for ident in source_order:
        node=nodes[ident]
        refs=json.loads(node['cell_token_ids']); names=[originals[r] for r in refs['name_raw']]
        amounts=[originals[r] for r in refs['amount_raw']]
        depth=node['depth'];expected_left=[197,215,233][depth];expected_right=[535,526,508][depth]
        if abs(names[0]['bbox'][0]-expected_left)>1 or not amounts or abs(max(w['bbox'][2] for w in amounts)-expected_right)>1:
            problem('explanation_geometry',row=ident,page=node['page'])
        stack=stacks.setdefault(node['moku_id'],[])
        stack[depth:]=[]
        if len(stack)!=depth or node['parent_id']!=(stack[-1] if stack else None):
            problem('explanation_parent',row=ident,page=node['page'])
        stack.append(ident)
        if node['parent_id']:
            children[node['parent_id']].append(ident)
        if node['closure']!='closed_in_scope':
            problem('open_explanation',row=ident,page=node['page'])
    financial=[]
    def compare(level,path,printed,total,source,*,reason=None,held=False):
        status='held' if held else 'not_checkable' if reason else ('matched' if integer(printed)==total else 'mismatched')
        financial.append({'level':level,'path':path,'printed':printed,'sum':total,
            'difference':None if reason else total-integer(printed),'status':status,'reason':reason,
            'page':source['page'],'bbox':source.get('bbox') or source.get('amount_box'),
            'y':source.get('y'),'scope':[108,449],'unit':'千円','account':'一般会計','amount_column':'本年度予算額'})
    row_index=tables['detail_index']
    if sorted(r['raw_row'] for r in row_index)!=list(range(1,len(raw)+1)):
        problem('detail_row_inventory')
    leaf_totals=defaultdict(int)
    represented=set()
    repeated=defaultdict(set)
    for idx in row_index:
        row=raw[idx['raw_row']-1];m=moku[idx['moku_id']]
        path=json.loads(idx['path_ids']);expected={name:None for name in row}
        expected.update({'款':m['kan_raw'],'項':m['kou_raw']})
        for key,label in LABELS.items():expected[label]=m[key+'_raw']
        for key,label in [('national','国都支出金'),('loan','地方債'),('other','その他')]:
            for i,f in enumerate([f for f in tables['funding'] if f['moku_id']==idx['moku_id'] and f['column_key']==key],1):
                expected[f'{label}_内訳{i}_名称']=f['name_raw'];expected[f'{label}_内訳{i}_金額']=f['amount_raw']
        for ident in path:
            node=nodes[ident];depth=node['depth']+1
            expected[f'説明{depth}_名称']=node['name_raw'];expected[f'説明{depth}_金額']=node['amount_raw']
            repeated[ident].add(row[f'説明{depth}_金額']);represented.add(ident)
        if row!=expected:problem('raw_source_values',raw_row=idx['raw_row'])
        if idx['explanation_id']:
            terminal=nodes[idx['explanation_id']]
            if not path or path[-1]!=idx['explanation_id'] or terminal['row_id'] in children:
                problem('raw_terminal',raw_row=idx['raw_row'])
            expected_path=[];active=terminal
            while active:
                expected_path.insert(0,active['row_id']);active=nodes.get(active['parent_id'])
            if path!=expected_path:problem('raw_path',raw_row=idx['raw_row'])
            section=[nodes[x] for x in path if nodes[x]['depth']==1]
            legal=setsu.get(idx['setsu_id'])
            if len(section)!=1 or not legal or legal['moku_id']!=idx['moku_id'] or legal['name_raw']!=section[0]['name_raw']:
                problem('raw_section_membership',raw_row=idx['raw_row'])
            else:
                leaf_totals[idx['setsu_id']]+=integer(row[f'説明{terminal["depth"]+1}_金額'])
        elif any(row[f'説明{i}_金額'] is not None for i in (1,2,3)):
            problem('empty_moku_has_explanation',raw_row=idx['raw_row'])
    if represented!=set(nodes):problem('raw_node_coverage',missing=list(set(nodes)-represented))
    for ident,values in repeated.items():
        if len(values)!=1:problem('repeated_parent_conflict',row=ident,values=sorted(values, key=lambda value: (value is not None, str(value))))
    for ident,kids in children.items():
        node=nodes[ident]
        source={'page':node['page'],'bbox':json.loads(node['bbox'])}
        if any(len(repeated[k]) != 1 or None in repeated[k] for k in kids):
            compare('explanation_children', [*moku_keys[node['moku_id']],node['name_raw']],
                    node['amount_raw'], None, source, reason='反復親金額が欠落または不一致', held=True)
            continue
        compare('explanation_children', [*moku_keys[node['moku_id']],node['name_raw']],
                node['amount_raw'],sum(integer(next(iter(repeated[k]))) for k in kids),source)
    for ident,s in setsu.items():
        compare('leaf_to_setsu',[*moku_keys[s['moku_id']],s['code_raw'],s['name_raw']],s['amount_raw'],
                leaf_totals[ident],{'page':s['page'],'bbox':json.loads(s['bbox'])})
    for ident,m in moku.items():
        legal=[s for s in setsu.values() if s['moku_id']==ident]
        source=source_moku[ident]
        compare('setsu_to_moku',moku_keys[ident],source['printed'],sum(integer(s['amount_raw']) for s in legal),source,
                reason=None if legal else '原典に法定節の内訳がない（説明も空白）')
    for c in controls['controls']:
        if c['kind']=='kou':
            total=sum(integer(raw[next(i['raw_row'] for i in row_index if i['moku_id']==ident)-1]['本年度予算額'])
                for ident,m in moku.items() if moku_keys[ident][:2]==[c['kan'],c['code']])
            compare('moku_to_kou',[c['kan'],c['code'],c['name']],c['printed'],total,c)
        elif c['kind']=='kan':
            total=sum(integer(k['printed']) for k in controls['controls'] if k['kind']=='kou' and k['kan']==c['kan'])
            compare('kou_to_kan',[c['kan'],c['name']],c['printed'],total,c)
        else:
            compare('kan_to_account',[c['name']],c['printed'],sum(integer(k['printed']) for k in controls['controls'] if k['kind']=='kan'),c)
    counts={level:dict(Counter(r['status'] for r in financial if r['level']==level)) for level in sorted({r['level'] for r in financial})}
    result={'raw':str(args.raw),'observations_directory':str(args.observations),'source_sha256':source_sha,
        'raw_sha256':hashlib.sha256(args.raw.read_bytes()).hexdigest(),
        'raw_rows':len(raw),'raw_columns':len(schema),'observations':{name:len(records) for name,records in tables.items()},
        'source_words':len(originals),'preservation_issues':issues,'hierarchy_counts':counts,'checks':financial,
        'status':'passed' if not issues and not any(r['status'] in ('mismatched','held') for r in financial) else 'failed'}
    (args.output/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    rows=''.join('<tr>'+''.join('<td>'+html.escape(str(r.get(k,'')))+'</td>' for k in
                ('level','status','path','page','bbox','printed','sum','difference','reason'))+'</tr>' for r in financial)
    document='<!doctype html><meta charset="utf-8"><title>昭島市2025一般会計歳出・取り込み検査</title><style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:6px;text-align:left}input{padding:8px;width:50%}pre{white-space:pre-wrap}</style><h1>昭島市2025一般会計歳出・取り込み検査</h1><p>原典: 物理108–449頁、千円、本年度予算額。保存済みParquetを独立原典観測と照合。位置は左上原点のPDFポイント。</p><pre>'+html.escape(json.dumps({k:result[k] for k in ('status','raw_rows','raw_columns','hierarchy_counts','preservation_issues')},ensure_ascii=False,indent=2))+'</pre><input placeholder="所属・頁・不一致などを検索" oninput="for(const r of document.querySelectorAll(\'tbody tr\'))r.hidden=!r.textContent.includes(this.value)"><table><thead><tr>'+''.join('<th>'+t+'</th>' for t in ('階層','結果','所属','物理頁','座標','印字額','集計額','差額','理由'))+'</tr></thead><tbody>'+rows+'</tbody></table>'
    (args.output/'inspection.html').write_text(document)
    print(json.dumps({**{k:result[k] for k in ('status','raw_rows','raw_columns','hierarchy_counts')},
                      'preservation_issues':len(issues),
                      'report':str(args.output/'validation.json')},ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__=='__main__':
    raise SystemExit(run_cli())
