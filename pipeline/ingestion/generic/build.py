"""Generic node builder: one PDF page range to a node table and an amount table.

Usage: uv run python -m ingestion.generic.build <pdf> <first>-<last>[,<first>-<last>] <out-dir> [--kind settlement]

The only per-table input is the page range, which the source selection already
declares. No coordinates, column names or level names are configured.
"""
from __future__ import annotations

import re

import argparse
from collections import Counter
import json
from pathlib import Path

from ingestion.generic.layout import logical_pages, normalize
from ingestion.generic.observe import Page, Rule, observe
from ingestion.generic.repair import repair
from ingestion.generic.units import check as check_units, resolve as resolve_units
from ingestion.generic.tree import DETAIL_PATTERNS, SUBJECT_PATTERNS, Built, build
from ingestion.lib.node_tables import AMOUNT_COLUMNS, NODE_COLUMNS, amount_phase, phase_dictionary
from ingestion.lib.tree_checks import check_tree
from ingestion.lib.parquet import write_parquet


def page_list(spec: str) -> list[int]:
    pages = []
    for part in spec.split(','):
        first, _, last = part.partition('-')
        pages += range(int(first), int(last or first) + 1)
    return pages


def dictionary_header(header: str, document_kind: str) -> str:
    """The longest suffix of a printed header path that the shared dictionary knows.

    Only for checking: the stored `header_path` keeps every printed level.
    """
    parts = header.split('／')
    known = {label for kind, label in phase_dictionary() if kind in ('', document_kind)}
    for start in range(len(parts)):
        candidate = '／'.join(parts[start:])
        if candidate in known:
            return candidate
    return header


def run(pdf: Path, pages: list[int], cache: Path | None = None, judge=None) -> Built:
    return run_with_repairs(pdf, pages, cache, judge)[0]


DIRECTION_TITLES = {'歳入': 'revenue', '歳出': 'expenditure'}


def page_titles(pages) -> dict[int, str | None]:
    """Each page's direction as printed: the page's own title line (`歳 入`, `歳 出`, above the table), or, for
    a page with none (the right half of a spread, a continued page), the title of the page before it."""
    result, current = {}, None
    for page in sorted(pages, key=lambda p: p.number):
        top = sorted((w for w in page.words if w.y0 < page.height * 0.25), key=lambda w: (w.y0, w.x0))
        rows: list[list] = []
        for word in top:
            if rows and abs(rows[-1][0].y0 - word.y0) <= 2:
                rows[-1].append(word)
            else:
                rows.append([word])
        for row in rows:
            line = normalize(''.join(w.text for w in sorted(row, key=lambda w: w.x0)))
            # `歳入` / `歳出`, or the title of the detail (`(歳入事項別明細書)`).
            title = DIRECTION_TITLES.get(re.sub(r'[()（）]|事項別明細書', '', line))
            if title:
                current = title
                break
        result[page.number] = current
    return result


def image_rules(pdf: Path, page: Page, staircase: bool = False) -> Page:
    """A text page whose ruled grid is a background image (281000): its rules read from the render, as a scan's are."""
    from ingestion.generic.scan import short_rows
    from ingestion.lib import pdf_rules
    detected = short_rows(pdf, pdf_rules.detect(pdf, page.number), staircase)
    rules = [Rule(r.position, r.start, r.position, r.end) for r in detected.vertical]
    rules += [Rule(r.start, r.position, r.end, r.position) for r in detected.horizontal]
    return Page(page.number, page.width, page.height, page.words, rules)


