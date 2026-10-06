"""Finite source-preserving materialization; no diagnostic or prior table inputs."""
import json,hashlib,re,copy,unicodedata
from pathlib import Path
from collections import Counter,defaultdict
import duckdb
from .decoder import decode
J=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
H=lambda b:hashlib.sha256(b).hexdigest()
def write_json(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def clean(s):return global_labels.get(s,unicodedata.normalize('NFKC',s or ''))
def images(sha,page):return active_bundle.image(sha,page)
def union(obs):
 return [min(o['bbox'][0] for o in obs),min(o['bbox'][1] for o in obs),max(o['bbox'][2] for o in obs),max(o['bbox'][3] for o in obs)] if obs else None

def nearest(raw,page,box,xlo=190):
 cy=(box[1]+box[3])/2
 return [o for o in raw[page]['observations'] if o['bbox'][0]>=xlo and abs((o['bbox'][1]+o['bbox'][3])/2-cy)<=8]
def num(s):
 s=unicodedata.normalize('NFKC',s).replace(' ','').replace(',','')
 neg=s.startswith(('△','▲','A','Δ','-'));s=s.lstrip('△▲AΔ-')
 return (-1 if neg else 1)*int(s) if s.isdigit() else None

def parquet(rows,kind,sha):
 # Explicit scalar columns and serialized original structures prevent inference of NULL fields.
 keys=list(rows[0]);types={k:'BOOLEAN' if any(isinstance(r[k],bool) for r in rows if r[k] is not None) else 'BIGINT' if any(isinstance(r[k],int) for r in rows if r[k] is not None) else 'DOUBLE' if any(isinstance(r[k],float) for r in rows if r[k] is not None) else 'VARCHAR' for k in keys}
 data=[[r[k] if not isinstance(r[k],(dict,list)) else J(r[k]) for k in keys] for r in rows]
 out=R/'candidates'/sha;out.mkdir(parents=True,exist_ok=True);working=out/f'{kind}.working.parquet'
 with duckdb.connect() as c:
  c.execute('CREATE TABLE t ('+','.join('"'+k+'" '+types[k] for k in keys)+')')
  c.executemany('INSERT INTO t VALUES ('+','.join('?' for k in keys)+')',data)
  c.execute('COPY t TO ? (FORMAT PARQUET, COMPRESSION ZSTD)',[str(working)])
  actual=c.execute('SELECT '+','.join('"'+k+'"' for k in keys)+' FROM read_parquet(?) ORDER BY source_row',[str(working)]).fetchall()
  expected=sorted(data,key=lambda r:r[keys.index('source_row')]);assert [list(r) for r in actual]==expected,(sha,kind,'all-field-readback')
  metrics=c.execute('SELECT count(*),count(distinct source_row),count(*) FILTER (WHERE amount IS NULL),sum(amount) FROM read_parquet(?)',[str(working)]).fetchone()
  schema=c.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(working)]).fetchall()
 b=working.read_bytes();h=H(b);final=out/f'{kind}-{h}.parquet'
 if final.exists():assert final.read_bytes()==b;working.unlink()
 else:working.rename(final)
 csv_path=out/f'{kind}.csv'
 with duckdb.connect() as c:
  c.execute('COPY (SELECT * FROM read_parquet($origin) ORDER BY source_row) TO $output (FORMAT CSV, HEADER, DELIMITER \',\')',{'origin':str(final),'output':str(csv_path)})
 return dict(csv_path=str(csv_path.relative_to(R)),csv_sha256=H(csv_path.read_bytes()),csv_bytes=csv_path.stat().st_size,kind=kind,path=str(final.relative_to(R)),sha256=h,bytes=len(b),row_count=metrics[0],distinct_source_rows=metrics[1],null_amounts=metrics[2],amount_sum=metrics[3],all_field_sql_readback_equal=True,all_field_row_hash=H(J(expected).encode()),schema=[dict(name=s[0],type=s[1],nullable=s[2]) for s in schema])

