"""Reproduce every printed-vs-calculated control comparison from decoded rows."""
from collections import defaultdict

def ledger_for(results):
    ledger=[]
    def cmp(year,kind,printed,calc,a,b):
        ledger.append(dict(fiscal_year=year,kind=kind,printed=printed,calculated=calc,ok=printed==calc,source_a=a,source_b=b))
    for y,(res,pages,approval) in results.items():
        fin=res['financial'];ctl=res['controls'];prj=res['projects']
        for aid in sorted(set(r['account_id'] for r in fin)):
            F=[r for r in fin if r['account_id']==aid]
            C=[r for r in ctl if r['account_id']==aid]
            P=[r for r in prj if r['account_id']==aid]
            ex=sum(r['amount_executed'] for r in F)
            tot=[r for r in C if r['source_grain']=='account_control']
            assert len(tot)==1,(y,aid,len(tot))
            cmp(y,'account_total',tot[0]['amount_executed'],ex,tot[0]['source_row_id'],'sum(financial)')
            ov=[r for r in C if r['source_grain']=='account_overview_control']
            assert len(ov)==1;cmp(y,'account_list',ov[0]['amount_executed'],ex,ov[0]['source_row_id'],'sum(financial)')
            gt=[r for r in C if r['source_grain']=='setsu_summary_grand_total_control']
            assert len(gt)==1,(y,aid,len(gt));cmp(y,'setsu_grand_total',gt[0]['amount_executed'],ex,gt[0]['source_row_id'],'sum(financial)')
            mk=defaultdict(int)
            for r in F:
                if r['source_grain']=='printed_legal_setsu': mk[(r['kan_code'],r['kou_code'],r['moku_code'],r['moku_name'])]+=r['amount_executed']
            for r in C:
                if r['source_grain']=='moku_control':
                    key=(r['kan_code'],r['kou_code'],r['moku_code'],r['moku_name'])
                    cmp(y,'moku_sum',r['amount_executed'],mk.get(key,0),r['source_row_id'],f'sum(legal {key})')
            pj=defaultdict(int)
            for r in P: pj[(r['kan_code'],r['kou_code'],r['moku_code'])]+=r['amount_executed']
            for r in C:
                if r['source_grain']=='moku_control':
                    key=(r['kan_code'],r['kou_code'],r['moku_code'])
                    if key in pj or r['amount_executed']!=0:
                        cmp(y,'project_to_moku',r['amount_executed'],pj.get(key,0),r['source_row_id'],'sum(projects)')
            kk=defaultdict(int)
            for r in F:
                if r['source_grain']=='printed_legal_setsu': kk[(r['kan_code'],r['kan_name'])]+=r['amount_executed']
            for r in C:
                if r['source_grain']=='kan_control':
                    cmp(y,'kan_sum',r['amount_executed'],kk.get((r['kan_code'],r['kan_name']),0),r['source_row_id'],'sum(legal kan)')
            ko=defaultdict(int)
            for r in F:
                if r['source_grain']=='printed_legal_setsu': ko[(r['kan_code'],r['kou_code'],r['kou_name'])]+=r['amount_executed']
            for r in C:
                if r['source_grain']=='kou_control':
                    cmp(y,'kou_sum',r['amount_executed'],ko.get((r['kan_code'],r['kou_code'],r['kou_name']),0),r['source_row_id'],'sum(legal kou)')
            ss=defaultdict(int)
            for r in F:
                if r['source_grain']=='printed_legal_setsu' and r['printed_setsu_code']:
                    ss[r['printed_setsu_code']]+=r['amount_executed']
            for r in C:
                if r['source_grain'].startswith('setsu_summary_') and 'subtotal' not in r['source_grain'] and 'grand' not in r['source_grain'] and r.get('printed_setsu_code'):
                    cmp(y,'setsu_summary',r['amount_executed'],ss.get(r['printed_setsu_code'],0),r['source_row_id'],f'sum(legal setsu {r["printed_setsu_code"]})')
            for r in C:
                if r['source_grain']=='account_kan_summary_control':
                    key=r['kan_code']
                    c=sum(v for (k,n),v in kk.items() if k==key) if key else sum(v for (k,n),v in kk.items() if n==r['printed_control_label'])
                    cmp(y,'soukatsu_kan',r['amount_executed'],c,r['source_row_id'],'sum(legal kan code)')
            for r in C:
                if r['source_grain']=='formal_settlement_control':
                    if r['kou_code']:
                        cc=sum(v for (k1,k2,n),v in ko.items() if k1==r['kan_code'] and k2==r['kou_code'])
                        cmp(y,'formal_kou',r['amount_executed'],cc,r['source_row_id'],'sum(legal kou)')
                    elif r['kan_code']:
                        cc=sum(v for (k,n),v in kk.items() if k==r['kan_code'])
                        cmp(y,'formal_kan',r['amount_executed'],cc,r['source_row_id'],'sum(legal kan)')
                    else:
                        cmp(y,'formal_total',r['amount_executed'],ex,r['source_row_id'],'sum(financial)')
    return ledger
