"""Explicit, isolated extraction of changed Komae expenditure moku.

This schema is separate from the frozen FY2023 pilot. A moku is never
allocated to explanation projects or setsu; only printed triples are emitted.
"""
from __future__ import annotations
from ingestion.inputs import record_input

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import duckdb

from ingestion.lib.pdf import chars_of, rows_of

VERSION = 1
TABLE_ID = 'expenditure-moku-changes-all'
COLUMNS = {
    'source_row': 'BIGINT', 'record_kind': 'VARCHAR',
    'fund_code': 'VARCHAR', 'fund_label': 'VARCHAR',
    'kan_code': 'VARCHAR', 'kou_code': 'VARCHAR', 'moku_code': 'VARCHAR',
    'moku_label': 'VARCHAR', 'before_text': 'VARCHAR', 'delta_text': 'VARCHAR',
    'after_text': 'VARCHAR', 'amount_before': 'BIGINT', 'amount_delta': 'BIGINT',
    'amount_after': 'BIGINT', 'page_number': 'BIGINT', 'bbox_json': 'VARCHAR',
    'amount_bboxes_json': 'VARCHAR', 'printed_text': 'VARCHAR',
    'printed_label_text': 'VARCHAR', 'printed_amounts_json': 'VARCHAR', 'fiscal_year': 'BIGINT',
    'unit_evidence_json': 'VARCHAR',
    'amendment_number': 'BIGINT', 'source_amount_unit': 'VARCHAR',
    'source_url': 'VARCHAR', 'source_sha256': 'VARCHAR',
}
AMOUNT = r'[△\-]?\d[\d,]*'
# Measured expenditure columns of the standalone Komae supplementary books.
BOUNDS = [(0, 110), (110, 160), (160, 215), (215, 270)]


