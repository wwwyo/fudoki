"""Original-only candidate CLI: two Parquet files plus schema3 inline declarations.

The --definitions file must be externally sealed by the parent before import.
This command does not save/upload objects, adopt a lock, or emit provenance.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--definitions',required=True,type=Path)
    args=parser.parse_args()
    from ingestion.fiscal.komae_supplementary_2020_1_contracts import (
        ORIGIN,ORIGIN_BYTES,FACTS,load,declaration,input_path,verify_definitions,
        validate_entry,verified_bytes,checked_bytes,
    )
    from ingestion.fiscal.extract_komae_supplementary_2020_1 import main as extract
    from ingestion.inputs import source_declaration
    definitions=json.loads(checked_bytes(args.definitions));verify_definitions(definitions)
    verified_bytes(args.original,dict(sha256=ORIGIN,bytes=ORIGIN_BYTES))
    if args.out.exists() or args.out.is_symlink():raise ValueError('new candidate output directory required')
    args.out.mkdir(parents=True,exist_ok=False)
    extract(args.original,args.out)
    entries=[]
    for spec in load().values():
        d=spec['direction'];fact=FACTS[d]
        verified_bytes(args.out/('table-'+d+'.parquet'),{k:fact[k] for k in ('sha256','bytes')})
        entry=dict(path=input_path(spec),jurisdiction='132195',fiscalYear=2020,
            documentKind='supplementary',direction=d,originEdition=ORIGIN,
            origin=dict(availability='stored',sha256=ORIGIN,
                object=dict(key='inputs/origin/sha256/'+ORIGIN,sha256=ORIGIN,bytes=ORIGIN_BYTES)),
            table=dict(key='inputs/table/sha256/'+fact['sha256'],sha256=fact['sha256'],bytes=fact['bytes']),
            source=source_declaration(declaration(spec,definitions)))
        validate_entry(entry,spec);entries.append(entry)
    (args.out/'inputs.lock.json').write_text(json.dumps(dict(schemaVersion=3,entries=entries),
        ensure_ascii=False,sort_keys=True,indent=2)+'\n')

if __name__=='__main__':main()
