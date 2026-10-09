"""Reuse Meguro's measured settlement columns with an explicit account scope."""

from importlib import import_module
import json
from pathlib import Path

from ingestion.lib.conversion import ConversionContext, write_conversion
from ingestion.lib.parquet import ParquetColumn

layout = import_module('ingestion.fiscal.jurisdictions.131105.layouts.text_settlement.convert')


def physical_pages(ranges):
    pages = []
    for first, last in ranges:
        if first > last or (pages and first <= pages[-1]):
            raise ValueError('Physical page ranges must be ordered and disjoint')
        pages.extend(range(first, last + 1))
    return pages


def convert(inputs, destination, options):
    if len(inputs) != 1:
        raise ValueError('Meguro settlement requires one original')
    source = inputs[0]
    if (source['target']['jurisdiction'] != '131105' or source['target']['document_kind'] != 'settlement'
            or source['direction'] != 'expenditure' or source['format'] != 'pdf' or source['pdf_type'] != 'text'):
        raise ValueError('This measured layout is Meguro text settlement expenditure only')
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
    observations = destination / f'meguro-{table_id}-observations'
    observations.mkdir()
    pages = []
    for index, (first, last) in enumerate(options['detail_pages']):
        pages.extend(layout.observe(source['path'], first, last, observations / f'detail-{index}-bbox.html'))
    sections, parents = layout.detail(pages)
    if not sections:
        raise ValueError('Configured detail scope has no leaf rows')
    (observations / 'parents.json').write_text(json.dumps({'detail': parents}, ensure_ascii=False, indent=2) + '\n')
    columns = tuple(ParquetColumn(k, 'BIGINT' if k.endswith('物理頁') else 'DOUBLE' if k.endswith(('上端', '下端'))
                                  else 'VARCHAR') for k in sections[0])
    output = write_conversion(destination / (table_id + '.parquet'), sections, columns=columns,
                              context=ConversionContext(source['sha256'], table_id, __file__))
    return {table_id: {'path': Path(output.path), 'metadata': layout.metadata(list(sections[0]))}}
