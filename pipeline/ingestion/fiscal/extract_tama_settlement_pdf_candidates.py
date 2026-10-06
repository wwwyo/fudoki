"""Bounded, source-positioned candidates for Tama settlement PDFs.

Candidate modes write private observations; canonical mode reproduces declared
partitions from SHA-verified fixed originals, without adoption or allocation.
Funding and legal-setsu tables have distinct grains. Book spread relationships are
accepted only at printed kan/kou/moku row boundaries and checked against printed
moku controls. A missing amount is an error, never a generated zero.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess

import duckdb
from ingestion.lib.pdf import pages_of

FUNDING = ('国庫支出金', '都支出金', '地方債', 'その他特定財源', '一般財源')
MONEY = re.compile(r'[△−-]?\d[\d,]*')


def amount(text: str) -> int:
    if not MONEY.fullmatch(text):
        raise ValueError(f'Unsupported printed money: {text!r}')
    return int(text.replace(',', '').replace('△', '-').replace('−', '-'))


def box(words):
    if not words:
        return None
    return [min(w[0] for w in words), min(w[1] for w in words),
            max(w[2] for w in words), max(w[3] for w in words)]


def positioned(words):
    return [{'bbox': list(w[:4]), 'text': w[4]} for w in sorted(words, key=lambda w: (w[1], w[0]))]


def one(words, context):
    if len(words) != 1:
        raise ValueError(f'{context}: expected one printed cell, observed {positioned(words)}')
    return words[0]


def write_rows(path: Path, rows: list[dict]):
    if not rows:
        raise ValueError(f'No candidate rows for {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    json_path = path.with_suffix('.jsonl')
    json_path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    con = duckdb.connect()
    con.execute('CREATE TABLE candidate AS SELECT * FROM read_json_auto(?, maximum_depth=-1, hive_partitioning=false)', [str(json_path)])
    # JSON inference can choose DOUBLE for mixed-sign nested integers. All money
    # was parsed from printed decimal digits; enforce integer storage explicitly.
    for column, data_type, *_ in con.execute('DESCRIBE candidate').fetchall():
        if column == 'moku_budget_columns':
            target = re.sub(r'((?:\w+_)?amount) DOUBLE', r'\1 BIGINT', data_type)
            con.execute(f'ALTER TABLE candidate ALTER COLUMN {column} TYPE {target}')
        elif column.endswith('_amount') or column in ('amount', 'source_amount'):
            con.execute(f'ALTER TABLE candidate ALTER COLUMN {column} TYPE BIGINT')
    con.execute('COPY candidate TO ? (FORMAT PARQUET)', [str(path)])
    observed = con.execute('SELECT count(*) FROM read_parquet(?, hive_partitioning=false)', [str(path)]).fetchone()[0]
    if observed != len(rows):
        raise ValueError(f'Candidate count changed: {observed} != {len(rows)}')
    readback=[json.loads(r[0]) for r in con.execute('SELECT to_json(t) FROM read_parquet(?, hive_partitioning=false) t', [str(path)]).fetchall()]
    if readback != rows:
        raise ValueError(f'Parquet row/value/position readback differs: {path}')
    schema = con.execute('DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)', [str(path)]).fetchall()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size, 'rows': observed, 'schema': schema, 'all_fields_readback_match': True}


def origin(spec):
    path = Path(spec['object_path'])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != spec['sha256']:
        raise ValueError(f'Original SHA mismatch: {path}: {digest}')
    return path


def funding(spec, output):
    pdf = origin(spec)
    pages = pages_of(pdf, 1, spec['pages'])
    rows, projects = [], []
    for page, (_, _, words) in enumerate(pages, 1):
        starts = sorted((w for w in words if w[4] == FUNDING[0] and 265 < w[0] < 274), key=lambda w: w[1])
        for start in starts:
            y = start[1]
            local = [w for w in words if y - .1 <= w[1] <= y + 35]
            primary = one([w for w in local if abs(w[1]-y)<1 and 100<w[0]<115 and re.fullmatch(r'\d{3}',w[4])], f'p{page} project {y}')
            secondary = one([w for w in local if abs(w[1]-y)<1 and 115<w[0]<130 and re.fullmatch(r'-\d{3}',w[4])], f'p{page} secondary {y}')
            hierarchy = sorted([w for w in local if abs(w[1]-y)<1 and 55<w[0]<95 and re.fullmatch(r'-?\d{2}',w[4])], key=lambda w:w[0])
            if len(hierarchy)!=3:
                raise ValueError(f'p{page} {y}: hierarchy {hierarchy}')
            name_words = [w for w in local if 100<w[0]<175 and w[1]>y+1]
            total = one([w for w in local if abs(w[2]-266.66)<.5 and MONEY.fullmatch(w[4])], f'p{page} project total {y}')
            unit_word=one([w for w in words if w[4]=='単位：千円'],f'p{page} funding unit')
            common = dict(unit_printed=unit_word[4],unit_box=list(unit_word[:4]),jurisdiction='132241',year=spec['year'],account='general',direction='expenditure',phase='executed',
                          origin_url=spec['url'],origin_sha256=spec['sha256'],unit='千円',physical_page=page,
                          table_id='project-funding',grain='printed-project-by-funding-source',
                          kan=hierarchy[0][4],kou=hierarchy[1][4].lstrip('-'),moku=hierarchy[2][4].lstrip('-'),
                          project_code=primary[4]+secondary[4],project_primary_code=primary[4],
                          project_name=''.join(w[4] for w in sorted(name_words,key=lambda w:(w[1],w[0]))),
                          project_code_box=box([primary,secondary]),hierarchy_words=positioned(hierarchy),
                          project_name_words=positioned(name_words),project_total_printed=total[4],
                          project_total_amount=amount(total[4]),project_total_box=list(total[:4]))
            shares=[]
            for code,label in enumerate(FUNDING,1):
                label_word=one([w for w in local if w[4]==label and 265<w[0]<274],f'p{page} {primary[4]} {label}')
                value=one([w for w in local if abs(w[1]-label_word[1])<.5 and abs(w[2]-375.05)<.5 and MONEY.fullmatch(w[4])],f'p{page} {primary[4]} {label} money')
                row=common|dict(source_row=len(rows)+1,funding_code=str(code),funding_label=label,
                                funding_label_box=list(label_word[:4]),amount_printed=value[4],amount=amount(value[4]),amount_box=list(value[:4]))
                rows.append(row);shares.append(row['amount'])
            projects.append(common|dict(funding_sum=sum(shares),matches_printed_total=sum(shares)==common['project_total_amount']))
    if not all(p['matches_printed_total'] for p in projects):
        raise ValueError('Funding sums do not match printed project controls')
    (output/'funding-project-controls.json').write_text(json.dumps(projects,ensure_ascii=False,indent=2))
    result=write_rows(output/'funding-full.parquet', rows)
    if 'csv' not in spec:
        checks=dict(full=result,project_count=len(projects),printed_project_sum=sum(p['project_total_amount'] for p in projects),
                    funding_sum=sum(r['amount'] for r in rows),project_controls_all_match=True,origin=spec)
        (output/'funding-reconciliation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
        return checks
    csv_spec=spec['csv'];body=Path(csv_spec['object_path']).read_bytes()
    if hashlib.sha256(body).hexdigest()!=csv_spec['sha256']:
        raise ValueError('CSV original SHA mismatch')
    csv_rows=list(csv.reader(io.StringIO(body.decode(csv_spec['encoding']),newline='')))[1:]
    key=lambda r:tuple(str(int(r[c])) for c in ('kan','kou','moku','project_primary_code','funding_code'))
    by_key={key(r):r for r in rows}
    if len(by_key)!=len(rows):
        raise ValueError('Printed funding keys collide')
    overlaps=[]
    for n,r in enumerate(csv_rows,1):
        if not all(v.strip().isdigit() for v in r[:5]):
            raise ValueError(f'Unexpected CSV row {n}: {r}')
        k=tuple(str(int(v)) for v in r[:5]);pdf_row=by_key.pop(k,None)
        if pdf_row is None or amount(r[5])!=pdf_row['amount']:
            raise ValueError(f'CSV/PDF disagreement row {n}: {r}, {pdf_row}')
        overlaps.append(dict(csv_source_row=n,pdf_source_row=pdf_row['source_row'],key=k,amount=pdf_row['amount']))
    missing=list(by_key.values())
    missing_result=write_rows(output/'funding-missing.parquet',missing)
    checks=dict(full=result,missing=missing_result,project_count=len(projects),printed_project_sum=sum(p['project_total_amount'] for p in projects),
                funding_sum=sum(r['amount'] for r in rows),csv_rows=len(csv_rows),csv_sum=sum(amount(r[5]) for r in csv_rows),
                overlap_count=len(overlaps),overlap_all_values_match=True,project_controls_all_match=True,
                missing_rows=len(missing),missing_sum=sum(r['amount'] for r in missing),csv_sha256=csv_spec['sha256'],origin=spec,
                missing_project_codes=sorted(set(r['project_code'] for r in missing)))
    (output/'funding-overlap.json').write_text(json.dumps(overlaps,ensure_ascii=False,indent=2))
    (output/'funding-reconciliation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
    return checks



def book_header(words, label):
    return one([w for w in words if w[4] == label], f'book header {label}')


def book_cells(left, right, page, spec, account, state, output_rows, controls):
    # Both pages are one printed table. The matching y positions are the same
    # rows, not a statistical/project allocation. Preserve both page positions.
    width, height, lw = left
    _, _, rw = right
    unit_word=one([w for w in rw if '単位：円' in w[4]], f'p{page} book unit')
    heads = [book_header(lw, label) for label in ('款', '項', '目')]
    centers = [(w[0]+w[2])/2 for w in heads]
    spacing = centers[1]-centers[0]
    edges = [centers[0]-spacing/2, (centers[0]+centers[1])/2,
             (centers[1]+centers[2])/2, centers[2]+spacing/2]
    # This 金 belongs to the 節 金額 column, not an amount in remarks.
    gold = book_header(rw, '金')
    body_y = gold[3]+4
    executed = book_header(rw, '支出済額')
    carry = book_header(rw, '翌年度繰越額')
    ex_center = (executed[0]+executed[2])/2
    carry_center = (carry[0]+carry[2])/2
    money_width = carry_center-ex_center
    ex_lo, ex_hi = ex_center-money_width/2, ex_center+money_width/2
    code_head = book_header(rw, '区')
    code_edge = code_head[2]
    label_end = gold[0]-8
    left_anchors = sorted([w for w in lw if re.fullmatch(r'\d{1,2}',w[4])
                           and edges[0] <= w[0] < edges[3] and body_y < w[1] < height*.94],key=lambda w:(w[1],w[0]))
    setsu_anchors = sorted([w for w in rw if re.fullmatch(r'\d{1,2}',w[4])
                            and w[0]<code_edge and w[2]<=code_edge+1
                            and body_y<w[1]<height*.94],key=lambda w:w[1])
    total_label_words=[w for w in lw if re.fullmatch(r'[歳出合計]+',w[4]) and w[0]<edges[3] and w[1]>body_y]
    totals=[]
    for anchor in total_label_words:
        label_words=[w for w in total_label_words if abs(w[1]-anchor[1])<1]
        if ''.join(w[4] for w in sorted(label_words,key=lambda w:w[0]))=='歳出合計':
            totals=[tuple(box(label_words))+('歳出合計',)];break
    events = sorted([(w[1], 'hierarchy', w) for w in left_anchors]+
                    [(w[1], 'setsu', w) for w in setsu_anchors],key=lambda e:(e[0],e[1]))
    numbers = [w for w in rw if MONEY.fullmatch(w[4]) and ex_lo<w[0]<ex_hi and w[2]<=ex_hi+2 and body_y<w[1]<height*.94]
    for y, kind, word in events:
        if kind=='hierarchy':
            level = next(i for i in range(3) if edges[i]<=word[0]<edges[i+1])
            if level<2:
                next_y=min((w[1] for w in left_anchors if w[1]>y+.5),default=height*.94)
                labels=[w for w in lw if word[2]<w[0]<edges[level+1] and y-.5<=w[1]<next_y-.5 and not any(abs(w[1]-t[1])<1 for t in totals)]
                state[level] = dict(code=word[4],page=page-1,code_box=list(word[:4]),
                                    name=''.join(w[4] for w in sorted(labels,key=lambda w:(w[1],w[0]))),name_words=positioned(labels))
                continue
            if not all(state[i] for i in (0,1)):
                raise ValueError(f'{spec["year"]} p{page-1}: moku without kan/kou')
            next_y = min((w[1] for w in left_anchors if w[1]>y+.5), default=height*.94)
            label_words = [w for w in lw if word[2]<w[0]<edges[3] and y-.5<=w[1]<next_y-.5 and not any(abs(w[1]-t[1])<1 for t in totals)]
            total = one([w for w in numbers if abs(w[1]-y)<1.1], f'{spec["year"]} p{page} moku total {word[4]} y{y}')
            control = dict(jurisdiction='132241',year=spec['year'],account=account,kan=state[0]['code'],kou=state[1]['code'],moku=word[4],
                           kan_position=state[0],kou_position=state[1],moku_name=''.join(w[4] for w in sorted(label_words,key=lambda w:(w[1],w[0]))),
                           hierarchy_physical_page=page-1,moku_code_box=list(word[:4]),moku_name_words=positioned(label_words),
                           total_physical_page=page,total_box=list(total[:4]),total_printed=total[4],total_amount=amount(total[4]),
                           origin_url=spec['url'],origin_sha256=spec['sha256'],unit='円',setsu_row_ids=[])
            budget_words=sorted([w for w in lw if abs(w[1]-y)<1.1 and w[0]>edges[3] and MONEY.fullmatch(w[4])],key=lambda w:w[0])
            if len(budget_words)!=5:
                raise ValueError(f'p{page-1} moku {word[4]}: expected five printed budget columns, got {budget_words}')
            for field,value in zip(('initial_budget','supplementary_delta','carried_budget','reserve_and_transfer_delta','current_budget'),budget_words,strict=True):
                control[field+'_printed']=value[4];control[field+'_amount']=amount(value[4]);control[field+'_box']=list(value[:4])
            control['budget_equation_matches']=sum(amount(w[4]) for w in budget_words[:4])==amount(budget_words[4][4])
            controls.append(control);state[2]=control
        else:
            if not state[2]:
                raise ValueError(f'{spec["year"]} p{page}: setsu without printed moku')
            next_y=min((e[0] for e in events if e[0]>y+.5),default=height*.94)
            label_words = [w for w in rw if word[2]<w[0]<label_end and y-.5<=w[1]<next_y-.5 and not any(abs(w[1]-t[1])<1 for t in totals)]
            value=one([w for w in numbers if abs(w[1]-y)<1.1],f'{spec["year"]} p{page} setsu {word[4]}')
            budget=one([w for w in rw if abs(w[1]-y)<1.1 and label_end<w[0]<ex_lo and MONEY.fullmatch(w[4])],f'{spec["year"]} p{page} setsu budget {word[4]}')
            m=state[2]
            row=dict(jurisdiction='132241',year=spec['year'],account=account,direction='expenditure',phase='executed',
                     origin_url=spec['url'],origin_sha256=spec['sha256'],unit='円',table_id='moku-legal-setsu',grain='printed-moku-by-legal-setsu',
                     source_row=len(output_rows)+1,physical_page=page,printed_page=spec['printed_pages'][page-1],
                     kan=m['kan'],kou=m['kou'],moku=m['moku'],moku_name=m['moku_name'],kan_name=m['kan_position']['name'],kou_name=m['kou_position']['name'],
                     unit_printed=unit_word[4],unit_box=list(unit_word[:4]),
                     kan_position=m['kan_position'],kou_position=m['kou_position'],hierarchy_physical_page=m['hierarchy_physical_page'],
                     moku_code_box=m['moku_code_box'],moku_name_words=m['moku_name_words'],moku_total_physical_page=m['total_physical_page'],
                     moku_total_printed=m['total_printed'],moku_total_box=m['total_box'],
                     setsu_code=word[4],setsu_code_box=list(word[:4]),setsu_label=''.join(w[4] for w in sorted(label_words,key=lambda w:(w[1],w[0]))),
                     setsu_label_words=positioned(label_words),amount_printed=value[4],amount=amount(value[4]),amount_box=list(value[:4]),
                     budget_current_printed=budget[4],budget_current_amount=amount(budget[4]),budget_current_box=list(budget[:4]),
                     printed_row_words=positioned([w for w in rw if y-.5<=w[1]<next_y-.5]),
                     moku_budget_columns={k:v for k,v in m.items() if any(k.startswith(f) for f in ('initial_budget','supplementary_delta','carried_budget','reserve_and_transfer_delta','current_budget'))})
            output_rows.append(row);m['setsu_row_ids'].append(row['source_row'])
    # Retain the independently printed account control when it exists.
    if totals:
        total=one([w for w in numbers if abs(w[1]-totals[0][1])<1.1],f'{spec["year"]} {account} account total')
        state[3]=dict(physical_page=page,bbox=list(total[:4]),printed=total[4],amount=amount(total[4]),label_page=page-1,label_box=list(totals[0][:4]))


def books(specs, output):
    results=[]
    for spec in specs:
        pdf=origin(spec)
        text=Path(spec['text_path']).read_text().split('\f')[:-1]
        spec=spec|dict(printed_pages=[int(t.strip().splitlines()[-1]) if t.strip() and t.strip().splitlines()[-1].strip().isdigit() else None for t in text])
        all_pages=pages_of(pdf,1,spec['pages'])
        word_rows=[dict(origin_url=spec['url'],origin_sha256=spec['sha256'],year=spec['year'],physical_page=i+1,
                        printed_page=spec['printed_pages'][i],page_width=width,page_height=height,word_index=j+1,
                        bbox=list(w[:4]),text=w[4])
                   for i,(width,height,words) in enumerate(all_pages) for j,w in enumerate(words)]
        words_result=write_rows(output/f'page-words-{spec["sha256"]}.parquet',word_rows)
        indices=[i+1 for i,t in enumerate(text) if '支出済額' in t and '節' in t]
        if spec['year']==2020:
            results.append(dict(year=2020,origin_url=spec['url'],origin_sha256=spec['sha256'],origin_bytes=spec['bytes'],
                                pages=spec['pages'],word_materialization=words_result,status='image-table-text-layer-missing',
                                error='pdftotext exposes footer words only; this mode cannot extract image tables; bounded native Vision candidates are separate'))
            continue
        groups=[]
        for i in indices:
            if not groups or i-groups[-1][-1]!=2:
                groups.append([])
            groups[-1].append(i)
        if len(groups)!=4:
            raise ValueError(f'{spec["year"]}: expected four printed account sections, got {groups}')
        rows=[];controls=[];accounts=[]
        for account,pages in zip(('general','national-health','care','elderly'),groups,strict=True):
            state=[None,None,None,None];start=len(rows);control_start=len(controls)
            for page in pages:
                book_cells(all_pages[page-2],all_pages[page-1],page,spec,account,state,rows,controls)
            part=rows[start:];by_id={r['source_row']:r for r in part}
            for c in controls[control_start:]:
                c['setsu_sum']=sum(by_id[n]['amount'] for n in c['setsu_row_ids'])
                c['matches_printed_total']=c['setsu_sum']==c['total_amount']
            printed_controls=controls[control_start:]
            accounts.append(dict(account=account,rows=len(part),sum=sum(r['amount'] for r in part),moku_count=len(printed_controls),
                                 moku_controls_matched=sum(c['matches_printed_total'] for c in printed_controls),
                                 moku_control_sum=sum(c['total_amount'] for c in printed_controls),
                                 account_control=state[3],account_control_matches=(state[3] is not None and state[3]['amount']==sum(r['amount'] for r in part)),
                                 hierarchy_pages=[i-1 for i in pages],amount_pages=pages))
        result=write_rows(output/f'moku-setsu-{spec["year"]}.parquet',rows)
        (output/f'moku-controls-{spec["year"]}.json').write_text(json.dumps(controls,ensure_ascii=False,indent=2))
        results.append(dict(year=spec['year'],origin_url=spec['url'],origin_sha256=spec['sha256'],origin_bytes=spec['bytes'],materialization=result,
                            word_materialization=words_result,accounts=accounts,errors=[c for c in controls if not c['matches_printed_total']]))
    (output/'book-reconciliation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    return results


def canonical(sources_path: Path, origin_dir: Path, output: Path):
    """Reproduce independent observation tables; original records remain reversible JSON."""
    from ingestion.fiscal.sources import load_settlement_pdf
    specs = load_settlement_pdf(sources_path)
    results=[]
    for key,spec in specs.items():
        code,year,*_=key.split(':');year=int(year)
        if code!='132241' or year not in (2021,2022,2023,2024,2025):
            raise ValueError(f'Unsupported canonical settlement scope: {key}')
        sha=spec['origin_sha256'];pdf=origin_dir/sha
        if pdf.stat().st_size!=spec['origin_bytes']:
            raise ValueError(f'Fixed original size differs: {pdf}')
        work=output/'work'/sha;work.mkdir(parents=True,exist_ok=True)
        actual=dict(object_path=str(pdf),sha256=sha,bytes=spec['origin_bytes'],url=spec['url'],pages=spec['physical_pages'],year=year)
        origin(actual)
        if spec['layout']=='tama-settlement-book':
            text=work/'text.txt'
            subprocess.run(['pdftotext','-layout',str(pdf),str(text)],check=True)
            actual['text_path']=str(text)
            reconciliation=books([actual],work)[0]
            legal=[json.loads(l) for l in (work/f'moku-setsu-{year}.jsonl').read_text().splitlines()]
            moku=json.loads((work/f'moku-controls-{year}.json').read_text())
            for i,r in enumerate(moku,1): r['source_row']=i
            account_controls=[dict(source_row=i,year=year,account=r['account'],unit='円',origin_url=spec['url'],origin_sha256=sha,**r['account_control']) for i,r in enumerate(reconciliation['accounts'],1)]
            if reconciliation['errors'] or not all(r['account_control_matches'] for r in reconciliation['accounts']):
                raise ValueError(f'Printed account/moku controls differ: {key}')
            candidates={'legal-setsu':legal,'moku-controls':moku,'account-controls':account_controls}
            words=[json.loads(l) for l in (work/f'page-words-{sha}.jsonl').read_text().splitlines()]
        else:
            reconciliation=funding(actual,work)
            candidates={'project-funding':[json.loads(l) for l in (work/'funding-full.jsonl').read_text().splitlines()],
                        'project-controls':json.loads((work/'funding-project-controls.json').read_text())}
            for i,r in enumerate(candidates['project-controls'],1):r['source_row']=i
            words=[dict(origin_url=spec['url'],origin_sha256=sha,year=year,physical_page=i,word_index=j,
                        page_width=width,page_height=height,bbox=list(w[:4]),text=w[4])
                   for i,(width,height,ws) in enumerate(pages_of(pdf,1,spec['physical_pages']),1) for j,w in enumerate(ws,1)]
        for i,r in enumerate(words,1):r['source_row']=i
        candidates['source-words']=words
        for table in spec['tables']:
            role=table['role'];observations=[r for r in candidates[role] if not table['account'] or r.get('account')==table['account']]
            rows=[]
            grain={'legal-setsu':'printed-moku-by-legal-setsu','project-funding':'printed-project-by-funding-source',
                   'moku-controls':'nonadditive-printed-moku-control','account-controls':'nonadditive-printed-account-control',
                   'project-controls':'nonadditive-printed-project-control','source-words':'nonadditive-positioned-source-word'}[role]
            for r in observations:
                value=r.get('amount',r.get('total_amount',r.get('project_total_amount')))
                printed=r.get('amount_printed',r.get('total_printed',r.get('project_total_printed',r.get('printed'))))
                bbox=r.get('amount_box',r.get('total_box',r.get('project_total_box',r.get('bbox'))))
                if role=='account-controls':value=r['amount'];printed=r['printed'];bbox=r['bbox']
                row=dict(jurisdiction_code=code,fiscal_year=year,document_kind='settlement',direction='expenditure',phase='executed',
                    source_key='settlement-pdf:'+key,origin_url=spec['url'],origin_sha256=sha,table_id=table['table_id'],
                    account=r.get('account',''),fund_label=table['fund_label'],grain=grain,observation_role=role,
                    source_row=r['source_row'],source_amount=value,source_amount_printed=printed,
                    source_amount_unit=spec['source_amount_unit'] if role!='source-words' else None,
                    unit_multiplier=spec['unit_multiplier'] if role!='source-words' else None,
                    source_physical_page=r.get('physical_page',r.get('total_physical_page')),
                    source_printed_page=r.get('printed_page'),source_bbox_json=json.dumps(bbox),
                    kan=r.get('kan'),kou=r.get('kou'),moku=r.get('moku'),kan_label=r.get('kan_name'),kou_label=r.get('kou_name'),moku_label=r.get('moku_name'),
                    setsu_code=r.get('setsu_code'),setsu_label=r.get('setsu_label'),project_code=r.get('project_code'),project_label=r.get('project_name'),
                    funding_code=r.get('funding_code'),funding_label=r.get('funding_label'),
                    source_observation_json=json.dumps(r,ensure_ascii=False,sort_keys=True))
                rows.append(row)
            logical=f'tama-settlement-pdf/jurisdiction={code}/year={year}/document_kind=settlement/edition={sha}/direction=expenditure/table={table["table_id"]}'
            target=output/'raw'/logical/'data.parquet'
            materialization=write_rows(target,rows)
            results.append(dict(source_key='settlement-pdf:'+key,scope_key=key,table=table,path=logical,
                                grain=grain,materialization=materialization,origin=actual,year_basis=spec['year_basis'],
                                printed_controls=reconciliation))
    (output/'canonical-materializations.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    return [{k:v for k,v in r.items() if k not in ('printed_controls','origin')} for r in results]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['funding','books','canonical'],required=True)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--sources', '--sources-toml', dest='sources', type=Path,
                        default=Path(__file__).with_name('sources.json'),
                        help='Source registry; an explicit TOML path replays a legacy declaration')
    parser.add_argument('--origin-dir',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if args.mode=='canonical':
        if args.origin_dir is None: parser.error('--origin-dir is required for canonical mode')
        result=canonical(args.sources,args.origin_dir,args.output)
    else:
        if args.manifest is None: parser.error('--manifest is required for candidate modes')
        spec=json.loads(args.manifest.read_text())
        result=funding(spec,args.output) if args.mode=='funding' else books(spec,args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
