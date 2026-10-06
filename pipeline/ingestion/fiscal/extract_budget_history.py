"""狛江市の当初・補正PDFから目の金額を読み、採用資料を固定する。"""
from __future__ import annotations
from ingestion.inputs import record_input

import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path

import duckdb

from ingestion.fiscal.sources import load_budget_history
from ingestion.inputs import encode
from ingestion.lib.http import http_get
from ingestion.lib.pdf import chars_of, rows_of
from ingestion.paths import CACHE

RAW = Path(os.environ.get("FUDOKI_INPUT_DIR", CACHE / "acquisition/budget-history/raw"))

VERSION = 2
TARGETS = {(7, 1, 2): '商工業振興費', (13, 1, 1): '予備費'}
COLUMNS = {'source_row': 'BIGINT', 'record_kind': 'VARCHAR', 'fund_code': 'VARCHAR',
           'fund_label': 'VARCHAR', 'kan_code': 'VARCHAR', 'kou_code': 'VARCHAR',
           'moku_code': 'VARCHAR', 'moku_label': 'VARCHAR', 'initial_text': 'VARCHAR',
           'before_text': 'VARCHAR', 'delta_text': 'VARCHAR', 'after_text': 'VARCHAR',
           'reported_amount_text': 'VARCHAR', 'executed_amount_text': 'VARCHAR',
           'page_number': 'BIGINT', 'bbox_json': 'VARCHAR', 'printed_text': 'VARCHAR'}


