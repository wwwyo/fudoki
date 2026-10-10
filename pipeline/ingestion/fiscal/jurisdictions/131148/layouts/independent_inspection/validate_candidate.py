"""Read-back inspection of a candidate parquet against independent origin observations.

Reads the candidate parquet with DuckDB and the independent observations produced
by inspect_origin.py / inspect_notes.py. No construction modules are imported.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import sys
from pathlib import Path

import duckdb

LEVELS = ['款', '項', '目']
NOTE_COLS = ['款_備考', '項_備考', '目_備考', '備考']
AMOUNT_LEFT = [('当初予算額', 'initial'), ('補正予算額', 'amendment'), ('継続費及び繰越事業費繰越額', 'prior'), ('予備費支出及び流用増減', 'transfer'), ('計', 'total')]
AMOUNT_RIGHT = [('支出済額', 'executed'), ('継続費逓次繰越', 'carry_continuing'), ('繰越明許費', 'carry_authorized'), ('事故繰越し', 'carry_accident'), ('不用額', 'unused')]
LEAF_AMOUNT = [('金額', 'total')] + AMOUNT_RIGHT
TOL = 1.0  # left/right page baselines differ by <=0.48pt


def norm(s: str) -> str:
    return (s or '').replace(' ', '')


def load_rows(parquet: Path):
    con = duckdb.connect()
    cols = [c[0] for c in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM '{parquet}')").fetchall()]
    rows = [dict(zip(cols, r)) for r in con.execute(f"SELECT * FROM '{parquet}'").fetchall()]
    return cols, rows


def leaf_path(row):
    return (row['款_番号'], row['項_番号'], row['目_番号'], row['区分_番号'])


def parent_cols(row, level):
    name = LEVELS[level]
    keys = [f'{name}_{c}' for c, _ in AMOUNT_LEFT + AMOUNT_RIGHT] + [f'{name}_番号', f'{name}_名称', f'{name}_備考', f'{name}_物理頁', f'{name}_上端', f'{name}_下端']
    return {k: row[k] for k in keys}


def validate(origin: Path, notes: Path, parquet: Path, out: Path):
    o = json.loads(origin.read_text())
    note_cells = json.loads(notes.read_text()).get('cells', []) if notes else []
    sha = hashlib.sha256(parquet.read_bytes()).hexdigest()
    cols, rows = load_rows(parquet)
    issues = []
    checks = []

    def issue(kind, detail):
        issues.append(dict(kind=kind, **detail))

    # --- structural ---
    if len(rows) != 531:
        issue('row-count', dict(actual=len(rows), expected=531))
    leaf_seen = {}
    for i, r in enumerate(rows):
        for col in ['款_番号', '項_番号', '目_番号', '区分_番号', '区分_名称', '金額']:
            if r[col] is None:
                issue('null-leaf-field', dict(row=i, column=col))
        leaf_seen.setdefault(leaf_path(r), []).append(i)
    for p, idxs in leaf_seen.items():
        if len(idxs) > 1:
            issue('duplicate-leaf-path', dict(path=list(p), rows=idxs))
    order = [(r['物理頁'], r['上端']) for r in rows]
    if order != sorted(order):
        issue('row-order', dict(detail='parquet row order is not printed (page, top) order'))

    leaf_nodes = {tuple(n['path']): n for n in o['nodes'] if n['level'] == 3}
    actual = {}

    # --- parent repetition must be identical on every leaf under the same parent ---
    for level in range(3):
        groups = {}
        for r in rows:
            groups.setdefault(leaf_path(r)[:level + 1], []).append(parent_cols(r, level))
        for key, sets in groups.items():
            if len({json.dumps(s, ensure_ascii=False, sort_keys=True) for s in sets}) != 1:
                issue('inconsistent-parent-repetition', dict(level=level, path=list(key)))

    # --- leaf value read-back vs observed nodes ---
    for n in o['nodes']:
        if n['level'] != 3:
            continue
        p = tuple(n['path'])
        cand = [r for r in rows if leaf_path(r) == p]
        if not cand:
            checks.append(dict(kind='missing-leaf', path=list(p), page=n['page'], status='mismatch', reason='No leaf row for observed setsu'))
            continue
        r = cand[0]
        actual[p] = dict(amounts={e: r[j] for j, e in LEAF_AMOUNT})
        for j, e in LEAF_AMOUNT:
            if norm(r[j]) != norm(n['amounts'][e]):
                issue('leaf-amount-text', dict(path=list(p), column=j, page=n['page'], original=n['amounts'][e], candidate=r[j]))
        if norm(r['区分_名称']) != norm(n['name']):
            issue('leaf-name', dict(path=list(p), page=n['page'], original=n['name'], candidate=r['区分_名称']))
        if r['区分_番号'] != n['number']:
            issue('leaf-number', dict(path=list(p), original=n['number'], candidate=r['区分_番号']))
        if r['物理頁'] != n['page']:
            issue('leaf-page', dict(path=list(p), original=n['page'], candidate=r['物理頁']))
        if r['上端'] is None or abs(r['上端'] - n['y']) > TOL:
            issue('leaf-top', dict(path=list(p), original_y=n['y'], candidate=r['上端']))
        span = None if r['下端'] is None or r['上端'] is None else r['下端'] - r['上端']
        if span is None or span <= 0:
            issue('leaf-bottom', dict(path=list(p), candidate=[r['上端'], r['下端']]))
        else:
            approx = 9.0 + 11.28 * (n['name'].count('\n'))
            if not (approx - 3.5 <= span <= approx + 3.5):
                issue('leaf-bottom-span', dict(path=list(p), name=n['name'], span=span, expected=approx))

    for p in leaf_seen:
        if p not in leaf_nodes:
            issue('extra-leaf-path', dict(path=list(p)))

    # --- parent values read-back vs observed nodes ---
    for level in range(3):
        name = LEVELS[level]
        for n in o['nodes']:
            if n['level'] != level:
                continue
            p = tuple(n['path'])
            under = [r for r in rows if leaf_path(r)[:level + 1] == p]
            if not under:
                checks.append(dict(kind='missing-parent', path=list(p), page=n['page'], status='mismatch', reason='No leaf row under observed parent'))
                continue
            pc = parent_cols(under[0], level)
            actual[p] = dict(amounts={e: pc[f'{name}_{j}'] for j, e in AMOUNT_LEFT + AMOUNT_RIGHT})
            if norm(pc[f'{name}_名称']) != norm(n['name']):
                issue('parent-name', dict(level=level, path=list(p), page=n['page'], original=n['name'], candidate=pc[f'{name}_名称']))
            if pc[f'{name}_番号'] != n['number']:
                issue('parent-number', dict(level=level, path=list(p), original=n['number'], candidate=pc[f'{name}_番号']))
            for j, e in AMOUNT_LEFT + AMOUNT_RIGHT:
                if norm(pc[f'{name}_{j}']) != norm(n['amounts'][e]):
                    issue('parent-amount-text', dict(level=level, path=list(p), column=f'{name}_{j}', page=n['page'], original=n['amounts'][e], candidate=pc[f'{name}_{j}']))
            if pc[f'{name}_物理頁'] != n['page']:
                issue('parent-page', dict(level=level, path=list(p), original=n['page'], candidate=pc[f'{name}_物理頁']))
            if pc[f'{name}_上端'] is None or abs(pc[f'{name}_上端'] - n['y']) > TOL:
                issue('parent-top', dict(level=level, path=list(p), original_y=n['y'], candidate=pc[f'{name}_上端']))
            span = None if pc[f'{name}_下端'] is None or pc[f'{name}_上端'] is None else pc[f'{name}_下端'] - pc[f'{name}_上端']
            if span is None or span <= 0:
                issue('parent-bottom', dict(level=level, path=list(p), candidate=[pc[f'{name}_上端'], pc[f'{name}_下端']]))
            else:
                approx = 9.0 + 11.28 * (n['name'].count('\n'))
                if not (approx - 3.5 <= span <= approx + 3.5):
                    issue('parent-bottom-span', dict(level=level, path=list(p), name=n['name'], span=span, expected=approx))

    for i, r in enumerate(rows):
        if r['款_番号'] is None or (r['款_名称'] and '歳出合計' in norm(r['款_名称'])):
            issue('grand-total-in-raw', dict(row=i))

    # --- control sums ---
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hierarchy import reconcile, number  # noqa: E402
    checks += reconcile(o, actual)

    # The printed 歳出合計 control row is not a raw leaf by design. Its absence is
    # not a pending verification: every printed amount of that row is checked via
    # the 款 sum (款-to-grand) and the independently printed summary row.
    grand_fields_matched = {c['field'] for c in checks if c['kind'] == '款-to-grand' and c['status'] == 'match'}
    for c in checks:
        if c['status'] == 'pending' and c['path'] == []:
            if c['kind'] == 'missing-path':
                c.update(status='absent-by-design', reason='歳出合計は統制行。raw節行に含めない構築判断と整合。印刷10列の全額は款-to-grand・総括行で検算済')
            elif c['kind'] == 'summary-to-detail' and c['field'] in grand_fields_matched:
                c.update(status='match', reason='rawに統制行を持たないため総括の歳出合計行はΣ款の読み戻し値で検算')
            elif c['kind'] == 'summary-to-detail':
                c.update(status='pending', reason='Control field not covered by 款-to-grand')

    # --- remark cells ---
    # A ruled cell's owner is the shallowest node path it vertically spans; the cell
    # is one remark scoped to that node's block. Home cell of a node path = the cell
    # whose span covers it (cells partition each right page). A printed line of cell C
    # placed in a column whose owner node lives in a different cell is attributed to
    # the home cell of that owner node, so identical text printed in two cells does
    # not cross-charge. For cell C a line is wrong when it lands in a column deeper
    # than C's owner level (fabricated affiliation), under a different owner subtree,
    # or never reaches C's owner column.
    home = {}
    for cell in note_cells:
        for p in cell['paths']:
            home[tuple(p)] = id(cell)
    home_by_id = {id(c): c for c in note_cells}

    def home_cell_of(owner_path):
        for cut in range(len(owner_path), 0, -1):
            if tuple(owner_path[:cut]) in home:
                return home[tuple(owner_path[:cut])]
        return None

    note_report = []
    for cell in note_cells:
        owner = min(cell['paths'], key=len)
        owner_level = len(owner) - 1
        placements = []
        verdict = 'ok'
        for line in cell['text'].split('\n'):
            mine, foreign = set(), set()
            for r in rows:
                if r['物理頁'] != cell['page'] - 1:
                    continue
                for col_level, col in enumerate(NOTE_COLS):
                    v = r[col]
                    if not v:
                        continue
                    if norm(line) and norm(line) in [norm(x) for x in v.split('\n')]:
                        owner_path = tuple(leaf_path(r)[:col_level + 1] if col_level < 3 else leaf_path(r))
                        (mine if home_cell_of(owner_path) == id(cell) else foreign).add((col_level, owner_path))
            problems = []
            if not mine and not foreign:
                verdict = 'missing-text'
                problems.append('line not found in any 備考 column on the page')
            for col_level, owner_path in sorted(mine):
                if col_level > owner_level:
                    verdict = 'wrong-affiliation'
                    problems.append(f'fragment in deeper column {NOTE_COLS[col_level]} of row {list(owner_path)}')
                elif col_level == owner_level and owner_path != tuple(owner):
                    verdict = 'wrong-affiliation'
                    problems.append(f'in {NOTE_COLS[col_level]} under {list(owner_path)}, cell owner is {owner}')
                elif col_level < owner_level:
                    verdict = 'wrong-affiliation'
                    problems.append(f'hoisted to {NOTE_COLS[col_level]} of {list(owner_path)}, cell owner is {owner}')
            if not any(col_level == owner_level and owner_path == tuple(owner) for col_level, owner_path in mine):
                if verdict == 'ok':
                    verdict = 'scope-lost'
                problems.append(f'line absent from owner column {NOTE_COLS[owner_level]} (owner {owner})')
            placements.append(dict(line=line, hits=[dict(column=NOTE_COLS[c], owner=list(p)) for c, p in sorted(mine)], foreign=[dict(column=NOTE_COLS[c], owner=list(p)) for c, p in sorted(foreign)], problems=problems))
        note_report.append(dict(page=cell['page'], edges=cell['edges'], owner=owner, owner_level=owner_level, owner_column=NOTE_COLS[owner_level], spanned_paths=cell['paths'], text=cell['text'], verdict=verdict, placements=placements))

    stray = []
    for i, r in enumerate(rows):
        v = r['備考']
        if not v:
            continue
        found = any(cell['page'] - 1 == r['物理頁'] and any(norm(line) and norm(line) in [norm(x) for x in v.split('\n')] for line in cell['text'].split('\n')) for cell in note_cells)
        if not found:
            stray.append(dict(row=i, path=list(leaf_path(r)), value=v))
    for s in stray:
        issue('stray-setsu-note', s)

    result = dict(parquet_sha256=sha, parquet_bytes=parquet.stat().st_size, columns=cols, row_count=len(rows), issues=issues, checks=checks, note_cells=note_report)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'candidate-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(
        issues=dict(Counter(i['kind'] for i in issues)),
        checks=dict(Counter(c['status'] for c in checks)),
        note_verdicts=dict(Counter(c['verdict'] for c in note_report)),
    ), ensure_ascii=False, indent=2))
    for i in issues:
        print('ISSUE', json.dumps(i, ensure_ascii=False))
    for c in checks:
        if c['status'] != 'match':
            print('CHECK', json.dumps(c, ensure_ascii=False))
    for c in note_report:
        if c['verdict'] != 'ok':
            print('NOTE', c['page'], c['owner'], c['verdict'])
            for pl in c['placements']:
                for prob in pl['problems']:
                    print('   ', repr(pl['line']), prob)
    bad = issues + [c for c in checks if c['status'] == 'mismatch'] + [c for c in note_report if c['verdict'] in ('missing-text', 'wrong-affiliation', 'scope-lost')]
    if bad:
        raise SystemExit(1)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for k in ['origin', 'notes', 'parquet', 'output']:
        p.add_argument('--' + k, type=Path, required=True)
    a = p.parse_args()
    validate(a.origin, a.notes, a.parquet, a.output)
