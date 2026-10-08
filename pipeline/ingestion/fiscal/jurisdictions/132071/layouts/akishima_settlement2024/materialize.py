"""Finite materialization: 18 per-account typed tables, aggregates and page inventory."""
from __future__ import annotations
import json,hashlib
from pathlib import Path
import duckdb
from .provider import Bundle,construct

H=lambda b:hashlib.sha256(b).hexdigest()
INT_KEYS={'fiscal_year','original_bytes','physical_page','paired_physical_page','printed_reference_amount','printed_budget_minus_executed','source_row_ordinal','account_title_physical_page'}
def typ(k):return 'BIGINT' if k in INT_KEYS or k.startswith('amount_') or k.startswith('budget_') or k.startswith('carry_') else 'VARCHAR'
def q(s):return '"'+s.replace('"','""')+'"'

def typed_table(db,name,rows):
    keys=sorted(set().union(*(r.keys() for r in rows)));types={k:typ(k) for k in keys}
    db.execute(f'create or replace table {q(name)} ('+','.join(q(k)+' '+types[k] for k in keys)+')')
    db.executemany(f'insert into {q(name)} values ('+','.join('?' for k in keys)+')',[[r.get(k) for k in keys] for r in rows])
    return keys,types

PAGE_REGION_ROLES=['account_title','expenditure_detail_left','expenditure_detail_right','real_surplus_statement','setsu_summary','account_kan_summary','formal_settlement_left','formal_settlement_right','account_overview_list','other_physical_page']
def page_inventory(pp,config):
    src=config['origin'];sha=src['sha256']
    def label(p):return ''.join(w[4] for w in sorted(pp[p-1],key=lambda w:w[0]) if w[1]>785)
    regions={}
    for a in config['accounts']:
        for p,role,acc in [(a['first_left']-1,'account_title',a['id']),(a['setsu_summary']-1,'real_surplus_statement',a['id']),(a['setsu_summary'],'setsu_summary',a['id']),(a['account_summary'],'account_kan_summary',a['id'])]+[(a['first_left']+i,'expenditure_detail_left',a['id']) for i in range(0,a['last_left']-a['first_left']+1,2)]+[(a['first_left']+i+1,'expenditure_detail_right',a['id']) for i in range(0,a['last_left']-a['first_left']+1,2)]+[(p,'formal_settlement_left',a['id']) for p in a['formal_left_pages']]+[(p+1,'formal_settlement_right',a['id']) for p in a['formal_left_pages']]:
            assert p not in regions,(p,a['id'],regions.get(p))
            regions[p]=(role,acc)
    regions[10]=('account_overview_list',None)
    rows=[]
    for p in range(1,len(pp)+1):
        role,acc=regions.get(p,('other_physical_page',None))
        name=next((a['name'] for a in config['accounts'] if a['id']==acc),None)
        rows.append(dict(source_row_id=f'{sha}:page-inventory:{p}',source_table_id='akishima-fy2024-settlement-page-inventory',source_row_ordinal=p,
            jurisdiction_id='132071',fiscal_year=2024,document_kind='settlement',original_url=src['url'],original_sha256=sha,original_bytes=src['bytes'],
            physical_page=p,printed_page_label=label(p) or None,native_word_count=len(pp[p-1]),page_region_role=role,account_id=acc,account_name=name,
            phase=None,unit=None,amount_executed=None,statutory_setsu_id=None,recognition_date=None))
    return rows

PAGE_SCHEMA=[('source_row_id','VARCHAR'),('source_table_id','VARCHAR'),('source_row_ordinal','BIGINT'),('jurisdiction_id','VARCHAR'),('fiscal_year','BIGINT'),('document_kind','VARCHAR'),('original_url','VARCHAR'),('original_sha256','VARCHAR'),('original_bytes','BIGINT'),('physical_page','BIGINT'),('printed_page_label','VARCHAR'),('native_word_count','BIGINT'),('page_region_role','VARCHAR'),('account_id','VARCHAR'),('account_name','VARCHAR'),('phase','VARCHAR'),('unit','VARCHAR'),('amount_executed','BIGINT'),('statutory_setsu_id','VARCHAR'),('recognition_date','VARCHAR')]

def copy_parquet(db,select,file):
    db.execute(f"copy ({select}) to '{file}' (format parquet, compression zstd)")