def normalize(text: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def amount(text: str) -> int:
    value = normalize(text).replace(',', '').replace('△', '-')
    if not re.fullmatch(r'-?\d+', value):
        raise ValueError(f'Invalid printed amount: {text!r}')
    return int(value)


def extract(pdf: Path, number: int, target_pages: list[int] | None = None, *,
            all_moku: bool = False, fiscal_year: int | None = None,
            fund_label: str = '一般会計', fund_code: str | None = None,
            source_url: str | None = None, expected_sha256: str | None = None,
            first_page: int = 1, last_page: int | None = None) -> list[dict]:
    """目欄の金額を抽出する。節・説明欄の反復印字を加算しない。"""
    if all_moku:
        from ingestion.fiscal.history_expansion import extract_document
        if fiscal_year is None:
            raise ValueError('all_moku requires the explicitly declared fiscal_year')
        return extract_document(pdf, number, fiscal_year=fiscal_year,
            fund_label=fund_label, fund_code=fund_code, source_url=source_url,
            expected_sha256=expected_sha256, first_page=first_page, last_page=last_page)['rows']
    if first_page != 1 or last_page is not None:
        raise ValueError('PDF page range requires all_moku=True')
    if fiscal_year is not None or fund_label != '一般会計' or any(
            value is not None for value in [fund_code, source_url, expected_sha256]):
        raise ValueError('Expansion document options require all_moku=True')
    records = []
    kan = kou = None
    expenditure = number == 0
    for page_number, chars in enumerate(chars_of(pdf, 1, 9999), 1):
        bands = []
        for y in sorted({y for _, y, _ in chars}):
            if not bands or y - bands[-1][-1] > 1:
                bands.append([])
            bands[-1].append(y)
        page_rows = rows_of(chars)
        for row_index, (row, ys) in enumerate(zip(page_rows, bands, strict=True)):
            whole = normalize(''.join(c for _, c in sorted(row)))
            if re.match(r'3[.．]歳出', whole):
                expenditure = True
                kan = kou = None
            if '給与費明細書' in whole:
                expenditure = False
            heading = re.search(r'\(款\)(\d+)[.．]', whole)
            if heading:
                kan = int(heading[1]); kou = None
            heading = re.search(r'\(項\)(\d+)[.．]', whole)
            if heading:
                kou = int(heading[1])
            cells = [normalize(''.join(c for x, c in sorted(row) if lo <= x < hi))
                     for lo, hi in [(0, 110), (110, 160), (160, 215), (215, 270)]]
            moku = re.fullmatch(r'(\d+)\.(.+)', cells[0])
            if not expenditure or not moku or not all(re.fullmatch(r'[△\-]?\d[\d,]*', s) for s in cells[1:]):
                continue
            if number == 0:
                if page_number not in (target_pages or []):
                    continue
                code = int(moku[1])
                if (kan, kou, code) not in TARGETS:
                    continue
            else:
                if kan is None or kou is None:
                    continue
                code = int(moku[1])
            values = [amount(v) for v in cells[1:]]
            if number and values[0] + values[1] != values[2]:
                raise ValueError(f'{number}:{page_number}:{cells}: before + delta != after')
            label = TARGETS.get((kan, kou, code), moku[2])
            if (kan, kou, code) in TARGETS:
                continuation = ''.join(c for x, c in sorted(page_rows[row_index + 1]) if x < 110) if row_index + 1 < len(page_rows) else ''
                printed_label = normalize(moku[2] + continuation)
                if not (label == moku[2] or printed_label == label):
                    raise ValueError(f'Target label differs from printed moku: {printed_label}')
            records.append(dict(source_row=len(records) + 1, record_kind='initial' if number == 0 else 'change',
                fund_code='1', fund_label='一般会計', kan_code=str(kan), kou_code=str(kou),
                moku_code=str(code), moku_label=label, initial_text=cells[1] if number == 0 else None,
                before_text=cells[1] if number else None, delta_text=cells[2] if number else None,
                after_text=cells[3] if number else None, page_number=page_number,
                bbox_json=json.dumps([min(x for x, _ in row), min(ys), 270, max(ys) + 12]),
                printed_text=whole))
    if number:
        header = ''.join(normalize(''.join(c for _, c in sorted(row))) for row in rows_of(next(chars_of(pdf, 2, 2))))
        total = re.search(r'第1条歳入歳出予算の総額[にから]+歳入歳出それぞれ([\d,]+)千円を(追加|減額)', header)
        if not total or f'一般会計補正予算(第{number}号)' not in header:
            raise ValueError('Declared issue or first-article amount not found')
        printed_delta = amount(total[1]) * (-1 if total[2] == '減額' else 1)
        if sum(amount(row['delta_text']) for row in records) != printed_delta:
            raise ValueError('Sum of extracted moku deltas differs from first-article expenditure delta')
    if not records:
        raise ValueError(f'Document {number} yielded no financial rows')
    return records


def approval(pdf: Path, document: dict) -> dict:
    """議案番号・号数・原案可決・議決日を同じ表の行集合で確認する。"""
    month, day = map(int, document['effective_at'].split('-')[1:])
    for page, chars in enumerate(chars_of(pdf, 1, 9999), 1):
        lines = [normalize(''.join(c for _, c in sorted(row))) for row in rows_of(chars)]
        for index, line in enumerate(lines):
            if f'議案第{document["bill_number"]}号' not in line:
                continue
            block = ''.join(lines[max(0, index - 1):index + 2])
            if all(value in block for value in ['令和5年度狛江市一般会計補正予算',
                                               f'(第{document["amendment_number"]}号)']) and all(
                    value in line for value in [f'{month}月{day}日', '原案可決']):
                return dict(source_row=1, record_kind='approval', page_number=page,
                            printed_text=block, bbox_json='[]')
    raise ValueError(f'Approval date or bill not verified: {document}')


def write_table(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute('create table t (' + ','.join(f'{k} {v}' for k, v in COLUMNS.items()) + ')')
    if records:
        connection.executemany('insert into t values (' + ','.join('?' for _ in COLUMNS) + ')',
                               [[record.get(k) for k in COLUMNS] for record in records])
    connection.execute('copy (select * from t order by source_row) to ? (format parquet, compression zstd)', [str(path)])
    connection.close()


def ingest(key: str) -> None:
    spec = load_budget_history()[key]
    code, year = key.split(':')
    if sorted(d['amendment_number'] for d in spec['documents']) != list(range(8)):
        raise ValueError('Initial budget and all seven supplementary issues must be declared once')
    for document in spec['documents']:
        got = http_get(document['url'])
        if got.sha256 != document['expected_sha256']:
            raise ValueError('Re-published document requires an explicit adoption decision')
        number = document['amendment_number']
        with tempfile.NamedTemporaryFile(suffix='.pdf') as temporary:
            temporary.write(got.body); temporary.flush()
            rows = extract(Path(temporary.name), number, document.get('target_pages'))
        checked = None
        if number:
            decision = http_get(document['approval_url'])
            if decision.sha256 != document['approval_sha256']:
                raise ValueError('Approval edition differs from declaration')
            with tempfile.NamedTemporaryFile(suffix='.pdf') as temporary:
                temporary.write(decision.body); temporary.flush()
                checked = approval(Path(temporary.name), document)
            _save(code, year, 'supplementary', 'approval', decision, [checked], spec, document)
        _save(code, year, 'budget' if number == 0 else 'supplementary', spec['table_id'], got, rows, spec, document,
              approval_evidence=checked)
        print(f'{key}:{number}: {len(rows)} moku rows')
    reported = spec['reported']
    got = http_get(reported['url'])
    if got.sha256 != reported['expected_sha256']:
        raise ValueError('Manually reviewed settlement edition changed')
    rows = [dict(row, source_row=i + 1, record_kind='reported', fund_code=spec['fund_code'],
                 fund_label=spec['fund_label'], printed_text=reported['method'])
            for i, row in enumerate(reported['rows'])]
    _save(code, year, 'settlement', 'reported-budget', got, rows,
          {**spec, 'source_amount_unit': '円'}, dict(amendment_number=0,
          effective_at='2024-03-31', effective_basis='年度末の報告予算現額'))


def _save(code, year, kind, table, got, rows, spec, document, approval_evidence=None):
    directory = RAW / f'jurisdiction={code}/year={year}/document_kind={kind}/edition={got.sha256}/direction=expenditure/resource={table}'
    # 同じ議決結果PDFに複数号が載るため、議決表は号ごとに区別する。
    if table == 'approval':
        directory = directory.with_name(f'resource=approval-{document["amendment_number"]}')
        table = f'approval-{document["amendment_number"]}'
    write_table(directory / 'data.parquet', rows)
    if table == 'reported-budget':
        document_title = '歳入歳出決算書'
    elif kind == 'budget':
        document_title = '当初予算書'
    elif table == spec['table_id']:
        document_title = f'補正予算書 第{document["amendment_number"]}号'
    else:
        document_title = '議案審査結果'

    if table == 'reported-budget':
        verification = 'manual-page-review; dbt compares settlement CSV totals'
    elif kind != 'budget' and table == spec['table_id']:
        verification = 'before-plus-delta-equals-after; all-moku-deltas-equal-first-article'
    elif table.startswith('approval-'):
        verification = 'bill-number-date-and-approved-text'
    else:
        verification = 'declared-target-and-printed-amount'
    prov = dict(jurisdiction_code=code, fiscal_year=int(year), direction='expenditure',
        document_kind=kind, amendment_number=document['amendment_number'], table_id=table,
        effective_at=document['effective_at'], effective_basis='議案の原案可決日。別適用日の指定なし' if document['amendment_number'] else document['effective_basis'],
        approval_evidence=approval_evidence, approval_url=document.get('approval_url'), approval_sha256=document.get('approval_sha256'),
        request_url=got.url, status=got.status, bytes=len(got.body), sha256=got.sha256,
        fetched_at=got.fetched_at, document_title='令和5年度狛江市一般会計 ' + document_title,
        dataset_title=None, resource_name=table, landing_page=spec['landing_page'], rows=len(rows),
        pages=[min(r['page_number'] for r in rows), max(r['page_number'] for r in rows)],
        header=list(COLUMNS), raw_form='extracted', roundtrip_verified=False,
        verification=verification,
        source_amount_unit=spec['source_amount_unit'], extractor=f'pipeline/ingestion/fiscal/extract_budget_history.py@{VERSION}',
        normalization=['NFKCと空白除去。桁区切りと△符号は保持'],
        **{k:spec[k] for k in ['redistribute','redistribute_basis','license_id','attribution']})
    record_input(directory, prov)


def main() -> None:
    import argparse
    import subprocess
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['pilot', 'all-moku'], default='pilot',
        help='pilot preserves frozen input IDs; all-moku writes isolated supplementary candidates')
    parser.add_argument('--describe', action='store_true', help='Print the all-moku input/output schema as JSON')
    parser.add_argument('--pdf', type=Path)
    parser.add_argument('--fiscal-year', type=int)
    parser.add_argument('--amendment-number', type=int)
    parser.add_argument('--fund-label', default='一般会計')
    parser.add_argument('--fund-code', help='Optional declared code; omitted codes are not invented')
    parser.add_argument('--source-url')
    parser.add_argument('--expected-sha256')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--first-page', type=int, default=1, help='First physical PDF page of an observed account edition')
    parser.add_argument('--last-page', type=int, help='Last physical PDF page; preserve original PDF SHA and page numbers')
    args = parser.parse_args()
    if args.describe:
        from ingestion.fiscal.history_expansion import COLUMNS, TABLE_ID
        print(json.dumps(dict(mode='all-moku', table_id=TABLE_ID,
            required=['pdf', 'fiscal_year', 'amendment_number', 'source_url', 'expected_sha256', 'output_dir'],
            optional=['fund_label', 'fund_code', 'first_page', 'last_page'],
            defaults=dict(fund_label='一般会計', fund_code=None, first_page=1, last_page=None),
            columns=COLUMNS, grain='changed expenditure moku', source_amount_unit='千円',
            approval='explicit cover-approved or unconfirmed; not inferred from file date'), ensure_ascii=False))
        return
    if args.mode == 'pilot':
        if any(value is not None for value in [args.pdf, args.fiscal_year, args.amendment_number,
                args.output_dir, args.source_url, args.expected_sha256, args.fund_code]) or args.fund_label != '一般会計':
            parser.error('document options require --mode all-moku')
        if args.first_page != 1 or args.last_page is not None:
            parser.error('page range requires --mode all-moku')
        for key in load_budget_history():
            ingest(key)
        return
    if any(value is None for value in [args.pdf, args.fiscal_year, args.amendment_number,
            args.output_dir, args.source_url, args.expected_sha256]):
        parser.error('all-moku requires --pdf, --fiscal-year, --amendment-number, --source-url, --expected-sha256, --output-dir')
    if not re.fullmatch(r'[0-9a-f]{64}', args.expected_sha256):
        parser.error('--expected-sha256 must be a lowercase 64-character SHA256')
    if not args.source_url.startswith('https://www.city.komae.tokyo.jp/') or any(ord(c) < 32 for c in args.source_url):
        parser.error('--source-url must be an official Komae HTTPS URL')
    output = args.output_dir.resolve()
    isolated = Path(__file__).resolve().parents[3] / '.agent'
    if not output.is_relative_to(isolated.resolve()):
        parser.error('--output-dir must be inside the repository .agent/ candidate area')
    from ingestion.fiscal.history_expansion import extract_document, materialize
    try:
        result = extract_document(args.pdf, args.amendment_number,
            fiscal_year=args.fiscal_year, fund_label=args.fund_label, fund_code=args.fund_code,
            source_url=args.source_url, expected_sha256=args.expected_sha256,
            first_page=args.first_page, last_page=args.last_page)
        evidence = materialize(output, result, request_url=args.source_url)
    except (ValueError, OSError, subprocess.CalledProcessError, duckdb.Error) as error:
        parser.exit(1, json.dumps(dict(status='error', error=str(error))) + '\n')
    print(json.dumps(dict(status='candidate-materialized', output_dir=str(output),
        rows=evidence['rows'], first_article=evidence['first_article'],
        approval_status=evidence['approval_status']), ensure_ascii=False))


if __name__ == '__main__':
    main()