def build(bundle,configs,output):
 global R,active_bundle,global_labels
 R=Path(output);R.mkdir(parents=True,exist_ok=True);active_bundle=bundle
 master=bundle.json('active-setsu-master-snapshot.json');visual=[];manifests=[];all_rows=[]
 for config in configs:
  g=config['identity'];global_labels=config['labels']
  sha=g['prior_sha256'];year=g['fiscal_year'];account=g['fund_label'];d=R/'ledgers'/sha;d.mkdir(parents=True,exist_ok=True);parsed=decode(bundle,config);raw={p['page']:p for p in bundle.jsonl(f'origins/{sha}/vision-observations.jsonl')};cells={p['page']:p for p in bundle.jsonl(f'origins/{sha}/vision-cells.jsonl')};lo,hi=parsed['spec']['pages']['expenditure']
  council=config['approval'];approved=bundle.approval(config);monthday=approved[2];m,day=map(int,re.findall(r'\d+',monthday));approval=f'{year}-{m:02}-{day:02}';submitted=config['submitted_date']
  base=dict(jurisdiction_code='132071',fiscal_year=year,account_name=account,direction='expenditure',phase='approved',source_url=g['url'],origin_sha256=sha,origin_bytes=g['prior_bytes'],source_table_id=parsed['rows'][0]['source_table_id'],submitted_date=submitted,approval_date=approval,approval_bill=approved[0],approval_result=approved[3],approval_evidence_url=council['url'],approval_evidence_sha256=council['html_sha256'],approval_evidence_row=J(approved),amount_unit='千円')
  rows=[];nodes=copy.deepcopy(parsed['nodes'])
  for n in nodes:
   override=config['field_transcriptions']['nodes'].get(str(n['node_id']))
   if override:n['printed_name']=override['printed_name'];n['source_location']['bbox']=override['bbox']
   n['confirmed_name']=clean(n['printed_name'])
  for ordinal,old in enumerate(parsed['rows'],1):
   loc=old['source_location'];page=loc['page'];box=loc['bbox'];observed=nearest(raw,page,box,0 if not old.get('setsu_name') else 190);fixed={k:clean(old.get(k)) for k in ['kan_name','kou_name','moku_name','project_name','setsu_name','detail_name']}
   for declaration in config['field_transcriptions']['paths']:
    if all(old.get(k)==v for k,v in declaration.items() if k.endswith('_code')):fixed[declaration['field']]=declaration['confirmed']
   fixed.update(config['field_transcriptions']['rows'].get(str(ordinal),{}))
   project=next((n for n in nodes if n['level']=='project' and n['source_location']['page']<=page and tuple(n.get(k+'_code') for k in ['kan','kou','moku'])==tuple(old.get(k+'_code') for k in ['kan','kou','moku']) and n['confirmed_name']==fixed['project_name']),None)
   # Multiple projects in one moku: exact parser project string is the observed nesting link.
   setsu=next((n for n in reversed(nodes) if n['level']=='setsu' and project and n['parent_node_id']==project['node_id'] and n['confirmed_name']==fixed['setsu_name'] and n['source_location']['page']<=page and (n['source_location']['page']<page or n['source_location']['bbox'][1]<box[1]) and tuple(n.get(k+'_code') for k in ['kan','kou','moku'])==tuple(old.get(k+'_code') for k in ['kan','kou','moku'])),None)
   pc=re.match(r'^(\d{3})(.*)$',fixed['project_name']) if year==2023 else None
   pname=pc[2] if pc else fixed['project_name'];dep=re.search(r'\(([^()]*)\)$',pname);department=dep[1] if dep else None
   image=images(sha,page);rid=f'{sha}:expenditure:{ordinal:04}'
   vals=dict(source_row=ordinal,source_row_id=rid,source_grain='printed-project-setsu-explanation-detail' if fixed['setsu_name'] else 'printed-moku-reserve',physical_page=page,source_bbox=J(box),printed_page=clean(next((o['text'] for o in raw[page]['observations'] if o['bbox'][1]>790 and re.search(r'\d',o['text'])),'')),amount=old['amount'],printed_value=str(old['amount']) if not observed else ' | '.join(o['text'] for o in observed if num(o['text'])==old['amount']) or str(old['amount']),printed_text_raw=J(observed),printed_text_confirmed=J(dict(**fixed,amount=old['amount'])),kan_code=old['kan_code'],kou_code=old['kou_code'],moku_code=old['moku_code'],**fixed,project_code=pc[1] if pc else None,project_label=pname,department=department,project_control_node_id=project['node_id'] if project else None,project_physical_page=project['source_location']['page'] if project else None,project_bbox=J(project['source_location']['bbox']) if project else None,setsu_control_node_id=setsu['node_id'] if setsu else None,setsu_physical_page=setsu['source_location']['page'] if setsu else None,setsu_bbox=J(setsu['source_location']['bbox']) if setsu else None,printed_setsu_code=None,statutory_setsu_id=None,statutory_mapping_state='unconfirmed-no-printed-explanation-code' if fixed['setsu_name'] else 'unconfirmed-blank-reserve-code',visual_evidence_path=image['path'],visual_evidence_sha256=image['sha256'],numeric_moku_control_matches=old['moku_reconciled'])
   row=base|vals;rows.append(row)
   changes={k:dict(raw=old.get(k),confirmed=fixed[k]) for k in fixed if old.get(k,'')!=fixed[k]};visual.append(dict(source_row_id=rid,physical_page=page,bbox=box,visual_evidence=image,raw_observations=observed,visually_confirmed_fields=fixed|{'amount':old['amount']},changes=changes,method='Direct review of original PDF raster; whitespace/NFKC normalized; no language correction or master-based substitution'))
  controls=[]
  def control(kind,amount,page,box,name='',path=None,**extra):
   ctrl=base|dict(source_row=len(controls)+1,source_row_id=f'{sha}:control:{len(controls)+1:04}',control_kind=kind,nonadditive=True,amount=amount,physical_page=page,source_bbox=J(box),printed_label=name,path_codes=J(path),printed_text_raw=J(nearest(raw,page,box,0)),visual_evidence_path=images(sha,page)['path'],visual_evidence_sha256=images(sha,page)['sha256'],extra_evidence=J(extra));controls.append(ctrl)
  for n in nodes:
   if n['level'] in ['project','setsu']:
    control('printed-'+n['level'],n['printed_amount'],n['source_location']['page'],n['source_location']['bbox'],n['confirmed_name'],[n.get(k+'_code') for k in ['kan','kou','moku']],node_id=n['node_id'],parent_node_id=n['parent_node_id'],descendant_leaf_sum=n['descendant_leaf_sum'],matches=n['control_matches'],raw_printed_name=n['printed_name'])
  left=[]
  left_source=copy.deepcopy(parsed['aux']['setsu_observations'])
  # Two tiny printed 1 cells missed by Vision, directly reviewed on native rasters.
  # These are observations of existing left control cells, not residual allocation.
  manual_left=config['direct_cells']['left_controls']
  for page,box,path,code,name in manual_left:
   left_source.append(dict(source_location=dict(page=page,bbox=box),setsu_code=code,setsu_name=name,amount=1,**dict(zip(['kan_code','kou_code','moku_code'],path))))
   visual.append(dict(source_row_id=f'{sha}:manual-left:{code}',physical_page=page,bbox=box,visual_evidence=images(sha,page),raw_observations=nearest(raw,page,box,0),visually_confirmed_fields=dict(printed_code=code,printed_name=name,printed_value='1',amount=1),changes=dict(reason='Native recognition omitted the explicitly printed left amount 1; direct original-cell transcription'),method='Direct visual transcription; no residual subtraction'))
  for i,s in enumerate(left_source,1):
   label=clean(s['setsu_name']);code=s['setsu_code'];
   if code in config['field_transcriptions']['left_codes']:label=config['field_transcriptions']['left_codes'][code]
   norm=code.zfill(2);active=[m for m in master if m['code']==norm and (m['valid_from_fiscal_year'] is None or year>=m['valid_from_fiscal_year']) and (m['valid_to_fiscal_year'] is None or year<=m['valid_to_fiscal_year'])];exact=[m for m in active if m['label']==label];mapped=exact[0]['expenditure_setsu_id'] if len(exact)==1 else None
   x=base|dict(source_row=i,source_row_id=f'{sha}:left-setsu:{i:04}',control_kind='printed-left-moku-legal-setsu',nonadditive=True,amount=s['amount'],physical_page=s['source_location']['page'],source_bbox=J(s['source_location']['bbox']),printed_code=code,printed_name_raw=s['setsu_name'],printed_name_confirmed=label,kan_code=s['kan_code'],kou_code=s['kou_code'],moku_code=s['moku_code'],statutory_setsu_id=mapped,statutory_mapping_state='confirmed-printed-code-name-active-year' if mapped else 'unconfirmed-printed-name-master-conflict',active_master_candidates=J(active),visual_evidence_path=images(sha,s['source_location']['page'])['path'],visual_evidence_sha256=images(sha,s['source_location']['page'])['sha256']);left.append(x)
   visual.append(dict(source_row_id=x['source_row_id'],physical_page=x['physical_page'],bbox=s['source_location']['bbox'],visual_evidence=images(sha,x['physical_page']),raw_observations=nearest(raw,x['physical_page'],s['source_location']['bbox'],0),visually_confirmed_fields=dict(printed_code=code,printed_name=label,amount=s['amount']),changes=dict(raw_label=s['setsu_name'],confirmed_label=label),statutory_mapping_state=x['statutory_mapping_state'],method='Original separate left-cell visual review; no assignment to project explanation rows'))
   control('printed-left-setsu',s['amount'],s['source_location']['page'],s['source_location']['bbox'],label,[s[k+'_code'] for k in ['kan','kou','moku']],printed_code=code,statutory_mapping_state=x['statutory_mapping_state'])
  # All independently printed current/prior/comparison numeric rows, including totals and
  # uncoded discontinued zero controls. Alignment uses observed physical cells only.
  comparisons=[]
  # Explicit exact visual cells whose native OCR is missing or wrong. Values below are
  # direct readings, never calculated from the other comparison columns.
  manual_comparison={sha[:4]:config['direct_cells']['body_comparison']}
  for page in range(lo,hi,2):
   obs=cells[page]['observations'];groups=[]
   numeric=sorted([o for o in obs if o.get('zone') in [2,3] and num(o['text']) is not None],key=lambda o:o['bbox'][1])
   for o in numeric:
    cy=(o['bbox'][1]+o['bbox'][3])/2
    if not groups or cy-groups[-1][0]>7:groups.append([cy,[]])
    groups[-1][1].append(o)
   for cy,seeds in groups:
    cols=[];values=[]
    for z in [2,3,4]:
     candidates=[o for o in obs if o.get('zone')==z and abs((o['bbox'][1]+o['bbox'][3])/2-cy)<7]
     numeric_candidates=[o for o in candidates if num(o['text']) is not None]
     value=num(numeric_candidates[0]['text']) if len(numeric_candidates)==1 else None
     manual=next((a for a in manual_comparison.get(sha[:4],[]) if a[0]==page and abs(a[1]-cy)<3 and a[2]==z),None)
     if manual:
      value=manual[3];xr=([138,197],[197,254],[254,311]) if year==2023 else ([127,184],[184,244],[244,303]);box=[xr[z-2][0],cy-8,xr[z-2][1],cy+8]
      visual.append(dict(source_row_id=f'{sha}:comparison:{page}:{cy:.2f}:{z}',physical_page=page,bbox=box,visual_evidence=images(sha,page),raw_observations=candidates,visually_confirmed_fields=dict(printed_value=manual[4],amount=value),changes=dict(reason='Direct source visual transcription of missing/wrong tiny cell'),method='Direct original-cell review; no arithmetic-derived fill'))
      cols+=candidates or [dict(text=manual[4],bbox=box,method='direct visual source-cell transcription')]
     else:cols+=numeric_candidates
     assert value is not None,(sha,page,cy,z,'unconfirmed comparison cell')
     values.append(value)
    labels=[o for o in obs if o.get('zone')==1 and abs((o['bbox'][1]+o['bbox'][3])/2-cy)<8]
    assert values[0]-values[1]==values[2],(sha,page,cy,values)
    comparisons.append(dict(physical_page=page,bbox=union(cols+labels),printed_labels=[o['text'] for o in labels],printed_current=values[0],printed_previous=values[1],printed_comparison=values[2],arithmetic_matches=True,raw_observations=cols+labels))
    control('printed-current-prior-comparison',values[0],page,union(cols+labels),' | '.join(o['text'] for o in labels),None,printed_previous=values[1],printed_comparison=values[2],arithmetic_matches=True,raw_cells=cols)
  expected_comparisons=config['expected_counts']['printed_comparison_controls']
  assert len(comparisons)==expected_comparisons,(sha,'comparison-row-census',len(comparisons))
  totals=tuple(config['first_article'][k] for k in ['amount','previous','comparison'])
  def totalbox(page,value):
   observed=[o for o in raw[page]['observations'] if str(value) in re.sub(r'[, ]','',o['text'])];return union(observed) or [0,0,*raw[page]['bounds']]
  control('first-article',totals[0],3,totalbox(3,totals[0]),'第1条 歳入歳出予算',None,bill=approved[0],submitted_date=submitted)
  ap=7 if account=='国民健康保険特別会計' else 5
  control('account-total',totals[0],ap,totalbox(ap,totals[0]),'歳出 合計',None,printed_previous=totals[1],printed_comparison=totals[2],arithmetic_matches=totals[0]-totals[1]==totals[2])
  printed_moku=[c for c in comparisons if c['printed_labels'] and re.match(r'^\d+\s*',c['printed_labels'][0])]
  assert len(printed_moku)==len(parsed['moku']),(sha,'coded-moku physical row census')
  for m,printed in zip(parsed['moku'],printed_moku):
   printed_code=re.match(r'^(\d+)',printed['printed_labels'][0])[1]
   assert printed_code==m['path'][2],(sha,'printed moku code/order disagreement')
   match=[r for r in rows if [r[k+'_code'] for k in ['kan','kou','moku']]==m['path']];assert sum(r['amount'] for r in match)==m['amount']==printed['printed_current']
   control('coded-moku',m['amount'],printed['physical_page'],printed['bbox'],match[0]['moku_name'],m['path'],leaf_sum=sum(r['amount'] for r in match),matches=True,printed_previous=printed['printed_previous'],printed_comparison=printed['printed_comparison'],arithmetic_matches=printed['arithmetic_matches'],identity_basis='Printed moku code and observed publication order under explicit kan/kou headers; no amount/name matching')
  summary_controls=[]
  manual_summary={sha[:4]:config['direct_cells']['summary_comparison']}
  kan=None;summary_kan=[];summary_kou=[]
  for pg in ([6,7] if account=='国民健康保険特別会計' else [5]):
   obs=raw[pg]['observations'];groups=[]
   numeric=sorted([o for o in obs if o['bbox'][0]>290 and num(o['text']) is not None and 95<o['bbox'][1]<765],key=lambda o:o['bbox'][1])
   for o in numeric:
    cy=(o['bbox'][1]+o['bbox'][3])/2
    if not groups or cy-groups[-1][0]>7:groups.append([cy,[]])
    groups[-1][1].append(o)
   for cy,observed in groups:
    values=[];cols=[]
    for z,(xl,xh) in enumerate([(290,400),(400,485),(485,580)]):
     selected=[o for o in observed if xl<=o['bbox'][0]<xh];value=num(selected[0]['text']) if len(selected)==1 else None
     manual=next((v for v in manual_summary.get(sha[:4],[]) if v[0]==pg and abs(v[1]-cy)<3 and v[2]==z),None)
     if manual:
      value=manual[3];box=[xl,cy-8,xh,cy+8];visual.append(dict(source_row_id=f'{sha}:summary:{pg}:{cy:.2f}:{z}',physical_page=pg,bbox=box,visual_evidence=images(sha,pg),raw_observations=selected,visually_confirmed_fields=dict(printed_value=manual[4],amount=value),changes=dict(reason='Direct source visual transcription; native OCR missing or misrecognized glyph'),method='No arithmetic-derived fill'))
      cols+=selected or [dict(text=manual[4],bbox=box,method='direct visual source-cell transcription')]
     else:cols+=selected
     assert value is not None,(sha,pg,cy,z,'unconfirmed summary cell')
     values.append(value)
    assert values[0]-values[1]==values[2],(sha,pg,cy,values,'summary comparison')
    labels=[o for o in obs if o['bbox'][0]<290 and abs((o['bbox'][1]+o['bbox'][3])/2-cy)<8]
    role='account-total' if any('合計' in o['text'].replace(' ','') for o in labels) else 'kan' if any(o['bbox'][0]<160 for o in labels) else 'kou'
    code=next((re.match(r'^(\d+)',o['text'])[1] for o in labels if re.match(r'^\d+',o['text'])),None)
    if role=='kan':kan=code
    path=[kan] if role=='kan' else [kan,code] if role=='kou' else None
    leaf_sum=sum(r['amount'] for r in rows if r['kan_code']==kan and (role=='kan' or r['kou_code']==code)) if code is not None and role in ['kan','kou'] else None
    if leaf_sum is not None:assert leaf_sum==values[0],(sha,path,leaf_sum,values[0],'independent kan/kou control')
    sc=dict(physical_page=pg,bbox=union(cols+labels),role=role,printed_code=code,path_codes=path,printed_labels=[o['text'] for o in labels],printed_current=values[0],printed_previous=values[1],printed_comparison=values[2],arithmetic_matches=True,expenditure_leaf_sum=leaf_sum,raw_observations=cols+labels)
    summary_controls.append(sc)
    control('first-budget-summary-'+role,values[0],pg,sc['bbox'],' | '.join(sc['printed_labels']),path,printed_code=code,printed_previous=values[1],printed_comparison=values[2],arithmetic_matches=True,expenditure_leaf_sum=leaf_sum,raw_cells=cols)
  expected_summary=config['expected_counts']['first_budget_summary_controls']
  assert len(summary_controls)==expected_summary,(sha,'first-budget summary row census')
  write_json(d/'first-budget-summary-controls.json',summary_controls)
  left_sums=defaultdict(int)
  for s in left:left_sums[tuple(s[k+'_code'] for k in ['kan','kou','moku'])]+=s['amount']
  for m in parsed['moku']:
   path=tuple(m['path']);is_reserve=all(not r['setsu_name'] for r in rows if tuple(r[k+'_code'] for k in ['kan','kou','moku'])==path)
   if not is_reserve:assert left_sums[path]==m['amount'],(sha,path,'left-control')
  assert sum(r['amount'] for r in rows)==sum(m['amount'] for m in parsed['moku'])==totals[0]
  assert all(n['control_matches'] for n in nodes if n['level'] in ['project','setsu'])
  files=[parquet(rows,'explanation-detail',sha),parquet(controls,'nonadditive-controls',sha),parquet(left,'printed-left-legal-setsu',sha)]
  write_json(d/'visual-confirmed-rows.json',rows);write_json(d/'visual-confirmed-controls.json',controls);write_json(d/'current-prior-comparison-controls.json',comparisons)
  result=dict(year=year,account=account,origin_url=g['url'],origin_sha256=sha,origin_bytes=g['prior_bytes'],physical_pages=g['physical_pages'],expenditure_scope=[lo,hi],submitted_date=submitted,approval_date=approval,approval_evidence=council['url'],approval_bill=approved[0],leaf_rows=len(rows),reserve_rows=sum(not r['setsu_name'] for r in rows),amount_sum_thousand_yen=totals[0],printed_previous_thousand_yen=totals[1],printed_comparison_thousand_yen=totals[2],coded_moku_controls=len(parsed['moku']),project_controls=sum(n['level']=='project' for n in nodes),setsu_controls=sum(n['level']=='setsu' for n in nodes),left_legal_setsu_controls=len(left),first_budget_summary_controls=len(summary_controls),first_budget_summary_failures=0,printed_comparison_controls=len(comparisons),printed_comparison_failures=sum(not a['arithmetic_matches'] for a in comparisons),confirmed_left_statutory_rows=sum(x['statutory_setsu_id'] is not None for x in left),unconfirmed_left_statutory_rows=sum(x['statutory_setsu_id'] is None for x in left),all_numeric_leaf_project_setsu_moku_account_article_controls_match=True,candidate_status='complete-expenditure-explanation-candidate-with-unconfirmed-explanation-statutory-code',tables=files)
  for key,value in config['expected_counts'].items():assert result[key]==value,(sha,key,'finite declared row/control count mismatch')
  manifests.append(result);all_rows+=rows
 write_json(R/'candidate-manifest.json',manifests)
 write_json(R/'visual-cell-ledger.json',visual)
 write_json(R/'actual-readback.json',dict(editions=len(manifests),rows=len(all_rows),unique_source_row_ids=len({r['source_row_id'] for r in all_rows}),null_amounts=sum(r['amount'] is None for r in all_rows),reserve_rows=sum(not r['setsu_name'] for r in all_rows),all_field_readback_equal=all(t['all_field_sql_readback_equal'] for m in manifests for t in m['tables']),tables=[t for m in manifests for t in m['tables']]))
 return dict(editions=len(manifests),rows=len(all_rows),controls=sum(t['row_count'] for m in manifests for t in m['tables'] if t['kind']=='nonadditive-controls'),left_rows=sum(t['row_count'] for m in manifests for t in m['tables'] if t['kind']=='printed-left-legal-setsu'),tables=len(manifests)*3)
