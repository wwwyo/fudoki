"""Frozen native observations and explicit visual readings; exact five original scope."""
import json,re,hashlib,collections
from ingestion.fiscal.extract_supplementary_expenditure import norm,number,validate
from ingestion.fiscal.extract_komae_council_approved_detail import validate_printed_labels,bind_approval,COLUMNS
AM=r'[△▲\-−]?\d[\d,、，]*'
def n(s):return number(norm(s).replace('、',',').replace('▲','△').replace('−','-'))
def obs_loc(o,p):return dict(page_number=p,bbox=o['bbox'],printed_text=o['text'],recognition_confidence=o['confidence'],native_observation_index=o['index'],native_observation_path=o.get('evidence_json_path'),direct_transcription=o.get('direct_transcription'))
def groups(obs):
 rs=[]
 for o in sorted(obs,key=lambda o:sum(o['bbox'][1::2])/2):
  cy=(o['bbox'][1]+o['bbox'][3])/2
  if not rs or abs(cy-rs[-1]['center'])>4:rs.append({'center':cy,'items':[]})
  rs[-1]['items'].append(o)
 return [(x['center'],sorted(x['items'],key=lambda o:o['bbox'][0])) for x in rs]
def label_amount(items):
 amounts=[o for o in items if re.fullmatch(AM,norm(o['text'])) and o['bbox'][0]>700]
 labels=[o for o in items if o not in amounts]
 return ''.join(norm(o['text']) for o in labels), (n(amounts[0]['text']) if len(amounts)==1 else None), (amounts[0]['text'] if len(amounts)==1 else None)
