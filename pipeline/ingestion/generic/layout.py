"""Stages 2–3: rule-bounded column bands, header paths and band kinds.

A *band* is the strip between two neighbouring vertical rules that reach the
table body. Its header path stacks the header cells (rule-bounded rectangles
above the first printed number) that cover the band, from the top. A page whose
leftmost band holds amounts continues the rows of the previous page (a spread);
the two are read as one logical page with the right page shifted to the right.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import re
import unicodedata

from ingestion.generic.observe import Page, Rule, Word

AMOUNT = re.compile(r'[△▲\-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)')
DASHES = {'－', '―', '—', '-', 'ー'}
SIGNS = {'△', '▲'}
SUBJECT_LEVELS = ('款', '項', '目')
TITLE = re.compile(r'^(?:第?([0-9]+)款|[(（]款[)）]([0-9]+))([^(（0-9]+)')  # `第２款 総務費` or `（款） 2 総 務 費`
# Share of a body row's words that must repeat the table's header words for the row to be a
# header printed again mid-page (a new table for the next 款 on the same page).
REPEATED_HEADER = .6
UNIT = re.compile(r'単位\s*[:：]?\s*(百万円|千円|円)')  # printed 単位; the rest of the unit rule is in units.py
# A header cell that is only the unit of the column below it (`円`, `（千円）`): the unit of the amounts,
# not a level of their heading.
UNIT_CELL = re.compile(r'^[(（]?(百万円|千円|円)[)）]?$')
FOLIO = re.compile(r'[-－―][0-9]+[-－―]')  # a page number printed as `-6-`


def normalize(text: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def is_amount(text: str) -> bool:
    text = normalize(text)
    return text in {normalize(d) for d in DASHES} or AMOUNT.fullmatch(text) is not None


@dataclass
class Glyph:
    """A word placed on a logical page. `x0`/`x1` include the spread offset."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int
    offset: float

    @property
    def original(self) -> tuple[float, float, float, float]:
        return self.x0 - self.offset, self.y0, self.x1 - self.offset, self.y1


@dataclass
class Band:
    x0: float
    x1: float
    page: int
    header: tuple[str, ...]
    rows: list[float]  # horizontal rules crossing this band in the body, sorted
    body_top: float
    body_bottom: float
    words: list[Glyph] = field(default_factory=list)
    kind: str | None = None  # 'amount' | 'label' | None (empty)
    spans: list[tuple[float, float, str]] = field(default_factory=list)  # header cells over the band
    offset: float = 0.0  # how far a spread's right page was moved to the right
    top: float | None = None  # top of the ruled frame (the header cells sit between it and `body_top`)
    left_rules: list[tuple[float, float]] = field(default_factory=list)  # (top, bottom) of each rule drawn on its left edge
    unit_mark: str | None = None  # a header cell that only names the unit (`円`), kept apart from the heading
    axis_header: str | None = None  # a declared printed axis spanning a spread's split header
    excluded: dict | None = None  # a declared column whose printed digits are not taken in (kind and reason)
    staircase: bool = False  # the layout setting `header.staircase`: a level's cell runs right until its own rule starts

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Logical:
    pages: list[int]
    bands: list[Band]
    unit: str | None
    outside: list[Glyph]
    ocr: bool = False  # the words came from OCR (`ingestion/generic/scan.py`): rules for its misreads apply

    @property
    def titles(self) -> list[tuple[str, str, list[Glyph]]]:
        """Table titles naming a 款 outside the table (`第２款 総務費（決算額 … 円）`): code, name, glyphs."""
        found = []
        for line in lines(self.outside):
            match = TITLE.match(normalize(text(line)))
            if match:
                found.append((match.group(1) or match.group(2), match.group(3), line))
        return found


def _crosses(rule: Rule, y: float) -> bool:
    return rule.y0 - 1 <= y <= rule.y1 + 1


def _covers(rule: Rule, x: float) -> bool:
    return rule.x0 - 1 <= x <= rule.x1 + 1


