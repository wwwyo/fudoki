"""生成した API 用の表を保存契約へ取り込み、容量と主要問い合わせを測る。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import os
from pathlib import Path

from ingestion.paths import BUILD, PACKAGES, REPO

TABLES = ['release_jurisdictions', 'fiscal_datasets', 'fiscal_lines', 'amounts', 'cofog', 'line_hierarchy', 'line_dimensions', 'names']


def load_tables(directory: Path, database: Path, release: str = 'r-' + '0' * 32) -> dict:
    if database.exists():
        database.unlink()
    con = sqlite3.connect(database)
    con.executescript((REPO / 'packages/data-contracts/schema.sql').read_text())
    con.execute('INSERT INTO releases VALUES (?, 1, ?, NULL, NULL, ?, ?)', (release, 'staging', '0' * 40, '0' * 64))
    master_path = directory / 'jurisdictions.jsonl'
    masters = [json.loads(line) for line in master_path.read_text().splitlines() if line]
    for row in masters:
        if set(row) != {'jurisdiction_code', 'name', 'ocd_id'}:
            raise ValueError('Jurisdiction master storage columns differ')
        con.execute('INSERT INTO jurisdictions VALUES(?,?,?)', [row['jurisdiction_code'], row['name'], row['ocd_id']])
    tables = {}
    for name in TABLES:
        path = directory / f'{name}.jsonl'
        columns = [row[1] for row in con.execute(f'PRAGMA table_info("{name}")') if row[1] != 'release_id']
        expected = set(columns)
        statement = f'INSERT INTO "{name}" (release_id, ' + ','.join(f'"{column}"' for column in columns) + ') VALUES (' + ','.join(['?'] * (len(columns) + 1)) + ')'
        count = 0
        with path.open() as stream:
            for line in stream:
                row = json.loads(line)
                if set(row) != expected:
                    raise ValueError(f'{name}: storage contract columns differ: {set(row) ^ expected}')
                if name == 'amounts':
                    for column in ['value', 'source_amount']:
                        if not isinstance(row[column], int) or abs(row[column]) > 2**53 - 1:
                            raise ValueError(f'{name}: {column} is not an exact API integer')
                con.execute(statement, [release] + [row[column] for column in columns])
                count += 1
        tables[name] = {'rows': count, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    foreign_keys = con.execute('PRAGMA foreign_key_check').fetchall()
    if foreign_keys:
        raise ValueError(f'Storage contract references do not resolve: {foreign_keys[:5]}')
    con.execute('UPDATE releases SET state = ?', ('published',))
    con.execute('INSERT INTO active_release(singleton,release_id) VALUES (1, ?)', (release,))
    con.commit()
    scope_totals = con.execute('''SELECT d.dataset_id, a.phase, count(*), sum(a.value)
      FROM fiscal_lines l JOIN fiscal_datasets d USING (release_id, dataset_id)
      JOIN amounts a USING (release_id, fiscal_line_id)
      WHERE l.release_id = ? GROUP BY d.dataset_id, a.phase ORDER BY d.dataset_id, a.phase''', (release,)).fetchall()
    measurements = {}
    statements = {
        'dataset_lines': ('SELECT fiscal_line_id FROM fiscal_lines WHERE release_id=? AND dataset_id=? ORDER BY fiscal_line_id LIMIT 51', (release, scope_totals[0][0])),
        'name_search': ('SELECT DISTINCT fiscal_line_id FROM names WHERE release_id=? AND instr(value, ?)>0 ORDER BY fiscal_line_id LIMIT 51', (release, '教育')),
        'cofog_comparison': ('''SELECT d.jurisdiction_code, d.fiscal_year, c.division, sum(a.value), count(*)
          FROM fiscal_datasets d JOIN fiscal_lines l USING (release_id,dataset_id)
          JOIN amounts a USING (release_id,fiscal_line_id) JOIN cofog c USING (release_id,fiscal_line_id)
          WHERE d.release_id=? AND a.phase=? AND d.direction='expenditure'
          GROUP BY d.jurisdiction_code,d.fiscal_year,c.division''', (release, 'approved')),
    }
    for label, (statement, values) in statements.items():
        start = time.perf_counter()
        result = con.execute(statement, values).fetchall()
        measurements[label] = {'milliseconds': round((time.perf_counter() - start) * 1000, 2), 'resultRows': len(result),
                               'plan': con.execute('EXPLAIN QUERY PLAN ' + statement, values).fetchall()}
    con.close()
    return {'masters': {'jurisdictions': {'rows': len(masters), 'sha256': hashlib.sha256(master_path.read_bytes()).hexdigest()}}, 'tables': tables, 'bytes': database.stat().st_size, 'threeReleasesEstimateBytes': database.stat().st_size * 3,
            'scopeTotals': scope_totals, 'localMeasurements': measurements}


def main():
    report = load_tables(PACKAGES.parent / 'api', BUILD / 'candidate.sqlite', os.environ.get('FUDOKI_RELEASE_ID', 'r-' + '0' * 32))
    (BUILD / 'd1-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'databaseBytes': report['bytes'], 'tables': {name: value['rows'] for name, value in report['tables'].items()},
                      'milliseconds': {name: value['milliseconds'] for name, value in report['localMeasurements'].items()}}))


if __name__ == '__main__':
    main()
