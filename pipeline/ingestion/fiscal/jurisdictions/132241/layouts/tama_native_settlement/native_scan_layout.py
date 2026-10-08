"""Proposed frozen-native positional reconstruction; no network or classification."""


def main():
    from pathlib import Path
    import json,re,hashlib,collections
    import duckdb
    import os
    B=Path(os.environ['TAMA_NATIVE_EVIDENCE']);OUT=Path(os.environ['TAMA_NATIVE_OUTPUT']);OUT.mkdir(parents=True,exist_ok=True)
    SCHEMA=json.loads(Path(os.environ['TAMA_NATIVE_SCHEMA']).read_text())
    PAGE_LABELS=json.loads(Path(os.environ['TAMA_NATIVE_MANIFEST']).read_text())['accepted_page_json_labels']
    PAGES={};COLUMNS={}
    PAGE_ROLES={r['printed_page']:r['page_role'] for r in json.loads((B/'all-page-inventory.json').read_text())}
    for p in (B/'pages').glob('*.json'):
     d=json.loads(p.read_text());d['json_path']=PAGE_LABELS[str(d['expected_printed_page'])];PAGES[d['expected_printed_page']]=d
    for p in (B/'columns').glob('*.json'):
     d=json.loads(p.read_text());COLUMNS[d['printed_page']]=d
    J=lambda x:json.dumps(x,ensure_ascii=False,separators=(',',':'))
    def y(w):return (w['bbox_normalized_top_left'][1]+w['bbox_normalized_top_left'][3])/2
    def x(w):return (w['bbox_normalized_top_left'][0]+w['bbox_normalized_top_left'][2])/2
    def identity(d,w,prefix='observation'):
     return f"{d['origin_sha256']}:p{d['physical_page']:03}:{prefix}:{w['column']}:{w['observation_index']:04}"
    def origin(d):return {'jurisdiction_code':'132241','financial_year':2020,'phase':'executed','origin_sha256':d['origin_sha256'],'origin_url':d['origin_url'],'part':d['part'],'physical_page':d['physical_page'],'printed_page':d['expected_printed_page'],'amount_unit':'円','amount_multiplier':1,'page_json':d['json_path']}
    def is_code(w):return re.match(r'^\s*([0-9]{1,2})\s*([^\d,].*[一-龯ぁ-んァ-ヶ].*|[一-龯ぁ-んァ-ヶ].*)$',w['text'])
    def parse(s):
     s=re.sub(r'\s','',s)
     if not re.fullmatch(r'(?:△|-|−)?(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)',s):return None
     neg=s[0] in '△-−';return int(s.lstrip('△-−').replace(',',''))*(-1 if neg else 1)
    LEFT=[('kan',.044,.145),('kou',.145,.245),('moku',.245,.344),('initial_budget',.344,.452),('supplementary_delta',.452,.56),('carried_budget',.56,.665),('reserve_and_transfer_delta',.665,.771),('current_budget',.771,.888)]
    RIGHT=[('setsu',.09,.216),('budget_current',.216,.322),('executed',.322,.432),('carryover',.432,.55),('unused',.55,.653),('remarks',.653,.93)]
    def words(n,column):
     d=PAGES[n];c=COLUMNS.get(n);shift=c['horizontal_shift'] if c else 0
     bounds=next((a,b) for col,a,b in (LEFT if n%2==0 else RIGHT) if col==column)
     out=[dict(w,pass_kind='adaptive') for w in c['observations'] if w['column']==column] if c else []
     for w in d['observations']:
      if w['column']=='full' and bounds[0]+shift-.005<x(w)<bounds[1]+shift+.005:
       # Do not assign observations spanning adjacent columns to a cell.
       bb=w['bbox_normalized_top_left']
       if bb[0]>=bounds[0]+shift-.012 and bb[2]<=bounds[1]+shift+.012:out.append(dict(w,pass_kind='full'))
     return out

    def cell(n,column,target,cell_bottom=None):
     ws=[w for w in words(n,column) if ((target-.0085<y(w)<cell_bottom) if column=='carryover' and cell_bottom else abs(y(w)-target)<.0085) and .205<y(w)<.924]
     vals=sorted(set(v for w in ws if (v:=parse(w['text'])) is not None))
     garbled=[w for w in ws if parse(w['text']) is None and re.search(r'[0-9△]',w['text'])]
     if column=='carryover' and cell_bottom:
      groups=[]
      for w in sorted(ws,key=y):
       value=parse(w['text'])
       if value is None:continue
       group=next((g for g in groups if abs(g['y']-y(w))<.007),None)
       if group:group['values'].add(value);group['observations'].append(w)
       else:groups.append({'y':y(w),'values':{value},'observations':[w]})
      if groups and all(len(g['values'])==1 for g in groups) and not garbled:
       total=sum(next(iter(g['values'])) for g in groups)
       return {'value':total,'status':'observed-agreement','values':vals,'observations':ws,'printed_components':[{'value':next(iter(g['values'])),'y':g['y'],'observations':g['observations']} for g in groups],'cell_bottom':cell_bottom}
     return {'value':vals[0] if len(vals)==1 else None,'status':'observed-agreement' if len(vals)==1 and not garbled else 'ambiguous' if vals or garbled else 'absent-observation','values':vals,'observations':ws,'cell_bottom':cell_bottom}

    def anchors(n,column,body=True):
     ws=[w for w in words(n,column) if is_code(w) and (.205<y(w)<.924 if body else .08<y(w)<.134)]
     groups=[]
     for w in sorted(ws,key=y):
      match=is_code(w);code=int(match.group(1));g=next((g for g in groups if abs(g['y']-y(w))<.007 and g['code']==code),None)
      if g:g['observations'].append(w)
      else:groups.append({'y':y(w),'code':code,'observations':[w]})
     for g in groups:
      primary=next((w for w in g['observations'] if w['pass_kind']=='adaptive'),g['observations'][0]);g['printed_label_observed']=is_code(primary).group(2).strip();g['primary']=primary
     return groups

    CONTROL_VISUAL={v['observed_id']:v for v in json.loads((B/'control-label-visual-observations.json').read_text())}
    HEADER_VISUAL={(v['printed_page'],v['level']):v for v in json.loads((B/'running-header-visual-observations.json').read_text())}
    legal=[];controls=[];errors=[];words_rows=[];column_rows=[];headers=[];spreads=[]
    accounts=[('general',48,118),('national-health-insurance',140,148),('nursing-care',170,178),('elderly-healthcare',196,198)]
    for account,start,end in accounts:
     for n in range(start,end+1,2):
      l=PAGES[n];r=PAGES[n+1];running=[w for w in l['observations'] if w['column']=='full' and is_code(w) and .08<y(w)<.133]
      running=sorted(running,key=y)
      state={};path_status='printed-running-header'
      if len(running)==3:
       for col,w in zip(['kan','kou','moku'],running):state[col]={'code':int(is_code(w).group(1)),'printed_label_observed':is_code(w).group(2).strip(),'printed_page':n,'physical_page':l['physical_page'],'origin_sha256':l['origin_sha256'],'observation':w,'role':'running-header'}
      else:errors.append({'page':n,'account':account,'error':'running-header-not-exactly-three','observations':running})
      for col in state:
       fix=HEADER_VISUAL[(n,col)];state[col]['code_observed']=state[col]['code'];state[col]['code']=fix['printed_code_visually_read'];state[col]['printed_label_visually_read']=fix['printed_label_visually_read'];state[col]['visual_observation']=fix
      headers.append({'account':account,'left_printed_page':n,'state':json.loads(J(state))})
      events=[]
      for col in ['kan','kou','moku']:
       for a in anchors(n,col):events.append(dict(a,column=col,kind='control'))
      for a in anchors(n+1,'setsu'):events.append(dict(a,column='setsu',kind='legal'))
      # Left/right source scans have small baseline differences; keep both positions.
      events.sort(key=lambda e:(round(e['y']/0.006),0 if e['kind']=='control' else 1))
      for e in events:
       next_y=min([v['y'] for v in events if v['y']>e['y']+.012],default=.921)
       cell_bottom=next_y-.009
       if e['kind']=='control':
        col=e['column'];control_id=f"{l['origin_sha256']}:p{l['physical_page']:03}:{col}:{e['y']:.6f}";fix=CONTROL_VISUAL[control_id];observed_code=e['code'];e['code']=fix['printed_code_visually_read'];state[col]={'code':e['code'],'printed_label_observed':e['printed_label_observed'],'printed_page':n,'physical_page':l['physical_page'],'origin_sha256':l['origin_sha256'],'observation':e['primary'],'role':'body-control','code_observed':observed_code,'printed_label_visually_read':fix['printed_label_visually_read'],'visual_observation':fix}
        target=e['y'];row=origin(l)|{'observed_id':f"{l['origin_sha256']}:p{l['physical_page']:03}:{col}:{target:.6f}",'account':account,'control_level':col,'printed_code':e['code'],'printed_code_ocr_observed':observed_code,'printed_label_visually_read':fix['printed_label_visually_read'],'label_visual_observation_json':J(fix),'printed_label_observed':e['printed_label_observed'],'path_json':J(state),'anchor_bbox_json':J(e['primary']['bbox_normalized_top_left']),'anchor_observations_json':J(e['observations']),'left_y':target,'right_physical_page':r['physical_page'],'right_origin_sha256':r['origin_sha256'],'right_printed_page':n+1}
        for field in ['initial_budget','supplementary_delta','carried_budget','reserve_and_transfer_delta','current_budget']:
         c=cell(n,field,target);row[field]=c['value'];row[field+'_status']=c['status'];row[field+'_observations_json']=J(c)
        for field in ['executed','carryover','unused']:
         c=cell(n+1,field,target,cell_bottom);row[field]=c['value'];row[field+'_status']=c['status'];row[field+'_observations_json']=J(c)
        controls.append(row)
       else:
        row=origin(r)|{'observed_id':f"{r['origin_sha256']}:p{r['physical_page']:03}:setsu:{e['y']:.6f}",'account':account,'source_grain':'printed-moku-by-printed-setsu','printed_setsu_code':e['code'],'printed_setsu_label_observed':e['printed_label_observed'],'path_json':J(state),'anchor_bbox_json':J(e['primary']['bbox_normalized_top_left']),'anchor_observations_json':J(e['observations']),'right_y':e['y'],'mapping_status':'not-classified; printed FY2020 code/name retained; active-year master comparison separate'}
        for col in ['kan','kou','moku']:
         row[col+'_code']=state.get(col,{}).get('code');row[col+'_label_observed']=state.get(col,{}).get('printed_label_observed');row[col+'_label_visually_read']=state.get(col,{}).get('printed_label_visually_read')
        for field in ['budget_current','executed','carryover','unused']:
         c=cell(n+1,field,e['y'],cell_bottom);row[field]=c['value'];row[field+'_status']=c['status'];row[field+'_observations_json']=J(c)
        legal.append(row)
      spreads.append({'account':account,'left_printed_page':n,'right_printed_page':n+1,'running_header_count':len(running),'legal_anchors':sum(e['kind']=='legal' for e in events),'control_anchors':sum(e['kind']=='control' for e in events)})
    for n,d in sorted(PAGES.items()):
     role=PAGE_ROLES[n]
     for w in d['observations']:
      if w['column']!='full':continue
      words_rows.append(origin(d)|{'phase':None,'amount_unit':None,'amount_multiplier':None,'observed_id':identity(d,w),'page_role':role,'observed_text':w['text'],'confidence':w['confidence'],'bbox_json':J(w['bbox_normalized_top_left']),'alternatives_json':J(w['alternatives'])})
     for w in COLUMNS.get(n,{}).get('observations',[]):column_rows.append(origin(d)|{'phase':None,'amount_unit':None,'amount_multiplier':None,'observed_id':identity(d,w,'adaptive'),'observed_column':w['column'],'observed_text':w['text'],'confidence':w['confidence'],'bbox_json':J(w['bbox_normalized_top_left']),'alternatives_json':J(w['alternatives'])})
    for fix in json.loads((B/'legal-label-visual-observations.json').read_text()):
     row=next(r for r in legal if r['observed_id']==fix['observed_id']);row['printed_setsu_code_ocr_observed']=row['printed_setsu_code'];row['printed_setsu_code']=fix['printed_code_visually_read'];row['printed_setsu_label_visually_read']=fix['printed_label_visually_read'];row['label_visual_observation_json']=J(fix)
    # Separately retained actual visual cell readings override only their identified field.
    for fix in json.loads((B/'monetary-visual-observations.json').read_text()):
     target=next(r for r in (legal if fix['table']=='legal-observations' else controls) if r['observed_id']==fix['observed_id'])
     field=fix['field'];raw=json.loads(target[field+'_observations_json']);raw['visual_observation']=fix;raw['value']=fix['value'];raw['status']='visually-read-original-cell'
     target[field]=fix['value'];target[field+'_status']='visually-read-original-cell';target[field+'_observations_json']=J(raw)
    # Preserve exact table row sequence and both normalized/image-independent PDF-point positions.
    for rows,kind in [(legal,'legal-expenditure'),(controls,'hierarchy-control')]:
     sequence=collections.Counter()
     for row in rows:
      sequence[row['origin_sha256']]+=1;row['source_row']=sequence[row['origin_sha256']];row['table_id']=kind+'-'+row['account'];row['direction']='expenditure';row['recognition_status']='unconfirmed'
      d=PAGES[row['printed_page']];row['page_width_points']=d['page_width'];row['page_height_points']=d['page_height'];row['bbox_coordinate_system']='top-left; normalized boxes and PDF media-box points'
      row['anchor_bbox_pdf_points_top_left_json']=J([v*(d['page_width'] if i%2==0 else d['page_height']) for i,v in enumerate(json.loads(row['anchor_bbox_json']))])
      fields=['budget_current','executed','carryover','unused'] if kind=='legal-expenditure' else ['initial_budget','supplementary_delta','carried_budget','reserve_and_transfer_delta','current_budget','executed','carryover','unused']
      for field in fields:
       observation=json.loads(row[field+'_observations_json']);original_page=PAGES[row['right_printed_page']] if kind=='hierarchy-control' and field in ['executed','carryover','unused'] else d
       boxes=[w['bbox_normalized_top_left'] for w in observation['observations']]
       if observation.get('visual_observation'):boxes.append(observation['visual_observation']['bbox'])
       row[field+'_bbox_pdf_points_top_left_json']=J([[v*(original_page['page_width'] if i%2==0 else original_page['page_height']) for i,v in enumerate(box)] for box in boxes])
      right=PAGES[row['right_printed_page']] if kind=='hierarchy-control' else d
      row['unit_evidence_json']=J({'origin_sha256':right['origin_sha256'],'physical_page':right['physical_page'],'printed_page':right['expected_printed_page'],'observations':[w for w in right['observations'] if w['column']=='full' and re.search('単位.*円',w['text'])]})
      if kind=='legal-expenditure':
       row['source_amount']=row['executed'];obs=json.loads(row['executed_observations_json']);row['amount_printed_observed']=obs['visual_observation']['visually_read_text'] if obs.get('visual_observation') else next(w['text'] for w in obs['observations'] if parse(w['text'])==row['executed'])
    manifest=[]
    for name,rows in [('legal-observations',legal),('hierarchy-controls',controls),('native-full-page-observations',words_rows),('native-adaptive-column-observations',column_rows),('revenue-native-observations',[r for r in words_rows if r['page_role']=='revenue-observations-only']),('nonfinancial-and-other-native-observations',[r for r in words_rows if r['page_role'] not in ['revenue-observations-only','ordinary-account-expenditure-detail','independent-expenditure-summary']])]:
     p=OUT/(name+'.parquet');j=p.with_suffix('.jsonl');j.write_text(''.join(J(row)+'\n' for row in rows))
     con=duckdb.connect();columns=SCHEMA[name]
     con.execute('create table candidates ('+', '.join(chr(34)+col['name']+chr(34)+' '+col['type'] for col in columns)+')')
     con.executemany('insert into candidates values ('+', '.join('?' for _ in columns)+')',[[row[col['name']] for col in columns] for row in rows])
     for col in ['initial_budget','supplementary_delta','carried_budget','reserve_and_transfer_delta','current_budget','budget_current','executed','carryover','unused']:
      if col in rows[0]:con.execute(f'alter table candidates alter column {col} type bigint')
     con.execute('copy candidates to ? (format parquet, compression zstd)',[str(p)])
     readback=[json.loads(t[0]) for t in con.execute('select to_json(t) from read_parquet(?) t',[str(p)]).fetchall()]
     if readback!=rows:raise ValueError(f'Exact row/value/position Parquet readback differs: {name}')
     schema=con.execute('describe select * from read_parquet(?)',[str(p)]).fetchall();data=p.read_bytes();manifest.append({'path':str(p),'rows':len(readback),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'schema':schema,'all_fields_readback_match':True,'unique_observed_ids':len(set(r['observed_id'] for r in readback))});print(name,len(rows))

    (OUT/'candidate-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));(OUT/'spreads.json').write_text(json.dumps(spreads,ensure_ascii=False,indent=2));(OUT/'running-headers.json').write_text(json.dumps(headers,ensure_ascii=False,indent=2));(OUT/'construction-errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2))
    if any(r['executed'] is None for r in legal+controls):raise ValueError('Missing printed executed field; no synthetic zero')
    summary=[]
    for account,_,_ in accounts:
     rows=[r for r in legal if r['account']==account];m=[r for r in controls if r['account']==account and r['control_level']=='moku'];summary.append({'account':account,'legal_rows':len(rows),'moku_rows':len(m),'legal_executed_observed_sum':sum(r['executed'] for r in rows),'moku_executed_observed_sum':sum(r['executed'] for r in m),'legal_executed_statuses':dict(collections.Counter(r['executed_status'] for r in rows)),'moku_executed_statuses':dict(collections.Counter(r['executed_status'] for r in m)),'legal_missing_executed':len([r for r in rows if r['executed'] is None])})
    (OUT/'candidate-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