def split_at_rules(word: Word, verticals: list[Rule]) -> list[Word]:
    """Split a word that a vertical rule crosses, by proportional character width."""
    y = (word.y0 + word.y1) / 2
    cuts = sorted(r.x0 for r in verticals if word.x0 + 1 < r.x0 < word.x1 - 1 and _crosses(r, y))
    if not cuts or len(word.text) < 2:
        return [word]
    width = (word.x1 - word.x0) / len(word.text)
    pieces, start = [], 0
    for cut in cuts + [word.x1 + 1]:
        end = len(word.text) if cut > word.x1 else max(start, min(len(word.text), round((cut - word.x0) / width)))
        if end > start:
            pieces.append(Word(word.text[start:end], word.x0 + start * width, word.y0,
                               word.x0 + end * width, word.y1))
        start = end
    return pieces


def repeated_header(page: Page, frame, header_bottom: float, body: list[tuple[int, Word]], header: set[str]) -> set[int]:
    """Words of header rows printed again inside the table body, and of a 款 title row just above them.

    A row is the space between full-width rules; it repeats the header when at least
    REPEATED_HEADER of its (four or more) words are header words. Those words stay outside
    the bands, so a title row becomes a table title (`Logical.titles`).
    """
    x0, x1, top, bottom, _ = frame
    full = sorted(h.y0 for h in page.rules if not h.vertical and h.x0 <= x0 + 3 and h.x1 >= x1 - 3
                  and header_bottom + 1 < h.y0 <= bottom + 1)
    rows = list(zip([header_bottom] + full, full))
    inside = lambda w, a, b: x0 < (w.x0 + w.x1) / 2 < x1 and a < (w.y0 + w.y1) / 2 < b
    skip: set[int] = set()
    for number, (upper, lower) in enumerate(rows):
        words = [(i, w) for i, w in body if inside(w, upper, lower)]
        if len(words) < 4 or sum(normalize(w.text) in header for _, w in words) < REPEATED_HEADER * len(words):
            continue
        skip.update(i for i, _ in words)
        if number:
            above = [(i, w) for i, w in body if inside(w, *rows[number - 1])]
            if above and TITLE.match(normalize(reading([w for _, w in above]))):
                skip.update(i for i, _ in above)
    return skip


def split_digits_at_rules(word: Word, verticals: list[Rule]) -> list[Word]:
    """Split a body word of digits where a vertical rule runs between two of its characters
    (the caller passes only the rules between two 款・項・目 columns).

    Narrow code bands print `１ １` (項1・目1) that Poppler joins into one word. Only a
    rule on a character boundary (within 1pt) splits, so a `10` overrunning a narrow
    band (the rule crosses a character) stays whole.
    """
    raw = normalize(word.text)
    if len(word.text) < 2 or not raw.isdigit():
        return [word]
    width = (word.x1 - word.x0) / len(word.text)
    y = (word.y0 + word.y1) / 2
    cuts = [r for r in verticals if word.x0 + 1 < r.x0 < word.x1 - 1 and _crosses(r, y)
            and abs((r.x0 - word.x0) / width - round((r.x0 - word.x0) / width)) * width <= 1]
    return split_at_rules(word, cuts) if cuts else [word]


def reading(words: list[Word]) -> str:
    """Text of words in reading order: lines by vertical overlap, then left to right.

    Rounding the top edge would split one printed line whose glyphs sit on
    slightly different baselines and read 予算現額 as 算予現額.
    """
    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda w: ((w.y0 + w.y1) / 2, w.x0)):
        if rows:
            last = rows[-1][-1]
            if min(last.y1, word.y1) - max(last.y0, word.y0) >= .5 * min(last.y1 - last.y0, word.y1 - word.y0):
                rows[-1].append(word)
                continue
        rows.append([word])
    return ''.join(w.text for row in rows for w in sorted(row, key=lambda w: w.x0))


