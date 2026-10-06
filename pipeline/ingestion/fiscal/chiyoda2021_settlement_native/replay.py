"""Supported reconstruction: origin PDF -> five typed Parquets, byte-exact.

Usage:
    python replay.py --extract-dir <dir-with-extract.py,run.py,serialize.py> \
        --origin <r3kessansho-2.pdf> --out <out_dir>

The extract scripts are immutable proof objects (evidence-manifest.json).
Determinism: run.py -> expenditure.json; serialize.py -> 5 CSVs + 5 Parquets
(fixed column order, explicit colspecs, no auto-detect). Receipts record SHA/rows.
"""
from __future__ import annotations

import argparse, hashlib, json, os, subprocess, sys
from pathlib import Path


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--extract-dir', required=True)
    ap.add_argument('--origin', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    ext, origin, out = Path(a.extract_dir), Path(a.origin), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    exp = out / 'expenditure.json'
    env = {**os.environ, 'BOOK': str(origin), 'OUT': str(exp), 'PAGE0': '56', 'PAGE1': '112'}
    r = subprocess.run([sys.executable, str(ext / 'run.py')], env=env,
                       capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stderr); return r.returncode
    r = subprocess.run([sys.executable, str(ext / 'serialize.py'),
                        str(exp), str(origin), str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stderr); return r.returncode
    receipt = {'origin_sha256': sha(origin.read_bytes()), 'origin_bytes': origin.stat().st_size,
               'tables': {}}
    for name in ('native_pages', 'native_observations', 'native_levels',
                 'native_setsu', 'native_notes'):
        b = (out / f'{name}.parquet').read_bytes()
        receipt['tables'][name] = {'sha256': sha(b), 'bytes': len(b)}
    (out / 'replay-receipt.json').write_text(json.dumps(receipt, indent=1))
    print(json.dumps(receipt, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
