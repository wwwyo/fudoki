"""Finite materialization: 63 per-account typed tables, 4 whole-account controls, 4 page inventories."""
from __future__ import annotations
import json,hashlib,shutil
from pathlib import Path
import duckdb
from .provider import Bundle,construct
from .verify import ledger_for

H=lambda b:hashlib.sha256(b).hexdigest()
INT_KEYS={'fiscal_year','original_bytes','physical_page','paired_physical_page','printed_reference_amount','printed_budget_minus_executed','source_row_ordinal','account_title_physical_page','word_count','native_word_count'}
def typ(k):
    if k=='blank':return 'BOOLEAN'
    return 'BIGINT' if k in INT_KEYS or k.startswith('amount_') or k.startswith('budget_') or k.startswith('carry_') else 'VARCHAR'
def q(s):return '"'+s.replace('"','""')+'"'

def typed_table(db,name,rows):
    keys=sorted(set().union(*(r.keys() for r in rows)));types={k:typ(k) for k in keys}
    db.execute(f'create or replace table {q(name)} ('+','.join(q(k)+' '+types[k] for k in keys)+')')
    db.executemany(f'insert into {q(name)} values ('+','.join('?' for k in keys)+')',[[r.get(k) for k in keys] for r in rows])
    return keys,types

def copy_parquet(db,select,file):
    db.execute(f"copy ({select}) to '{file}' (format parquet, compression zstd)")

def page_inventory(pages,ycfg):
    """Per-edition physical-page inventory bound to this book only."""
    y=ycfg['fiscal_year'];src=ycfg['origin'];sha=src['sha256'];landscape=ycfg['layout']=='landscape'
    def label(p):return ''.join(w[4] for w in sorted(pages[p-1],key=lambda w:w[0]) if w[1]>785)
    regions={}
    regions[ycfg['account_list_page']]=('account_overview_list',None)
    for a in ycfg['accounts']:
        regions[a['title_page']]=('account_title',a['id'])
        regions[a['jisshitsu']]=('real_surplus_statement',a['id'])
        regions[a['setsu_summary']]=('setsu_summary',a['id'])
        regions[a['soukatsu']]=('account_kan_summary',a['id'])
        for p in range(a['detail_first'],a['detail_last']+1):
            if landscape:regions[p]=('expenditure_detail',a['id'])
            else:regions[p]=('expenditure_detail_left' if p%2==(a['detail_first']%2) else 'expenditure_detail_right',a['id'])
        for p in a['formal_pages']:
            regions[p]=('formal_settlement_left' if not landscape else 'formal_settlement',a['id'])
            if not landscape:regions[p+1]=('formal_settlement_right',a['id'])
    rows=[]
    for p in range(1,len(pages)+1):
        role,acc=regions.get(p,('other_physical_page',None))
        name=next((a['name'] for a in ycfg['accounts'] if a['id']==acc),None)
        rows.append(dict(source_row_id=f'{sha}:page-inventory:{p}',source_table_id=f'akishima-fy{y}-settlement-page-inventory',
            source_row_ordinal=p,jurisdiction_id='132071',fiscal_year=y,document_kind='settlement',
            original_url=src['url'],original_sha256=sha,original_bytes=src['bytes'],physical_page=p,
            printed_page_label=label(p) or None,native_word_count=len(pages[p-1]),blank=not pages[p-1],
            page_region_role=role,account_id=acc,account_name=name,phase=None,unit=None,amount_executed=None))
    return rows

def build(bundle,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    results,config=construct(bundle)
    (out/'approvals.json').write_text(json.dumps({str(y):a for y,(r,p,a) in results.items()},ensure_ascii=False,indent=2)+'\n')
    raw_manifest=[];proof=[];db=duckdb.connect(str(out/'warehouse.duckdb'))
    cand=out/'candidates';cand.mkdir(exist_ok=True)
    def emit_file(rows,table_id,meta):
        if not rows:return
        keys,types=typed_table(db,'tmp_'+table_id,rows)
        file=cand/(table_id+'.parquet')
        copy_parquet(db,f'select * from {q("tmp_"+table_id)} order by source_row_id',file)
        actual=db.execute('select * from read_parquet(?) order by source_row_id',[str(file)]).fetchall()
        expected=sorted([tuple(r.get(k) for k in keys) for r in rows],key=lambda r:r[keys.index('source_row_id')])
        assert actual==expected,table_id
        b=file.read_bytes()
        raw_manifest.append(dict(table_id=table_id,path='candidates/'+file.name,sha256=H(b),bytes=len(b),rows=len(actual),schema=[dict(name=k,type=types[k]) for k in keys],all_field_readback_equal=True,**meta))
        db.execute('drop table '+q('tmp_'+table_id))
    for y,(result,pages,approval) in results.items():
        ycfg=next(c for c in config['years'] if c['fiscal_year']==y)
        for a in ycfg['accounts']:
            for role,rows in result.items():
                sub=[r for r in rows if r['account_id']==a['id']]
                if not sub:assert role!='financial';continue
                emit_file(sub,f"fy{y}-{a['id']}-{role}",dict(fiscal_year=y,account_id=a['id'],raw_role=role))
        whole=[r for rows in result.values() for r in rows if r['account_id']=='_all']
        assert len(whole)==1,(y)
        emit_file(whole,f'fy{y}-all-controls',dict(fiscal_year=y,account_id='_all',raw_role='controls'))
        inv=page_inventory(pages,ycfg)
        emit_file(inv,f'fy{y}-page-inventory',dict(fiscal_year=y,account_id=None,raw_role='page_inventory'))
    ledger=ledger_for(results)
    assert all(l['ok'] for l in ledger),[l for l in ledger if not l['ok']][:3]
    (out/'independent-controls-ledger.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=1)+'\n')
    (out/'materialization-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    (out/'raw-table-manifest.json').write_text(json.dumps(raw_manifest,ensure_ascii=False,indent=2)+'\n')
    return {'years':{str(y):{k:len(v) for k,v in r.items()} for y,(r,p,a) in results.items()},
            'raw_tables':len(raw_manifest),'comparisons':len(ledger),'comparison_failures':0,
            'executed_yen':sum(r['amount_executed'] for y,(rr,p,a) in results.items() for r in rr['financial'])}