def _frames(page: Page, spread: dict | None = None,
            staircase: bool = False) -> list[tuple[float, float, float, float, list[float]]]:
    """Frames as (x0, x1, top, bottom, band edges) from rules that bound a table.

    `staircase` (the layout setting `header.staircase`): the 款・項 cells run down the page with no closing
    rule, so the frame ends at the lowest rule its sides reach that crosses most of its columns or is drawn
    where the sides end (281000)."""
    horizontals = [r for r in page.rules if not r.vertical]
    # A column edge drawn in pieces (the header cell and the rows that have a cell of their own) is one rule.
    drawn: dict[float, float] = defaultdict(float)
    for r in page.rules:
        if r.vertical:
            drawn[round(r.x0, 1)] += r.y1 - r.y0
    xs = {x for x, length in drawn.items() if length > 40}
    if spread is not None:
        # Only the declared spread's gutter: never split a column at an
        # interior row endpoint. The nearest repeated edge on each side bounds it.
        gutter = page.width * spread['gutter']
        endpoints: dict[float, list[float]] = defaultdict(list)
        for rule in horizontals:
            for x in (rule.x0, rule.x1):
                endpoints[round(x, 1)].append(rule.y0)
        repeated = [x for x, ys in endpoints.items() if max(ys) - min(ys) > 40]
        edges = (max((x for x in repeated if x < gutter), default=None),
                 min((x for x in repeated if x > gutter), default=None))
        xs.update(x for x in edges if x is not None)
    xs = sorted(xs)
    edges: list[float] = []
    for x in xs:
        if not edges or x - edges[-1] > 3:
            edges.append(x)
    frames, current = [], []
    for left, right in zip(edges, edges[1:]):
        middle = (left + right) / 2
        inside = [h for h in horizontals if _covers(h, middle)]
        if len(inside) >= 2:
            if not current:
                current = [left]
            current.append(right)
        elif current:
            frames.append(current); current = []
    if current:
        frames.append(current)
    result = []
    for frame in frames:
        middle = [(a + b) / 2 for a, b in zip(frame, frame[1:])]
        # A rule that crosses the frame, or at least most of its columns (a free-text column at the right end that
        # draws no row lines leaves the row rules short of the frame's edge).
        spanning = [h for h in horizontals if all(_covers(h, m) for m in middle)]
        if len(spanning) < 2:
            spanning = [h for h in horizontals if sum(1 for m in middle if _covers(h, m)) >= max(2, .6 * len(middle))]
        if len(spanning) < 2:
            continue
        bottom = max(h.y0 for h in spanning)
        if staircase:
            # The rows of a staircase draw their rules from the deeper columns only: the frame ends at the lowest
            # rule its own sides reach that crosses most of its columns, or that is drawn where the sides end.
            end = min(max((r.y1 for r in page.rules if r.vertical and abs(r.x0 - x) <= 3), default=bottom)
                      for x in (frame[0], frame[-1]))
            bottom = max([h.y0 for h in horizontals if bottom < h.y0 <= end + 2 and h.x0 < frame[-1] and h.x1 > frame[0]
                          and (abs(h.y0 - end) <= 2 or sum(1 for m in middle if _covers(h, m)) >= max(2, .6 * len(middle)))]
                         or [bottom])
        result.append((frame[0], frame[-1], min(h.y0 for h in spanning), bottom, frame))
    # A column that draws no row rules at all (the 支出済額 column printed between two ruled halves of one wide
    # page) splits a table in two. Two frames that start and end on the same rules, one column apart, with the
    # figures of that column printed between them, are one.
    merged: list = []
    for frame in result:
        if merged and abs(frame[2] - merged[-1][2]) <= 2 and abs(frame[3] - merged[-1][3]) <= 2 \
                and 0 < frame[0] - merged[-1][1] <= 200 and sum(
                    1 for w in page.words if merged[-1][1] < (w.x0 + w.x1) / 2 < frame[0]
                    and frame[2] < w.y0 < frame[3] and re.search(r'[0-9０-９]', w.text)) >= 5:
            previous = merged.pop()
            merged.append((previous[0], frame[1], previous[2], previous[3], previous[4] + frame[4]))
        else:
            merged.append(frame)
    return merged


