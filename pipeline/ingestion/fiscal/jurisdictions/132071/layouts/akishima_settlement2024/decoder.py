"""Finite FY2024 native-cell decoder; no OCR, network, allocation or name matching."""
from __future__ import annotations
import re, html, json, hashlib
from collections import defaultdict

MONEY = re.compile(r'^(?:△|-)?[\d,]+$')

def pages(raw):
    result=[]
    # Native output contains XML-forbidden font codes in the property appendix.
    # Parse exact word markup rather than replacing or correcting those observations.
    for part in raw.decode('utf-8').split('<page ')[1:]:
        words=[]
        for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)"[^>]*>(.*?)</word>',part):
            words.append([*[float(m[i]) for i in range(1,5)],html.unescape(m[5])])
        result.append(words)
    assert len(result)==651
    return result

def lines(words, body=True):
    out=[]
    for w in sorted(words,key=lambda w:(w[1],w[0])):
        if body and not 130<w[1]<780:continue
        if not out or w[1]-out[-1][0][1]>1.0:out.append([])
        out[-1].append(w)
    return [sorted(r,key=lambda w:w[0]) for r in out]

def cell(row, edge, tolerance=1.0):
    return [w for w in row if abs(w[2]-edge)<tolerance and MONEY.fullmatch(w[4])]

def num(words):
    assert len(words)==1,words
    return int(words[0][4].replace(',','').replace('△','-'))