def parse(c,runtime):
 keys=runtime.identities
 TRANS=runtime.transcriptions
 direct_indices=runtime.transcription_indices
 if (c['fiscal_year'],c['fund_label'],c['amendment_number']) not in keys:raise ValueError('Outside exact five-edition private scope')
 runtime.object(c['expected_sha256'])
 pages=[];problems=[];arithmetic_failures=[];title=f"令和{c['fiscal_year']-2018}年度狛江市{c['fund_label']}補正予算(第{c['amendment_number']}号)"
 for p in range(c['first_page'],c['last_page']+1):
  variant='vision-adaptive' if ((c['fiscal_year'],c['amendment_number'])==(2021,11) and p>=17) or ((c['fiscal_year'],c['amendment_number'])==(2022,1) and p>=29) else 'vision-final'
  d=runtime.page(c,p,variant)
  for i,o in enumerate(d['observations']):o['index']=i;o['evidence_json_path']=runtime.page_ref(c,p,variant)['archival_label']
  for tr in TRANS:
   if str(tr['native_observation_index']).startswith('reduced-') or tr.get('variant',tr.get('observation_base','vision-final'))!=variant:continue
   if tr['original_sha256']!=c['expected_sha256'] or tr['physical_pdf_page']!=p:continue
   runtime.verify_transcription(c,p,variant,tr)
   if tr['native_observation_index'] is not None:
    o=d['observations'][tr['native_observation_index']]
    if o['text']!=tr['previous_text']:raise ValueError('Direct observation target text differs')
    o.update(text=tr['observed_text'],bbox=tr['bbox'],direct_transcription=tr)
   else:d['observations'].append(dict(column=tr['column'],text=tr['observed_text'],bbox=tr['bbox'],confidence=None,index='direct-'+str(direct_indices[TRANS.index(tr)]),direct_transcription=tr))
  pages.append((p,d))
 alltext={p:''.join(norm(o['text']) for _,g in groups([o for o in d['observations'] if o['column']=='whole']) for o in g) for p,d in pages}
 cover=next((p for p,d in pages[:4] if title in alltext[p] and '第1条' not in alltext[p]),None)
 article=next((p for p,d in pages[:5] if title in alltext[p] and '第1条' in alltext[p]),None)
 if cover is None or article is None:raise ValueError(f'OCR cover/article identity not fully decoded: cover={cover} article={article}')
 a=alltext[article];match=re.search(r'第1条歳入歳出予算の総額[にから]+[、,]?歳入歳出それぞれ([\d,、]+)千円を(追加|減額)',a)
 if not match:raise ValueError('OCR first article amount/action not fully decoded')
 delta=n(match[1])*(-1 if match[2]=='減額' else 1)
 submitted=re.search(r'令和(\d+)年(\d+)月(\d+)日(提出|専決)',a)
 if not submitted:raise ValueError('Printed submission/disposition date not decoded')
 control={'printed_cover_text':alltext[cover],'submitted_at':f'{2018+int(submitted[1])}-{int(submitted[2]):02}-{int(submitted[3]):02}','submitted_basis':submitted[4],'approval_status':'unconfirmed','edition_status':'published','effective_at':None,'approval_evidence':None,'source_page_range':[cover,c['last_page']],'first_article':{'page_number':article,'amount_delta':delta,'printed_text':match[0],'native_page_observation_path':runtime.page_ref(c,article,'vision-final')['archival_label']}}
 # Readable numbered proposal and official decision remain the original approval proof;
 # OCR cover is preserved separately, never used to promote a cabinet draft.
 cc={**c,'submitted_at':control['submitted_at'],'approval_proof':{**c['approval_proof'],'original_identity_evidence':[e for e in c['approval_proof']['original_identity_evidence'] if '上記の議案' in e['observed_text'] or '地方自治法' in e['observed_text']]}}
 runtime.verify_approval(cc,runtime.object(c['expected_sha256']),control)
 moku_controls={};projects=[];leaves=[];left=[];headers=[];moku=None;project=None;left_open=None;pending=None;kan=kou=None;expenditure=False;department='';units=None
 for p,d in pages:
  reduced=False
  me,be,de,ae,ll,lr,el,er=({(2021,11):(142,190,237,284,516,628,628,762),(2022,1):(100,155,209,263,533,656,656,810)}.get((c['fiscal_year'],c['amendment_number']),(115,170,220,275,528,650,650,810)))
  if any('当該年度末現在高見込額' in norm(o['text']) for o in d['observations'] if o['column']=='whole'):expenditure=False
  whole=[o for o in d['observations'] if o['column']=='whole'];
  body=[o for o in whole if o['bbox'][0]>=ae or '(款)' in norm(o['text']) or '(項)' in norm(o['text']) or '歳出' in norm(o['text']) or '歲出' in norm(o['text']) or '千円'==norm(o['text']) or '給与費' in norm(o['text']) or '地方債' in norm(o['text'])]
  body += [o for o in d['observations'] if o['column'] in ['moku','before','delta','after'] and norm(o['text'])!='千円']
  wg=groups(body)
  cell=[o for o in d['observations'] if o['column'] in ['left_setsu','explanation']];cg=groups(cell)
  events=[]
  for y,g in wg:events.append((y,'whole',g))
  for y,g in cg:events.append((y,'cell',g))
  for y,kind,g in sorted(events,key=lambda x:(x[0],x[1])):
   t=''.join(norm(o['text']) for o in g)
   if kind=='whole':
    hg=[o for o in whole if abs((o['bbox'][1]+o['bbox'][3])/2-y)<5]
    if any('(款)' in norm(o['text']) or '(項)' in norm(o['text']) for o in hg):
     if y>530:continue # Repeated footer identity is outside the printed table.
     t=''.join(norm(o['text']) for o in sorted(hg,key=lambda o:o['bbox'][0]))
    if re.match(r'3[.．][歳歲]出',t):expenditure=True;kan=kou=None;continue
    if re.match(r'2[.．]歳入',t) or any(q in t for q in ['給与費明細書','地方債の前前年度末','債務負担行為で翌年度以降']):expenditure=False
    if not expenditure:continue
    kh=re.search(r'\(款\)(\d+)[.．]',t);qh=re.search(r'\(項\)(\d+)[.．]',t)
    if kh:kan=int(kh[1]);kou=None
    if qh:kou=int(qh[1])
    if kh or qh:continue
    currency=[o for o in d['observations'] if norm(o['text'])=='千円' and abs((o['bbox'][1]+o['bbox'][3])/2-y)<4];cu={}
    for name,lo,hi in [('before',me,be),('delta',be,de),('after',de,ae),('left_setsu',ll,lr),('explanation',el,er)]:
     matches=[o for o in currency if lo<o['bbox'][0]<hi]
     matches=sorted(matches,key=lambda o:(o['column']!='whole',-(o['confidence'] or 0)))[:1]
     if len(matches)==1:cu[name]=obs_loc(matches[0],p)
    if len(cu)==5:units={'unit':'千円',**cu}
    labelobs=[o for o in g if o['bbox'][0]<me];label=''.join(norm(o['text']) for o in labelobs);mh=re.fullmatch(r'(\d+)[.．](.+)',label)
    if not mh:
     if moku and p==moku_controls[moku]['page_number'] and y<json.loads(moku_controls[moku]['bbox_json'])[3]+35 and label and not re.fullmatch(r'\d+[.．]',label) and not any(z in label for z in ['計','目','(款)','(項)','歳出','補正','千円','区','分']) and all(o['column']=='moku' for o in labelobs):
      moku_controls[moku]['moku_label']+=label
      moku_controls[moku].setdefault('label_continuation_evidence',[]).extend(obs_loc(o,p) for o in labelobs)
     continue
    if units is None:continue
    if any(o['bbox'][0]<me and '(款)' in norm(o['text']) for o in whole if abs((o['bbox'][1]+o['bbox'][3])/2-y)<5):continue
    if '地方債' in t or '普通債' in t:continue
    amounts=[];aobs=[]
    for lo,hi in [(me,be),(be,de),(de,ae)]:
     os=[o for o in g if lo<=o['bbox'][0]<hi and re.fullmatch(AM,norm(o['text']))]
     if len(os)!=1:raise ValueError(f'Physical{p} moku {label} lacks independently printed triple: {t}')
     amounts.append(n(os[0]['text']));aobs.append(os[0])
    before,change,after=amounts
    if before+change!=after:arithmetic_failures.append(dict(page_number=p,moku_label=label,amount_before=before,amount_delta=change,amount_after=after,observations=[obs_loc(o,p) for o in aobs],status='printed-triple-disagreement-held'))
    if not units:raise ValueError(f'Physical{p} independent unit/header evidence incomplete')
    moku=(kan,kou,int(mh[1]));project=None;left_open=None;department=''
    if kan is None or kou is None or moku in moku_controls:raise ValueError(f'Physical{p} missing hierarchy/duplicate moku {moku}')
    moku_controls[moku]={'source_row':len(moku_controls)+1,'kan_code':str(kan),'kou_code':str(kou),'moku_code':mh[1],'moku_label':mh[2],'amount_before':before,'amount_delta':change,'amount_after':after,'page_number':p,'bbox_json':json.dumps([min(o['bbox'][0] for o in g),min(o['bbox'][1] for o in g),ae,max(o['bbox'][3] for o in g)]),'amount_observations':[obs_loc(o,p) for o in aobs]}
    headers.append({'moku':moku,'location':obs_loc(labelobs[0],p)})
   elif expenditure and moku:
    ls=[o for o in g if o['column']=='left_setsu'];es=[o for o in g if o['column']=='explanation']
    la=[o for o in ls if re.fullmatch(AM,norm(o['text'])) and o['bbox'][0]>lr-60];ln=[o for o in ls if o not in la];name=''.join(norm(o['text']) for o in ln)
    if ln:
     start=min(o['bbox'][0] for o in ln);lm=re.fullmatch(r'(\d+)[.．](.*)',name)
     if lm and start<ll+4:
      left_open={'moku':moku,'code':lm[1],'label':lm[2],'amount':n(la[0]['text']) if len(la)==1 else None,'raw_amount':la[0]['text'] if len(la)==1 else None,'locations':[obs_loc(o,p) for o in ls],'name_open':True};left.append(left_open)
     elif left_open and left_open['name_open'] and ll+14<start<ll+23 and not la and name:left_open['label']+=name;left_open['locations'] += [obs_loc(o,p) for o in ln]
     elif left_open:left_open['name_open']=False
    if not es:continue
    name,amount,raw=label_amount(es);locs=[obs_loc(o,p) for o in es]
    labels=[o for o in es if not (re.fullmatch(AM,norm(o['text'])) and o['bbox'][0]>700)];start=min((o['bbox'][0] for o in labels),default=999)
    if any(q in name for q in ['千円','説明','区分']) or name in ['説','明','-']:continue
    ph=re.match(r'^(\d+)[.．](.*)',name)
    if ph and start<el+6:
     if pending:problems.append({'reason':'Unfinished OCR explanation name','moku':moku,'page_number':p});pending=None
     project={'source_row':len(projects)+1,'moku':moku,'code':ph[1],'label':ph[2],'amount':amount,'raw_amount':raw,'locations':locs};projects.append(project);department='';continue
    if name.startswith(('〔','[','［','〕')):department=name;continue
    if project and project['amount'] is None and (start<el+26 or not name):
     project['label']+=name;project['locations']+=locs
     if amount is not None:project['amount']=amount;project['raw_amount']=raw
     continue
    if start<el+4 and name:
     if pending:name=pending['name']+name;locs=pending['locations']+locs
     if amount is None:pending={'name':name,'locations':locs};continue
     if project is None:problems.append({'reason':'OCR explanation without observed preceding project','moku':moku,'page_number':p});continue
     leaves.append({'project':project,'moku':moku,'department':department,'setsu_label':name,'amount':amount,'raw_amount':raw,'locations':locs,'unit_evidence':units,'same_row_left_region':{'page_number':p,'bbox':[ll,y-6,lr,y+6],'printed_text':''.join(o['text'] for o in ls)}});pending=None
 if pending:problems.append({'reason':'Unfinished final OCR explanation name','moku':moku,'page_number':p})
 if not moku_controls:raise ValueError('No actual complete expenditure moku triples recovered')
 for tr in runtime.moku_transcriptions:
  if tr['identity']!=f"{c['fiscal_year']}-{c['fund_label']}-{c['amendment_number']}":continue
  runtime.verify_moku_transcription(c,tr)
  k=tuple(tr['control_moku_key'])
  if k not in moku_controls:raise ValueError('Direct moku code path absent')
  moku_controls[k]['moku_label']=tr['observed_label'];moku_controls[k]['direct_moku_transcription']=tr
 control['rows']=list(moku_controls.values())
 result=validate_printed_labels(cc,control,moku_controls,projects,leaves,left,problems,units,headers)
 result=bind_approval(result,cc,control);result['observed_left_controls']=left;result['observed_moku_controls']=list(moku_controls.values());result['ocr_control_total_sum']=sum(x['amount_delta'] for x in moku_controls.values());result['original_candidate']=c;result['printed_arithmetic_failures']=arithmetic_failures
 if arithmetic_failures:result['fully_complete_observed_grain']=False;result['fully_complete']=False
 return result
