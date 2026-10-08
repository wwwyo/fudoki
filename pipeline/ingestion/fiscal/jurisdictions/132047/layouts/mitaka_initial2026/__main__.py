"""Portable CLI: describe | verify | emit — 25-column mart-schema rows."""
import argparse, csv, json, sys
from pathlib import Path
from . import reconstruct

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('command', choices=['describe', 'verify', 'emit'])
    ap.add_argument('fmt', nargs='?', default='jsonl')
    ap.add_argument('--objects', default=None)
    a = ap.parse_args()
    cfg = reconstruct.config()
    if a.command == 'describe':
        e = cfg['edition']
        print(json.dumps({'namespace': cfg['namespace'], 'source_key': cfg['source_key'],
          'tables': cfg['tables'],
          'origin': {'sha256': e['sha256'], 'bytes': e['bytes'],
                     'key': 'inputs/origin/sha256/' + e['sha256']}}, ensure_ascii=False))
        return
    objects = a.objects
    if objects is None:
        from ingestion.paths import CACHE
        objects = str(CACHE / 'objects')
    if a.command == 'verify':
        reconstruct.verify_origin(cfg, objects); print(json.dumps({'verified': 1})); return
    rows, _ = reconstruct.typed_rows(cfg, objects)
    if a.fmt == 'csv':
        w = csv.DictWriter(sys.stdout, fieldnames=reconstruct.F25)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                        for k, v in r.items()})
    else:
        for r in rows: print(json.dumps(r, ensure_ascii=False))

if __name__ == '__main__':
    main()
