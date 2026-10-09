"""Compare saved enterprise raw to independent XML observations and printed totals."""
import argparse, collections, hashlib, json, re
from pathlib import Path
import duckdb

def canon(value):return re.sub(r'\s+','',value or '')
def amount(value):return int(value.replace(',',''))
def read(path):
    with duckdb.connect() as con:
        result=con.execute('select * from read_parquet(?, hive_partitioning=false)',[str(path)])
        columns=[c[0] for c in result.description]
        rows=[dict(zip(columns,row)) for row in result.fetchall()]
        types=con.execute('describe select * from read_parquet(?, hive_partitioning=false)',[str(path)]).fetchall()
    if any(t[1] not in ('VARCHAR','BIGINT','DOUBLE') for t in types):raise ValueError('Non-scalar raw type')
    return rows

def validate(origin, manifest, candidate, out, pdf):
    document=json.loads(manifest.read_text());obs=json.loads(origin.read_text());issues=[];checks=[];cell_count=0;tables={}
    sha=hashlib.sha256(pdf.read_bytes()).hexdigest()
    if sha!=obs['sha256'] or {i['sha256'] for c in document['conversions'] for i in c['inputs']}!={sha}:raise ValueError('Independent original identity differs')
    def equal(kind,path,expected,actual,page=None):
        checks.append({'kind':kind,'path':path,'page':page,'printed':expected,'observed':actual,'status':'一致' if expected==actual else '不一致'})
    def cells(expected,actual,ident):
        nonlocal cell_count
        if len(expected)!=len(actual):issues.append({'kind':'row_count','table':ident,'expected':len(expected),'actual':len(actual)})
        for index,(a,b) in enumerate(zip(expected,actual)):
            for key,value in a.items():
                cell_count+=1
                got=b.get(key)
                if got!=value:issues.append({'kind':'文字・所属','table':ident,'row':index,'column':key,'expected':value,'actual':got})
    for table in document['tables']:
        ident=table['table_id'];path=candidate/(ident+'.parquet')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=table['object']['sha256'] or path.stat().st_size!=table['object']['bytes']:raise ValueError('Candidate identity differs')
        rows=read(path);tables[ident]=rows
        if len(rows)!=table['row_count']:raise ValueError('Receipt rows differ')
        if ident.endswith('-detail'):
            capital=ident.endswith('capital-detail');sections=[s for s in obs['sections'] if (s['page']>=30)==capital];expected=[]
            for section in sections:
                for remark in section['remarks'] or [None]:
                    expected.append({**section['path'],'節':section['name'],'金額（円）':section['amount'],'備考_予算額':section['budget'],'備考_名称':remark['name'] if remark else None,'備考_金額':remark['amount'] if remark else None,'物理頁':section['page'],'印刷頁':'-'+str(section['page']-3)+'-'})
            cells(expected,rows,ident)
            if set(rows[0])!=set(expected[0])|{'原典位置_上端','原典位置_下端'}:issues.append({'kind':'raw列集合','table':ident})
            for row,section in zip(rows,[s for s in sections for _ in (s['remarks'] or [None])],strict=False):
                y=section['y']/1.5
                if not row['原典位置_上端']-2<=y<=row['原典位置_下端']+2:issues.append({'kind':'原典位置','table':ident,'page':section['page'],'source_y':y})
            # Read raw anew by each complete original path. Repeated parents must agree before a single value can be used.
            def group(columns,value):
                grouped=collections.defaultdict(list)
                for row in rows:grouped[tuple(row[k] for k in columns)].append(row)
                values={}
                for key,members in grouped.items():
                    amounts={r[value] for r in members}
                    if len(amounts)!=1:issues.append({'kind':'反復親不一致','table':ident,'path':key,'values':sorted(amounts)})
                    else:values[key]=amount(next(iter(amounts)))
                return values,grouped
            sections_raw,groups=group(['款','項','目','節'],'金額（円）')
            for key,members in groups.items():
                names=[r['備考_名称'] for r in members]
                if names[0] is not None:
                    if len(set(names))!=len(names):issues.append({'kind':'duplicate_leaf','path':key})
                    equal('備考実績内訳→節',key,sections_raw.get(key),sum(amount(r['備考_金額']) for r in members),members[0]['物理頁'])
                else:checks.append({'kind':'備考実績内訳→節','path':key,'status':'検算不可','reason':'原典の備考実績内訳がない。節は印字値保持を検査。'})
            child_values=sections_raw
            for columns,parent,kind in [(['款','項','目'],'目_金額','節→目'),(['款','項'],'項_金額','目→項'),(['款'],'款_金額','項→款')]:
                values,members=group(columns,parent)
                sums=collections.defaultdict(int)
                for key,value in child_values.items():sums[key[:-1]]+=value
                for key,value in values.items():equal(kind,key,value,sums.get(key),members[key][0]['物理頁'])
                child_values=values
        else:
            suffix='capital-report' if ident.endswith('capital-report') else 'revenue-report'
            parent,*children=obs['reports'][suffix];expected=[]
            for child in children:
                expected.append({'区分_款':parent['区分'],'区分_項':child['区分'],**{'区分_款_'+k:v for k,v in parent.items() if k not in ('区分','page','y')},**{k:v for k,v in child.items() if k not in ('区分','page','y')},'物理頁':child['page'],'印刷頁':'-'+str(child['page']-3)+'-','右物理頁':child['page']+1,'右印刷頁':'-'+str(child['page']-2)+'-'})
            cells(expected,rows,ident)
            position_columns={'原典位置_上端','原典位置_下端','区分_款_物理頁','区分_款_印刷頁','区分_款_右物理頁','区分_款_右印刷頁','区分_款_原典位置_上端','区分_款_原典位置_下端'}
            if set(rows[0])!=set(expected[0])|position_columns:issues.append({'kind':'raw列集合','table':ident})
            for row,child in zip(rows,children):
                if not row['原典位置_上端']-2<=child['y']/1.5<=row['原典位置_下端']+2:issues.append({'kind':'原典位置','table':ident})
                if row['区分_款_物理頁']!=parent['page'] or row['区分_款_印刷頁']!='-'+str(parent['page']-3)+'-' or row['区分_款_右物理頁']!=parent['page']+1 or row['区分_款_右印刷頁']!='-'+str(parent['page']-2)+'-':issues.append({'kind':'反復親原典頁','table':ident})
                if not row['区分_款_原典位置_上端']-2<=parent['y']/1.5<=row['区分_款_原典位置_下端']+2:issues.append({'kind':'反復親原典位置','table':ident})
            for column,value in parent.items():
                if column in ('区分','page','y','備考_名称'):continue
                repeated={row['区分_款_'+column] for row in rows}
                if len(repeated)!=1:issues.append({'kind':'反復款不一致','table':ident,'column':column})
                equal('項→款('+column+')',[parent['区分']],amount(value),sum(amount(row[column]) for row in rows),parent['page'])
            # Each row's printed budget subtotal and remainder are independent checks.
            saved_parent={'区分':rows[0]['区分_款'],'page':parent['page'],**{k:rows[0]['区分_款_'+k] for k in parent if k not in ('区分','page','y')}}
            saved_children=[{**r,'区分':r['区分_項'],'page':r['物理頁']} for r in rows]
            for row in [saved_parent,*saved_children]:
                subtotal=sum(amount(row[k]) for k in ['当初予算額','補正予算額','予備費支出額','流用増減額'])
                if suffix=='revenue-report':subtotal+=amount(row['地方公営企業法第24条第3項の規定による支出額'])
                equal('予算内訳→小計',row['区分'],amount(row['小計']),subtotal,row['page'])
                carry=amount(row['地方公営企業法第26条の規定による前年度繰越額'])+amount(row['継続費逓次繰越額']) if suffix=='capital-report' else amount(row['地方公営企業法第26条第２項の規定による繰越額'])
                equal('小計・繰越→合計',row['区分'],amount(row['合計']),amount(row['小計'])+carry,row['page'])
                carryout=amount(row['翌年度繰越額_合計']) if suffix=='capital-report' else amount(row['地方公営企業法第26条第2項の規定による繰越額'])
                if suffix=='capital-report':equal('翌年度繰越内訳→合計',row['区分'],carryout,amount(row['地方公営企業法第26条の規定による繰越額'])+amount(row['翌年度繰越額_継続費逓次繰越額']),row['page'])
                equal('決算・繰越・不用→予算合計',row['区分'],amount(row['合計']),amount(row['決算額'])+carryout+amount(row['不用額']),row['page'])
    for suffix in ['revenue-detail','capital-detail']:
        checks.append({'kind':'税込報告↔税抜明細','path':suffix,'status':'検算不可','reason':'税区分が異なる独立原典表。完全な税調整対応の印字が選定範囲にないため同額比較しない。'})
    counts=dict(collections.Counter(c['status'] for c in checks));summary={'text_cells_checked':cell_count,'text_or_structure_mismatches':len(issues),'amount_checks':counts,'tables':{k:{'rows':len(v),'columns':len(v[0])} for k,v in tables.items()}}
    out.mkdir(parents=True,exist_ok=False);(out/'checks.json').write_text(json.dumps({'summary':summary,'issues':issues,'checks':checks},ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
    return 1 if issues or counts.get('不一致',0) or counts.get('保留',0) else 0
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pdf',type=Path,required=True);p.add_argument('--origin',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();raise SystemExit(validate(a.origin,a.manifest,a.candidate,a.out,a.pdf))