def run_pages(pdf: Path, pages: list[int], cache: Path | None = None, judge=None,
              document_kind: str = 'settlement', account: str | None = None, stop: bool = True,
              partial: bool = False, direction: str | None = None, layout: dict | None = None,
              columns: dict | None = None, spread: dict | None = None, header: dict | None = None,
              text_layer: dict | None = None):
    """Build one table and keep what the converter needs next to it: the repaired pages (their
    words are the digit-coverage scope), the logical pages (their amount bands) and the unit check.

    A page that is printed as the other direction (a revenue page of a scope that shares its pages with the
    summary, `歳 入` over a 款・項 table) is not read: `report.skipped_pages` lists them.
    Stops when the unit check fails (款 sum ≠ printed total, or a general account's digits);
    `stop=False` returns the check in `report.unit` instead, for a measurement that goes on."""
    printed = observe(pdf, pages, cache)
    if (text_layer or {}).get('image_rules'):
        staircase = bool((header or {}).get('staircase'))
        printed = [image_rules(pdf, page, staircase) if not page.rules else page for page in printed]
    titles = page_titles(printed) if direction else {}  # before the repair: it drops what is outside the frame
    observed, report = repair(pdf, printed, bool((text_layer or {}).get('form_clips')))
    if direction:
        report.skipped_pages = [number for number, title in titles.items() if title not in (None, direction)]
        observed = [page for page in observed if page.number not in report.skipped_pages]
    logicals = logical_pages(observed, columns=columns, spread=spread, header=header)
    # A staircase declares how the levels are marked: each level's band (see `layout.level_cells`).
    built, choice = choose_pattern(logicals, document_kind, judge, layout,
                                   ('bands',) if (header or {}).get('staircase') else SUBJECT_PATTERNS)
    report.pattern = choice
    unit = check_units(built, document_kind, account, partial)
    if unit['stopped'] and stop:
        raise ValueError(f'Unit check failed: {unit}')
    report.unit = unit
    return built, report, observed, logicals


def run_with_repairs(pdf: Path, pages: list[int], cache: Path | None = None, judge=None,
                     document_kind: str = 'settlement', account: str | None = None):
    """Build one table; stop when the unit check fails (款 sum ≠ printed total, or a general account's digits)."""
    built, report, _, _ = run_pages(pdf, pages, cache, judge, document_kind, account)
    return built, report


def closure(built: Built, document_kind: str) -> dict:
    """How well a tree closes: the selection criterion, kept in one place.

    The subject pattern decides the 款・項・目 levels, so the score is the
    subject axis's own closure: parent/child groups on the subject axis whose
    sums agree, minus twice those that disagree. Ties go to named subject nodes
    minus unnamed ones, then to the whole tree's closure (a pattern that splits
    a code from the name printed below it makes a nameless node per code, 134015).
    A pattern that finds no subject column gets no score. (Scoring the whole tree
    let a pattern that found 7 of 25 subject nodes win on the breakdown axes
    alone, 131148.)
    """
    result = check(built, document_kind)
    subject_results = [r for r in result['results'] if r['axis_header'] == '科目']
    agree = sum(1 for r in subject_results if r['status'] == '一致')
    disagree = len(subject_results) - agree
    total_agree, total_disagree = result['counts'].get('一致', 0), result['counts'].get('不一致', 0)
    subject = sum(1 for n in built.nodes if n['axis_header'] == '科目')
    named = sum(1 for n in built.nodes if n['axis_header'] == '科目' and n['name_text'])
    return {'subject_agree': agree, 'subject_disagree': disagree, 'agree': total_agree, 'disagree': total_disagree,
            'issues': len(result['issues']), 'subject_nodes': subject, 'named_subject_nodes': named,
            'score': (agree - 2 * disagree, named - (subject - named), total_agree - 2 * total_disagree)}