def _norm(text: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def _amount(text: str) -> int:
    value = _norm(text).replace(',', '').replace('△', '-')
    if not re.fullmatch(r'-?\d+', value):
        raise ValueError(f'Invalid printed amount: {text!r}')
    return int(value)


def _text(row, lo=0, hi=float('inf')) -> str:
    return ''.join(c for x, c in sorted(row) if lo <= x < hi)


def _box(row, lo, hi):
    selected = [x for x, _ in row if lo <= x < hi]
    if not selected:
        return None
    return [min(selected), min(row.ys), max(selected) + 6, max(row.ys) + 12]


def extract_document(pdf: Path, number: int, *, fiscal_year: int,
                     fund_label: str, fund_code: str | None = None,
                     source_url: str | None = None,
                     expected_sha256: str | None = None,
                     first_page: int = 1, last_page: int | None = None) -> dict:
    """Return changed rows plus independent printed total and edition evidence.

    Fail closed on unsupported layouts, wrong edition identity, missing totals,
    duplicate moku, arithmetic failures, or incomplete extraction. Approval is
    a separate status: proposal amounts are never labelled approved implicitly.
    """
    if number < 1:
        raise ValueError('all-moku mode supports supplementary changed rows only')
    if not 2019 <= fiscal_year <= 2099:
        raise ValueError('Unsupported fiscal year (only Reiwa editions supported)')
    if first_page < 1 or (last_page is not None and last_page < first_page):
        raise ValueError('Invalid PDF page range')
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if expected_sha256 and sha != expected_sha256:
        raise ValueError('PDF SHA differs from the requested edition')
    pages = [rows_of(chars) for chars in chars_of(pdf, first_page, last_page or 9999)]
    if len(pages) < 2:
        raise ValueError('No standalone budget book: fewer than two pages')
    cover = ''.join(_norm(_text(row)) for row in pages[0])
    title = f'令和{fiscal_year - 2018}年度狛江市{_norm(fund_label)}補正予算(第{number}号)'
    article_page = next((i for i in range(1, min(len(pages), 4))
        if title in ''.join(_norm(_text(row)) for row in pages[i])
        and '第1条' in ''.join(_norm(_text(row)) for row in pages[i])), None)
    if title not in cover or article_page is None:
        raise ValueError('Standalone year/account/issue title not verified on cover and article page')
    identities = set()
    for page in pages:
        text = ''.join(_norm(_text(row)) for row in page)
        identities.update(f'令和{year}年度狛江市{account}補正予算(第{issue}号)'
            for year, account, issue in re.findall(
                r'令和(\d+)年度狛江市(?:の)?([^()。、]+?会計)補正予算\(第(\d+)号\)', text))
    if identities != {title}:
        raise ValueError('Multiple account/year/issue editions: an explicit observed page range is required')
    header = ''.join(_norm(_text(row)) for row in pages[article_page])
    total = re.search(r'第1条歳入歳出予算の総額[にから]+[、,]?歳入歳出それぞれ([\d,]+)千円を(追加|減額)', header)
    if total:
        delta = _amount(total[1]) * (-1 if total[2] == '減額' else 1)
        total_text = total[0]
    elif '第1条歳入歳出予算の総額を、増減なしとし' in header:
        delta = 0
        total_text = '第1条歳入歳出予算の総額を、増減なしとし'
    else:
        raise ValueError('First-article expenditure delta absent (possibly carryover-only or enterprise-account amendment)')
    article_rows = [row for row in pages[article_page] if '第1条' in _norm(_text(row))]
    approval = re.search(r'令和(\d+)年(\d+)月(\d+)日原案可決', cover)
    approval_row = next((row for row in pages[0] if '原案可決' in _norm(_text(row))), None)
    effective_at = f'{2018 + int(approval[1]):04d}-{int(approval[2]):02d}-{int(approval[3]):02d}' if approval else None
    bill = re.search(r'議案第(\d+)号', cover)
    submitted = re.search(r'令和(\d+)年(\d+)月(\d+)日(提出|専決)', header)
    submitted_at = f'{2018 + int(submitted[1]):04d}-{int(submitted[2]):02d}-{int(submitted[3]):02d}' if submitted else None
    rows = []
    keys = set()
    kan = kou = None
    expenditure = False
    unit_evidence = None
    bounds = BOUNDS
    zero_rows = []
    for page_number, page_rows in enumerate(pages, first_page):
        for i, row in enumerate(page_rows):
            whole = _norm(_text(row))
            if re.match(r'3[.．]歳出', whole):
                expenditure = True
                kan = kou = None
                unit_evidence = None
                bounds = BOUNDS
                continue
            if re.match(r'2[.．]歳入', whole) or any(label in whole for label in
                    ['給与費明細書', '地方債の前前年度末', '債務負担行為で翌年度以降']):
                expenditure = False
            heading = re.search(r'\(款\)(\d+)[.．]', whole)
            if heading:
                kan, kou = int(heading[1]), None
            heading = re.search(r'\(項\)(\d+)[.．]', whole)
            if heading:
                kou = int(heading[1])
            # Council bundles include reduced, shifted copies of the same book.
            # Locate their three printed currency anchors before reading cells.
            if expenditure and re.fullmatch(r'(千円){3,}', whole):
                anchors = [x for x, c in sorted(row) if c == '千']
                if anchors[0] > 155:
                    scale = (anchors[1] - anchors[0]) / 53.7
                    if not 0.85 <= scale <= 1.05 or abs(anchors[2] - anchors[1] - (anchors[1] - anchors[0])) > 1:
                        raise ValueError(f'Unsupported amount-column currency anchors at page {page_number}')
                    transform = lambda x: anchors[0] + (x - 138.6) * scale
                    bounds = [(0, transform(110)), (transform(110), transform(160)),
                              (transform(160), transform(215)), (transform(215), transform(270))]
            cells = [_norm(_text(row, lo, hi)) for lo, hi in bounds]
            if expenditure and cells[1:] == ['千円'] * 3:
                unit_evidence = dict(page_number=page_number, printed_text=_text(row),
                    amount_bboxes=[_box(row, lo, hi) for lo, hi in bounds[1:]])
                if bounds != BOUNDS:
                    unit_evidence['column_bounds'] = bounds
            moku = re.fullmatch(r'(\d+)\.(.+)', cells[0])
            if not expenditure or not moku:
                continue
            if not all(re.fullmatch(AMOUNT, cell) for cell in cells[1:]):
                raise ValueError(f'Incomplete printed moku triple at page {page_number}: {cells}')
            if kan is None or kou is None:
                raise ValueError(f'Missing printed hierarchy at page {page_number}')
            if unit_evidence is None:
                raise ValueError(f'Printed amount-column units not verified at page {page_number}')
            before, change, after = map(_amount, cells[1:])
            if before + change != after:
                raise ValueError(f'before + delta != after at page {page_number}: {cells}')
            key = kan, kou, int(moku[1])
            if key in keys:
                raise ValueError(f'Duplicate printed moku (continuation unsupported): {key}')
            keys.add(key)
            label_parts = [_text(row, *bounds[0])]
            for following in page_rows[i + 1:]:
                continuation = _norm(_text(following, *bounds[0]))
                if not continuation:
                    break
                if not re.fullmatch(r'[一-龯ぁ-んァ-ヶー・及び]+', continuation) or continuation == '計':
                    break
                label_parts.append(_text(following, *bounds[0]))
            label = re.sub(r'^\d+\.', '', _norm(''.join(label_parts)))
            boxes = [_box(row, lo, hi) for lo, hi in bounds[1:]]
            if change == 0:
                zero_rows.append(dict(page_number=page_number, hierarchy=key, printed_values=cells[1:]))
                continue
            rows.append(dict(source_row=len(rows) + 1, record_kind='change',
                fund_code=fund_code, fund_label=fund_label, kan_code=str(kan),
                kou_code=str(kou), moku_code=moku[1], moku_label=label,
                before_text=cells[1], delta_text=cells[2], after_text=cells[3],
                amount_before=before, amount_delta=change, amount_after=after,
                page_number=page_number, bbox_json=json.dumps(_box(row, 0, bounds[-1][1])),
                amount_bboxes_json=json.dumps(dict(zip(['before', 'delta', 'after'], boxes, strict=True))),
                printed_text=_text(row), printed_label_text='\n'.join(label_parts),
                printed_amounts_json=json.dumps(dict(zip(['before', 'delta', 'after'],
                    [_text(row, lo, hi) for lo, hi in bounds[1:]], strict=True)), ensure_ascii=False),
                unit_evidence_json=json.dumps(unit_evidence, ensure_ascii=False),
                fiscal_year=fiscal_year, amendment_number=number, source_amount_unit='千円',
                source_url=source_url, source_sha256=sha))
    extracted = sum(row['amount_delta'] for row in rows)
    if extracted != delta:
        raise ValueError(f'Sum of changed moku deltas {extracted} != first article {delta} 千円')
    if not rows:
        raise ValueError('No changed expenditure moku (zero-total amendment; no synthetic unchanged rows)')
    return dict(rows=rows, source_sha256=sha, fiscal_year=fiscal_year,
        fund_label=fund_label, fund_code=fund_code, amendment_number=number,
        source_amount_unit='千円', source_grain='moku', table_id=TABLE_ID,
        first_article=dict(page_number=article_page + first_page, amount_delta=delta, printed_text=total_text,
                           bbox_json=json.dumps(_box(article_rows[0], 0, float('inf')))),
        extracted_delta=extracted, omitted_zero_delta_rows=zero_rows,
        approval_status='cover-approved' if approval else 'unconfirmed',
        edition_status='preliminary-counts' if '計数整理中' in cover else 'published',
        submitted_at=submitted_at, submitted_basis=submitted[4] if submitted else None,
        effective_at=effective_at, effective_basis='official-cover-printed-original-approval' if approval else None,
        approval_evidence=dict(page_number=first_page, printed_text=approval[0],
            bbox_json=json.dumps(_box(approval_row, 0, float('inf'))) if approval_row else None) if approval else None,
        source_page_range=[first_page, first_page + len(pages) - 1],
        bill_number=int(bill[1]) if bill else None, printed_cover_text=cover,
        verification='before-plus-delta-equals-after; changed-moku-deltas-equal-first-article',
        extractor=f'pipeline/ingestion/fiscal/history_expansion.py@{VERSION}')


def materialize(directory: Path, extraction: dict, **provenance) -> dict:
    """Write candidate Parquet/provenance without touching the adopted registry."""
    isolated = Path(__file__).resolve().parents[3] / '.agent'
    if not directory.resolve().is_relative_to(isolated.resolve()):
        raise ValueError('Candidate materialization must stay inside the repository .agent/ area')
    directory.mkdir(parents=True, exist_ok=True)
    parquet = directory / 'data.parquet'
    if parquet.exists():
        raise ValueError(f'Candidate directory already exists: {directory}')
    with duckdb.connect() as connection:
        connection.execute('create table t (' + ','.join(f'{k} {v}' for k, v in COLUMNS.items()) + ')')
        connection.executemany('insert into t values (' + ','.join('?' for _ in COLUMNS) + ')',
            [[row.get(k) for k in COLUMNS] for row in extraction['rows']])
        connection.execute('copy (select * from t order by source_row) to ? (format parquet, compression zstd)', [str(parquet)])
    evidence = {**provenance, **{k: v for k, v in extraction.items() if k != 'rows'},
        'jurisdiction_code': '132195', 'direction': 'expenditure', 'document_kind': 'supplementary',
        'rows': len(extraction['rows']), 'header': list(COLUMNS), 'raw_form': 'extracted',
        'normalization': ['NFKC and whitespace removal in before/delta/after text; commas and triangle signs retained',
                          'Signed integers in printed thousand-yen units; raw printed amount strings retained separately'],
        'roundtrip_verified': False, 'parquet_sha256': hashlib.sha256(parquet.read_bytes()).hexdigest()}
    record_input(directory, evidence)
    return evidence
