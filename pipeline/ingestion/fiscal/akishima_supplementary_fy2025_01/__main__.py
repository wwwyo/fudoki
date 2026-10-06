"""Origin-only extraction: stored PDF bytes -> pdftotext -bbox words -> decode ->
three typed kan-summary parquets. Deterministic; no OCR, no network.
Usage: python -m akishima_supplementary_fy2025_01 <origin.pdf> <out_dir>
Writes <out_dir>/{kan-summary-revenue,kan-summary-expenditure-purpose,
kan-summary-expenditure-nature}.parquet and prints per-table sha256+rows.
"""
from __future__ import annotations
import hashlib, json, subprocess, sys
from pathlib import Path

import duckdb

from .decoder import decode, W  # reuse the reviewed decoder

DEFAULT_META = json.loads((Path(__file__).with_name('config.json')).read_text())


def build(origin_pdf: Path, out_dir: Path, meta: dict | None = None):
    digest = hashlib.sha256(origin_pdf.read_bytes()).hexdigest()
    if digest!='dafed3c8b026ea1c7681aee3d464cc27b0b19287287be7bbc0812f51fb461b5b' or origin_pdf.stat().st_size!=94147:
        raise ValueError('Finite FY2025 No.1 origin identity differs')
    xhtml = subprocess.run(['pdftotext', '-bbox', str(origin_pdf), '-'],
                           check=True, capture_output=True).stdout.decode('utf-8')
    # persist the bbox word layer as extraction evidence, then decode it
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'origin.bbox.xhtml').write_text(xhtml)
    xhtml_path = str(out_dir / 'origin.bbox.xhtml')
    meta = {**DEFAULT_META, **(meta or {})}
    meta = dict(meta, sha256=digest, bytes=origin_pdf.stat().st_size,
                url=meta.get('url', ''), fiscal_year=meta.get('fiscal_year', 2025),
                amendment=meta.get('amendment', 1), file=meta['file'], xhtml=xhtml_path)
    rows = decode(meta)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for seq, dire, tid in ((1, 'revenue', 'kan-summary-revenue'),
                           (2, 'expenditure', 'kan-summary-expenditure-purpose'),
                           (3, 'expenditure', 'kan-summary-expenditure-nature')):
        fin = [r for r in rows if r['role'] == 'kan_summary' and not r['annex']
               and r['direction'] == dire and r['section_index'] == seq]
        fields = ['source_row_id', 'fiscal_year', 'account_id', 'amendment_number', 'direction',
                  'classification', 'section_index', 'section_variant', 'kan_code', 'kan_name',
                  'amount_change', 'budget_before', 'budget_after', 'unit', 'physical_page',
                  'bbox_xmin', 'bbox_ymin', 'bbox_xmax', 'bbox_ymax', 'raw_line',
                  'original_url', 'original_sha256', 'source_table_id', 'source_row_ordinal',
                  'additive_scope', 'canonical_comparable']
        pr = []
        for i, r in enumerate(fin):
            d = dict(r, amount_change=r['amount_delta'],
                     section_variant=(r['direction'] + '-summary' + ('' if not r['classification'] else '-' + r['classification'])),
                     source_row_ordinal=i + 1, additive_scope='section', canonical_comparable=False)
            pr.append({f: d.get(f) for f in fields})
        db = duckdb.connect()
        cols = ','.join(f'"{f}" ' + ('integer' if f in
                        ('fiscal_year', 'amendment_number', 'amount_change', 'budget_before',
                         'budget_after', 'section_index', 'physical_page', 'source_row_ordinal')
                        else 'double' if f.startswith('bbox_') else 'varchar') for f in fields)
        db.execute('create table t (' + cols + ')')
        db.executemany('insert into t values (' + ','.join('?' * len(fields)) + ')',
                       [[r[f] for f in fields] for r in pr])
        out = out_dir / f'{tid}.parquet'
        db.execute(f"copy t to '{out}' (format parquet)"); db.close()
        results[tid] = dict(rows=len(pr), sha256=hashlib.sha256(out.read_bytes()).hexdigest(),
                            delta_sum=sum(r['amount_change'] or 0 for r in pr))
    print(json.dumps(results, indent=1))
    return results


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path(sys.argv[2]))
