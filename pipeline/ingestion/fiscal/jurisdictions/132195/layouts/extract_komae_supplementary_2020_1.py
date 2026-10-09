"""Supported original-only extractor driver: Komae FY2020 suppl no.1.

Takes one original PDF, extracts per-page native text (pdftotext -layout),
runs the token-lane parser (extract_v2.py) against that text, serializes the
two direction tables to parquet, and verifies pinned SHA256 values.
No OCR, no network, no writes outside outdir.
"""
from __future__ import annotations
import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
EXPECTED={
 'origin_sha256':'55b99cec58e42222cfdd93d59821ab92d25464f23f2fcead40d0e19a3f17492a',
 'origin_bytes':471659,
 'expenditure':{'sha256':'a3d334e638c43d472ccfa43a47d3ff67aacc21acad51a015846be98c3ba77c68','rows':291,'bytes':13068},
 'revenue':{'sha256':'a0ce026498e70e919079136261411c1eab50598aa57d7c9c882a540f234b58ef','rows':100,'bytes':8287},
}
COLS=['source_row','kind','direction','kan_code','kou_code','moku_code','moku_label',
      'setsu_code','setsu_label','setsu_level','setsu_x','block_id','before','delta','total',
      'natl','metro','bond','other','general','physical_page','raw_text']

def extract_text(origin:Path,outdir:Path)->Path:
    ev=outdir/'evidence';ev.mkdir(parents=True,exist_ok=True)
    for i in range(1,14):
        txt=subprocess.run(['pdftotext','-layout','-f',str(i),'-l',str(i),str(origin),'-'],
                           capture_output=True,text=True,check=True).stdout
        (ev/f'page-{i}.txt').write_text(txt)
    return ev

def parse_pages(evid:Path,outdir:Path)->list[dict]:
    part1=outdir/'part1.json'
    env=dict(os.environ,EVID_DIR=str(evid),PART1_OUT=str(part1))
    subprocess.run([sys.executable,'-S',str(HERE/'extract_komae_supplementary_2020_1_lanes.py')],check=True,env=env)
    return json.loads(part1.read_text())

def to_parquet(rows,outdir:Path):
    import duckdb
    con=duckdb.connect(config={'memory_limit':'256MB','threads':1})
    for d in ('expenditure','revenue'):
        sub=[r for r in rows if r['direction'] in (d,None)]
        for r in sub:
            for c in COLS:r.setdefault(c,None)
        con.execute("""create or replace table t(source_row bigint,kind varchar,direction varchar,
            kan_code varchar,kou_code varchar,moku_code varchar,moku_label varchar,setsu_code varchar,
            setsu_label varchar,setsu_level varchar,setsu_x bigint,block_id varchar,before_amt bigint,delta bigint,
            total bigint,natl bigint,metro bigint,bond bigint,other bigint,general bigint,
            physical_page bigint,raw_text varchar)""")
        for r in sub:
            con.execute('insert into t values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [r['source_row'],r['kind'],r['direction'],r['kan_code'],r['kou_code'],r['moku_code'],
                 r['moku_label'],r['setsu_code'],r['setsu_label'],r['setsu_level'],r['setsu_x'],r['block_id'],
                 r['before'],r['delta'],r['total'],r['natl'],r['metro'],r['bond'],r['other'],
                 r['general'],r['physical_page'],r['raw_text']])
        out=outdir/f'table-{d}.parquet'
        con.execute(f"copy t to '{out}' (format parquet)")

def main(origin:Path,outdir:Path):
    b=origin.read_bytes()
    sha=hashlib.sha256(b).hexdigest()
    if sha!=EXPECTED['origin_sha256'] or len(b)!=EXPECTED['origin_bytes']:
        raise SystemExit(f'origin mismatch sha={sha} bytes={len(b)}')
    outdir.mkdir(parents=True,exist_ok=True)
    rows=parse_pages(extract_text(origin,outdir),outdir)
    to_parquet(rows,outdir)
    receipt={'origin_sha256':sha,'tables':{}}
    ok=True
    for d in ('expenditure','revenue'):
        f=outdir/f'table-{d}.parquet';got=hashlib.sha256(f.read_bytes()).hexdigest()
        # bind actual rows + column count (22-field schema incl. setsu_x) + bytes
        import duckdb
        cc=duckdb.connect(config={'memory_limit':'256MB','threads':1})
        cols=cc.execute(f"describe (select * from read_parquet('{f}',hive_partitioning=false))").fetchall()
        nrows=cc.execute(f"select count(*) from read_parquet('{f}',hive_partitioning=false)").fetchone()[0]
        match=(got==EXPECTED[d]['sha256'] and f.stat().st_size==EXPECTED[d]['bytes']
               and nrows==EXPECTED[d]['rows'] and len(cols)==22)
        receipt['tables'][d]={'path':str(f),'sha256':got,'bytes':f.stat().st_size,
            'expected_sha256':EXPECTED[d]['sha256'],'match':match}
        ok&=match
        print(d,got,'MATCH' if match else 'MISMATCH')
    (outdir/'replay-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=1))
    if not ok:raise SystemExit('pinned table sha mismatch')

if __name__=='__main__':
    main(Path(sys.argv[1]),Path(sys.argv[2]))
