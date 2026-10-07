"""Read Mitaka native supplementary books without inferring adoption or approval.

Independent left setsu and right project roots remain separate printed grains.
"""
from pathlib import Path
from collections import Counter,defaultdict
import json,re,subprocess,statistics,copy
from ingestion.inputs import digest
from ingestion.lib.pdf import pages_of
from ingestion.fiscal.tama_budget_detail import normalize,number,positioned_rows,location

def joined_money(words):
    """Join a geometric printed monetary cell; integral money only."""
    if not words:return None
    text=''.join(w[4] for w in sorted(words,key=lambda w:w[0]));value=number(text)
    return (value,text,words) if value is not None else None

def split_money(words):
    """Separate adjacent numeric fragments from descriptions, preserving operands."""
    chunks=[];current=[]
    for w in sorted(words,key=lambda w:w[0]):
        t=normalize(w[4])
        if re.fullmatch(r'[△▲−\-\d,]+',t):
            if current and w[0]-current[-1][2]>2:chunks.append(current);current=[]
            current.append(w)
        else:
            if current:chunks.append(current);current=[]
    if current:chunks.append(current)
    return [m for chunk in chunks if (m:=joined_money(chunk)) is not None]

class Rows:
    def __init__(self):self.records=[]
    def emit(self,kind,row,code=None,label=None,money=None,kan=None,kou=None,moku=None,project=None,setsu=None,extra=None):
        rec=dict(source_row=len(self.records)+1,record_kind=kind,code=code,label=label,
            amount=money[0] if money else None,amount_text=money[1] if money else None,
            kan=kan,kou=kou,moku=moku,project=project,setsu=setsu,department='',
            location=location(row,row['words']))
        if extra:rec['record_context']=extra
        self.records.append(rec);return rec

def write_table(directory,records,*,financial):
    import duckdb
    directory.mkdir(parents=True,exist_ok=True)
    columns=[('source_row','BIGINT'),('source_observation_row','BIGINT'),('record_kind','VARCHAR'),('code','VARCHAR'),('label','VARCHAR'),('amount','BIGINT'),('amount_text','VARCHAR'),('physical_page','INTEGER'),('bbox_json','VARCHAR'),('printed_text','VARCHAR'),('words_json','VARCHAR'),('context_json','VARCHAR'),('source_grain','VARCHAR'),('printed_setsu_code','VARCHAR')]
    values=[]
    for n,r in enumerate(records,1):
        context={k:r[k] for k in ('kan','kou','moku','project','setsu','department')}
        if r.get('record_context'):context['printed_record_context']=r['record_context']
        values.append((n if financial else r['source_row'],r['source_row'],r['record_kind'],r['code'],r['label'],r['amount'],r['amount_text'],r['location']['page'],json.dumps(r['location']['bbox']),r['location']['printed_text'],json.dumps(r['location']['words'],ensure_ascii=False),json.dumps(context,ensure_ascii=False),r.get('source_grain'),r.get('printed_setsu_code')))
    with duckdb.connect() as c:
        c.execute('create table candidate ('+','.join(a+' '+b for a,b in columns)+')')
        c.executemany('insert into candidate values ('+','.join('?' for _ in columns)+')',values)
        c.execute('copy candidate to ? (format parquet,compression zstd)',[str(directory/'data.parquet')])

def heading_parts(words):
    text=normalize(''.join(w[4] for w in words));match=re.match(r'(\d+)[.．](.+)',text)
    return (match[1],match[2]) if match else None

def hierarchy_x(names,money):
    code=heading_parts(names)[0]
    widths=[(w[2]-w[0])/len(w[4]) for m in money for w in m[2] if re.fullmatch(r'[\d,]+',w[4])]
    if not widths:raise ValueError('No printed digit width for hierarchy indent')
    return names[0][0]+statistics.median(widths)*(len(code)-1)

