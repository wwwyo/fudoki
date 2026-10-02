"""旧配布物と新しい CSV を、原典行の対応を固定して比較する。"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def rows(path):
    with path.open() as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def normalized(row):
    return {key.replace('budget_', 'fiscal_'): value for key, value in row.items()}


def compare(baseline: Path, candidate: Path):
    files = sorted(baseline.glob('*/*.csv'))
    if {str(p.relative_to(baseline)) for p in files} != {str(p.relative_to(candidate)) for p in candidate.glob('*/*.csv')}:
        raise ValueError('Distribution resource sets differ')
    mappings = {}
    for old_path in files:
        if old_path.stem not in ['expenditure', 'revenue']:
            continue
        relative = old_path.relative_to(baseline)
        _, old = rows(old_path)
        _, new = rows(candidate / relative)
        current = {}
        for row in new:
            key = (row['fiscal_year'], row['source_row'], row['phase_id'])
            if key in current:
                raise ValueError(f'New statement has duplicate original row and phase: {relative}:{key}')
            current[key] = row
        mapping = mappings.setdefault(relative.parts[0], {})
        for row in old:
            current_row = current.get((row['fiscal_year'], row['source_row'], row['phase_id']))
            if not current_row:
                raise ValueError(f'Original row is missing: {relative}:{row["source_row"]}')
            old_id = row['budget_line_id']
            if old_id in mapping and mapping[old_id] != current_row['fiscal_line_id']:
                raise ValueError('One previous line maps to different current lines')
            mapping[old_id] = current_row['fiscal_line_id']
        if len(set(mapping.values())) != len(mapping):
            raise ValueError('Previous line identities were collapsed')
    result = []
    for old_path in files:
        relative = old_path.relative_to(baseline)
        old_columns, old_rows = rows(old_path)
        new_columns, new_rows = rows(candidate / relative)
        columns = [column.replace('budget_', 'fiscal_') for column in old_columns]
        extra = set(new_columns) - set(columns)
        if set(columns) - set(new_columns) or extra - {'dataset_id', 'document_kind', 'origin_sha256', 'phase_label', 'source_amount_unit'}:
            raise ValueError(f'Unexpected column change: {relative}')
        expected = []
        for row in old_rows:
            row = normalized(row)
            if 'fiscal_line_id' in row:
                row['fiscal_line_id'] = mappings[relative.parts[0]][row['fiscal_line_id']]
            expected.append(tuple(row[column] for column in columns))
        actual = [tuple(row[column] for column in columns) for row in new_rows]
        if Counter(expected) != Counter(actual):
            raise ValueError(f'Numeric, source, name or classification values differ: {relative}')
        result.append({'resource': str(relative), 'rows': len(actual), 'originalLineMappingChecked': 'fiscal_line_id' in columns})
    return {'csvResources': len(result), 'resources': result, 'lineMappings': {code: len(mapping) for code, mapping in mappings.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.baseline, args.candidate)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'csvResources': report['csvResources'], 'lineMappings': report['lineMappings']}))


if __name__ == '__main__':
    main()
