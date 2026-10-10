"""Reconcile observed or read-back paths against independent original controls."""
from __future__ import annotations

def number(text: str) -> int:
    if text is None: raise ValueError('Missing original amount')
    return int(text.replace(',', '').replace('△', '-'))

def reconcile(source: dict, actual: dict[tuple, dict]) -> list[dict]:
    checks=[]
    def check(kind,path,field,parent,children,page,reason=None):
        checks.append(dict(kind=kind,path=list(path),field=field,page=page,unit='円',parent=parent,children=children,difference=None if children is None else children-parent,status='pending' if reason and ('absent' in reason.lower() or 'No complete' in reason) else 'uncheckable' if reason else 'match' if parent==children else 'mismatch',reason=reason))
    for expected in source['nodes']:
        path=tuple(expected['path']);a=actual.get(path)
        if a is None:
            check('missing-path',path,'row',None,None,expected['page'],'Original path absent from read-back')
            continue
        vals={k:number(v) for k,v in a['amounts'].items()}
        check('balance',path,'total',vals['total'],sum(vals[k] for k in ['executed','carry_continuing','carry_authorized','carry_accident','unused']),expected['page'])
        if expected['level']<3:
            check('budget-components',path,'total',vals['total'],sum(vals[k] for k in ['initial','amendment','prior','transfer']),expected['page'])
        if 0<=expected['level']<3:
            kids=[v for k,v in actual.items() if len(k)==len(path)+1 and k[:-1]==path]
            fields=['total','executed','carry_continuing','carry_authorized','carry_accident','unused'] if expected['level']==2 else list(expected['amounts'])
            for field in fields:
                check('hierarchy',path,field,number(expected['amounts'][field]),sum(number(n['amounts'][field]) for n in kids) if kids else None,expected['page'],None if kids else 'No complete child breakdown')
            if expected['level']==2:
                for field in ['initial','amendment','prior','transfer']:
                    check('hierarchy',path,field,number(expected['amounts'][field]),None,expected['page'],'節に当初・補正・前年度繰越・流用の個別内訳が印字されない')
    kan=[n for p,n in actual.items() if len(p)==1]
    grand=next(n for n in source['nodes'] if n['level']==-1)
    for field,value in grand['amounts'].items():
        check('款-to-grand',(),field,number(value),sum(number(n['amounts'][field]) for n in kan),grand['page'])
    for s in source['summary']:
        path=(s['number'],) if s['number'] else ()
        for field,value in s['amounts'].items():
            total=number(actual[path]['amounts'][field]) if path in actual else None
            check('summary-to-detail',path,field,number(value),total,s['page'],None if total is not None else 'Read-back path absent')
    return checks
