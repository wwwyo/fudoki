"""The generic node builder as a converter: one selected text PDF's account scope to node and amount tables.

`convert(inputs, destination, options)` is the contract of every converter in
`ingestion/fiscal/layouts/`; the entry `fiscal/layouts/generic_text/convert.py` re-exports it. The declarations
are the account and the table ID (and `partial` for one volume of an account printed in several). The pages
are the selection's own scope of that account and direction, so nothing about a coordinate, a column or a
level name is written down.

The builder already produces node and amount tables, so the result is handed to `run.py` as a
`{'nodes': path, 'amounts': path}` descriptor (no wide table, no migration). Beside it the converter writes
the digit-coverage scope (`<table_id>.coverage.json`, `node_tables.coverage_sidecar`).

Money printed as a note (流用・充用・不用額・繰越明許費…) is laid on the 注記 axis the way ADR 0024 keeps it:
a node of kind (the shared dictionary's value) under the account it annotates, the note's own words as its
name, and an amount under the heading 注記金額. The builder keeps such amounts off the account itself, so a
note never adds to a sum. A note whose words give no kind stays unadopted, and its digits stop the coverage
check rather than becoming an amount of something.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re

from ingestion.generic import observe as observe_module
from ingestion.generic.build import run_pages
from ingestion.generic.headers import canonical
from ingestion.generic.layout import is_amount, lines, normalize
from ingestion.generic.layout_settings import load as load_layout
from ingestion.generic.notes import kind_of
from ingestion.lib.node_tables import AMOUNT_COLUMNS, NODE_COLUMNS, coverage_regions, phase_dictionary, write_coverage_words
from ingestion.lib.parquet import write_parquet
from ingestion.paths import CACHE

NOTE_SEPARATOR = '／注記／'
# An account code joined by hyphens (`02-01-02-15-11-01`): printed text in a transfer note's label, and
# amount-shaped to the coverage check, which never lets a hyphen-and-digits word be a label.
ACCOUNT_CODE = re.compile(r'[0-9０-９][-－―—][0-9０-９]')
TOTAL_ROW = re.compile(r'(?:合計|総計)$|^計$')
FOOTNOTE_MARK = re.compile(r'[※＊*][0-9]+')
# An item number printed with its separator (`1.`, `1.職員人件費`, `（1）消耗品費`): the builder keeps the number alone.
ITEM_NUMBER = re.compile(r'^[(（]?([0-9０-９]{1,4})(?:[)）]|[.．](?=$|[^0-9０-９]))')
# The 事業 number printed in brackets under a name (`【010111】`): an identifier, no amount.
BRACKET_CODE = re.compile(r'[【\[][0-9０-９]+[】\]]')
# The part number a work's name ends with (`舗装補修工事(7-1)`): digits of a name, a hyphen between them.
NAME_PART_NUMBER = re.compile(r'[^0-9０-９(（][(（][0-9０-９]{1,2}[-－][0-9０-９]{1,2}[)）]')
RATIO_HEADER = re.compile(r'割合|比率|構成比|率$')
ZERO_MARK = re.compile(r'^0+$')


def scope_pages(source: dict, account: str, within: list | None = None) -> list[int]:
    """The physical pages the selection declares for the account (and the manifest's direction).

    `within` (the conversion's `pages`): the part of the scope this table reads, when one original prints
    several divisions' tables of the account one after another (281000: three committees in one volume)."""
    scopes = [scope for scope in source['scope'] if scope['account'] == account]
    if len(scopes) != 1:
        raise ValueError(f'The selected original needs exactly one scope for {account}')
    pages = [page for first, last in scopes[0]['pages'] for page in range(first, last + 1)]
    if within is None:
        return pages
    chosen = [page for first, last in within for page in range(first, last + 1)]
    if not chosen or not set(chosen) <= set(pages):
        raise ValueError(f'The conversion pages {within} are not within the scope of {account}')
    return chosen


def printed(glyphs: list) -> str:
    """The words as printed: a space where two words on a line are apart (`annotations.py` keeps a heading so)."""
    parts, previous = [], None
    for glyph in sorted(glyphs, key=lambda g: (g.page, round(g.y0), g.x0)):
        if previous is not None and glyph.page == previous.page and abs(glyph.y0 - previous.y0) <= 2 \
                and glyph.x0 - previous.x1 > 2:
            parts.append(' ')
        parts.append(glyph.text)
        previous = glyph
    return ''.join(parts)


def union(glyphs: list) -> tuple[float, float, float, float]:
    boxes = [g.original for g in glyphs]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def lay_notes(built) -> tuple[list[dict], list[dict], list[dict], set, list]:
    """The 注記 axis of a built table: nodes and their amounts (heading 注記金額), and the printed notes
    that no kind could be given (left unadopted: their digits stay in front of the coverage check).

    A note is a remark on an account's own line, or an amount kind printed inside an item whose label is a
    word of the shared annotation dictionary. A column whose printed heading ends in such a word
    (歳出総括／翌年度繰越額／繰越明許費) is a column of the table and never reaches here.
    Both leave the node's own amounts: a note is not part of any sum (ADR 0024).
    """
    nodes, amounts, unresolved, dropped = [], [], [], set()
    codes = []  # words of a note's label that print a joined account code
    seen = set()
    for record in built.annotations:
        label = printed(record['label'])
        # The dictionary first; then what the account says (a reserve's remarks are 充用); then the
        # transfer words of a remark.
        kind = kind_of(label) or record.get('hint') or kind_of(label, words=record['kind'] == 'annotation')
        if kind is None:
            if record['kind'] == 'annotation' and record['runs']:
                where = record['runs'][0][0] if record['runs'] else (record['label'][0] if record['label'] else None)
                unresolved.append({'label': label, 'amounts': [''.join(g.text for g in run) for run in record['runs']],
                                   'page': where.page if where else None, 'y': round(where.y0) if where else None})
            continue
        if record['kind'] == 'kind line':
            dropped.add((record['node_key'], record['heading']))
        codes += [g for g in record['label'] if ACCOUNT_CODE.search(g.text)]
        for run in record['runs']:
            x0, y0, x1, y1 = union(run)
            page = run[0].page
            ident = (record['parent_node_key'], page, round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1), label)
            if ident in seen:
                continue
            seen.add(ident)
            key = 'a-' + hashlib.sha256(json.dumps(ident, ensure_ascii=False).encode()).hexdigest()[:24]
            lx0, ly0, lx1, ly1 = union(record['label']) if record['label'] else (x0, y0, x1, y1)
            nodes.append({'node_key': key, 'parent_node_key': record['parent_node_key'], 'axis_header': '注記',
                          'depth': 1, 'level_header': kind, 'code_text': None, 'name_text': label or None,
                          'physical_page': record['label'][0].page if record['label'] else page,
                          'x0': lx0, 'y0': ly0, 'x1': lx1, 'y1': ly1})
            amounts.append({'node_key': key, 'header_path': '注記金額', 'amount_text': ''.join(g.text for g in run),
                            'unit_text': record['unit'], 'physical_page': page, 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1})
    # The remark amounts were laid on the account (`<header>／注記／<label>`) for the measurement tools; the
    # note replaces them. A remark whose kind is unknown also leaves the account: it is no amount of it.
    return nodes, amounts, unresolved, dropped, codes


def split_notes(built) -> tuple[list[dict], list[dict], list[dict], list[dict], list]:
    """Node amounts without the notes, the 注記 nodes and amounts, the notes left unadopted, and the
    account-code words printed in the labels of the notes that were laid."""
    nodes, amounts, unresolved, dropped, codes = lay_notes(built)
    # Two separately printed notes may have the same words under one subject. They are not
    # repeated subject amounts once both prints have their own note nodes. A missing print,
    # contradictory readings at one position, or an ordinary amount still keeps its conflict.
    position = lambda a: tuple(a[k] for k in ('physical_page', 'x0', 'y0', 'x1', 'y1'))
    identity = lambda a: (*position(a), normalize(a['amount_text']), a['unit_text'])
    adopted = {identity(a) for a in amounts}

    def resolved_note_conflict(issue):
        sources = issue.get('sources', [])
        return (issue['kind'] == 'conflicting amount' and NOTE_SEPARATOR in issue.get('header', '')
                and len(sources) == 2 and len({position(a) for a in sources}) == 2
                and all(identity(a) in adopted for a in sources))

    built.unowned[:] = [issue for issue in built.unowned if not resolved_note_conflict(issue)]
    kept = [a for a in built.amounts
            if NOTE_SEPARATOR not in a['header_path'] and (a['node_key'], a['header_path']) not in dropped]
    return kept, nodes, amounts, unresolved, codes


def amount_columns(logicals) -> list[dict]:
    """The amount bands in the page's own x (a spread's right page is moved back)."""
    return [{'header': '／'.join(band.header), 'x_range': [band.x0 - band.offset, band.x1 - band.offset]}
            for logical in logicals for band in logical.bands if band.kind == 'amount' and band.x0 - band.offset < band.x1 - band.offset]


def excluded_regions(built, logicals, codes, observed) -> list[dict]:
    """Printed digits the builder knows are not amounts, each with a kind of the shared vocabulary.

    - the account codes in a laid note's label (`02-01-02-15-11-01から流用`): 本文;
    - a ratio column (見出しが割合・率): 数量表, the whole column of that page;
    - a column the layout file declares excluded (`columns.<見出し>.excluded`): its kind and reason, the whole column;
    - a footnote mark (`※1`): 本文;
    - a number of zeros printed before a name (`00 一般会計繰出金`): the bullet of a remark drawn as digits, which
      the builder takes off the name (item numbers start from 1): 本文;
    - the 合計 row (歳出合計) and a 計 row (a subtotal): 総括;
    - a frame that is no expenditure detail (no 款・項・目 column, no 予算現額・支出済額… column): 総括. On a spread its label is printed on the other physical page than its
      amounts, so the coverage check's own same-baseline rule cannot see the label.
    """
    regions = coverage_regions([(g.page, g.original, g.text) for g in codes], kind='本文',
                               reason='注記の文言に印字された流用元・流用先の科目コード。金額は注記金額として取り込み済み。')
    for logical in logicals:
        for band in logical.bands:
            if band.excluded:  # a column the layout file declares not taken in, with its kind and reason
                regions.append({**band.excluded, 'pages': [[band.page, band.page]],
                                'x_range': [band.x0 - band.offset, band.x1 - band.offset]})
            if band.kind == 'label' and RATIO_HEADER.search(''.join(band.header)) and band.x0 - band.offset < band.x1 - band.offset:
                regions.append({'kind': '数量表', 'reason': '比率の欄（見出しが割合・率）。金額の欄ではない。',
                                'pages': [[band.page, band.page]], 'x_range': [band.x0 - band.offset, band.x1 - band.offset]})
    marks = [(page.number, (w.x0, w.y0, w.x1, w.y1), w.text) for page in observed for w in page.words
             if FOOTNOTE_MARK.fullmatch(normalize(w.text))]
    regions += coverage_regions(marks, kind='本文', reason='脚注の番号（※1）。金額ではない。')
    part_numbers = [(page.number, (w.x0, w.y0, w.x1, w.y1), w.text) for page in observed for w in page.words
                    if NAME_PART_NUMBER.search(normalize(w.text)) and normalize(w.text).endswith((')', '）'))]
    regions += coverage_regions(part_numbers, kind='本文', reason='工事名の末尾の枝番（(7-1)）。名称の一部で、金額ではない。')
    codes_printed = [(page.number, (w.x0, w.y0, w.x1, w.y1), w.text) for page in observed for w in page.words
                     if BRACKET_CODE.fullmatch(normalize(w.text))]
    regions += coverage_regions(codes_printed, kind='本文', reason='事業の識別番号（【010111】）。金額ではない。')
    regions += coverage_regions([(g.page, g.original, g.text) for g in built.repeated_codes], kind='本文',
                                reason='継続頁に繰り返し印字された科目の番号。直前の同じ科目（番号・名称が一致）の金額と番号であり、新しい金額ではない。')
    regions += coverage_regions([(g.page, g.original, g.text) for g in built.repeated_amounts], kind='親の繰り返し',
                                reason='名前のない行（予備費の節の行）。印字された金額はすべて、直上の款・項・目の同じ列の金額と一致する。親の金額の繰り返しで、新しい金額ではない。')
    regions += coverage_regions(zero_marks(logicals), kind='本文',
                                reason='名前の前に数字で描かれた箇条書きの印（00）。項目の番号は1から始まり、金額ではない。')
    for logical in built.skipped:
        by_page = defaultdict(list)
        for band in logical.bands:
            by_page[band.page].append((band.x0 - band.offset, band.top if band.top is not None else band.body_top,
                                       band.x1 - band.offset, band.body_bottom))
        for page, boxes in by_page.items():
            regions.append({'kind': '総括', 'reason': '款・項・目の欄も予算現額・支出済額の欄も持たない表（流用・繰越の一覧など）。支出の明細ではない。',
                            'page': page, 'bbox': [min(b[0] for b in boxes), min(b[1] for b in boxes),
                                                   max(b[2] for b in boxes), max(b[3] for b in boxes)]})
    totals = [note for note in built.notes if note.get('kind') == 'total amount' and note.get('box')
              and TOTAL_ROW.search(normalize(note.get('label') or ''))]
    regions += [{'kind': '総括', 'reason': '合計の行。款の和には入れない統制値。見開きでは見出しの語が反対の頁にある。',
                 'page': note['page'], 'bbox': list(note['box'])} for note in totals]
    return regions


def zero_marks(logicals) -> list[tuple]:
    """The first word of a band's line when it is only zeros and a name follows it on the line: the item
    numbers of the builder start from 1 (`tree._split_code`), so such a number is a bullet. A cell of an
    amount column that prints a lone 0 is no mark: nothing but amounts follows it in its band."""
    found, seen = [], set()
    for logical in logicals:
        for band in logical.bands:
            for line in lines(band.words):
                first = line[0]
                if (ZERO_MARK.match(normalize(first.text)) and any(not is_amount(g.text) for g in line[1:])
                        and (first.page, first.x0, first.y0) not in seen):
                    seen.add((first.page, first.x0, first.y0))
                    found.append((first.page, first.original, first.text))
    return found


def frame_words(observed, logicals) -> list[tuple]:
    """The printed words inside the table's ruled frame: what digit coverage must account for.

    A page's title, its folio and a note outside the ruled frame are not cells of the table (every measured
    converter reads the table only). The frame keeps its header cells: the repeated 款・項・目 header is what
    confirms a continued page's codes. A band's rectangle is its rule-bounded strip from the frame's top to its
    last row, in the page's own x (a spread's right page is moved back).
    """
    frames = defaultdict(list)
    for logical in logicals:
        for band in logical.bands:
            frames[band.page].append((band.x0 - band.offset, band.top if band.top is not None else band.body_top,
                                      band.x1 - band.offset, band.body_bottom))
    words = []
    for page in observed:
        for word in page.words:
            x, y = (word.x0 + word.x1) / 2, (word.y0 + word.y1) / 2
            if any(left <= x <= right and top <= y <= bottom for left, top, right, bottom in frames.get(page.number, ())):
                # An item number printed with its separator (`1.` `1．`) is the number `1`: the separator is
                # punctuation, and the builder keeps the number without it.
                words.extend(_glued_amount_split(page.number, word))
    return words


BULLET_BEFORE_DIGIT = re.compile(r'^[〇○●◎□■◇◆・]+(?=[0-9０-９])')
GLUED_AMOUNT = re.compile(r'^(.*[^0-9,△▲])([△▲]?[0-9]{1,3}(?:,[0-9]{3})+)$')


def _glued_amount_split(page: int, word) -> list[tuple]:
    """A word printed with its amount touching its name (`…（会長1人・委員9人）134,200`) is two words when the
    name has digits of its own: the builder reads the amount apart (proportionally, as the printed word has
    no gap), and the name's digits are the name's."""
    text = ITEM_NUMBER.sub(r'\1', word.text)
    # A bullet before a count (`○1消耗品費`) is punctuation: the builder keeps the name without it.
    text = BULLET_BEFORE_DIGIT.sub('', text)
    found = GLUED_AMOUNT.match(text)
    if not found or not re.search(r'[0-9]', found.group(1)):
        return [(page, (word.x0, word.y0, word.x1, word.y1), text)]
    width = (word.x1 - word.x0) / len(text)
    cut = word.x0 + len(found.group(1)) * width
    return [(page, (word.x0, word.y0, cut, word.y1), found.group(1)), (page, (cut, word.y0, word.x1, word.y1), found.group(2))]


def observation_cache(source: dict, pages: list[int]) -> Path:
    """Local-only cache of the observation (words and rules). The key is the original's identity, the pages and the observation code."""
    page_key = hashlib.sha256(','.join(map(str, pages)).encode()).hexdigest()[:16]
    # The observation code is part of the key: a cache read after `observe.py` changed would hide the change.
    code_key = hashlib.sha256(Path(observe_module.__file__).read_bytes()).hexdigest()[:8]
    return CACHE / 'generic-observation' / f'{source["sha256"]}-{page_key}-{code_key}.json'


@dataclass
class Table:
    nodes: list[dict]          # the builder's nodes and the 注記 nodes
    amounts: list[dict]        # the builder's amounts (notes taken out) and the 注記 amounts
    unresolved: list[dict]     # notes with no kind in the shared dictionary: left unadopted
    excluded: list[dict]       # printed digits that are not amounts, as the coverage scope declares them
    built: object
    report: object
    observed: list
    logicals: list
    headings: dict = field(default_factory=dict)  # `{(printed heading path, heading kept): count}`
    plain_names: list = field(default_factory=list)  # names the settings declare to be items, not notes


def build_table(source: dict, options: dict, *, stop: bool = True) -> Table:
    """Everything the converter derives from one original, before anything is written."""
    if source.get('format') != 'pdf' or source.get('pdf_type') != 'text':
        raise ValueError('The generic builder reads text PDFs only')
    account = options['account']
    pages = scope_pages(source, account, options.get('pages'))
    layout = load_layout(source['target'], source.get('direction', 'expenditure'))
    if layout and account in layout.get('accounts', {}):
        # An account's own settings replace the document's, key by key: accounts of one
        # original can print the same marks for different levels.
        layout = {**layout, **layout['accounts'][account]}
    built, report, observed, logicals = run_pages(
        Path(source['path']), pages, observation_cache(source, pages),
        document_kind=source['target']['document_kind'], account=account, stop=stop,
        partial=bool(options.get('partial')), direction=source.get('direction'),
        layout=(layout or {}).get('breakdown'), columns=(layout or {}).get('columns'),
        spread=(layout or {}).get('spread'), header=(layout or {}).get('header'),
        text_layer=(layout or {}).get('text_layer'))
    kept, nodes, amounts, unresolved, codes = split_notes(built)
    built.notes.extend({'kind': 'name correction', 'text': text} for text in correct_names(built.nodes, options.get('name_corrections')))
    all_nodes = [*built.nodes, *nodes]
    all_amounts, headings = canonical_headings([*kept, *amounts], all_nodes, source['target']['document_kind'],
                                               (layout or {}).get('header'))
    fine_sections(all_nodes)
    plain = [name for hints in ((layout or {}).get('breakdown') or {}).values() for name in hints.get('plain_names', ())]
    return Table(all_nodes, all_amounts, unresolved, excluded_regions(built, logicals, codes, observed),
                 built, report, observed, logicals, headings, plain)


def correct_names(nodes: list[dict], rules: list[dict] | None) -> list[str]:
    """Names the text layer or OCR misread, put back to what the original prints (`name_corrections` of the
    conversion's options, each checked on the rendered page). A rule names the page, the code and the name as
    read (and its top `y` in points when the same misread repeats on the page); it must find exactly that one
    node, or the conversion stops. A breakdown item's misread number
    (`corrected_code`) is put right with it: the item's place in the tree never depended on it."""
    notes = []
    for rule in rules or ():
        found = [n for n in nodes if n['physical_page'] == rule['page'] and n['name_text'] == rule['observed_name']
                 and n['code_text'] == rule.get('code') and ('y' not in rule or abs(n['y0'] - rule['y']) <= 3)]
        if len(found) != 1:
            raise ValueError(f'A name correction must find one node: {rule["id"]} ({len(found)})')
        found[0]['name_text'] = rule['corrected_name']
        if rule.get('corrected_code'):
            found[0]['code_text'] = rule['corrected_code']
        notes.append(f'{rule.get("code") or ""}{rule["observed_name"]}→{rule.get("corrected_code") or rule.get("code") or ""}{rule["corrected_name"]}')
    return notes


def fine_sections(nodes: list[dict]) -> None:
    """The items printed under a 節 in the 節 column (`10 需用費` / `1 消耗品費`) are 細節 of it, not 節: the 節
    axis holds the legal 節 only (`int_fiscal__expenditure_setsu` names each of its nodes). They go on an axis of
    their own, parent unchanged, depth counted from that axis."""
    for node in nodes:
        if node['axis_header'] == '節' and node['depth'] >= 2:
            node['axis_header'] = '細節'
            node['depth'] -= 1


def canonical_headings(amounts: list[dict], nodes: list[dict], document_kind: str,
                       header: dict | None = None) -> tuple[list[dict], dict]:
    """The amounts with a heading path the shared dictionary does not know, brought to the heading they print
    (`ingestion/generic/headers.py`). Returns the amounts and what was changed, `{(printed, kept): count}`."""
    known = {label for kind, label in phase_dictionary() if kind in ('', document_kind)}
    axis = {n['node_key']: n['axis_header'] for n in nodes}
    level = {n['node_key']: n['level_header'] for n in nodes}
    changed: Counter = Counter()
    for amount in amounts:
        path = canonical(amount['header_path'], axis.get(amount['node_key']), known,
                         bool((header or {}).get('kind_by_characters')))
        if path == '金額' and axis.get(amount['node_key']) == '科目' and level.get(amount['node_key']):
            # A 款・項・目 row that prints its total in the 節 金額 column: the column of that level (`科目／款`).
            path = f"科目／{level[amount['node_key']]}"
        if path != amount['header_path']:
            changed[(amount['header_path'], path)] += 1
            amount['header_path'] = path
    return amounts, changed


def write_files(destination: Path, table_id: str, table: Table) -> dict:
    """The node and amount tables and the coverage scope of one built table."""
    destination = Path(destination)
    nodes_path = destination / f'{table_id}-nodes.parquet'
    amounts_path = destination / f'{table_id}-amounts.parquet'
    pick = lambda columns, rows: [{c.name: row[c.name] for c in columns} for row in rows]
    write_parquet(nodes_path, pick(NODE_COLUMNS, table.nodes), columns=NODE_COLUMNS)
    write_parquet(amounts_path, pick(AMOUNT_COLUMNS, table.amounts), columns=AMOUNT_COLUMNS)
    # The coverage sidecar is named after the table, not its files: `run.py` and `verify` look for it so.
    write_coverage_words(destination / f'{table_id}.parquet', frame_words(table.observed, table.logicals),
                         amount_columns=amount_columns(table.logicals), excluded_regions=table.excluded,
                         plain_names=table.plain_names)
    return {table_id: {'nodes': nodes_path, 'amounts': amounts_path, 'notes': receipt_notes(table)}}


def receipt_notes(table: Table) -> list[str]:
    """What the receipt says of how the table was read (the unit and its check, the tree, the notes)."""
    unit, pattern = table.report.unit, table.report.pattern
    sources = {key: count for key, count in (pattern.get('units') or {}).items() if count}
    named = '・'.join(f'{key} {count}頁' for key, count in sources.items())
    if unit.get('partial'):
        check = f'分冊のため款の和 {unit.get("kan_sum"):,} と印字の歳出合計は照合していない（分冊をまたぐ照合は検査の外）'
    elif unit.get('printed_total') is not None:
        check = f'款の和 {unit["kan_sum"]:,} と印字の「{unit.get("total_label")}」{unit["printed_total"]:,} が一致'
    else:
        check = f'款の和 {unit.get("kan_sum"):,}（頁に歳出合計の印字なし。桁だけを確かめた）'
    kinds = Counter(n['level_header'] for n in table.nodes if n['axis_header'] == '注記')
    notes = [
        '汎用のノード生成機（docs/prd/generic-node-builder）が選定の scope の頁を罫線・見出し・字下げ・番号から読んだ。'
        f'科目の段は {pattern.get("chosen")}、内訳の段は {pattern.get("detail")}。',
        f'金額の単位は {named} から決めた。{check}。',
        f'金額の注記 {sum(kinds.values())} 件（{"・".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "なし"}）を注記軸に置いた。'
        + (f'種類を決められなかった注記 {len(table.unresolved)} 件は取り込んでいない。' if table.unresolved else ''),
    ]
    if table.headings:
        moved = '・'.join(f'{printed}→{kept}' for printed, kept in sorted(table.headings))
        notes.append(f'共有辞書に無い金額の見出し {len(table.headings)} 種（{sum(table.headings.values())} 件）を、印字された語から辞書の見出しに寄せた: {moved}。')
    corrected = [n['text'] for n in table.built.notes if n.get('kind') == 'name correction']
    if corrected:
        notes.append(f'原画で確かめた名称の誤読 {len(corrected)} 件を、管理 JSON の name_corrections で印字に直した: {"・".join(corrected)}。')
    if table.report.skipped_pages:
        notes.append(f'選定の scope が共有していた別の方向（歳入）の頁 {len(table.report.skipped_pages)} 頁は読んでいない。')
    return notes


def convert(inputs: list[dict], destination: Path, options: dict) -> dict:
    if len(inputs) != 1:
        raise ValueError('The generic builder converts one original per table')
    return write_files(destination, options['table_id'], build_table(inputs[0], options))