def js(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'))

def decode(raw,config,approval,health_cells):
    pp=pages(raw); financial=[]; controls=[]; projects=[]; diagnostics=[]
    src=config['origin']; sha=src['sha256']
    assert '令和６年度' in ''.join(w[4] for w in pp[0])
    assert '歳入歳出決算書' in ''.join(w[4] for w in pp[0])
    def base(a,p,y,role):
        ident=f'{sha}:{a["id"]}:{role}:{p}:{y:.6f}'
        return dict(source_row_id=ident,jurisdiction_id='132071',fiscal_year=2024,account_id=a['id'],account_name=a['name'],source_grain=role,phase='executed',unit='円',original_url=src['url'],original_sha256=sha,original_bytes=src['bytes'],physical_page=p,recognition_date='2025-10-02',recognition_bill=approval[a['id']]['bill'],recognition_source_json=js(approval[a['id']]),submitted_date=None,statutory_setsu_id=None,department=None,header_source_json=js([w for w in pp[p-1] if w[1]<130]),printed_page_label=''.join(w[4] for w in sorted(pp[p-1],key=lambda w:w[0]) if w[1]>785),account_title_physical_page=a['first_left']-1,account_title_source_json=js(pp[a['first_left']-2]))
    for a in config['accounts']:
        contexts=[None,None,None]; last_legal=None; moku_events={}; project_pending=None
        for p in range(a['first_left'],a['last_left']+1,2):
            rr=lines(pp[p]); bands=[]
            assert any('単位：円' in w[4] for w in pp[p] if w[1]<130)
            assert any(w[4]=='支出済額' for w in pp[p] if w[1]<130)
            for row in lines(pp[p-1]):
                y=row[0][1]; pair=[r for r in rr if abs(r[0][1]-y)<.8]
                hcodes=[[w for w in row if abs(w[2]-edge)<.4 and re.fullmatch(r'\d+',w[4])] for edge in [22.68,39.24,55.80]]
                b=[cell(row,e) for e in [164.04,224.88,285.72,346.56,407.4]]
                budget=all(len(c)==1 for c in b)
                level=next((i for i in [2,1,0] if hcodes[i]),None)
                if level is not None and budget:
                    assert all(not hcodes[i] or (contexts[i] and hcodes[i][0][4]==contexts[i]["code"]) for i in range(level)),(p,y,row)
                    name=[w for w in row if [26,43,59][level]<=w[0]<108]
                    contexts[level]={'code':hcodes[level][0][4],'parts':[w[4] for w in name],'words':name}
                    for i in range(level+1,3):contexts[i]=None
                    last_legal=None
                elif level is not None:
                    # Printed continuation hierarchy codes are not monetary rows.
                    for i,cc in enumerate(hcodes):
                        if cc and contexts[i]: assert cc[0][4]==contexts[i]['code'],(p,y,i,cc,contexts)
                if level is None:
                    for i,start in enumerate([26.52,43.08,59.64]):
                        tail=[w for w in row if abs(w[0]-start)<.25 and w[2]<108 and not MONEY.fullmatch(w[4])]
                        if tail and contexts[i]: contexts[i]['parts'] += [w[4] for w in tail];contexts[i]['words']+=tail
                codes=[w for w in row if 415<w[0]<425 and re.fullmatch(r'\d{1,2}',w[4])]
                lc=cell(row,534.03)
                hierarchy=budget and level is not None
                total=budget and '歳出合計' in ''.join(w[4] for w in row)
                if codes or hierarchy or total:
                    assert len(pair)==1,(p,y,pair)
                    r=pair[0]; money=[cell(r,e) for e in [105.72,166.56,227.4,288.24,349.08]]
                    assert all(len(c)==1 for c in money),(p,y,money)
                    values=[num(c) for c in money]
                    ratio=[w for w in r if 350<w[0]<395 and re.fullmatch(r'[\d.]+',w[4])]
                    assert len(ratio)==1,(p,y,ratio)
                    islegal=bool(codes)
                    role='printed_legal_setsu' if islegal else ('account_control' if total else ['kan_control','kou_control','moku_control'][level])
                    obj=base(a,p,y,role)
                    obj.update(printed_setsu_code=codes[0][4] if islegal else None,printed_setsu_name=None,amount_executed=values[0],carry_continuing=values[1],carry_authorized=values[2],carry_accident=values[3],amount_unspent=values[4],printed_execution_ratio=ratio[0][4],budget_initial=None,budget_supplementary=None,budget_prior_carry=None,budget_reserve_transfer=None,budget_current=num(lc) if islegal else num(b[-1]),paired_physical_page=p+1,raw_left_row_json=js(row),raw_right_row_json=js([w for w in r if w[0]<395]),money_cells_json=js({'left':lc if islegal else b,'right':money,'ratio':ratio}),hierarchy_source_json=None,_context=tuple(contexts),_label_words=[])
                    if not islegal:
                        for key,c in zip(['budget_initial','budget_supplementary','budget_prior_carry','budget_reserve_transfer','budget_current'],b):obj[key]=num(c)
                        assert obj['budget_initial']+obj['budget_supplementary']+obj['budget_prior_carry']+obj['budget_reserve_transfer']==obj['budget_current'],(p,y,obj)
                    assert sum(values)==obj['budget_current'],(p,y,obj)
                    if islegal:
                        assert all(contexts), (p,y,contexts)
                        financial.append(obj);last_legal=obj
                    else:controls.append(obj)
                # All literal label fragments stay tied to their printed legal cell.
                labels=[w for w in row if 428<w[0]<486 and not MONEY.fullmatch(w[4])]
                if labels and last_legal: last_legal['_label_words']+=labels
                if contexts[2]:bands.append((y,tuple(contexts)))
            moku_events[p]=bands
            # Project remarks are independent controls. Their code is only a
            # printed remark ordinal, never a inferred statutory or target code.
            for row in rr:
                y=row[0][1]; start=[w for w in row if abs(w[0]-397.68)<.25 and re.fullmatch(r'\d{3}',w[4])]
                if start:
                    assert project_pending is None,(p,y,project_pending)
                    ctx=next((c for yy,c in reversed(bands) if yy<=y+.8),tuple(contexts))
                    project_pending={'code':start[0][4],'words':list(row),'context':ctx,'page':p+1,'y':y,'parts':[w[4] for w in row if 414<w[0]<552 and not MONEY.fullmatch(w[4])],'amount_words':None}
                elif project_pending:
                    project_pending['words']+=row
                    project_pending['parts'] += [w[4] for w in row if 414<w[0]<552 and not MONEY.fullmatch(w[4])]
                amounts=cell(row,551.2)
                if project_pending and amounts:
                    assert len(amounts)==1
                    q=project_pending;obj=base(a,q['page'],q['y'],'project_control')
                    obj.update(printed_project_ordinal=q['code'],printed_project_label=''.join(q['parts']),amount_executed=num(amounts),raw_project_json=js(q['words']),money_cells_json=js(amounts),_context=q['context'])
                    projects.append(obj);project_pending=None
            # Pending labels may continue across a physical spread.
        assert project_pending is None,project_pending
        # Independent account-list row on physical page 10.
        row=[w for w in pp[9] if abs(w[1]-a['account_list_y'])<.7]
        money=[w for w in row if 314<w[0]<389 and MONEY.fullmatch(w[4])]
        obj=base(a,10,a['account_list_y'],'account_overview_control');obj.update(amount_executed=num(money),raw_control_json=js(row),money_cells_json=js(money));controls.append(obj)
        # Two independently printed setsu-summary halves plus subtotals/total.
        for row in lines(pp[a['setsu_summary']-1]):
            y=row[0][1]
            if not 195<y<775:continue
            for lo,hi,edge in [(70,215,295.2),(307,445,529.2)]:
                ws=[w for w in row if lo<w[0]<hi];am=cell(row,edge,.6)
                if not ws or not am:continue
                text=''.join(w[4] for w in ws);match=re.match(r'^(\d{1,2})(.*)$',text)
                if not match:continue
                obj=base(a,a['setsu_summary'],y,f'setsu_summary_{lo}_control')
                obj.update(printed_setsu_code=match[1],printed_setsu_name=match[2],amount_executed=num(am),raw_control_json=js(ws+am),money_cells_json=js(am));controls.append(obj)
            for edge in [295.2,529.2]:
                am=cell(row,edge,.6)
                if am and y>695:
                    obj=base(a,a['setsu_summary'],y,f'setsu_summary_total_{edge}_control');obj.update(amount_executed=num(am),raw_control_json=js(row),money_cells_json=js(am));controls.append(obj)
        for row in lines(pp[a['setsu_summary']-1]):
            if 730<row[0][1]<750:
                am=[w for w in row if w[0]>390 and MONEY.fullmatch(w[4])]
                obj=base(a,a['setsu_summary'],row[0][1],'setsu_summary_grand_total_control');obj.update(amount_executed=num(am),raw_control_json=js(row),money_cells_json=js(am));controls.append(obj)
        # Actual surplus statement monetary cells; its carry amounts are funds
        # required for next-year commitments, not interchangeable with table carry.
        for row in lines(pp[a['setsu_summary']-2]):
            am=[w for w in row if w[0]>350 and abs(w[2]-490)<1 and MONEY.fullmatch(w[4])]
            if am:
                obj=base(a,a['setsu_summary']-1,row[0][1],'real_surplus_reference_control')
                obj.update(phase=None,amount_executed=None,printed_reference_amount=num(am),raw_control_json=js(row),money_cells_json=js(am));controls.append(obj)
        # Independently published account/kan summary, four money columns.
        for row in lines(pp[a['account_summary']-1]):
            y=row[0][1]; cells=[[w for w in row if lo<w[0]<hi and MONEY.fullmatch(w[4])] for lo,hi in ([(180,249),(259,327),(339,394),(400,465)] if a['id'] in ['elderly','land','north'] else [(169,241),(247,318),(330,391),(395,461)])]
            if not all(len(c)==1 for c in cells):continue
            values=[num(c) for c in cells]
            if not 180<y<530:continue
            assert values[0]==sum(values[1:]),(a['id'],y,values)
            code=[w for w in row if 70<w[0]<84 and re.fullmatch(r'\d+',w[4])]
            obj=base(a,a['account_summary'],y,'account_kan_summary_control')
            obj.update(kan_code=code[0][4] if code else None,printed_control_label=''.join(w[4] for w in row if 86<w[0]<169),budget_current=values[0],amount_executed=values[1],carry_total=values[2],amount_unspent=values[3],raw_control_json=js(row),money_cells_json=js(cells));controls.append(obj)
        if a['id']=='health':
            for r in health_cells['rows']:
                assert all(w in pp[450] for w in r['raw_native_row'])
                assert all(w in pp[450] for c in r['cells'] for w in c['native_words'])
                obj=base(a,451,r['y'],'account_kan_summary_control')
                obj.update(kan_code=r['printed_kan_code'],printed_control_label=r['printed_label'],printed_execution_ratio=r['printed_execution_ratio'],printed_composition_ratio=r['printed_composition_ratio'],raw_control_json=js(r['raw_native_row']),money_cells_json=js([c['native_words'] for c in r['cells']]),visual_cell_ledger_json=js(r),reading_method='direct original visual cells, immutable ledger')
                for c in r['cells']:obj[c['column']]=c['value']
                assert obj['budget_current']==obj['amount_executed']+obj['carry_total']+obj['amount_unspent']
                controls.append(obj)
        # Formal settlement table's independent kan/kou rows and account total.
        kan=None
        for p in a['formal_left_pages']:
            right=lines(pp[p])
            for row in lines(pp[p-1]):
                y=row[0][1];b=[w for w in row if w[0]>440 and abs(w[2]-514.5)<1 and MONEY.fullmatch(w[4])]
                if not b:continue
                pair=[r for r in right if abs(r[0][1]-y)<1]
                assert len(pair)==1,(p,y)
                cells=[cell(pair[0],e,1) for e in [169.1,294.74,420.4,546.0]]
                assert all(len(c)==1 for c in cells),(p,y,cells)
                values=[num(c) for c in cells];assert num(b)==sum(values[:3]);assert values[3]==sum(values[1:3])
                kc=[w for w in row if w[0]<35 and re.fullmatch(r'\d+',w[4])];oc=[w for w in row if 210<w[0]<222 and re.fullmatch(r'\d+',w[4])]
                if kc:kan=kc[0][4]
                obj=base(a,p,y,'formal_settlement_control')
                obj.update(kan_code=kan if kc or oc else None,kou_code=oc[0][4] if oc else None,printed_control_label=''.join(w[4] for w in row if w[0]<440 and not MONEY.fullmatch(w[4])),budget_current=num(b),amount_executed=values[0],carry_total=values[1],amount_unspent=values[2],printed_budget_minus_executed=values[3],paired_physical_page=p+1,raw_control_json=js(row),raw_right_row_json=js(pair[0]),money_cells_json=js({'left':b,'right':cells}));controls.append(obj)
    # Finalize mutable hierarchy labels after native wrapped lines have arrived.
    for obj in financial+controls+projects:
        context=obj.pop('_context',None)
        if context:
            for k,v in zip(['kan','kou','moku'],context):
                obj[k+'_code']=v['code'] if v else None;obj[k+'_name']=''.join(v['parts']) if v else None
            obj['hierarchy_source_json']=js(context)
        if '_label_words' in obj:
            words=obj.pop('_label_words');obj['printed_setsu_name']=''.join(w[4] for w in words) if words else None;obj['printed_label_cells_json']=js(words)
    for a in config['accounts']:
        reserves=[r for r in controls if r['account_id']==a['id'] and r['source_grain']=='moku_control' and r['moku_name']=='予備費']
        assert len(reserves)==1
        obj=dict(reserves[0]);obj['control_source_row_id']=obj['source_row_id'];obj['source_row_id']=obj['source_row_id'].replace('moku_control','printed_reserve_moku');obj['source_grain']='printed_reserve_moku';obj['printed_setsu_code']=None;obj['printed_setsu_name']=None
        assert obj['amount_executed']==0
        financial.append(obj)
    for role,rows in [('financial',financial),('controls',controls),('projects',projects)]:
        for a in config['accounts']:
            ordered=sorted([r for r in rows if r['account_id']==a['id']],key=lambda r:(r['physical_page'],r['source_row_id']))
            for i,r in enumerate(ordered,1):r['source_row_ordinal']=i;r['source_table_id']='akishima-fy2024-settlement-'+a['id']+'-'+role
    return {'financial':financial,'controls':controls,'projects':projects},pp
