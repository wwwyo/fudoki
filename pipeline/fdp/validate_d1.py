"""団体別の提供データを保存契約へ取り込み、数値と参照・容量を検査する。"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from ingestion.paths import BUILD, PACKAGES, REPO


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def load_tables(directory: Path, database: Path) -> dict:
    if database.exists():
        database.unlink()
    con = sqlite3.connect(database)
    con.executescript((REPO / 'packages/data-contracts/schema.sql').read_text())
    candidate = directory.parent
    verification = json.loads((candidate / 'verification.json').read_text())
    manifest = json.loads((candidate / 'manifest.json').read_text())
    masters = {}
    for name in ['jurisdictions', 'cofog_codes']:
        path = directory / f'{name}.jsonl'
        rows = read_rows(path)
        columns = [r[1] for r in con.execute(f'PRAGMA table_info({name})')]
        for row in rows:
            if set(row) != set(columns):
                raise ValueError(f'{name}: storage columns differ')
            con.execute(f'INSERT INTO {name} VALUES ({",".join("?" for _ in columns)})', [row[c] for c in columns])
        masters[name] = {'rows': len(rows), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    versions = {v['jurisdictionCode']: v['versionId'] for v in manifest['jurisdictions']}
    for version in manifest['jurisdictions']:
        con.execute('INSERT INTO fiscal_jurisdiction_versions VALUES(?,?,?,?,?,?,?,?,?,?)', (
            version['versionId'], version['jurisdictionCode'], 2, version['packageId'],
            version['name'], version['ocdId'], json.dumps(version['caveats'], ensure_ascii=False, separators=(',', ':')),
            '1970-01-01T00:00:00.000Z', 'https://example.invalid/manifest.json', verification['manifestSha256']))
    data = {name: read_rows(directory / f'{name}.jsonl') for name in verification['tables']}
    datasets = {r['dataset_id']: r for r in data['fiscal_datasets']}
    line_owners, item_owners = {}, {}
    for direction in ['expenditure', 'revenue']:
        for name in [f'fiscal_settlement_{direction}_lines', f'fiscal_initial_{direction}_budget_lines']:
            for row in data[name]:
                line_owners[row['fiscal_line_id']] = datasets[row['dataset_id']]['jurisdiction_code']
        for row in data[f'fiscal_{direction}_budget_items']:
            item_owners[row['budget_item_id']] = row['jurisdiction_code']
    tables = {}
    for name, rows in data.items():
        columns = [r[1] for r in con.execute(f'PRAGMA table_info({name})') if r[1] != 'version_id']
        statement = f'INSERT INTO {name}(version_id,{",".join(columns)}) VALUES ({",".join("?" for _ in range(len(columns)+1))})'
        for row in rows:
            if set(row) != set(columns):
                raise ValueError(f'{name}: storage columns differ: {set(row)^set(columns)}')
            owner = row.get('jurisdiction_code') or datasets.get(row.get('dataset_id'), {}).get('jurisdiction_code') or line_owners.get(row.get('fiscal_line_id')) or item_owners.get(row.get('budget_item_id'))
            if owner not in versions:
                raise ValueError(f'{name}: cannot identify jurisdiction')
            for column in ['amount', 'amount_delta']:
                if column in row and (type(row[column]) is not int or abs(row[column]) > 2**53-1):
                    raise ValueError(f'{name}: {column} is not an exact integer')
            con.execute(statement, [versions[owner]] + [row[c] for c in columns])
        path = directory / f'{name}.jsonl'
        tables[name] = {'rows': len(rows), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    for file in manifest['files']:
        code = file['path'].split('/')[1]
        package = next(p for p in manifest['packages'] if p['jurisdictionCode'] == code)
        if not file['objectKey'].startswith(f"fiscal/{code}/{package['packageId']}/"):
            raise ValueError('R2 file belongs to another jurisdiction or package')
        con.execute('INSERT INTO fiscal_package_files VALUES(?,?,?,?,?,?,?)', (versions[code], file['path'], code, file['objectKey'], file['sha256'], file['bytes'], file['contentType']))
    if con.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Storage references do not resolve')
    for direction in ['expenditure', 'revenue']:
        if con.execute(f'''SELECT 1 FROM fiscal_initial_{direction}_budget_lines l
          JOIN fiscal_datasets d USING(version_id,dataset_id)
          JOIN fiscal_{direction}_budget_items b USING(version_id,budget_item_id)
          WHERE b.fiscal_year!=d.fiscal_year OR b.initial_state!='recorded' LIMIT 1''').fetchone():
            raise ValueError('Initial budget target year or state differs')
        if con.execute(f'''SELECT 1 FROM fiscal_{direction}_settlement_links x
          JOIN fiscal_{direction}_budget_items b USING(version_id,budget_item_id)
          JOIN fiscal_settlement_{direction}_lines l ON l.version_id=x.version_id AND l.fiscal_line_id=x.settlement_line_id
          JOIN fiscal_datasets d ON d.version_id=l.version_id AND d.dataset_id=l.dataset_id
          WHERE b.fiscal_year!=d.fiscal_year OR b.fund_code!=l.fund_code LIMIT 1''').fetchone():
            raise ValueError('Settlement correspondence year or fund differs')
        if con.execute(f"""SELECT 1 FROM fiscal_{direction}_budget_items b
          LEFT JOIN fiscal_initial_{direction}_budget_lines l USING(version_id,budget_item_id)
          WHERE (b.initial_state='recorded' AND l.fiscal_line_id IS NULL)
             OR (b.initial_state!='recorded' AND l.fiscal_line_id IS NOT NULL) LIMIT 1""").fetchone():
            raise ValueError('Initial budget evidence disagrees with target state')
        if con.execute(f"""SELECT 1 FROM fiscal_{direction}_budget_changes c
          JOIN fiscal_{direction}_budget_items b USING(version_id,budget_item_id)
          LEFT JOIN fiscal_{direction}_budget_items other ON other.version_id=c.version_id AND other.budget_item_id=c.counterpart_budget_item_id
          WHERE (c.change_kind='carryover' AND (c.carryover_from_year IS NULL OR c.carryover_to_year IS NULL OR c.carryover_to_year!=b.fiscal_year OR c.carryover_from_year>=c.carryover_to_year))
             OR (c.change_kind!='carryover' AND (c.carryover_from_year IS NOT NULL OR c.carryover_to_year IS NOT NULL))
             OR (other.budget_item_id IS NOT NULL AND (other.jurisdiction_code!=b.jurisdiction_code OR other.fiscal_year!=b.fiscal_year OR other.fund_code!=b.fund_code)) LIMIT 1""").fetchone():
            raise ValueError('Budget change counterpart or carryover years differ')
        for member in ['budget_item_id','settlement_line_id']:
            if con.execute(f"""SELECT 1 FROM fiscal_{direction}_settlement_links WHERE match_status='verified'
              GROUP BY version_id,{member} HAVING count(DISTINCT match_group_id)>1 LIMIT 1""").fetchone():
                raise ValueError('Verified correspondence spans multiple groups')
    con.commit()
    totals=[]
    for table in tables:
        if table.endswith('_lines') or table.endswith('_budget_changes'):
            amount = 'amount_delta' if table.endswith('_budget_changes') else 'amount'
            totals.extend([dataset, jurisdiction, table, count, value] for dataset,jurisdiction,count,value in con.execute(f'''SELECT l.dataset_id,d.jurisdiction_code,count(*),sum(l.{amount}) FROM {table} l JOIN fiscal_datasets d USING(version_id,dataset_id) GROUP BY l.dataset_id,d.jurisdiction_code ORDER BY l.dataset_id'''))
    measurements={}
    for direction in ['expenditure','revenue']:
        sql=f'SELECT fiscal_line_id FROM fiscal_settlement_{direction}_lines WHERE version_id=? AND dataset_id=? ORDER BY fiscal_line_id LIMIT 51'
        target=next((t for t in totals if t[2]==f'fiscal_settlement_{direction}_lines'),None)
        if target:
            args=(versions[target[1]],target[0]);start=time.perf_counter();result=con.execute(sql,args).fetchall()
            measurements[f'{direction}_lines']={'milliseconds':round((time.perf_counter()-start)*1000,2),'resultRows':len(result),'plan':con.execute('EXPLAIN QUERY PLAN '+sql,args).fetchall()}
    con.close()
    return {'masters':masters,'tables':tables,'bytes':database.stat().st_size,'scopeTotals':totals,'localMeasurements':measurements,'versions':len(versions)}


def main():
    report=load_tables(PACKAGES.parent/'api',BUILD/'candidate.sqlite')
    (BUILD/'d1-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'databaseBytes':report['bytes'],'tables':{n:v['rows'] for n,v in report['tables'].items()}}))


if __name__=='__main__':
    main()
