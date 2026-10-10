"""Compare every saved Parquet value and reference; no origin acceptance verdict."""
import argparse
import hashlib
import json
from pathlib import Path

import duckdb


def verify(first, second):
    reports=[]
    a=json.loads((first/'conversion.json').read_text())
    b=json.loads((second/'conversion.json').read_text())
    if list(a)!=list(b):
        raise ValueError('Table coverage differs')
    with duckdb.connect(config={'threads':1}) as con:
        for name in a:
            paths=[p/(name+'.parquet') for p in (first,second)]
            values=[con.execute('SELECT * FROM read_parquet(?)',[str(p)]).fetchall() for p in paths]
            schemas=[con.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(p)]).fetchall() for p in paths]
            digests=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
            if values[0]!=values[1] or schemas[0]!=schemas[1] or digests[0]!=digests[1]:
                raise ValueError(f'Parquet bytes/schema/ordered values differ: {name}')
            if a[name]['metadata']!=b[name]['metadata']:
                raise ValueError(f'Metadata differs: {name}')
            reports.append({'table':name,'rows':len(values[0]),'columns':len(schemas[0]),
                'sha256':digests[0],'schema_value_null_order_duplicate_equal':True,
                'metadata_equal':True})
    observations=[json.loads((p/'observations.json').read_text()) for p in (first,second)]
    if observations[0]!=observations[1]:
        raise ValueError('Native binding/correction/coverage differs')
    return {'tables':reports,'observation_bindings_equal':True,'missing':len(observations[0]['missing']),
            'unassigned':len(observations[0]['unassigned']),
            'corrections':len(observations[0]['corrections_used'])}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--first',type=Path,required=True)
    parser.add_argument('--second',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=verify(args.first,args.second)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':
    main()
