import sys, json
from pathlib import Path
from . import provider

def main():
    cmd = sys.argv[1]
    if cmd == 'schema':
        print(json.dumps({'tables': ['raw_financial','raw_controls','raw_projects','raw_revenue','raw_pages']}))
    elif cmd == 'build':
        originals, outdir = Path(sys.argv[2]), Path(sys.argv[3]); outdir.mkdir(parents=True, exist_ok=True)
        manifest = provider.verify_originals(originals)
        (outdir/'originals-manifest.json').write_text(json.dumps(manifest, indent=1)+'\n')
        tables = provider.produce(originals)
        for name, rows in tables.items():
            (outdir/f'{name}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1)+'\n')
        print(json.dumps({k: len(v) for k, v in tables.items()}))
    elif cmd == 'restore-evidence':
        plan = provider.restore_evidence(sys.argv[2], sys.argv[3])
        print(json.dumps(plan, indent=1))

main()
