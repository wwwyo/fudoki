"""Reuse the existing spread reader on supplied, selected local PDF bytes."""
from copy import deepcopy
import json
from pathlib import Path

from ingestion.fiscal.management.sources import load_statements
from ingestion.fiscal.layouts.fiscal_general.extract_statement import read_pages, extract, reconcile, _write


def convert(inputs: list[dict], destination: Path, options: dict) -> dict[str, Path]:
    if len(inputs) != 1 or inputs[0]['format'] != 'pdf' or len(inputs[0]['scope']) != 1:
        raise ValueError('Statement reader needs one PDF and one account scope')
    source = inputs[0]
    scope, target = source['scope'][0], source['target']
    key = options['source_key']
    if key.split(':')[:2] != [target['jurisdiction'], str(target['fiscal_year'])]:
        raise ValueError('Statement definition belongs to another target')
    spec = deepcopy(load_statements()[key])
    kind = 'initial' if spec['document_kind'] == 'budget' else spec['document_kind']
    if kind != target['document_kind'] or spec['fund_label'] != scope['account']:
        raise ValueError('Statement definition differs from supplied document/account')
    if len(scope['pages']) != 1:
        raise ValueError('Convert disjoint statement ranges separately')
    direction = source['direction']
    first, last = scope['pages'][0]
    declared_first, declared_last = spec['pages'][direction]
    if not declared_first <= first <= last <= declared_last:
        raise ValueError('Requested pages are outside the measured statement layout')
    spec['pages'] = {direction: [first, last]}
    pages = read_pages(source['path'], spec, direction)
    rows, totals, auxiliary = extract(pages, spec, direction)
    checks = reconcile(rows, totals, auxiliary)
    directory = destination / options['table_id']
    _write(directory, direction, scope['account'], rows, target['fiscal_year'])
    (directory / 'checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2) + '\n')
    return {options['table_id']: directory / 'data.parquet'}