def book(source,edition,allpages,texts,end):
    firsts=[n for n in range(edition['page'],end+1) if any(normalize(t) in ('3歳出','3.歳出','歳出') for t in texts[n-1].splitlines())]
    if len(firsts)!=1:raise ValueError('No unique expenditure heading in declared edition')
    first=firsts[0];stop=next((n for n in range(first+1,end+1) if any(s in normalize(texts[n-1]) for s in ('給与費明細書','継続費について','地方債の前','債務負担行為で翌年度以降'))),end+1)
    last=stop-1
    while last>=first and not allpages[last-1][2]:last-=1
    if (last-first+1)%2:raise ValueError(f'Unpaired supplementary table pages {first}-{last}')
    pairs=[];xs=[]
    for p in range(first,last+1,2):
        left=positioned_rows(allpages[p-1],p);right=positioned_rows(allpages[p],p+1)
        for row in left:
            name=[w for w in row['words'] if w[0]<170]
            money=split_money([w for w in row['words'] if 170<=w[0]<395])
            if heading_parts(name) and len(money)>=3:xs.append(hierarchy_x(name,money))
        pairs.append((left,right))
    clusters=[]
    for x in sorted(xs):
        if not clusters or x-clusters[-1][-1]>2:clusters.append([x])
        else:clusters[-1].append(x)
    centers=[sum(c)/len(c) for c in clusters]
    if len(centers)!=3:raise ValueError(f'Expected three printed hierarchy indent columns, found {centers}')
    obs=Rows();kan=kou=moku=project=left_setsu=None;pending_name=None;pending_project=None
    moku_controls={};projects={};setsu_controls=defaultdict(int);project_sums=defaultdict(int);details=defaultdict(int);problems=[]
    for left,right in pairs:
        printed_edges=[m[2][-1][2] for r in right if 110<r['y']<750 for m in split_money([w for w in r['words'] if w[0]>=455])]
        root_edge=max(printed_edges) if printed_edges else None
        for _,side,row in sorted([(r['y'],0,r) for r in left]+[(r['y'],1,r) for r in right]):
            words=row['words'];text=normalize(row['text'])
            if row['y']<110 or row['y']>750:
                obs.emit('page-context',row,kan=kan,kou=kou,moku=moku);continue
            if side==0:
                names=[w for w in words if w[0]<170];coded=heading_parts(names);money=split_money([w for w in words if 170<=w[0]<395])
                if coded and len(money)==3:
                    code,label=coded;level=min(range(3),key=lambda i:abs(hierarchy_x(names,money)-centers[i]));before,delta,after=money
                    if before[0]+delta[0]!=after[0]:problems.append({'page':row['page'],'reason':'before+delta!=after','printed':[a[0] for a in money]})
                    if level==0:
                        if kan is None or kan[0]!=code:moku=project=left_setsu=None;kou=None
                        kan=[code,label]
                    elif level==1:
                        if kou is None or kou[0]!=code:moku=project=left_setsu=None
                        kou=[code,label]
                    else:
                        if kan is None or kou is None:problems.append({'page':row['page'],'reason':'moku hierarchy absent'})
                        key=[kan[0] if kan else None,kou[0] if kou else None,code]
                        if moku is None or moku['key']!=key:
                            moku={'key':key,'code':code,'label':label,'before':before[0],'delta':delta[0],'after':after[0],'operand_words':[a[2] for a in money]};project=left_setsu=None
                        elif moku['delta']!=delta[0]:problems.append({'page':row['page'],'reason':'reprinted moku delta changed'})
                        moku_controls[tuple(key)]=delta[0]
                    kind=('kan','kou','moku')[level];obs.emit(kind,row,code,label,delta,kan,kou,moku,extra={'before':before[0],'delta':delta[0],'after':after[0],'operand_words':[a[2] for a in money]})
                    pending_name=(kind,kan if level==0 else kou if level==1 else moku,row['y'],names[0][0]+statistics.median([(w[2]-w[0])/len(w[4]) for a in money for w in a[2] if re.fullmatch(r'[\d,]+',w[4])])*(len(code)+1))
                else:
                    if pending_name and names and not money and 0<row['y']-pending_name[2]<24 and abs(names[0][0]-pending_name[3])<1.5:
                        fragment=normalize(''.join(w[4] for w in names))
                        if pending_name[0]=='moku':pending_name[1]['label']+=fragment
                        else:pending_name[1][1]+=fragment
                        pending_name=(*pending_name[:2],row['y'],pending_name[3])
                    # Original fragments also remain explicit observations.
                    obs.emit('left-context',row,label=normalize(''.join(w[4] for w in names)) or None,kan=kan,kou=kou,moku=moku)
                continue
            section=[w for w in words if w[0]<262];explanation=[w for w in words if w[0]>=262]
            if section:
                monies=split_money([w for w in section if w[0]>=205]);m=monies[-1] if len(monies)==1 else None
                name=[w for w in section if not m or w not in m[2]];coded=heading_parts(name)
                if coded:
                    code,label=coded;left_setsu={'code':code,'label':label,'row':len(obs.records)+1,'label_x':name[0][0]+4.5*(len(code)+1)};obs.emit('left-setsu',dict(row,words=section),code,label,m,kan,kou,moku,setsu=left_setsu)
                    if m and moku:setsu_controls[tuple(moku['key'])]+=m[0]
                else:
                    fragment=normalize(''.join(w[4] for w in name))
                    if left_setsu and name and not m and not fragment.startswith(('(','（')) and abs(name[0][0]-left_setsu['label_x'])<1.5:left_setsu['label']+=fragment
                    obs.emit('left-setsu-context',dict(row,words=section),label=normalize(''.join(w[4] for w in name)) or None,money=m,kan=kan,kou=kou,moku=moku,setsu=left_setsu)
            if not explanation:continue
            monies=split_money([w for w in explanation if w[0]>=455]);m=monies[-1] if len(monies)==1 else None
            name=[w for w in explanation if not m or w not in m[2]];coded=heading_parts(name)
            fragment=normalize(''.join(w[4] for w in name))
            if pending_project and name and not (coded and name[0][0]<282) and 0<row['y']-pending_project['y']<24 and abs(name[0][0]-pending_project['label_x'])<2:
                project['label']+=fragment
                projects[project['row']]['label']=project['label']
                project.setdefault('label_fragments',[]).append({'page':row['page'],'words':name})
                pending_project['y']=row['y']
            else:pending_project=None
            if project is not None and projects[project['row']]['amount'] is None and not (coded and name[0][0]<282) and m and root_edge is not None and abs(m[2][-1][2]-root_edge)<1.5:
                rec=obs.emit('project-delta-continuation',dict(row,words=explanation),project['code'],project['label'],m,kan,kou,moku,project=project,extra={'project_header_source_row':project['row'],'amount_printed_on_following_row':True})
                projects[project['row']]=rec;pending_project=None
                if moku:project_sums[tuple(moku['key'])]+=m[0]
                continue
            if coded and name[0][0]<282:
                code,label=coded;project={'code':code,'label':label,'row':len(obs.records)+1,'label_fragments':[{'page':row['page'],'words':name}]}
                pending_project={'y':row['y'],'label_x':name[0][0]+4.5*(len(code)+2)} if m is None else None
                rec=obs.emit('project-delta',dict(row,words=explanation),code,label,m,kan,kou,moku,project=project)
                projects[rec['source_row']]=rec
                if m and moku:project_sums[tuple(moku['key'])]+=m[0]
            else:
                rec=obs.emit('project-detail' if project else 'right-context',dict(row,words=explanation),label=normalize(''.join(w[4] for w in name)) or None,money=m,kan=kan,kou=kou,moku=moku,project=project)
                if m and project:details[project['row']]+=m[0]
    for p in range(stop,end+1):
        for row in positioned_rows(allpages[p-1],p):
            obs.emit('separate-appendix-context',row,extra={'outside_expenditure_detail':True,'nonadditive':True})
    reserve_records=[]
    for key,delta in moku_controls.items():
        controls=[r for r in obs.records if r['record_kind']=='moku' and r['moku'] and tuple(r['moku']['key'])==key]
        if controls and controls[0]['moku']['label']=='予備費' and key not in setsu_controls and key not in project_sums:
            right_money=[r for r in obs.records if r['record_kind'] in ('project-delta','project-delta-continuation','project-detail','right-context','left-setsu') and r['moku'] and tuple(r['moku']['key'])==key and r['amount'] is not None]
            if not right_money:reserve_records.append(dict(controls[0],source_grain='moku',printed_setsu_code=None))
    reserve_keys={tuple(r['moku']['key']) for r in reserve_records}
    moku_diff=[{'moku':k,'delta':v,'project_sum':project_sums.get(k),'left_setsu_sum':setsu_controls.get(k)} for k,v in moku_controls.items() if k not in reserve_keys and (project_sums.get(k)!=v or setsu_controls.get(k)!=v)]
    detail_diff=[{'project_row':k,'root':r['amount'],'detail_sum':details.get(k)} for k,r in projects.items() if r['amount']!=details.get(k)]
    leaves=[dict(r,source_grain='project',printed_setsu_code=None) for r in projects.values() if r['amount'] is not None and r['moku'] is not None]+reserve_records
    articles=[]
    for physical_page in range(edition['page'],first):
        article=normalize(texts[physical_page-1])
        match=re.search(r'歳入歳出それぞれ([△▲−\-\d,]+)千円を(追加|増額|減額)',article)
        if match and '第1条' in article:
            articles.append((physical_page,number(match[1])*(-1 if match[2]=='減額' else 1)))
    if len(articles)!=1:raise ValueError('No unique printed first-article page and amount in declared edition')
    article_page,total=articles[0]
    checks={'reserve_moku_without_right_project_or_setsu':[{'source_row':r['source_row'],'page':r['location']['page'],'amount':r['amount'],'grain':'moku; right explanation blank; independent left-setu/project control unavailable'} for r in reserve_records],'moku_controls':len(moku_controls),'projects':len(projects),'left_setsu_amount_groups':len(setsu_controls),'moku_differences':moku_diff,'project_detail_differences':detail_diff,'parser_problems':problems,'printed_article_page':article_page,'printed_article_delta':total,'project_delta_sum':sum(r['amount'] for r in leaves),'account_delta_match':total is not None and total==sum(r['amount'] for r in leaves),'legal_project_setsu_relation':'unconfirmed-independent-decompositions'}
    return obs.records,leaves,checks,[first,last]


