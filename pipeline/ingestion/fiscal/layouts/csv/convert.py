"""Convert one supplied headered CSV without inferring fiscal semantics."""
from pathlib import Path
import json
from ingestion.lib.conversion import ConversionContext, convert_csv


def convert(inputs: list[dict], destination: Path, options: dict) -> dict[str, Path]:
    if len(inputs) != 1 or inputs[0]['format'] != 'csv':
        raise ValueError('CSV layout requires exactly one CSV original')
    source = inputs[0]
    table_id = options['table_id']
    output = destination / f'{table_id}.parquet'
    context = ConversionContext(source['sha256'], table_id, 'fiscal/layouts/csv/convert.py')
    report = destination / f'{table_id}.checks.json'
    checks = {'check': 'csv_to_parquet_preservation', 'table_id': table_id,
              'origin_sha256': source['sha256'], 'encoding': options['encoding'],
              'delimiter': options.get('delimiter', ','), 'quotechar': options.get('quotechar', '"')}
    try:
        result = convert_csv(source['path'], output, context=context, encoding=options['encoding'],
                             delimiter=checks['delimiter'], quotechar=checks['quotechar'],
                             source_line_columns=(options.get('line_start_column', 'source_line_start'),
                                                  options.get('line_end_column', 'source_line_end')))
    except Exception as error:
        report.write_text(json.dumps(checks | {'status': 'failed', 'error': str(error)},
                                     ensure_ascii=False, indent=2) + '\n')
        raise
    report.write_text(json.dumps(checks | {'status': 'passed', 'row_count': result.row_count,
                                         'parquet_sha256': result.sha256}, ensure_ascii=False, indent=2) + '\n')
    return {table_id: output}
