"""Black-box negative fixtures, stored separately from every real candidate."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import duckdb

p=argparse.ArgumentParser(description=__doc__)
for k in ['pdf','origin','remarks-origin','candidate','output']:
    p.add_argument('--'+k,type=Path,required=True)
p.add_argument('--table-id',default='general-setsu')
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
source=a.candidate/(a.table_id+'.parquet'); validator=Path(__file__).with_name('validate_candidate.py');results=[]
for name,sql in [
    ('name-loss','select * exclude(rn) replace (case when rn=1 then \'誤った名称\' else "区分_名称" end as "区分_名称") from fixture'),
    ('membership-only','select * exclude(rn) replace (case when rn=1 then \'99\' else "区分_番号" end as "区分_番号") from fixture'),
    ('remarks-membership','select * exclude(rn) replace (case when rn=1 then \'誤った備考\' else "備考" end as "備考") from fixture'),
    ('repeated-parent','select * exclude(rn) replace (case when rn=1 then \'0\' else "款_計" end as "款_計") from fixture'),
]:
    folder=a.output/name;folder.mkdir();file=folder/(a.table_id+'.parquet')
    with duckdb.connect() as c:
        c.execute('create table fixture as select *, row_number() over() rn from read_parquet(?)',[str(source)])
        c.execute('copy ('+sql+') to ? (format parquet)',[str(file)])
    cmd=[sys.executable,str(validator),'--pdf',str(a.pdf),'--origin',str(a.origin),'--remarks-origin',str(a.remarks_origin),'--candidate',str(folder),'--output',str(folder/'checks'),'--table-id',a.table_id]
    result=subprocess.run(cmd,capture_output=True,text=True)
    (folder/'stdout.txt').write_text(result.stdout);(folder/'stderr.txt').write_text(result.stderr)
    if result.returncode==0:raise ValueError('Invalid fixture accepted: '+name)
    check=json.loads((folder/'checks/result.json').read_text())
    if not check['cell_mismatches']:raise ValueError('Negative fixture failed without detecting its mutation: '+name)
    results.append(dict(case=name,rejected=True,cell_mismatches=check['cell_mismatches']))
(a.output/'result.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results))
