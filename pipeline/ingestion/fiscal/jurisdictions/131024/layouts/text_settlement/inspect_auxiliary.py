"""Independent original observations of Chuo's quantity cells and ancillary text."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from inspect_cells import segments

# Source-observed table header baselines and body extents, not converter state.
GRIDS = ((96,0,561,578,682), (107,0,341,358,372), (107,0,415,432,466),
 (110,0,351,369,526), (110,646,709,727,741), (123,646,531,549,619),
 (128,646,147,165,470), (131,0,162,181,349), (134,0,546,560,700),
 (136,646,262,280,357), (136,646,390,410,466), (136,646,516,537,591),
 (137,0,130,147,160), (147,0,188,206,410), (148,0,462,480,583),
 (148,0,625,643,693), (154,0,187,207,220), (155,646,107,125,138),
 (155,646,218,237,249), (156,0,378,398,410), (159,0,190,207,289))
LISTS = ((96,0,360,444),(96,0,486,516),(105,0,537,568),
         (106,0,617,648),(153,0,402,433))
# Independently confirmed prose and wrapped descriptions without a numeric
# pattern. These positions were measured from the original, not construction.
PROSE_LINES = ((100,0,472.58),(109,0,528.33),(111,0,200.39),
 (128,0,376.69),(129,646,353.94),(134,0,287.77),(136,0,753.53),
 (140,0,644.09),(141,0,283.64),(141,0,332.14),(141,0,429.14),
 (141,0,531.64),(143,0,172.10),(147,0,536.67),(147,0,583.17),
 (147,0,683.68),(147,0,730.18),(148,0,113.96),(148,0,160.46),
 (148,0,224.96),(148,0,271.47),(148,0,335.97),(148,0,400.47),
 (148,646,270.95),(148,646,306.95),(148,646,342.95),
 (155,646,486.62),(158,0,343.51))
# Printed financial explanation owners, independently read in the original.
# The y coordinate identifies the amount-bearing heading, not a legal section
# at the same height on the other half of a statement page.
GRID_OWNER_Y = (522.3639,305.4412,377.4412,326.5013,686.1263,
 505.9453,92.6953,127.2396,521.7738,199.9453,365.9453,473.9453,
 91.9866,163.6658,441.9707,603.9707,153.4113,72.6172,178.4932,
 343.3674,154.2195)
LIST_OWNER_Y = (342.3639,468.3639,519.2798,599.5958,384.1225)
PROSE_OWNER = ((100,0,454.5831),(109,0,510.3348),(111,0,182.3949),
 (127,0,201.5968),(129,646,335.9449),None,(136,0,91.9453),
 (140,0,626.0918),(141,0,271.1341),(141,0,319.6351),
 (141,0,416.6371),(141,0,519.1381),(143,0,154.0945),
 (147,0,513.6668),(147,0,513.6668),(147,0,641.1788),(147,0,641.1788),
 (148,0,72.9527),(148,0,72.9527),(148,0,72.9527),(148,0,72.9527),
 (148,0,72.9527),(148,0,377.4677),(148,646,234.9527),
 (148,646,288.9527),(148,646,288.9527),(155,646,486.8466),(158,0,325.5086))

# Source-observed geometry is account-specific. 'nhi' entries were
# independently measured on the NHI settlement pages 178-187: three ruled
# quantity grids (区分件数 p180 y218.3-343.8 and y453.4-534.8, 内訳対象者人数
# p184 y204.5-308.0) with their financial-owner heading baselines, and the
# reserve-transfer block on page 187 (y190-370) as the supplementary zone.
SCOPES = {
    'general': {'grids': GRIDS, 'lists': LISTS, 'prose_lines': PROSE_LINES,
                'grid_owner_y': GRID_OWNER_Y, 'list_owner_y': LIST_OWNER_Y,
                'prose_owner': PROSE_OWNER,
                'supplementary_zones': [{'page': 163, 'y0': 190, 'y1': 430},
                                        {'page': 112, 'text': '貸付状況'}]},
    'nhi': {'grids': ((180, 0, 218.3, 233.8, 343.8),
                      (180, 0, 453.4, 468.8, 534.8),
                      (184, 0, 204.5, 220.0, 308.0)),
            'lists': (), 'prose_lines': (),
            'grid_owner_y': (189.3, 424.5, 180.8),
            'list_owner_y': (), 'prose_owner': (),
            'supplementary_zones': [{'page': 187, 'y0': 190, 'y1': 370}]},
}

def words_text(words):
    lines=[]
    for word in sorted(words,key=lambda w:(w['y0'],w['x0'])):
        line=next((q for q in reversed(lines) if abs(q[0]['y0']-word['y0'])<2.5),None)
        if line is None:
            line=[];lines.append(line)
        line.append(word)
    return ''.join(w['text'] for line in lines for w in sorted(line,key=lambda w:w['x0']))

def office_scopes(original):
    """Read standalone office/department headings across the entire original."""
    moku=[c for c in original['controls'] if c['level']=='目']
    headings=[]
    for page in original['pages']:
        for pane in (0,646):
            lines=[]
            for word in sorted(page['words'],key=lambda w:(w['y0'],w['x0'])):
                if not pane+20<word['x0']<pane+524:continue
                line=next((q for q in reversed(lines) if abs(q[0]['y0']-word['y0'])<2.5),None)
                if line is None:line=[];lines.append(line)
                line.append(word)
            for words in lines:
                text=words_text(words)
                if ('［' not in text or text.startswith('［') or '円' in text
                        or re.match(r'\d|\(|（|令和|平成',text)):continue
                y=min(w['y0'] for w in words)
                before=[c for c in moku if (c['page'],0,c['y'])<(page['page'],pane,y)]
                if not before:raise ValueError('Office without original fiscal subject')
                headings.append({'page':page['page'],'pane':pane,'y0':y,'text':text,
                    'path':max(before,key=lambda c:(c['page'],c['y']))['path'],
                    'bounds':[min(w['x0'] for w in words),y,
                              max(w['x1'] for w in words),max(w['y1'] for w in words)],'words':words})
    return sorted(headings,key=lambda q:(q['page'],q['pane'],q['y0']))

def observe(pdf: Path, observations: Path, output: Path, scope='general'):
    output.mkdir(parents=True,exist_ok=False)
    original=json.loads(observations.read_text())
    if hashlib.sha256(pdf.read_bytes()).hexdigest()!=original['sha256']:
        raise ValueError('Original identity mismatch')
    scope_consts = SCOPES[scope]
    grids, lists_spec = scope_consts['grids'], scope_consts['lists']
    prose_lines, prose_owner = scope_consts['prose_lines'], scope_consts['prose_owner']
    grid_owner_y, list_owner_y = scope_consts['grid_owner_y'], scope_consts['list_owner_y']
    pages={p['page']:p for p in original['pages']}
    geometry={}
    for n in sorted({s[0] for s in grids}):
        svg=output/f'quantity-{n}.svg'
        subprocess.run(['pdftocairo','-f',str(n),'-l',str(n),'-svg',str(pdf),str(svg)],check=True)
        geometry[n]=segments(svg)
    tables=[]
    for n,pane,header_y,body_start,body_end in grids:
        page=pages[n];vs,hs=geometry[n]
        xs=sorted({round(x,2) for x,lo,hi in vs if lo-.5<header_y+4<hi+.5 and pane+20<x<pane+524})
        if len(xs)<2:
            tables.append({'page':n,'pane':pane,'header_y':header_y,'error':'No column ruling'});continue
        header_words=[w for w in page['words'] if pane+20<w['x0']<pane+524
                      and header_y-16<w['y0']<header_y+10]
        occupied=[(left,right) for left,right in zip(xs,xs[1:])
                  if any(left<(w['x0']+w['x1'])/2<right for w in header_words)]
        if not occupied:
            raise ValueError(f'No header cells on {n}:{header_y}')
        left_edge,right_edge=occupied[0][0],occupied[-1][1]
        xs=[x for x in xs if left_edge<=x<=right_edge]
        # Body rows are defined by their original rules. A merged category cell
        # can intersect several finest rows and is observed once for each row.
        ys=sorted({round(y,2) for y,lo,hi in hs if body_start-8<y<body_end+8 and lo<xs[-1] and hi>xs[0]})
        rows=[]
        for top,bottom in zip(ys,ys[1:]):
            if bottom-top<4:continue
            cells=[]
            row_xs=sorted({xs[0],xs[-1]} | {round(x,2) for x,lo,hi in vs
                           if xs[0]<x<xs[-1] and lo-.3<(top+bottom)/2<hi+.3})
            for left,right in zip(row_xs,row_xs[1:]):
                middle=(left+right)/2
                cuts=sorted({y for y,lo,hi in hs if lo-.5<middle<hi+.5})
                center=(top+bottom)/2
                above=[y for y in cuts if y<center];below=[y for y in cuts if y>center]
                if not above or not below:continue
                cell_top,cell_bottom=max(above),min(below)
                ws=[w for w in page['words'] if left-.3<(w['x0']+w['x1'])/2<right+.3
                    and cell_top-.3<(w['y0']+w['y1'])/2<cell_bottom+.3]
                has_number=any(re.search(r'\d',w['text']) for w in ws)
                units=[w for w in ws if has_number and w['text'] in ('人','回','件','戸籍','世帯','園','校','学級','冊','㎡','ｍ','個','％')]
                ws=[w for w in ws if w not in units]
                text=words_text(ws)
                cells.append({'bounds':[left,cell_top,right,cell_bottom],'text':text,'words':ws,'units':[w['text'] for w in units]})
            if not any(re.search(r'\d',c['text']) for c in cells):continue
            rows.append({'bounds':[xs[0],top,xs[-1],bottom],'cells':cells})
        tables.append({'page':n,'pane':pane,'header_y':header_y,'columns':xs,'rows':rows})
    lists=[]
    for n,pane,lo,hi in lists_spec:
        lines=[]
        for w in pages[n]['words']:
            if not(pane+20<w['x0']<pane+395 and lo-.5<w['y0']<hi):continue
            line=next((l for l in lines if abs(min(q['y0'] for q in l['words'])-w['y0'])<2.5),None)
            if line is None:line={'y':w['y1'],'words':[]};lines.append(line)
            line['words'].append(w)
        lists.extend({'page':n,'pane':pane,'y':l['y'],'text':words_text(l['words']),'words':l['words']}
                     for l in lines if re.search(r'\d+[人回]',words_text(l['words'])))
    notes=[]
    list_controls=[]
    reserve_page = original.get('reserve_page', 163)
    for n,p in pages.items():
        # The reserve-transfer region is independently retained and checked in
        # its existing separate raw table, not as main expenditure prose.
        if n==reserve_page:continue
        for pane in (0,646):
            lines=[]
            for w in p['words']:
                if not(pane+20<w['x0']<pane+395 and 85<w['y0']<780):continue
                line=next((l for l in lines if abs(min(q['y0'] for q in l['words'])-w['y0'])<2.5),None)
                if line is None:line={'y':w['y1'],'words':[]};lines.append(line)
                line['words'].append(w)
            for l in lines:
                text=words_text(l['words'])
                within_grid=any(n==nn and pane==pp and start-4<l['y']<end+12
                                for nn,pp,_,start,end in grids)
                within_list=any(n==nn and pane==pp and lo<l['y']<hi+10
                                for nn,pp,lo,hi in lists_spec)
                salary=any(q['page']==n and abs(q['y']+9-l['y'])<2
                           for q in original.get('personnel_rows',[]))
                control=any(abs(c['y']+9-l['y'])<3 for c in original['controls'] if c['page']==n)
                if re.fullmatch(r'計\d+人（[^）]+）',text) and not salary:
                    list_controls.append({'page':n,'pane':pane,'y':l['y'],'text':text,'words':l['words']})
                within_money=False
                for h in original['monetary_table_headers']:
                    if h['page']!=n or h['pane']!=pane:continue
                    body=[r['y'] for r in original['monetary_rows'] if r['page']==n and r['pane']==pane and r['table_y']==h['y']]
                    if body and h['y']<l['y']<max(body)+15:within_money=True
                caption=(re.match(r'所在地|場所|完成予定|完了予定|完成|完了|規模|※|件数も含まれる',text)
                         or ((text.startswith('（') or (('（' in text or '(' in text) and re.search(r'\d',text)))
                             and not re.search(r'円|^（[款項目]）|^\(\d+\)',text)))
                if caption and not within_grid and not within_list and not salary and not control and not within_money and '計' != text[:1]:
                    notes.append({'page':n,'pane':pane,'y':l['y'],'text':text,'words':l['words']})
    for n,pane,y in prose_lines:
        ws=[w for w in pages[n]['words'] if pane+20<w['x0']<pane+524 and abs(w['y0']-y)<2.5]
        if not ws:raise ValueError(f'Missing independently measured prose {n}:{y}')
        old=next((q for q in notes if q['page']==n and q['pane']==pane and abs(q['y']-y-9)<3),None)
        item={'page':n,'pane':pane,'y':max(w['y1'] for w in ws),'text':words_text(ws),'words':ws}
        if old is None:notes.append(item)
        else:old.update(item)
    # The fiscal subject is observed from the original controls, including new
    # moku boundaries before their first printed monetary explanation.
    moku=[c for c in original['controls'] if c['level']=='目']
    for item in [*tables,*lists,*notes]:
        y=item.get('header_y',item.get('y'))
        before=[c for c in moku if (c['page'],0,c['y'])<(item['page'],item['pane'],y)]
        if before:item['path']=max(before,key=lambda c:(c['page'],c['y']))['path']
    def owner_amount(n,pane,y):
        ws=[w for w in pages[n]['words'] if pane+20<w['x0']<pane+524 and abs(w['y0']-y)<2.5]
        currencies=[w for w in ws if w['text']=='円']
        if len(currencies)!=1:raise ValueError(f'Original owner currency cell {n}:{y}')
        circle=currencies[0]
        numbers=[w for w in ws if re.search(r'\d[\d,]*$',w['text']) and w['x1']<circle['x0']+.1]
        if not numbers:raise ValueError(f'Original owner amount {n}:{y}')
        amount=max(numbers,key=lambda w:w['x1'])
        marker=re.match(r'^(\(\d+\)|\d+)',words_text(ws))
        return {'page':n,'text':re.search(r'\d[\d,]*$',amount['text'])[0]+'円','x0':amount['x0'],'y0':amount['y0'],
                'x1':circle['x1'],'y1':max(amount['y1'],circle['y1']),
                'number':marker[0] if marker else None}
    for table,y in zip(tables,grid_owner_y,strict=True):
        table['financial_owner']=owner_amount(table['page'],table['pane'],y)
    for item in lists:
        index=next(i for i,(n,p,lo,hi) in enumerate(lists_spec)
                   if item['page']==n and item['pane']==p and lo<item['y']<hi+10)
        item['financial_owner']=owner_amount(item['page'],item['pane'],list_owner_y[index])
    for (n,pane,y),owner in zip(prose_lines,prose_owner,strict=True):
        item=next(q for q in notes if q['page']==n and q['pane']==pane and abs(q['y']-y-9)<3)
        if owner is None:item['owner_kind']='目'
        else:
            item['financial_owner']=owner_amount(*owner)
            # The indexed heading is on the preceding line; the amount is on
            # the native location line inside the same printed item.
            if n==155:item['financial_owner']['number']='(6)'
    scopes=[]
    if scope=='general':
        title=next(q for q in notes if q['page']==128 and q['pane']==0 and abs(q['y']-385.6949)<1)
        scopes=[{'page':128,'title':title['text'],'title_bounds':[
            min(w['x0'] for w in title['words']),min(w['y0'] for w in title['words']),
            max(w['x1'] for w in title['words']),max(w['y1'] for w in title['words'])],
            'rows':[r for r in original['cell_values'] if r['page']==128 and 413.9<r['y']<433.8]}]
        if len(scopes[0]['rows'])!=1:raise ValueError('Original special benefit table scope')
    result={'sha256':original['sha256'],'scope':scope,'tables':tables,'lists':lists,'list_controls':list_controls,'notes':notes,
            'table_scopes':scopes,'office_scopes':office_scopes(original),
            'supplementary_zones':scope_consts['supplementary_zones']}
    (output/'observations.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'tables':len(tables),'grid_rows':sum(len(t.get('rows',[])) for t in tables),
                      'list_rows':len(lists),'notes':len(notes),'errors':[t for t in tables if 'error' in t]},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pdf',type=Path,required=True)
    p.add_argument('--observations',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--scope',choices=sorted(SCOPES),default='general')
    a=p.parse_args();observe(a.pdf,a.observations,a.output,a.scope)
