"""Reuse Shinjuku's measured settlement layout with an explicit account scope.

The shared layout module keeps the measured column edges, cell readers and
assembly functions. This entry resolves which printed pages belong to the
declared account and passes that account's observed row count and amount
column right edges; all remaining measurement and assembly is the shared code.
"""
from importlib import import_module
import json
from pathlib import Path

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

layout = import_module('ingestion.fiscal.jurisdictions.131041.layouts.text_settlement.convert')

# Measured on the scoped special-account pages: wide initial-budget values start
# slightly left of, and the unused-amount and remark amount columns are
# right-aligned about one point wider than, the shared defaults measured on the
# general account pages.
DETAIL_EDGES = [(94, 169), *layout.DETAIL_EDGES[1:-1], (790, 866)]
NOTE_BOUNDS = (1090, 1177)
# Printed △ signs spill a few points left across each column's left edge on the
# scoped pages (observed at x 165.7–174.7 before the amendment column and
# 303.8–312.8 before the transfer column). Sign zones partition on boundaries
# shifted seven points left so each sign belongs to the column to its right.
_sign_lefts = [left - 7 for left, _ in DETAIL_EDGES]
SIGN_EDGES = [(left, _sign_lefts[i + 1] if i + 1 < len(_sign_lefts) else DETAIL_EDGES[i][1])
              for i, left in enumerate(_sign_lefts)]


def physical_pages(ranges):
    pages = []
    for first, last in ranges:
        if first > last or (pages and first <= pages[-1]):
            raise ValueError('Physical page ranges must be ordered and disjoint')
        pages.extend(range(first, last + 1))
    return pages


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Measured Shinjuku settlement uses one original')
    source = inputs[0]
    if (source['target']['jurisdiction'] != '131041' or source['target']['document_kind'] != 'settlement'
            or source['direction'] != 'expenditure' or source['format'] != 'pdf' or source['pdf_type'] != 'text'):
        raise ValueError('This measured layout is Shinjuku text settlement expenditure only')
    summary = physical_pages(options['summary_pages'])
    detail_pages = physical_pages(options['detail_pages'])
    if set(summary).intersection(detail_pages):
        raise ValueError('Summary and detail pages must be disjoint')
    selected = [p for scope in source['scope'] if scope['account'] == options['account']
                for first, last in scope['pages'] for p in range(first, last + 1)]
    if sorted(selected) != sorted(summary + detail_pages):
        raise ValueError('Configured account pages differ from selected expenditure scope')
    destination = Path(destination)
    table_id = options['table_id']
    prefix = table_id.removesuffix('-expenditure-detail')
    observations = destination / f'shinjuku-{prefix}-observations'
    observations.mkdir()
    scoped_summary = []
    for index, (first, last) in enumerate(options['summary_pages']):
        scoped_summary.extend(layout.observe(source['path'], first, last,
                                             observations / f'summary-{index}-bbox.html'))
    if len(scoped_summary) != 1:
        raise ValueError('Scoped summary must be exactly one physical page')
    summary = layout.summary(scoped_summary, expected_rows=options['summary_rows'])
    scoped_detail = []
    for index, (first, last) in enumerate(options['detail_pages']):
        scoped_detail.extend(layout.observe(source['path'], first, last,
                                            observations / f'detail-{index}-bbox.html'))
    sections, remarks, parents = layout.detail(scoped_detail, edges=DETAIL_EDGES,
                                               note_bounds=NOTE_BOUNDS, sign_edges=SIGN_EDGES)
    if not remarks:
        raise ValueError('Configured detail scope has no leaf rows')
    (observations / 'parents.json').write_text(json.dumps(parents, ensure_ascii=False, indent=2) + '\n')
    rows = layout.expenditure_detail(remarks, summary)
    results = {}
    for suffix, observed in [('summary', summary), ('setsu', sections), ('expenditure-detail', rows)]:
        columns = tuple(ParquetColumn(k, 'BIGINT' if k.endswith('物理頁') else 'DOUBLE' if k.endswith(('上端', '下端'))
                                      else 'VARCHAR') for k in observed[0])
        table_destination = destination if suffix == 'expenditure-detail' else observations
        result = write_conversion(table_destination / (prefix + '-' + suffix + '.parquet'), observed,
                                  columns=columns,
                                  context=ConversionContext(source['sha256'], prefix + '-' + suffix, __file__))
        if suffix == 'expenditure-detail':
            results[table_id] = {'path': Path(result.path), 'metadata': layout.metadata(observed, suffix)}
    return results
