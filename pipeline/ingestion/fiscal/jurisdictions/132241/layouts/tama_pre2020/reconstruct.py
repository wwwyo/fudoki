"""Reconstruct fixed pre-FY2020 Tama observation partitions from immutable originals only.

Reads original document bytes from the content-addressed input object cache
(default: ingestion.inputs.OBJECTS) and Git-declared evidence files beside this
module. Never touches the network, a mutable official URL, or any former
.agent recovery directory. Produces one raw partition per (original, table_id)
plus a whole-table readback for review.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import duckdb

DIRECTORY = Path(__file__).resolve().parent
NAMESPACE = 'tama-pre2020'

COMMON = [("source_url", "VARCHAR"), ("origin_sha256", "VARCHAR"), ("source_ordinal", "BIGINT")]
LEXICAL_EXTRA = [("physical_line_start", "BIGINT"), ("physical_line_end", "BIGINT"),
                 ("byte_start", "BIGINT"), ("byte_end", "BIGINT"), ("raw_lexical_record", "VARCHAR"),
                 ("original_cells_json", "VARCHAR"), ("observed_column_count", "BIGINT"),
                 ("role", "VARCHAR"), ("encoding", "VARCHAR")]
CONTROL_EXTRA = [("source_column_ordinal", "BIGINT"), ("printed_year", "VARCHAR"), ("fiscal_year", "BIGINT"),
                 ("printed_account", "VARCHAR"), ("printed_value", "VARCHAR"), ("cell_present", "BOOLEAN"),
                 ("observed_amount", "BIGINT"), ("declared_source_unit", "VARCHAR"), ("unit_multiplier", "BIGINT"),
                 ("amount_kind", "VARCHAR"), ("direction", "VARCHAR"), ("role", "VARCHAR"), ("unit_evidence_url", "VARCHAR")]
WORD_EXTRA = [("physical_page", "BIGINT"), ("printed_word", "VARCHAR"), ("x_min", "DOUBLE"), ("y_min", "DOUBLE"),
              ("x_max", "DOUBLE"), ("y_max", "DOUBLE"), ("direction", "VARCHAR"), ("phase", "VARCHAR"),
              ("source_unit", "VARCHAR"), ("observed_amount", "BIGINT"), ("role", "VARCHAR")]
PAGE_EXTRA = [("physical_page", "BIGINT"), ("width", "DOUBLE"), ("height", "DOUBLE"), ("word_count", "BIGINT"),
              ("printed_page_candidates_json", "VARCHAR"), ("printed_year_words_json", "VARCHAR"),
              ("unit_words_json", "VARCHAR"), ("original_words_json", "VARCHAR"), ("direction", "VARCHAR"),
              ("phase", "VARCHAR"), ("source_unit", "VARCHAR"), ("observed_amount", "BIGINT"), ("role", "VARCHAR")]
# Only the three source-named account-total tables have a monetary role.
MONEY_FILES = {'R6.01tousyoyosan.csv': ('initial-budget-observed-approval-unconfirmed', None),
               'R6.02sainyuukessa.csv': ('executed', 'revenue'),
               'R6.03saisyutsukessan.csv': ('executed', 'expenditure')}
UNIT_EVIDENCE_URL = 'https://www.city.tama.lg.jp/shisei/zaisei/zaisei/1004885.html'


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def load_manifest() -> dict:
    return json.loads((DIRECTORY / 'evidence-manifest.json').read_text())


def origin_bytes(cache_dir: Path, sha: str, expected_bytes: int) -> bytes:
    path = cache_dir / 'inputs/origin/sha256' / sha
    if not path.is_file():
        raise FileNotFoundError('Immutable original unavailable: ' + sha)
    body = path.read_bytes()
    if digest(body) != sha or len(body) != expected_bytes:
        raise ValueError('Immutable original SHA/byte mismatch: ' + sha)
    return body


def csv_lexical(url: str, sha: str, body: bytes):
    text = body.decode('cp932', errors='strict')
    if text.encode('cp932') != body:
        raise ValueError('encoding roundtrip mismatch')
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode('cp932')))
    reader = csv.reader(io.StringIO(text, newline=''))
    lexical, source_rows, previous, header = [], [], 0, None
    for ordinal, cells in enumerate(reader, 1):
        start, end = previous, reader.line_num
        raw = ''.join(lines[start:end])
        previous = end
        if header is None:
            header = cells
        source_rows.append(cells)
        lexical.append([url, sha, ordinal, start + 1, end, offsets[start], offsets[end], raw,
                        json.dumps(cells, ensure_ascii=False), len(cells),
                        'header' if ordinal == 1 else 'reference-original-row', 'cp932'])
    width = max(map(len, source_rows))
    columns = COMMON + LEXICAL_EXTRA + [(f"original_column_{n:03d}", "VARCHAR") for n in range(1, width + 1)]
    rows = [base + cells + [None] * (width - len(cells)) for base, cells in zip(lexical, source_rows)]
    controls = []
    kind = MONEY_FILES.get(url.rsplit('/', 1)[-1])
    if kind:
        amount_kind, direction = kind
        for rowno, cells in enumerate(source_rows[1:], 2):
            year = {'H29': 2017, 'H30': 2018, 'R1': 2019}.get(cells[0])
            if year is None:
                continue
            for colno, label in enumerate(header[1:], 2):
                lexeme = cells[colno - 1] if colno <= len(cells) else None
                numeric = int(lexeme.replace(',', '')) if lexeme and re.fullmatch(r'-?[0-9,]+', lexeme) else None
                controls.append([url, sha, rowno, colno, cells[0], year, label, lexeme, colno <= len(cells),
                                 numeric, '千円', 1000, amount_kind, direction,
                                 'nonadditive-account-reference-control', UNIT_EVIDENCE_URL])
    return columns, rows, controls


def pdf_observations(url: str, sha: str, body: bytes, work: Path):
    with tempfile.NamedTemporaryFile(suffix='.pdf', dir=work, delete=False) as tmp:
        tmp.write(body)
        pdf = Path(tmp.name)
    xml = pdf.with_suffix('.xml')
    subprocess.run(['pdftotext', '-bbox-layout', str(pdf), str(xml)],
                   capture_output=True, check=True)
    pages = [e for e in ET.parse(xml).iter() if e.tag.endswith('page')]
    word_rows, page_rows, page_words = [], [], []
    for n, page in enumerate(pages, 1):
        words = []
        for k, e in enumerate([e for e in page.iter() if e.tag.endswith('word')], 1):
            box = [float(e.attrib[a]) for a in ['xMin', 'yMin', 'xMax', 'yMax']]
            text = e.text or ''
            words.append({'source_word_ordinal': k, 'bbox': box, 'text': text})
            word_rows.append([url, sha, k, n, text, *box, None, None, None, None,
                              'positioned-original-text-layer-observation'])
        page_words.append(words)
        width, height = float(page.attrib['width']), float(page.attrib['height'])
        footer = [w for w in words if w['bbox'][1] > height * .9 and re.fullmatch(r'[0-9]+', w['text'])]
        units = [w for w in words if any(t in w['text'] for t in ['円', '千円', '単位'])]
        year_words = [w for w in words if '年度' in w['text']]
        page_rows.append([url, sha, n, n, width, height, len(words), json.dumps(footer, ensure_ascii=False),
                          json.dumps(year_words, ensure_ascii=False), json.dumps(units, ensure_ascii=False),
                          json.dumps(words, ensure_ascii=False), None, None, None, None,
                          'whole-physical-page-observation'])
    return word_rows, page_rows, page_words


HEALTH_FIELDS = ['initial_budget', 'september_amendment', 'december_amendment', 'march_amendment',
                 'transfer', 'budget_current', 'executed_yen', 'executed_thousand_yen',
                 'prior_year_reference', 'change_percent']


def health_rows(url: str, sha: str, grid: dict, words: list):
    rows = []
    source_ordinal = 0
    for panel in grid['panels']:
        e = panel['edges']
        anchors = [w for w in words if e[1] <= w['bbox'][0] < e[2] and w['bbox'][1] >= grid['start_y']
                   and re.fullmatch('[0-9,]+', w['text'])]
        for a in sorted(anchors, key=lambda w: w['bbox'][1]):
            y = a['bbox'][1]
            selected = [w for w in words if e[0] <= w['bbox'][0] < e[-1] and y - 1.6 <= w['bbox'][1] < y + grid['step'] / 2]
            labelwords = sorted([w for w in selected if w['bbox'][0] < e[1]], key=lambda w: w['bbox'][0])
            if not labelwords:
                raise ValueError('row missing original label')
            label = ' '.join(w['text'] for w in labelwords)
            code = next((w for w in labelwords if re.fullmatch('[0-9０-９]+', w['text'])), None)
            level = None
            if code:
                for i in range(4):
                    if panel['code_edges'][i] <= code['bbox'][0] < panel['code_edges'][i + 1]:
                        level = ['kan-control', 'kou-control', 'moku-observation',
                                 'printed-sub-moku-or-reference'][i]
            if not level:
                level = 'account-control' if '合 計' in label or '予備費を除いた額' in label else 'unconfirmed-original-row'
            cells, amounts = {}, {}
            for i, f in enumerate(HEALTH_FIELDS, 1):
                cell = [w for w in selected if e[i] <= w['bbox'][0] < e[i + 1]]
                printed = ' '.join(w['text'] for w in sorted(cell, key=lambda w: w['bbox'][0])) if cell else None
                cells[f] = {'printed': printed, 'words': cell,
                            'unit': '円' if f == 'executed_yen' else '%' if f == 'change_percent' else '千円',
                            'amount_kind': 'executed' if f.startswith('executed_') else
                            'prior-year-executed-reference' if f == 'prior_year_reference' else 'printed-other-control-field'}
                amounts[f] = int(printed.replace(',', '')) if printed is not None and re.fullmatch('-?[0-9,]+', printed) else None
            box = [min(w['bbox'][0] for w in selected), min(w['bbox'][1] for w in selected),
                   max(w['bbox'][2] for w in selected), max(w['bbox'][3] for w in selected)]
            source_ordinal += 1
            rows.append(dict(observed_id=sha + ':p1:' + panel['label'] + ':y' + format(y, '.6f'),
                             source_url=url, origin_sha256=sha, fiscal_year=grid['fiscal_year'],
                             printed_account='多摩市国民健康保険特別会計', physical_page=1, printed_page=None,
                             panel=panel['label'], source_ordinal=source_ordinal, printed_row_label=label,
                             printed_code=code['text'] if code else None, observed_grain=level,
                             original_cells_json=json.dumps(cells, ensure_ascii=False),
                             original_words_json=json.dumps(selected, ensure_ascii=False),
                             bbox_json=json.dumps(box),
                             printed_executed_yen=cells['executed_yen']['printed'], executed_yen=amounts['executed_yen'],
                             printed_executed_thousand_yen=cells['executed_thousand_yen']['printed'],
                             executed_thousand_yen=amounts['executed_thousand_yen'],
                             printed_budget_current=cells['budget_current']['printed'],
                             budget_current_thousand_yen=amounts['budget_current'],
                             printed_initial_budget=cells['initial_budget']['printed'],
                             initial_budget_thousand_yen=amounts['initial_budget'],
                             amount_phase='executed', source_unit='円', unit_multiplier=1,
                             recognition_status='unconfirmed', legal_setsu_id=None,
                             project_setsu_relationship='unconfirmed',
                             **{f'printed_{f}': cells[f]['printed'] for f in HEALTH_FIELDS
                                if f not in ['executed_yen', 'executed_thousand_yen', 'budget_current', 'initial_budget']}))
    return rows


def health_columns(rows):
    return {k: ('BIGINT' if k in ['fiscal_year', 'physical_page', 'printed_page', 'source_ordinal',
                                  'executed_yen', 'executed_thousand_yen', 'budget_current_thousand_yen',
                                  'initial_budget_thousand_yen', 'unit_multiplier'] else 'VARCHAR')
            for k in rows[0]}


def write_table(con, name, columns, rows, out: Path):
    con.execute('CREATE TABLE "' + name + '" (' + ','.join('"' + n + '" ' + t for n, t in columns) + ')')
    if rows:
        con.executemany('INSERT INTO "' + name + '" VALUES (' + ','.join('?' for _ in columns) + ')',
                        rows)
    con.execute('COPY "' + name + '" TO ? (FORMAT PARQUET)', [str(out)])
    got = [tuple(x) for x in con.execute('SELECT * FROM read_parquet(?)', [str(out)]).fetchall()]
    if got != [tuple(x) for x in rows]:
        raise ValueError('every-field readback mismatch ' + name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--partition-output', type=Path, required=True)
    try:
        from ingestion.inputs import OBJECTS
        default_cache = OBJECTS
    except Exception:
        default_cache = None
    parser.add_argument('--cache-dir', type=Path, required=default_cache is None, default=default_cache)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.partition_output.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    originals = {o['sha256']: o for o in manifest['originals']}
    grids = {g['sha']: dict(g, fiscal_year=g['year']) for g in json.loads((DIRECTORY / 'health-grid-declarations.json').read_text())}
    con = duckdb.connect(':memory:')
    partitions, merged = [], collections.defaultdict(list)
    with tempfile.TemporaryDirectory() as work:
        for sha, o in sorted(originals.items()):
            body = origin_bytes(args.cache_dir, sha, o['bytes'])
            url = o['url']
            if o['ext'] == 'csv':
                columns, rows, controls = csv_lexical(url, sha, body)
                stem = o['stem']
                parts = [(f'csv-lexical-{stem}', 'csv-lexical-original-rows', columns, rows)]
                if controls:
                    parts.append(('account-reference-controls', 'nonadditive-account-reference-control',
                                  COMMON + CONTROL_EXTRA, controls))
            else:
                word_rows, page_rows, page_words = pdf_observations(url, sha, body, Path(work))
                parts = [('pdf-word-observations', 'positioned-original-text-layer-observation',
                          COMMON + WORD_EXTRA, word_rows),
                         ('pdf-page-observations', 'whole-physical-page-observation',
                          COMMON + PAGE_EXTRA, page_rows)]
                if sha in grids:
                    hrows = health_rows(url, sha, grids[sha], page_words[0])
                    cols = [(k, t) for k, t in health_columns(hrows).items()]
                    parts.append(('health-expenditure-rows', 'health-expenditure-original-rows', cols,
                                  [[r[c[0]] for c in cols] for r in hrows]))
            for table_id, role, columns, rows in parts:
                name = table_id.replace('-', '_')
                target = args.partition_output / sha
                target.mkdir(exist_ok=True)
                out = target / (table_id + '.parquet')
                write_table(con, name + '_' + sha[:8], columns, rows, out)
                body2 = out.read_bytes()
                partitions.append({'origin_sha256': sha, 'url': url, 'table_id': table_id, 'role': role,
                                   'rows': len(rows), 'bytes': len(body2), 'sha256': digest(body2),
                                   'schema': [{'name': c[0], 'type': c[1]} for c in columns],
                                   'path': str(out)})
                merged[table_id if table_id.startswith('csv-lexical') else role].extend(rows)
    result = {'status': 'private-proposal-only', 'canonical_adoption': False, 'r2_uploaded': False,
              'partition_count': len(partitions), 'partitions': partitions,
              'merged_table_rows': {k: len(v) for k, v in sorted(merged.items())}}
    (args.partition_output / 'partition-readback.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (args.output / 'reconstruction-readback.json').write_text(json.dumps(
        {'origins': len(originals), 'partitions': len(partitions),
         'roles': dict(collections.Counter(p['role'] for p in partitions)),
         'all_fields_exact_readback': True}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'partitions': len(partitions), 'merged': result['merged_table_rows']}))


if __name__ == '__main__':
    main()