def _header_bottom(page: Page, frame) -> float:
    x0, x1, top, bottom, _ = frame
    horizontals = [r for r in page.rules if not r.vertical]
    # A rule from the frame's left edge across most of it (a free-text column at the right end may draw none).
    full = sorted(h.y0 for h in horizontals
                  if h.x0 <= x0 + 3 and h.x1 >= x1 - 3 and top - 1 <= h.y0 <= bottom + 1)
    if len(full) < 2:  # most of the frame's width (a free-text column at the right end may draw no row rules)
        full = sorted(h.y0 for h in horizontals
                      if h.x0 <= x0 + 3 and h.x1 - x0 >= .6 * (x1 - x0) and top - 1 <= h.y0 <= bottom + 1)
    if len(full) < 2:  # two ruled halves of one frame (see `_frames`): the rules that touch either end
        full = sorted({h.y0 for h in horizontals if (h.x0 <= x0 + 3 or h.x1 >= x1 - 3) and top - 1 <= h.y0 <= bottom + 1})
    digits = [w.y0 for w in page.words if x0 < (w.x0 + w.x1) / 2 < x1 and top + 1 < w.y0 < bottom
              and re.search(r'[0-9０-９]', w.text)]
    first = min(digits) if digits else bottom
    candidates = [y for y in full if top + 1 < y <= first + 1]
    if candidates:
        return candidates[-1]
    return full[1] if len(full) > 1 else top


def level_cells(cells: list[tuple[tuple, str]], edges: list[float]) -> list[tuple[tuple, str]]:
    """A header cell printing the levels together (`款 項 目`) over as many columns as it names gives each
    column its own level: in a staircase the rules between the narrow code columns start below the header.
    The columns name the levels in order, so a scan's reading that drops one of the spaced characters
    (`款目`) still gives 款・項・目 to its three columns."""
    result = []
    for key, value in cells:
        inner = [(left, right) for left, right in zip(edges, edges[1:]) if key[0] - 1 <= left and right <= key[1] + 1]
        if (value.startswith('款') and set(value) <= set('款項目') and len(set(value)) == len(value)
                and len(inner) in (2, 3) and len(value) <= len(inner)):
            result.extend(((left, right, key[2], key[3]), level) for (left, right), level in zip(inner, '款項目'))
        else:
            result.append((key, value))
    return result


def page_bands(page: Page, spread: dict | None = None,
               header: dict | None = None) -> tuple[list[Band], list[Word]]:
    """Bands of every frame on one physical page, and the words outside frames."""
    verticals = [r for r in page.rules if r.vertical]
    horizontals = [r for r in page.rules if not r.vertical]
    # Header words split at rules (a spanning header prints 款項 as one word);
    # body words keep Poppler's extent and belong to the band where they start,
    # so a two-digit code that overruns a narrow band stays whole.
    split = [(index, piece) for index, word in enumerate(page.words) for piece in split_at_rules(word, verticals)]
    used: set[int] = set()
    bands = []
    whole = list(enumerate(page.words))
    staircase = bool((header or {}).get('staircase'))
    for frame in _frames(page, spread, staircase):
        x0, x1, top, bottom, edges = frame
        header_bottom = _header_bottom(page, frame)
        title_ignored = bool((header or {}).get('ignore_frame_title'))
        # Header cells: the rule-bounded rectangle around each header word.
        cells: dict[tuple, list[Word]] = defaultdict(list)
        for index, word in split:
            cx, cy = (word.x0 + word.x1) / 2, (word.y0 + word.y1) / 2
            if not (x0 < cx < x1 and top < cy < header_bottom):
                continue
            used.add(index)
            left = max([r.x0 for r in verticals if r.x0 <= cx and _crosses(r, cy)] or [x0])
            right = min([r.x0 for r in verticals if r.x0 >= cx and _crosses(r, cy)] or [x1])
            upper = max([h.y0 for h in horizontals if h.y0 <= cy and _covers(h, cx)] or [top])
            lower = min([h.y0 for h in horizontals if h.y0 >= cy and _covers(h, cx)] or [header_bottom])
            if title_ignored and left <= x0 + 3 and right >= x1 - 3:
                continue  # the title of the page: it names no column, only the whole frame
            cells[left, right, upper, lower].append(word)
        header_cells = sorted(((key, normalize(reading(ws))) for key, ws in cells.items()), key=lambda c: c[0][2])
        if staircase:
            header_cells = level_cells(header_cells, edges)
        covering_of = lambda middle: [(key, text) for key, text in header_cells if key[0] - 1 <= middle <= key[1] + 1 and text]
        # Only a rule between two 款・項・目 columns splits a body word of digits (`１１` = 項1・目1);
        # amounts stay whole even when a rule crosses them.
        subject = [bool(c) and c[-1][1] in SUBJECT_LEVELS
                   for c in (covering_of((left + right) / 2) for left, right in zip(edges, edges[1:]))]
        between = [r for x, a, b in zip(edges[1:-1], subject, subject[1:]) if a and b
                   for r in verticals if abs(r.x0 - x) <= 3]  # the rules as drawn: a rule ending early splits nothing below it
        body = [(index, piece) for index, word in whole for piece in split_digits_at_rules(word, between)]
        skip = repeated_header(page, frame, header_bottom, body, {normalize(w.text) for ws in cells.values() for w in ws})
        for left, right in zip(edges, edges[1:]):
            middle = (left + right) / 2
            covering = covering_of(middle)
            rows = sorted(h.y0 for h in horizontals if _covers(h, middle) and header_bottom - 1 <= h.y0 <= bottom + 1)
            marks = [text for _, text in covering if UNIT_CELL.match(text)]
            covering = [(key, text) for key, text in covering if not UNIT_CELL.match(text)]
            band = Band(left, right, page.number, tuple(text for _, text in covering), rows, header_bottom, bottom,
                        spans=[(key[0], key[1], text) for key, text in covering], top=top,
                        left_rules=[(r.y0, r.y1) for r in verticals if abs(r.x0 - left) <= 3],
                        unit_mark=UNIT_CELL.match(marks[-1]).group(1) if marks else None, staircase=staircase)
            for index, word in body:
                if index in skip or (staircase and FOLIO.fullmatch(normalize(word.text))):
                    continue  # a staircase frame runs to the foot of the page, over its folio (`-6-`)
                sx, cy = word.x0 + min(2, (word.x1 - word.x0) / 2), (word.y0 + word.y1) / 2
                if re.match(r'^[△▲]|.*,[0-9]{3}', word.text) and is_amount(word.text):
                    # A grouped or signed amount belongs to the column that holds most of it: its sign or
                    # first digits can overhang the column on its left (`△22,990,000`, 133051).
                    sx = (word.x0 + word.x1) / 2
                if left < sx < right and header_bottom < cy < bottom:
                    band.words.append(Glyph(word.text, word.x0, word.y0, word.x1, word.y1, page.number, 0))
                    used.add(index)
            bands.append(band)
    outside = [w for i, w in enumerate(page.words) if i not in used]
    return bands, outside


