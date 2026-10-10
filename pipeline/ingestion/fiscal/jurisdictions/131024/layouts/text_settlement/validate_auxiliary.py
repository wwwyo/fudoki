"""Compare independent original quantity cells with saved scalar raw facts."""
from __future__ import annotations
import argparse
import collections
import json
import re
from pathlib import Path
from validate_candidate import read_raw, normalized


def validate(raw: Path, observations: Path, output: Path):
    output.mkdir(parents=True,exist_ok=False)
    rows,_=read_raw(raw);origin=json.loads(observations.read_text());issues=[];checks=[];used=set()
    expected=[];controls=[]
    for table in origin['tables']:
        if 'error' in table:
            issues.append(table);continue
        for row in table['rows']:
            groups=[row['cells']]
            if table['page']==110 and table['pane']==0:
                groups=[row['cells'][:2],row['cells'][2:]]
            for cells in groups:
                if (table['page'],table['header_y']) in ((147,188),(148,462)):
                    cells=[{**c,'text':c['text']+''.join(c.get('units',[]))} for c in cells]
                item={'page':table['page'],'pane':table['pane'],'header_y':table['header_y'],
                      'bounds':row['bounds'],'cells':cells,'path':table.get('path'),
                      'financial_owner':table.get('financial_owner')}
                if any(normalized(c['text'])=='計' for c in cells):controls.append(item)
                else:expected.append(item)
    quantity_columns=sorted({name for row in rows for name in row if name.startswith('数量表_')
                            and not re.search(r'_原典(?:物理頁|xMin|xMax|yMin|yMax)$',name)
                            and name not in ('数量表_見出し','数量表_現在日')})
    cell_checks=0
    row_sources={}
    matched_values={}
    def check_subject(row,printed,source_field=None):
        path=printed.get('path')
        if path and any(str(row.get(k+'_番号'))!=str(v) for k,v in path.items()):
            issues.append({'kind':'auxiliary original fiscal subject','origin':path,
                           'raw':{k:row.get(k+'_番号') for k in path},'page':printed['page']})
        owner=printed.get('financial_owner')
        if printed.get('owner_kind')=='目' and source_field and not source_field.startswith('目_'):
            issues.append({'kind':'moku heading incorrectly assigned to business','page':printed['page'],
                           'text':printed['text'],'raw_business':row.get('事業_名称')})
        if owner:
            tiers=[t for t in ('事業','内訳1','内訳2','内訳3','内訳4') if row.get(t+'_名称')]
            tier=tiers[-1] if tiers else ''
            if (normalized(row.get(tier+'_金額') or '')!=normalized(owner['text'])
                    or normalized(row.get(tier+'_番号') or '')!=normalized(owner.get('number') or '')
                    or row.get(tier+'_原典物理頁')!=owner['page']
                    or not row.get(tier+'_原典xMin',1e9)-1<owner['x0']<row.get(tier+'_原典xMax',-1)+1
                    or not row.get(tier+'_原典yMin',1e9)-1<owner['y0']<row.get(tier+'_原典yMax',-1)+1):
                issues.append({'kind':'quantity original financial explanation owner','origin':owner,'raw_tier':tier,
                               'raw_name':row.get(tier+'_名称'),'raw_amount':row.get(tier+'_金額')})
    for printed in expected:
        numeric=[c for c in printed['cells'] if re.search(r'\d',c['text'])]
        anchor=numeric[-1] if numeric else printed['cells'][-1]
        left,top,right,bottom=anchor['bounds']
        matches=[]
        for i,row in enumerate(rows):
            for field in quantity_columns:
                value=row.get(field)
                if value is None or normalized(value)!=normalized(anchor['text']):continue
                if row.get(field+'_原典物理頁')!=printed['page']:continue
                x=row.get(field+'_原典xMin');y=row.get(field+'_原典yMin')
                if x is not None and y is not None and left-.5<x<right+.5 and top-.5<y<bottom+.5:
                    matches.append(i);break
        if len(matches)!=1:
            issues.append({'kind':'quantity finest row coverage','printed':printed,'matching_rows':matches});continue
        i=matches[0];row=rows[i];used.add(i);row_sources[i]=printed
        check_subject(row,printed)
        if row.get('明細金額') is not None:
            issues.append({'kind':'invented quantity amount','row':i})
        for cell in printed['cells']:
            value=cell['text']
            if not value.strip():continue
            left,top,right,bottom=cell['bounds'];matching=[]
            for field in quantity_columns:
                x=row.get(field+'_原典xMin');y=row.get(field+'_原典yMin')
                if row.get(field+'_原典物理頁')==printed['page'] and x is not None and y is not None:
                    if left-.5<x<right+.5 and top-.5<y<bottom+.5:matching.append(field)
            if len(matching)!=1:
                issues.append({'kind':'quantity original cell membership','row':i,'cell':cell,'columns':matching});continue
            field=matching[0];actual=row[field];cell_checks+=1
            matched_values[(printed['page'],printed['pane'],printed['header_y'],tuple(printed['bounds']),tuple(cell['bounds']))]=actual
            if normalized(actual)!=normalized(value):
                issues.append({'kind':'quantity original cell text','row':i,'field':field,'origin':value,'raw':actual})
    def integer(value):
        value=normalized(value)
        if value in ('－','—','-'):
            return None
        return int(value.replace(',','')) if re.fullmatch(r'[\d,]+',value) else None

    def control_check(label, source, values, complete=True):
        expected_value=integer(source)
        if expected_value is None:
            return
        actual=sum(v for v in (integer(value) for value in values) if v is not None) if complete else None
        checks.append({'level':label,'origin':expected_value,'sum':actual,
                       'delta':None if actual is None else actual-expected_value,
                       'status':'保留' if actual is None else '一致' if actual==expected_value else '不一致'})
    for control in controls:
        table_rows=[r for r in expected if (r['page'],r['pane'],r['header_y'])==
                    (control['page'],control['pane'],control['header_y'])]
        for column,cell in enumerate(control['cells']):
            if integer(cell['text']) is None:
                continue
            # Parallel facility columns share one printed total on their right.
            terms=[];complete=True
            for r in table_rows:
                if control['page']==110 and control['pane']==0:
                    c=r['cells'][1]
                else:
                    center=(cell['bounds'][0]+cell['bounds'][2])/2
                    aligned=[c for c in r['cells'] if c['bounds'][0]<center<c['bounds'][2]]
                    if len(aligned)!=1:
                        complete=False;continue
                    c=aligned[0]
                key=(r['page'],r['pane'],r['header_y'],tuple(r['bounds']),tuple(c['bounds']))
                if key not in matched_values:complete=False
                else:terms.append(matched_values[key])
            control_check(f"数量内訳→印字計/{control['page']}/{control['header_y']}/{column}",
                          cell['text'],terms,complete)
    for r in expected:
        groups=[]
        if r['page']==128:groups=[([1,2],3),([4,5],6)]
        if r['page']==131:groups=[([1,2,3,4,5],6)]
        if r['page']==107 and r['header_y']==415:groups=[([1,2,3],4)]
        if r['page']==137:groups=[([0,1,2,3,4],5)]
        for columns,total_column in groups:
            terms=[];complete=True
            for column in columns:
                c=r['cells'][column]
                key=(r['page'],r['pane'],r['header_y'],tuple(r['bounds']),tuple(c['bounds']))
                if key not in matched_values:complete=False
                else:terms.append(matched_values[key])
            control_check(f"数量列内訳→行計/{r['page']}/{r['bounds'][1]}/{total_column}",
                          r['cells'][total_column]['text'],terms,complete)
    list_values={}
    list_rows={}
    for printed in origin['lists']:
        matches=[]
        for i,row in enumerate(rows):
            if row.get('原典物理頁')!=printed['page'] or not printed['pane']+20<row.get('原典xMin',0)<printed['pane']+395:continue
            fields=[f for f in quantity_columns if row.get(f) is not None
                    and row.get(f+'_原典物理頁')==printed['page']]
            if not any(abs(row.get(f+'_原典yMin',-100)-(printed['y']-9))<1 for f in fields):continue
            fields.sort(key=lambda f:row.get(f+'_原典xMin',0))
            text=normalized(''.join(str(row[f]) for f in fields))
            if text==normalized(printed['text']):matches.append(i)
        if len(matches)!=1:issues.append({'kind':'quantity original list row','origin':printed,'matches':matches})
        else:
            used.add(matches[0]);cell_checks+=1
            list_row=rows[matches[0]]
            check_subject(list_row,printed)
            list_values[(printed['page'],printed['pane'],printed['y'])]=next(
                (list_row[f] for f in quantity_columns if f.endswith('_人数') and list_row.get(f)),None)
            list_rows[(printed['page'],printed['pane'],printed['y'])]=list_row
    for c in origin.get('list_controls',[]):
        values=[re.match(r'\d+',normalized(value or ''))[0]
                for (page,pane,y),value in list_values.items()
                if page==c['page'] and pane==c['pane'] and c['y']-120<y<c['y'] and value]
        control_check(f"人数区分→印字計/{c['page']}/{c['y']}",re.search(r'\d+',c['text'])[0],values)
        date=re.search(r'（[^）]+）',c['text'])
        if date:
            for (page,pane,y),row in list_rows.items():
                if page==c['page'] and pane==c['pane'] and c['y']-120<y<c['y']:
                    if normalized(row.get('数量表_現在日') or '')!=normalized(date[0]):
                        issues.append({'kind':'quantity original list date','page':page,'y':y,
                                       'origin':date[0],'raw':row.get('数量表_現在日')})
    # Native scalar text can already be retained in an ordinary original name.
    # Find matching source positions rather than borrowing the same string from
    # an unrelated page or parent.
    notes_checked=0
    for note in origin['notes']:
        found=False
        for row_index,row in enumerate(rows):
            source_fields=['補足_本文', *[f'{tier}_名称' for tier in ('事業','内訳1','内訳2','内訳3','内訳4')], '数量表_見出し']
            source_fields += [f for f,v in row.items() if isinstance(v,str)
                              and ((note.get('owner_kind')=='目' and f.startswith('目_'))
                                   or (f.startswith('内表_') and f.endswith('表題')))]
            for field in source_fields:
                value=row.get(field)
                if not value:continue
                prefix=field.rsplit('_',1)[0]
                page=row.get(field+'_原典物理頁',row.get(prefix+'_原典物理頁',row.get('原典物理頁')))
                lo=row.get(field+'_原典yMin',row.get(prefix+'_原典yMin',row.get('原典yMin',-100)))
                hi=row.get(field+'_原典yMax',row.get(prefix+'_原典yMax',row.get('原典yMax',-100)))
                source=row_sources.get(row_index)
                quantity_heading=(field=='数量表_見出し' and source and source['page']==note['page']
                                  and source['pane']==note['pane'] and source['header_y']-90<note['y']<source['bounds'][1])
                moku_context=(note.get('owner_kind')=='目' and field.startswith('目_')
                              and row.get('目_原典物理頁')==note['page']
                              and all(str(row.get(k+'_番号'))==str(v) for k,v in note['path'].items()))
                if not moku_context and (page!=note['page'] or (not quantity_heading and not lo-2<note['y']<hi+12)):continue
                text=normalized(value)
                if field=='数量表_見出し':text+=normalized(row.get('数量表_現在日') or '')
                if field.endswith('_名称') and row.get(prefix+'_金額'):
                    text+=normalized(row[prefix+'_金額'])
                if moku_context and normalized(note['text']) not in text:
                    text+=normalized(row.get('目_所属') or '')
                if normalized(note['text']) in text:found=True;check_subject(row,note,field);break
            if found:break
        if found:notes_checked+=1
        else:issues.append({'kind':'ancillary source text preservation','origin':{k:v for k,v in note.items() if k!='words'}})
    scope_rows_checked=0
    for scope in origin.get('table_scopes',[]):
        expected_keys=set()
        for printed in scope['rows']:
            matches=[(i,row) for i,row in enumerate(rows) if row.get('内表_金額_原典物理頁')==printed['page']
                     and abs(row.get('内表_金額_原典yMin',-100)-printed['y'])<.1]
            if len(matches)!=1:
                issues.append({'kind':'original titled table finest row','origin':printed,'matches':len(matches)});continue
            i,row=matches[0];expected_keys.add(i)
            fields=[f for f,v in row.items() if f.startswith('内表_') and f.endswith('表題')
                    and normalized(v or '')==normalized(scope['title'])]
            if len(fields)!=1:
                issues.append({'kind':'original table title row membership','row':i,'origin':scope['title'],'fields':fields});continue
            f=fields[0];left,top,right,bottom=scope['title_bounds']
            if (row.get(f+'_原典物理頁')!=scope['page'] or row.get(f+'_原典xMin') is None
                    or not left-1<row[f+'_原典xMin']<right+1 or row.get(f+'_原典yMin') is None
                    or not top-1<row[f+'_原典yMin']<bottom+1):
                issues.append({'kind':'original table title position','row':i,'field':f})
            scope_rows_checked+=1
        for i,row in enumerate(rows):
            if any(f.startswith('内表_') and f.endswith('表題') and normalized(v or '')==normalized(scope['title'])
                   for f,v in row.items()) and i not in expected_keys:
                issues.append({'kind':'original table title applied outside its printed table','row':i})
    for i,row in enumerate(rows):
        if any(row.get(f) is not None for f in quantity_columns) and i not in used:
            issues.append({'kind':'unexpected quantity finest row','row':i})
        zones=origin.get('supplementary_zones',[{'page':163,'y0':190,'y1':430},
                                                {'page':112,'text':'貸付状況'}])
        if row.get('補足_本文') and any(
                row.get('原典物理頁')==zone.get('page')
                and (('y0' in zone and zone['y0']<row.get('原典yMin',0)<zone['y1'])
                     or ('text' in zone and zone['text'] in normalized(row['補足_本文'])))
                for zone in zones):
            issues.append({'kind':'separately retained supplementary table mixed into main','row':i})
    # Offices are original additional dimensions. The same moku may contain
    # several offices with repeated business numbers; source reading order,
    # rather than a moku-wide name join, determines their membership.
    office_counts=collections.Counter()
    offices=origin.get('office_scopes',[])
    office_fields=sorted({f for row in rows for f,v in row.items()
                          if isinstance(v,str) and any(normalized(v)==normalized(q['text']) for q in offices)})
    for i,row in enumerate(rows):
        source_prefix='事業_' if row.get('事業_原典物理頁') is not None else ''
        page=row.get(source_prefix+'原典物理頁')
        x=row.get(source_prefix+'原典xMin');y=row.get(source_prefix+'原典yMin')
        before=[q for q in offices if all(str(row.get(k+'_番号'))==str(v) for k,v in q['path'].items())
                and page is not None and x is not None and y is not None
                and (q['page'],q['pane'],q['y0'])<(page,646 if x>=646 else 0,y)]
        office_expected=max(before,key=lambda q:(q['page'],q['pane'],q['y0'])) if before else None
        present=[f for f in office_fields if row.get(f) is not None]
        if office_expected is None:
            if present:issues.append({'kind':'office applied outside original scope','row':i,'fields':present})
            continue
        fields=[f for f in present if normalized(row[f])==normalized(office_expected['text'])]
        if len(fields)!=1:
            issues.append({'kind':'original office finest row membership','row':i,'origin':office_expected['text'],
                           'fields':present,'source_position':[page,x,y]});continue
        field=fields[0];left,top,right,bottom=office_expected['bounds']
        coordinates=[row.get(field+'_原典'+part) for part in ('xMin','yMin','xMax','yMax')]
        if (row.get(field+'_原典物理頁')!=office_expected['page'] or any(c is None for c in coordinates)
                or any(abs(a-b)>.1 for a,b in zip(coordinates,(left,top,right,bottom)))):
            issues.append({'kind':'original office position','row':i,'field':field,'origin':office_expected['bounds'],
                           'raw':coordinates})
        office_counts[office_expected['text']]+=1
    for office in offices:
        if not office_counts[office['text']]:
            issues.append({'kind':'unrepresented original office scope','origin':office['text']})
    result={'status':'failed' if issues or any(c['status']!='一致' for c in checks) else 'passed','expected_quantity_rows':len(expected)+len(origin['lists']),
            'quantity_rows_checked':len(used),'quantity_cells_checked':cell_checks,
            'quantity_hierarchy_counts':dict(collections.Counter(c['status'] for c in checks)),'original_control_rows':len(controls),'ancillary_rows_checked':notes_checked,'preservation_issues':len(issues)}
    result['original_table_scope_rows_checked']=scope_rows_checked
    result['original_office_scope_rows_checked']=dict(office_counts)
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    (output/'issues.json').write_text(json.dumps(issues,ensure_ascii=False,indent=2))
    (output/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
    (output/'controls.json').write_text(json.dumps(controls,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False));return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw',type=Path,required=True)
    p.add_argument('--observations',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();raise SystemExit(0 if validate(a.raw,a.observations,a.output)['status']=='passed' else 1)
