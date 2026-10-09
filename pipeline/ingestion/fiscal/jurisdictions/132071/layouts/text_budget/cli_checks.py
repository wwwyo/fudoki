"""Black-box CLI rejection checks using read-only original inputs and local variants."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import duckdb


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--origin-sha256', required=True)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--observations', type=Path, required=True)
    parser.add_argument('--origin-observations', type=Path, required=True)
    parser.add_argument('--detail-controls', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New test directory; must not exist')
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    validator = Path(__file__).with_name('validate_candidate.py').resolve()
    command = [sys.executable, str(validator)]
    for name in ('source', 'raw', 'observations', 'origin_observations', 'detail_controls'):
        command.extend(['--' + name.replace('_', '-'), str(getattr(args, name).resolve())])
    command.extend(['--origin-sha256', args.origin_sha256])
    initial_sha = hashlib.sha256(args.raw.read_bytes()).hexdigest()
    outcomes = []

    def invoke(name, updates, *, category=None, no_report=False):
        current = command.copy()
        for flag, value in updates.items():
            current[current.index(flag) + 1] = str(value)
        output = root / name
        completed = subprocess.run([*current, '--output', str(output)], cwd=root,
                                   capture_output=True, text=True)
        summary = json.loads(completed.stdout)
        assert completed.returncode != 0 and summary['status'] == 'failed', (name, completed)
        report = output / 'validation.json'
        if no_report:
            assert not report.exists(), name
        else:
            result = json.loads(report.read_text())
            assert result['status'] == 'failed', name
            assert category in {issue['category'] for issue in result['preservation_issues']}, name
            if name == 'renamed':
                counts = Counter(check['status'] for check in result['checks'])
                assert counts == {'matched': 3216, 'not_checkable': 3}, counts
            if name == 'amount':
                assert any(check['status'] == 'mismatched' for check in result['checks']), name
        outcomes.append({'case': name, 'exit_code': completed.returncode, 'stdout': summary})

    with duckdb.connect() as con:
        con.execute('create table candidate as select * from read_parquet(?, hive_partitioning=false)', [str(args.raw)])
        con.execute('update candidate set "説明1_名称" = \'名称変更\' where rowid=0')
        renamed = root / 'renamed.parquet'
        con.execute('copy candidate to ? (format parquet)', [str(renamed)])
        con.execute('drop table candidate')
        con.execute('create table candidate as select * from read_parquet(?, hive_partitioning=false)', [str(args.raw)])
        con.execute('update candidate set "説明3_金額" = cast(cast(replace("説明3_金額", \',\', \'\') as bigint)+1 as varchar) where rowid=(select min(rowid) from candidate where "説明3_金額" is not null)')
        amount = root / 'amount.parquet'
        con.execute('copy candidate to ? (format parquet)', [str(amount)])
    invoke('renamed', {'--raw': renamed}, category='raw_source_values')
    invoke('amount', {'--raw': amount}, category='raw_source_values')
    invoke('missing', {'--raw': root / 'absent.parquet'}, no_report=True)
    invoke('wrong_origin', {'--origin-sha256': '0' * 64}, no_report=True)
    reused = root / 'existing'
    reused.mkdir()
    marker = reused / 'validation.json'
    marker.write_text('{"status":"passed","marker":"previous run"}\n')
    marker_sha = hashlib.sha256(marker.read_bytes()).hexdigest()
    completed = subprocess.run([*command, '--output', str(reused)], cwd=root, capture_output=True, text=True)
    assert completed.returncode != 0 and json.loads(completed.stdout)['status'] == 'failed'
    assert hashlib.sha256(marker.read_bytes()).hexdigest() == marker_sha
    outcomes.append({'case': 'existing_output_refused', 'exit_code': completed.returncode})
    assert hashlib.sha256(args.raw.read_bytes()).hexdigest() == initial_sha
    result = {'status': 'passed', 'checks': outcomes, 'raw_sha256': initial_sha}
    (root / 'cli-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'checks': len(outcomes), 'report': str(root / 'cli-checks.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