def lines(words: list[Glyph], tolerance: float = 2.0) -> list[list[Glyph]]:
    """Words of one band grouped into printed lines (by vertical centre)."""
    result: list[list[Glyph]] = []
    for word in sorted(words, key=lambda w: ((w.y0 + w.y1) / 2, w.x0)):
        cy = (word.y0 + word.y1) / 2
        if result and abs(cy - sum((w.y0 + w.y1) / 2 for w in result[-1]) / len(result[-1])) <= tolerance:
            result[-1].append(word)
        else:
            result.append([word])
    return [sorted(line, key=lambda w: w.x0) for line in result]


def runs(line: list[Glyph], gap: float = 2.5) -> list[list[Glyph]]:
    """Touching words of one line: Poppler splits digits and names arbitrarily."""
    result: list[list[Glyph]] = []
    for word in line:
        if result and word.x0 - result[-1][-1].x1 <= gap:
            result[-1].append(word)
        else:
            result.append([word])
    return result


def text(words: list[Glyph]) -> str:
    return ''.join(w.text for w in words)


# A right-hand page joins the page before it only when their row rules line up:
# the share of the shorter page's row rules found on the other page within 1pt,
# after the one vertical shift (up to SPREAD_MAX_SHIFT) that lines up the most
# (132217 prints its right pages 1.7pt higher).
SPREAD_ROW_MATCH = 0.6
SPREAD_MAX_SHIFT = 8.0


def _subject(band: Band) -> bool:
    return bool(band.header) and (band.header[-1] in SUBJECT_LEVELS or '科目' in band.header[0])


