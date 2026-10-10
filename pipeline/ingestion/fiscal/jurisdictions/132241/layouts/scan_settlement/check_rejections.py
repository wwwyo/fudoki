"""Verify that plausible corruptions of a submitted candidate are rejected."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

import duckdb

from validate_candidate import digest, validate


def check(candidate, source, reference, rules):
    baseline = validate(candidate, source, reference, rules)
    if baseline['status'] != 'passed':
        raise ValueError('Negative checks require an independently accepted baseline')
    receipt = json.loads((candidate/'receipt.json').read_text())
    results = []
    cases = [
        ('amount', 'details', "金額 = '1'", "row_id = 'spread-16-17:band-3'", 'original-money'),
        ('ancestry', 'details', "款_row_id = 'nonexistent-parent'", "row_id = 'spread-18-19:band-0'", 'wrong-parent-reference'),
        ('position', 'cell_observations', 'left_pt = left_pt + 100', "table_id = 'details' AND field = '金額'", 'altered-native-coordinate'),
    ]
    for name, table, assignment, condition, expected_kind in cases:
        with tempfile.TemporaryDirectory(prefix='scan-rejection-') as temp:
            directory = Path(temp)
            copied = deepcopy(receipt)
            for file in candidate.glob('*.parquet'):
                if file.stem != table:
                    os.link(file, directory/file.name)
            original = candidate/f'{table}.parquet'
            changed = directory/original.name
            with duckdb.connect() as con:
                con.execute('CREATE TABLE test AS SELECT * FROM read_parquet(?)', [str(original)])
                con.execute(f'UPDATE test SET {assignment} WHERE {condition}')
                con.execute('COPY test TO ? (FORMAT PARQUET)', [str(changed)])
            copied['tables'][table]['sha256'] = digest(changed)
            copied['tables'][table]['bytes'] = changed.stat().st_size
            (directory/'receipt.json').write_text(json.dumps(copied, ensure_ascii=False))
            os.link(candidate/'unknowns.json', directory/'unknowns.json')
            result = validate(directory, source, reference, rules)
            kinds = {issue['kind'] for issue in result['issues']}
            if result['status'] != 'failed' or expected_kind not in kinds:
                raise AssertionError(f'{name} was not rejected by {expected_kind}: {kinds}')
            results.append({'case': name, 'rejected_by': expected_kind})
    if receipt.get('dictionary_name_corrections'):
        with tempfile.TemporaryDirectory(prefix='scan-dictionary-rejection-') as temp:
            directory=Path(temp)
            copied=deepcopy(receipt)
            correction=copied['dictionary_name_corrections'][0]
            dictionary=json.loads(Path(correction['dictionary_path']).read_text())
            correction['rule_id']=next(rule['id'] for rule in dictionary['rules']
                                       if rule['id']!=correction['rule_id'])
            for file in [*candidate.glob('*.parquet'),candidate/'unknowns.json']:
                os.link(file,directory/file.name)
            (directory/'receipt.json').write_text(json.dumps(copied,ensure_ascii=False))
            result=validate(directory,source,reference,rules)
            expected_kind='wrong-whole-name-dictionary-application'
            if result['status']!='failed' or expected_kind not in {issue['kind'] for issue in result['issues']}:
                raise AssertionError('Incorrect dictionary rule was not rejected')
            results.append({'case':'dictionary-rule','rejected_by':expected_kind})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'source', 'reference', 'rules', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = check(args.candidate, args.source, args.reference, args.rules)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