def inspect_original(pdf, source):
    """Read verified immutable native pages once; no family or approval inference."""
    spec = source['content_inspection']; body = pdf.read_bytes()
    if digest(body) != spec['sha256'] or len(body) != spec['bytes']:
        raise ValueError('Mitaka original SHA/bytes differs from source declaration')
    texts = subprocess.check_output(['pdftotext','-layout',str(pdf),'-']).decode().split('\f')
    if not texts[-1].strip(): texts.pop()
    pages = pages_of(pdf,1,spec['pages'])
    if len(pages) != len(texts) or len(pages) != spec['pages']:
        raise ValueError('Mitaka declared/native page counts differ')
    covers = {n for n,t in enumerate(texts,1) if re.search(r'年度三鷹市.*補正予算\(第\d+号\)及び同説明書',normalize(t))}
    starts = sorted({e['page'] for e in source['editions']} | covers)
    return {'source':source,'pages':pages,'texts':texts,'starts':starts}

def extract(original, edition):
    end = min((p-1 for p in original['starts'] if p>edition['page']),default=len(original['pages']))
    rows,leaves,checks,extent = book(original['source'],edition,original['pages'],original['texts'],end)
    if not checks['account_delta_match'] or checks['moku_differences'] or checks['parser_problems']:
        raise ValueError('Mitaka independent article/moku/setsu/project root controls failed')
    return rows,leaves,checks,extent

