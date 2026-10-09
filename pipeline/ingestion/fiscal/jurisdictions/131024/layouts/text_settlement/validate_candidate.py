"""Read saved Chuo raw independently and compare with printed observations."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

import duckdb

from inspect_origin import FIELDS, number

TIERS = ('事業', '内訳1', '内訳2', '内訳3', '内訳4')
MONEY_COUNT = re.compile(r'\d[\d,]*')


def normalized(text: str) -> str:
    return re.sub(r'\s+', '', text)


def read_raw(path: Path) -> tuple[list[dict], list[tuple]]:
    with duckdb.connect() as connection:
        result = connection.execute('SELECT * FROM read_parquet(?)', [str(path)])
        schema = [(column[0], str(column[1])) for column in result.description]
        names = [column[0] for column in result.description]
        return [dict(zip(names, row)) for row in result.fetchall()], schema


def validate(raw: Path, observation_path: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    observation = json.loads(observation_path.read_text())
    rows, schema = read_raw(raw)
    inner_column = '内表_給付額' if any(n == '内表_給付額' for n, _ in schema) else '内表_金額'
    annual_current = next((name for name, _ in schema if normalized(name) == '施工概要_令和7年度'), None)
    issues, checks = [], []
    pages = {p['page']: p for p in observation['pages']}
    controls = observation['controls']
    origin_controls = {(c['level'], tuple(c['path'].get(k) for k in ('款', '項', '目'))): c
                       for c in controls if c['level'] != '合計'}
    if not rows:
        issues.append({'kind': 'empty raw'})
    signatures = collections.Counter(tuple(row.values()) for row in rows)
    if any(count > 1 for count in signatures.values()):
        issues.append({'kind': 'duplicate complete original row'})
    for name, type_ in schema:
        if any(t in type_ for t in ('STRUCT', '[]', 'JSON', 'MAP')):
            issues.append({'kind': 'non-scalar raw', 'column': name, 'type': type_})
        if name in ('jurisdiction', 'fiscal_year', 'unit', 'row_id', 'node_id'):
            issues.append({'kind': 'management column in raw', 'column': name})
    represented = {}
    hierarchy_nodes, descendants = {}, collections.defaultdict(dict)
    leaf_total = collections.defaultdict(dict)
    source_name_checks, source_amount_checks = 0, 0
    annual_matches = set()
    annual_table_rows = collections.defaultdict(list)
    schema_names = {normalized(name): name for name, _ in schema}
    personnel_matches = set()
    personnel_groups = collections.defaultdict(list)
    terminal_matches = set()
    for printed in observation.get('terminal_sections', []):
        matches=[(i,row) for i,row in enumerate(rows) if row.get('節_番号')==printed['code']
                 and row.get('節_原典物理頁')==printed['page']
                 and all(str(row.get(k+'_番号'))==v for k,v in printed['path'].items())]
        if len(matches)!=1:
            issues.append({'kind':'terminal section original row coverage','origin':printed,'matches':len(matches)});continue
        i,row=matches[0];terminal_matches.add(i)
        for field,expected in [('名称',printed['name']),('所属',printed.get('department','')),
                               ('金額',printed['values']['予算現額計']),
                               *[(k,printed['values'][k]) for k in ('支出済額','翌年度繰越額','不用額')]]:
            actual=row.get('節_'+field)
            if normalized(actual or '')!=normalized(expected):
                issues.append({'kind':'terminal section scalar preservation','row':i,'field':field,'origin':expected,'raw':actual})
    for i,row in enumerate(rows):
        if row.get('節_番号') is not None and i not in terminal_matches:
            issues.append({'kind':'unexpected terminal section row','row':i})
    for printed in observation.get('personnel_rows', []):
        if printed['is_total']:
            continue
        matches = [(i,row) for i,row in enumerate(rows) if row.get('職員_区分') is not None
                   and row.get('原典物理頁') == printed['page']
                   and abs(row.get('原典yMin',-100)-printed['y']) < .05]
        if len(matches) != 1:
            issues.append({'kind':'personnel original row coverage','origin':printed,'matches':len(matches)})
            continue
        i,row = matches[0];personnel_matches.add(i)
        key = (printed['page'],tuple(printed['path'][k] for k in ('款','項','目')))
        personnel_groups[key].append(row)
        total = next(p for p in observation['personnel_rows'] if p['is_total'] and p['page']==printed['page']
                     and p['path']==printed['path'])
        date = re.search(r'（[^）]+）',total['value'])[0]
        for field,expected in [('区分',printed['name']),('人数',printed['value']),('現在日',date)]:
            if normalized(row.get('職員_'+field) or '') != normalized(expected):
                issues.append({'kind':'personnel scalar preservation','row':i,'field':field,'origin':expected,'raw':row.get('職員_'+field)})
    for i,row in enumerate(rows):
        if row.get('職員_区分') is not None and i not in personnel_matches:
            issues.append({'kind':'unexpected personnel row','row':i})
    for printed in observation.get('annual_rows', []):
        if printed['is_total']:
            continue
        matches = [(i, row) for i, row in enumerate(rows)
                   if normalized(row.get('施工概要_区分') or '') == normalized(printed['name'])
                   and row.get('原典物理頁') == printed['page']
                   and row.get('原典yMin', 10000) - 3 <= printed['y'] <= row.get('原典yMax', -1) + 3]
        if len(matches) != 1:
            issues.append({'kind': 'annual row coverage', 'page': printed['page'], 'y': printed['y'],
                           'name': printed['name'], 'matches': len(matches)})
            continue
        row_index, row = matches[0]
        annual_matches.add(row_index)
        annual_table_rows[(printed['table_page'],printed['table_y'])].append((printed,row))
        for header, expected in printed['values'].items():
            column = schema_names.get('施工概要_' + normalized(header))
            actual = row.get(column) if column else None
            if actual is None or normalized(actual).removesuffix('円') != normalized(expected):
                issues.append({'kind': 'annual cell preservation', 'row': row_index,
                               'page': printed['page'], 'header': header, 'origin': expected, 'raw': actual})
    for i, row in enumerate(rows):
        if row.get('施工概要_区分') is not None and i not in annual_matches:
            issues.append({'kind': 'unexpected annual row', 'row': i, 'page': row.get('原典物理頁')})
    monetary_matches = set()
    for printed in observation.get('monetary_rows', []):
        if printed['is_total'] or printed['unit'] != '円':
            continue
        matches = [row for row in rows if row.get(inner_column + '_原典物理頁') == printed['page']
                   and abs(row.get(inner_column + '_原典yMin', -100)-printed['y']) < .05]
        if not matches:
            issues.append({'kind': 'missing printed money cell', 'page': printed['page'], 'y': printed['y']})
        source_word = next(w for w in pages[printed['page']]['words']
                           if abs(w['x0']-printed['x0']) < .05 and abs(w['y0']-printed['y']) < .05)
        for row in matches:
            if (abs(row[inner_column + '_原典yMax']-source_word['y1']) > .05
                    or abs(row[inner_column + '_原典xMin']-printed['x0']) > .05
                    or abs(row[inner_column + '_原典xMax']-printed['x1']) > .05
                    or number(row[inner_column]) != number(printed['amount'])):
                issues.append({'kind': 'printed money cell identity', 'page': printed['page'], 'y': printed['y']})
    cell_comparisons = 0
    for printed in observation.get('cell_values', []):
        candidates = [(i, row) for i, row in enumerate(rows) if row.get(inner_column) is not None
                      and row.get(inner_column + '_原典物理頁') == printed['page']
                      and abs(row.get(inner_column + '_原典yMin', -100) - printed['y']) < 2]
        matches = [(i, row) for i, row in candidates if all(
            collections.Counter(normalized(expected)) == collections.Counter(normalized(row.get('内表_'+field) or ''))
            for field, expected in printed['fields'].items())]
        if len(matches) != 1 or matches[0][0] in monetary_matches:
            issues.append({'kind': 'vector cell row membership', 'page': printed['page'], 'y': printed['y'],
                           'row_bounds': printed['row_bounds'], 'expected': printed['fields'],
                           'candidates': [{k:v for k,v in row.items() if k.startswith('内表_')} for _,row in candidates],
                           'matches': len(matches)})
            continue
        monetary_matches.add(matches[0][0])
        cell_comparisons += len(printed['fields'])
    for i, row in enumerate(rows):
        if row.get(inner_column) is not None and i not in monetary_matches:
            issues.append({'kind': 'unexpected monetary row', 'row': i})

    def source_words(row: dict, prefix: str) -> list[dict]:
        page = row.get(prefix + '_原典物理頁')
        if page not in pages:
            return []
        lo_x, lo_y, hi_x, hi_y = (row.get(prefix + '_原典' + key) for key in ('xMin', 'yMin', 'xMax', 'yMax'))
        if None in (lo_x, lo_y, hi_x, hi_y):
            return []
        # Glyph ascenders (negative triangle) may extend above text baseline.
        return [w for w in pages[page]['words'] if w['x0'] >= lo_x - 1.5 and w['x1'] <= hi_x + 1.5
                and w['y1'] >= lo_y - 1.5 and w['y0'] <= hi_y + 1.5]

    for row_index, row in enumerate(rows):
        path = tuple(str(row.get(level + '_番号')) for level in ('款', '項', '目'))
        if observation.get('personnel_rows') and row.get('事業_原典物理頁') is not None:
            location = (row['事業_原典物理頁'],row['事業_原典yMin'])
            parent = max((c for c in controls if c['level']=='目' and (c['page'],c['y']) < location),
                         key=lambda c:(c['page'],c['y']))
            expected_path = tuple(parent['path'][k] for k in ('款','項','目'))
            if path != expected_path:
                issues.append({'kind':'original project fiscal membership','row':row_index,'origin':expected_path,'raw':path})
        for position, level in enumerate(('款', '項', '目')):
            key = (level, path[:position + 1] + (None,) * (2 - position))
            origin = origin_controls.get(key)
            if origin is None:
                issues.append({'kind': 'unknown fiscal path', 'row': row_index, 'path': path, 'level': level})
                continue
            represented[key] = origin
            for field in ('名称', *FIELDS):
                actual = row.get(level + '_' + field)
                expected = origin['name'] if field == '名称' else origin['values'][field]
                if actual is None or normalized(str(actual)) != normalized(expected):
                    issues.append({'kind': 'fiscal control cell', 'row': row_index, 'path': path,
                                   'page': origin['page'], 'column': level + '_' + field,
                                   'origin': expected, 'raw': actual})
            if row.get(level + '_原典物理頁') != origin['page']:
                issues.append({'kind': 'fiscal control page', 'row': row_index, 'level': level})
        chain = []
        for tier in TIERS:
            name = row.get(tier + '_名称')
            if name is None:
                continue
            words = source_words(row, tier)
            compact = normalized(''.join(w['text'] for w in sorted(words, key=lambda w: (w['y0'], w['x0']))))
            fragments = [normalized(fragment) for fragment in name.splitlines() if normalized(fragment)]
            cursor = 0
            for fragment in fragments:
                found = compact.find(fragment, cursor)
                cursor = -1 if found < 0 else found + len(fragment)
                if cursor < 0:
                    break
            if not fragments or cursor < 0:
                issues.append({'kind': 'detail name not in source region', 'row': row_index, 'tier': tier,
                               'name': name, 'page': row.get(tier + '_原典物理頁'), 'source': compact})
            department = row.get(tier + '_所属')
            department_words = [w for w in pages[row[tier+'_原典物理頁']]['words']
                                if row[tier+'_原典xMax']-140 < w['x0'] < row[tier+'_原典xMax']+1
                                and row[tier+'_原典yMin']-2 < w['y0'] < row[tier+'_原典yMax']+15]
            department_lines = []
            for word in sorted(department_words,key=lambda w:(w['y0'],w['x0'])):
                if not department_lines or word['y0']-department_lines[-1][0]['y0'] > 3:
                    department_lines.append([])
                department_lines[-1].append(word)
            department_source = normalized(''.join(w['text'] for line in department_lines
                                                   for w in sorted(line,key=lambda w:w['x0'])))
            if department is not None and normalized(department) not in department_source:
                issues.append({'kind': 'department not in original region', 'row': row_index,
                               'tier': tier, 'department': department})
            source_name_checks += 1
            amount = row.get(tier + '_金額')
            if amount is not None:
                if normalized(amount).strip('円') not in compact or ('円' in amount and '円' not in compact):
                    issues.append({'kind': 'detail amount not in source region', 'row': row_index, 'tier': tier,
                                   'amount': amount, 'page': row.get(tier + '_原典物理頁')})
                source_amount_checks += 1
            node_key = (path, tier, row.get(tier + '_原典物理頁'), row.get(tier + '_原典xMin'),
                        row.get(tier + '_原典yMin'))
            node = {'name': name, 'amount': amount, 'page': row.get(tier + '_原典物理頁'),
                    'tier': tier, 'path': path}
            if node_key in hierarchy_nodes and hierarchy_nodes[node_key] != node:
                issues.append({'kind': 'inconsistent repeated ancestor', 'row': row_index, 'node': node_key})
            hierarchy_nodes[node_key] = node
            if chain:
                descendants[chain[-1]][node_key] = node
            chain.append(node_key)
        if row.get('施工概要_区分') is not None:
            amount = row.get(annual_current)
            if amount is not None and normalized(amount).removesuffix('円') not in ('－', '—', '-'):
                leaf_total[path][('annual', row.get('原典物理頁'), row.get('原典xMin'), row.get('原典yMin'))] = number(amount)
            if row.get('明細金額') is not None:
                issues.append({'kind': 'double amount on construction leaf', 'row': row_index})
            if chain:
                table_key = (path, '施工概要', row.get('原典物理頁'), row.get('原典xMin'), row.get('原典yMin'))
                descendants[chain[-1]][table_key] = {'amount': amount}
        elif row.get(inner_column) is not None:
            money_identity = (path, inner_column, *(row.get(inner_column + '_原典'+field) for field in ('物理頁','xMin','yMin','xMax','yMax')))
            value = number(row[inner_column])
            if money_identity in leaf_total[path] and leaf_total[path][money_identity] != value:
                issues.append({'kind': 'inconsistent shared money cell', 'row': row_index})
            leaf_total[path][money_identity] = value
            if row.get('明細金額') is not None:
                issues.append({'kind': 'double amount on inner table leaf', 'row': row_index})
            if chain:
                table_key = money_identity
                descendants[chain[-1]][table_key] = {'amount': row[inner_column]}
        elif row.get('職員_区分') is not None:
            if row.get('明細金額') is not None or not chain:
                issues.append({'kind':'invented personnel spending allocation','row':row_index})
            else:
                leaf_total[path][('personnel parent',chain[-1])] = number(hierarchy_nodes[chain[-1]]['amount'])
        elif row.get('明細金額') is not None:
            expected_leaf = hierarchy_nodes[chain[-1]]['amount'] if chain else row['目_支出済額']
            if expected_leaf is None or number(row['明細金額']) != number(expected_leaf):
                issues.append({'kind': 'ordinary leaf differs from original cell', 'row': row_index,
                               'origin': expected_leaf, 'raw': row['明細金額']})
            leaf_total[path][('detail', row_index)] = number(row['明細金額'])
        elif row.get('節_番号') is not None:
            leaf_total[path][('section',row['節_番号'],row['節_原典物理頁'],row['節_原典yMin'])]=number(row['節_支出済額'])
        elif not chain:
            # Printed items with no explanatory rows remain at the item grain.
            leaf_total[path][('item', path)] = number(row['目_支出済額'])
        else:
            issues.append({'kind': 'leaf without amount', 'row': row_index, 'path': path})
    for key, origin in origin_controls.items():
        if key not in represented:
            issues.append({'kind': 'missing fiscal control', 'path': key, 'page': origin['page']})

    def check(level: str, path, page: int, field: str, expected: int, actual: int | None, reason=None, unit='円'):
        checks.append({'level': level, 'path': path, 'page': page, 'field': field, 'unit': unit,
                       'origin': expected, 'sum': actual, 'delta': None if actual is None else actual - expected,
                       'status': ('保留' if reason == 'rawに当該目の葉がない' else '検算不可') if actual is None else '一致' if actual == expected else '不一致',
                       'reason': reason})

    for printed in observation.get('personnel_rows', []):
        if printed['is_total']:
            key=(printed['page'],tuple(printed['path'][k] for k in ('款','項','目')))
            expected=int(re.match(r'\d+',printed['value'])[0])
            actual=sum(int(re.match(r'\d+',row['職員_人数'])[0]) for row in personnel_groups[key])
            check('職員人数→印字計',printed['path'],printed['page'],'人数',expected,actual,unit='人')

    dashes = ('－', '—', '-')
    def annual_value(value):
        # A printed dash remains a dash in raw; it contributes no numeric term.
        return None if normalized(value).removesuffix('円') in dashes else number(value)

    for printed in observation.get('annual_rows', []):
        table_key = (printed['table_page'], printed['table_y'])
        if printed['is_total']:
            for header, value in printed['values'].items():
                expected = annual_value(value)
                if expected is None:
                    continue
                column = schema_names.get('施工概要_' + normalized(header))
                values = [annual_value(row[column]) for _, row in annual_table_rows[table_key]]
                check('施工概要内訳→年度計', table_key, printed['page'], header, expected,
                      sum(value for value in values if value is not None))
        elif '計' in printed['values']:
            matched = [row for source,row in annual_table_rows[table_key] if source is printed]
            if len(matched) != 1:
                continue
            row = matched[0]
            expected = annual_value(row[schema_names['施工概要_計']])
            if expected is not None:
                values = [annual_value(row[schema_names['施工概要_'+normalized(header)]])
                          for header in printed['values'] if header != '計']
                check('施工概要年度→行計', table_key+(printed['name'],printed['y']), printed['page'], '計', expected,
                      sum(value for value in values if value is not None))
    for printed in observation.get('monetary_rows', []):
        if not printed['is_total'] or printed['unit'] != '円':
            continue
        source_cells = [cell for cell in observation['monetary_rows'] if not cell['is_total']
                        and cell['page']==printed['page'] and cell['table_y']==printed['table_y']]
        values = {}
        for cell in source_cells:
            for row in rows:
                if row.get(inner_column + '_原典物理頁')==cell['page'] and abs(row.get(inner_column + '_原典yMin',-100)-cell['y'])<.05:
                    identity = tuple(row.get(inner_column + '_原典'+field) for field in ('物理頁','xMin','yMin','xMax','yMax'))
                    values[identity] = number(row[inner_column])
        check('内表金額→印字計', (printed['page'],printed['table_y']),printed['page'],'金額',number(printed['amount']),sum(values.values()))
        if printed.get('amount_header') == '給付額':
            source_words = [w for w in pages[printed['page']]['words'] if abs(w['y0']-printed['y'])<1
                            and w['x1'] < printed['x0'] and MONEY_COUNT.fullmatch(w['text'])]
            expected_count = number(max(source_words,key=lambda w:w['x0'])['text'])
            header_y=printed['table_y']
            table_rows=[row for row in rows if row.get(inner_column) is not None
                        and row.get(inner_column+'_原典物理頁')==printed['page']
                        and header_y<row.get(inner_column+'_原典yMin',-1)<printed['y']]
            check('内表件数→印字計',(printed['page'],header_y),printed['page'],'件数',expected_count,
                  sum(number(row['内表_件数']) for row in table_rows),unit='件')

    for control in controls:
        level, path = control['level'], control['path']
        if level == '合計':
            children = [q for q in represented.values() if q['level'] == '款']
        elif level == '款':
            children = [q for q in represented.values() if q['level'] == '項' and q['path']['款'] == path['款']]
        elif level == '項':
            children = [q for q in represented.values() if q['level'] == '目'
                        and all(q['path'][key] == path[key] for key in ('款', '項'))]
        else:
            children = [q for q in observation['sections'] if q['path'] == path]
        for field in FIELDS:
            if field == '執行率' or (level == '目' and field not in ('予算現額計', '支出済額', '翌年度繰越額', '不用額')):
                continue
            check(level, path, control['page'], field, number(control['values'][field]),
                  sum(number(q['values'][field]) for q in children) if children else None,
                  '原典に法定節内訳がない' if not children else None)
        if level == '目':
            fiscal_path = tuple(path[key] for key in ('款', '項', '目'))
            check('明細→目', path, control['page'], '支出済額', number(control['values']['支出済額']),
                  sum(leaf_total[fiscal_path].values()) if fiscal_path in leaf_total else None,
                  'rawに当該目の葉がない' if fiscal_path not in leaf_total else None)
    for key, children in descendants.items():
        node = hierarchy_nodes[key]
        if node['amount'] is None:
            continue
        values = [child['amount'] for child in children.values()]
        check('説明内訳→' + node['tier'], node['path'] + (node['name'],), node['page'], '支出済額',
              number(node['amount']), sum(number(value) for value in values if value not in ('－', '－ 円', '-', '—')) if all(value is not None for value in values) else None,
              '金額のない説明階層を含む' if any(value is None for value in values) else None)
    counts = collections.Counter(q['status'] for q in checks)
    result = {'status': 'failed' if issues or counts['不一致'] or counts['保留'] else 'passed',
              'origin_sha256': observation['sha256'], 'raw_sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
              'raw_bytes': raw.stat().st_size, 'raw_rows': len(rows), 'raw_columns': len(schema),
              'source_name_checks': source_name_checks, 'source_amount_checks': source_amount_checks,
              'annual_rows_checked': len(annual_matches), 'monetary_rows_checked': len(monetary_matches),
              'vector_cells_checked': cell_comparisons,
              'personnel_rows_checked':len(personnel_matches),
              'terminal_section_rows_checked':len(terminal_matches),
              'preservation_issues': len(issues), 'hierarchy_counts': dict(counts)}
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (output / 'issues.json').write_text(json.dumps(issues, ensure_ascii=False, indent=2))
    (output / 'checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', required=True, type=Path)
    parser.add_argument('--observations', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = validate(args.raw, args.observations, args.output)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