def same_rows(left: Page, right: Page) -> bool:
    """Whether two pages print the same rows, i.e. are the halves of one spread."""
    rows = lambda page: sorted({round(r.y0, 1) for r in page.rules if not r.vertical and r.x1 - r.x0 > 50})
    a, b = rows(left), rows(right)
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    shifts = {round(y - x, 1) for x in shorter for y in longer if abs(y - x) <= SPREAD_MAX_SHIFT} or {0.0}
    found = max(sum(1 for x in shorter if any(abs(x + shift - y) <= 1.0 for y in longer)) for shift in shifts)
    return found / len(shorter) >= SPREAD_ROW_MATCH


def logical_pages(pages: list[Page], *, columns: dict | None = None, spread: dict | None = None,
                  header: dict | None = None) -> list[Logical]:
    """Read each page's bands, classify them once per document, then join spreads."""
    per_page = [(page, *page_bands(page, spread, header)) for page in pages]
    # Band kind by content, learned per header path over the whole document so
    # that empty continuation pages keep it. A band is a label band when at least
    # half of its printed lines carry text; otherwise it holds amounts if any
    # grouped number or only zeros appear (item codes alone are labels).
    stats: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for _, bands, _ in per_page:
        for band in bands:
            for line in lines(band.words):
                kinds = set()
                for run in runs(line):
                    value = normalize(text(run))
                    # A unit printed alone in the body (`円` at the top of each 款 row's cells) names the unit,
                    # not a label: counted as text, it turned amount columns into label columns.
                    if value in SIGNS or UNIT_CELL.match(value):
                        continue
                    if not is_amount(value):
                        kinds.add('text')
                    elif ',' in value or len(value.lstrip('△▲-')) > 3:
                        kinds.add('grouped')
                    elif value.lstrip('△▲-') in ('0',) or value in {normalize(d) for d in DASHES}:
                        kinds.add('zero')
                    else:
                        kinds.add('code')
                counts = stats[band.header]
                counts['lines'] += 1
                for kind in kinds:
                    counts[kind] += 1
    for _, bands, _ in per_page:
        for band in bands:
            counts = stats[band.header]
            if band.header and band.header[-1] in SUBJECT_LEVELS:
                band.kind = 'label'
            elif not counts['lines']:
                band.kind = None
            elif counts['text'] * 2 >= counts['lines']:
                band.kind = 'label'
            elif counts['grouped'] or (counts['zero'] and not counts['code']):
                band.kind = 'amount'
            else:
                band.kind = 'label'
            setting = (columns or {}).get('／'.join(band.header), {})
            band.kind = setting.get('kind', band.kind)
            band.axis_header = setting.get('axis_header')
            band.excluded = setting.get('excluded')
            if band.excluded:
                band.kind = None  # not read: its words are no items and its digits a declared exclusion
    result: list[Logical] = []
    observed = {page.number: page for page, _, _ in per_page}
    for page, bands, outside in per_page:
        unit = None
        for line in lines([Glyph(w.text, w.x0, w.y0, w.x1, w.y1, page.number, 0) for w in outside]):
            found = UNIT.search(normalize(text(line)))
            if found:
                unit = found.group(1)
        glyphs = [Glyph(w.text, w.x0, w.y0, w.x1, w.y1, page.number, 0) for w in outside]
        if not bands:
            continue
        first = min(bands, key=lambda b: b.x0)
        previous_page = observed.get(result[-1].pages[-1]) if result else None
        # The right half of a spread starts with an amount column, or (when the 節 column
        # opens the right page) at least carries no 款・項・目 column while the left half does.
        continues = first.kind == 'amount' or (not any(_subject(b) for b in bands) and bool(result)
                                               and any(_subject(b) for b in result[-1].bands))
        if (continues and result and len(result[-1].pages) == 1
                and previous_page is not None and same_rows(previous_page, page)):
            previous = result[-1]
            offset = max(b.x1 for b in previous.bands) + 10 - first.x0
            for band in bands:
                band.x0 += offset; band.x1 += offset; band.offset = offset
                band.spans = [(a + offset, b + offset, t) for a, b, t in band.spans]
                for word in band.words:
                    word.x0 += offset; word.x1 += offset; word.offset = offset
            previous.pages.append(page.number)
            previous.bands.extend(bands)
            previous.unit = previous.unit or unit
            previous.outside.extend(glyphs)
            continue
        result.append(Logical([page.number], bands, unit, glyphs))
    return result