def choose_pattern(logicals, document_kind: str = 'settlement', judge=None, layout: dict | None = None,
                   patterns: tuple[str, ...] = SUBJECT_PATTERNS) -> tuple[Built, dict]:
    """Decide the unit, build the tree with every subject pattern and keep the one that closes best."""
    unit_sources = resolve_units(logicals, document_kind)
    trials = {}
    for pattern in patterns:
        built = build(logicals, judge, pattern, layout=layout)
        trials[pattern] = (built, closure(built, document_kind))
    # A pattern that finds no subject column is not a reading of this document.
    eligible = [p for p in trials if trials[p][1]['subject_nodes']] or list(trials)
    best = max(eligible, key=lambda p: (*trials[p][1]['score'], -SUBJECT_PATTERNS.index(p)))
    # Breakdown levels per axis: indentation or numbering shapes, whichever closes a larger
    # share of that axis's parent/child groups. A share, not a count: flattening an axis
    # removes comparisons and would win a count (杉並の備考: 6,670 items on one level).
    per_axis = {}
    for detail in DETAIL_PATTERNS:
        built = trials[best][0] if detail == 'indent' else build(logicals, judge, best, detail, layout)
        for result in check(built, document_kind)['results']:
            if result['axis_header'] != '科目':
                counts = per_axis.setdefault(result['axis_header'], {d: [0, 0] for d in DETAIL_PATTERNS})
                counts[detail][0 if result['status'] == '一致' else 1] += 1
    share = lambda c: (c[0] / (c[0] + c[1]) if c[0] + c[1] else 0, c[0])
    chosen = {axis: max(DETAIL_PATTERNS, key=lambda d: (*share(counts[d]), -DETAIL_PATTERNS.index(d)))
              for axis, counts in per_axis.items()}
    built = trials[best][0] if all(d == 'indent' for d in chosen.values()) else build(logicals, judge, best, chosen, layout)
    return built, {'chosen': best, 'detail': chosen, 'detail_scores': per_axis, 'units': unit_sources,
                   'trials': {p: c for p, (_, c) in trials.items()}}


def check(built: Built, document_kind: str = 'settlement') -> dict:
    amounts = [{**a, 'header_path': dictionary_header(a['header_path'], document_kind)} for a in built.amounts]
    return check_tree(built.nodes, amounts, document_kind)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('pdf', type=Path)
    parser.add_argument('pages')
    parser.add_argument('out', type=Path)
    parser.add_argument('--kind', default='settlement')
    parser.add_argument('--table', default='generic')
    parser.add_argument('--account', help='the account name (一般会計 turns on the digit check of the unit)')
    parser.add_argument('--jev', action='store_true', help='variant B: Jev chooses codeless remark line roles')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    client = None
    judge = None
    if args.jev:
        from ingestion.generic.jev import Client, line_roles
        client = Client(args.out / f'{args.table}-jev-cache.json')
        judge = lambda features: line_roles(client, features)
    built, repairs = run_with_repairs(args.pdf, page_list(args.pages), args.out / f'{args.table}-observed.json', judge,
                                      document_kind=args.kind, account=args.account)
    result = check(built, args.kind)
    for kind in ('nodes', 'amounts'):
        (args.out / f'{args.table}-{kind}.parquet').unlink(missing_ok=True)
    write_parquet(args.out / f'{args.table}-nodes.parquet', built.nodes, columns=NODE_COLUMNS)
    write_parquet(args.out / f'{args.table}-amounts.parquet', built.amounts, columns=AMOUNT_COLUMNS)
    report = {'nodes': len(built.nodes), 'amounts': len(built.amounts),
              'unowned': dict(Counter(u['kind'] for u in built.unowned)),
              'notes': dict(Counter(n['kind'] for n in built.notes)),
              'tree_check': {'passed': result['passed'], 'counts': result['counts'], 'issues': result['issues'][:20]},
              'mismatches': [r for r in result['results'] if r['status'] != '一致'][:50],
              'unowned_examples': built.unowned[:50], 'repairs': repairs.as_dict()}
    if client is not None:
        report['jev'] = {'model': 'jev-1.13.0', 'requests': client.requests, 'input_tokens': client.input_tokens,
                         'cost_usd': round(client.cost, 4), 'seconds': round(client.seconds, 1)}
    (args.out / f'{args.table}-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: report[k] for k in ('nodes', 'amounts', 'unowned', 'notes', 'tree_check', 'jev') if k in report},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