def build(bundle,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    result,pp,config,approval=construct(bundle)
    (out/'approval-readback.json').write_text(json.dumps(approval,ensure_ascii=False,indent=2)+'\n')
    for role,rows in result.items():(out/(role+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    inventory=page_inventory(pp,config)
    (out/'page-inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    proof=[];db=duckdb.connect(str(out/'warehouse.duckdb'))
    for role,rows in result.items():
        keys,types=typed_table(db,role,rows)
        actual=db.execute(f'select * from {q(role)} order by source_row_id').fetchall()
        expected=sorted([tuple(r.get(k) for k in keys) for r in rows],key=lambda r:r[keys.index('source_row_id')]);assert actual==expected
        for ext in ['parquet','csv']:
            file=out/(role+'.'+ext)
            opts='FORMAT PARQUET, COMPRESSION ZSTD' if ext=='parquet' else 'FORMAT CSV, HEADER TRUE'
            db.execute(f'copy (select * from {q(role)} order by source_row_id) to ? ({opts})',[str(file)])
            read=db.execute(f'select * from read_{"parquet" if ext=="parquet" else "csv"}(?, '+('' if ext=='parquet' else 'columns='+json.dumps(types).replace('"',"'")+", allow_quoted_nulls=false")+' ) order by source_row_id',[str(file)]).fetchall() if ext=='csv' else db.execute('select * from read_parquet(?) order by source_row_id',[str(file)]).fetchall()
            assert read==expected,(role,ext)
            b=file.read_bytes();proof.append(dict(role=role,file=file.name,rows=len(rows),sha256=H(b),bytes=len(b),schema=[dict(name=k,type=types[k]) for k in keys],all_field_readback_equal=True,amount_executed_sum=sum(r.get('amount_executed') or 0 for r in rows)))
    db.execute('create or replace table page_inventory ('+','.join(q(k)+' '+t for k,t in PAGE_SCHEMA)+')')
    db.executemany('insert into page_inventory values ('+','.join('?' for _ in PAGE_SCHEMA)+')',[[r[k] for k,_ in PAGE_SCHEMA] for r in inventory])
    invfile=out/'page-inventory.parquet';copy_parquet(db,'select * from page_inventory order by source_row_id',invfile)
    read=db.execute('select * from read_parquet(?) order by source_row_id',[str(invfile)]).fetchall()
    assert read==sorted([tuple(r[k] for k,_ in PAGE_SCHEMA) for r in inventory],key=lambda r:r[0])
    b=invfile.read_bytes();proof.append(dict(role='page_inventory',file=invfile.name,rows=len(inventory),sha256=H(b),bytes=len(b),schema=[dict(name=k,type=t) for k,t in PAGE_SCHEMA],all_field_readback_equal=True,amount_executed_sum=None))
    # 18 finite per-account raw tables, candidate Parquet layout (order by source_row_id).
    raw_manifest=[]
    for role,rows in result.items():
        keys,types=typed_table(db,'tmp_'+role,rows)
        for a in config['accounts']:
            file=out/'candidates'/(a['id']+'-'+role+'.parquet');file.parent.mkdir(exist_ok=True)
            copy_parquet(db,f"select * from {q('tmp_'+role)} where account_id='{a['id']}' order by source_row_id",file)
            actual=db.execute('select * from read_parquet(?) order by source_row_id',[str(file)]).fetchall()
            expected=sorted([tuple(r.get(k) for k in keys) for r in rows if r['account_id']==a['id']],key=lambda r:r[keys.index('source_row_id')])
            assert actual==expected
            b=file.read_bytes();raw_manifest.append(dict(role=role,account_id=a['id'],table_id=f"fy2024-{a['id']}-{role}",path='candidates/'+file.name,sha256=H(b),bytes=len(b),rows=len(actual),schema=[dict(name=k,type=types[k]) for k in keys],all_field_readback_equal=True))
        db.execute('drop table '+q('tmp_'+role))
    invsrc=out/'candidates'/'page-inventory.parquet'
    import shutil;shutil.copyfile(invfile,invsrc)
    b=invsrc.read_bytes();raw_manifest.append(dict(role='page_inventory',account_id=None,table_id='fy2024-page-inventory',path='candidates/'+invsrc.name,sha256=H(b),bytes=len(b),rows=len(inventory),schema=[dict(name=k,type=t) for k,t in PAGE_SCHEMA],all_field_readback_equal=True))
    (out/'materialization-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    (out/'raw-table-manifest.json').write_text(json.dumps(raw_manifest,ensure_ascii=False,indent=2)+'\n')
    return {'roles':{k:len(v) for k,v in result.items()},'page_inventory_rows':len(inventory),'raw_tables':len(raw_manifest),'executed_yen':sum(r['amount_executed'] for r in result['financial'])}