def punctuation(t):return normalize(t).translate(str.maketrans('','','、，,・･'))
def match(code,label,year,master):
 if code is None or label is None:return []
 return [m for m in master if m['code']==code.zfill(2) and punctuation(m['label'])==punctuation(label) and (m['valid_from_fiscal_year'] is None or m['valid_from_fiscal_year']<=year) and (m['valid_to_fiscal_year'] is None or m['valid_to_fiscal_year']>=year)]

def extract_left(raw, original, edition, extent, master, mastersha):
 s=original['source'];sid=s['id'];sp=s['content_inspection'];pages=original['pages'];year=edition['fiscal_year'];scope=f'132047:{year}:{edition["account_label"]}:supplementary:{edition["amendment_number"]}'
 records=[];financial=[];unknown=[];controls={};sums=defaultdict(int);multiplicity=Counter()
 for row in raw:
  if row['record_kind']=='page-context' and row['location']['page'] in range(extent[0]+1,extent[1]+1,2) and row['location']['bbox'][1]<110:
   words=row['location']['words'] if '単位' in normalize(row['location']['printed_text']) else [w for w in row['location']['words'] if w[0]<262]
   if words:
    header_rec=copy.deepcopy(row);header_rec.update(record_kind='left-setsu-header',kan=None,kou=None,moku=None,project=None,setsu=None,source_grain='header',printed_setsu_code=None);header_rec['location']=location({'page':row['location']['page']},words);header_rec['record_context']={'nonadditive':True,'financial_phase':None,'source_role':'left-printed-moku-setsu'};records.append(header_rec)
   continue
  if row['record_kind'] not in ('kan','kou','moku','left-context','left-setsu','left-setsu-context'):continue
  rec=copy.deepcopy(row);rec['project']=None;rec['source_grain']='moku_setsu' if row['record_kind'].startswith('left-setsu') else row['record_kind'];rec['printed_setsu_code']=row['setsu']['code'] if row['setsu'] else None
  detail=rec.setdefault('record_context',{});detail.update({'source_role':'left-printed-moku-setsu','printed_column':'節 金額; amount is supplementary delta, not before/after totals','financial_phase':None,'approval_assigned':False,'project_setsu_relation':'unconfirmed-independent-decompositions','raw_original_observation_row':row['source_row']})
  if row['record_kind']=='moku' and row['moku']:controls[tuple(row['moku']['key'])]=row['moku']['delta']
  if rec['setsu']:
   matches=match(rec['setsu']['code'],rec['setsu']['label'],year,master);detail['legal_setsu_master_id']=matches[0]['expenditure_setsu_id'] if len(matches)==1 else None;detail['legal_setsu_match_status']='printed_code_name_active_year_match' if len(matches)==1 else 'unknown';detail['legal_setsu_master_sha256']=mastersha;detail['printed_full_setsu_label']=rec['setsu']['label'];detail['printed_setsu_heading_source_row']=rec['setsu']['row']
   if row['record_kind']=='left-setsu' and len(matches)!=1:unknown.append({'source_row':row['source_row'],'code':rec['code'],'label':rec['setsu']['label'],'page':rec['location']['page']})
  records.append(rec)
  if row['record_kind']=='left-setsu' and row['amount'] is not None:
   financial.append(rec);key=tuple(row['moku']['key']) if row['moku'] else None;sums[key]+=row['amount'];multiplicity[(key,row['code'])]+=1
 header=[]
 for page in range(extent[0]+1,extent[1]+1,2):
  for row in positioned_rows(pages[page-1],page):
   if row['y']>=110:continue
   words=row['words'] if '単位' in normalize(row['text']) else [w for w in row['words'] if w[0]<262]
   if words:header.append({'page':page,**location(row,words)})
 diffs=[{'moku':list(k),'printed_moku_delta':v,'left_setsu_delta_sum':sums.get(k)} for k,v in controls.items() if sums.get(k)!=v];reserve=[x for x in diffs if any(r['record_kind']=='moku' and r['moku'] and tuple(r['moku']['key'])==tuple(x['moku']) and r['moku']['label']=='予備費' for r in raw)];nonreserve=[x for x in diffs if x not in reserve]
 result={'source_id':sid,'scope':scope,'primary_url':s['download_url'],'origin_sha256':sp['sha256'],'pages':extent,'printed_left_headers':header,'raw_rows':len(records),'financial_setsu_delta_rows':len(financial),'blank_coded_setsu_amounts':sum(r['record_kind']=='left-setsu' and r['amount'] is None for r in records),'zero_coded_setsu_amounts':sum(r['record_kind']=='left-setsu' and r['amount']==0 for r in records),'noncoded_left_money_rows':[{'source_row':r['source_row'],'amount':r['amount'],'printed_text':r['location']['printed_text'],'context':r.get('record_context')} for r in records if r['record_kind']=='left-setsu-context' and r['amount'] is not None],'master_unknown_headings':unknown,'moku_controls':len(controls),'control_differences':nonreserve,'reserve_without_printed_setsu':reserve,'duplicate_code_within_moku':[{'moku':list(k),'code':code,'rows':n} for (k,code),n in multiplicity.items() if n>1],'phases':[],'approval_assigned':False,'project_allocation':None,'status':'candidate-independent-left-controls-passed' if not nonreserve else 'candidate-controls-unresolved'}
 if nonreserve:raise ValueError('Mitaka left statutory setsu/moku controls differ')
 return records,financial,result
