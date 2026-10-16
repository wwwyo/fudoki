"""Stages 4–5: items, left–right ownership of amounts, and the tree.

* Label groups: neighbouring label bands whose header leaves are 款・項・目 form
  the subject axis (科目). Every other label band is its own axis, named by the
  lowest header cell that spans it together with its amount bands.
* Items: in a label group, a printed code or an amount starts an item; other
  lines continue it. A rule-bounded cell holding one code is one item, so a code
  printed beside a wrapped name joins it.
* Left–right: an amount in an amount band belongs to the item, in the nearest
  label group to its left, whose first line lies in the amount's rule-bounded
  row. An amount inside a label band belongs to the item on its own line.
* Up–down: subject depth is the 款・項・目 band where the code starts. Other axes
  rank the indentation of the name start, learned over the document. Parents are
  the nearest shallower open item; the roots of other axes hang under the open
  subject item. A subject code equal to the open one at that depth repeats it.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from bisect import bisect_right
from math import floor
from dataclasses import dataclass, field
import hashlib
import re
import unicodedata

from ingestion.generic.notes import kind_of, reads_as_note
from ingestion.lib.node_tables import phase_dictionary
from shared.amount import number
from ingestion.generic.layout import (SUBJECT_LEVELS, UNIT_CELL, Band, Glyph, Logical, is_amount, lines, normalize,
                                      runs, text)

# A leading item number; the separator after it (`1.議会費`, `1．`) is not part of the name.
CODE = re.compile(r'^[(（]?([0-9０-９]{1,4})[)）]?(?:[.．](?=[^0-9０-９]))?(?=\D|$)')
BARE_CODE = re.compile(r'^[0-9０-９]{1,4}$')
TRANSFER = re.compile(r'(流用|充用|充当|予備費支出|予備費充当|予備費[よか]り|第[0-9０-９]+節[へか]|^第[0-9０-９]+[款項目節]|^[○〇●]?同[款項目])')
# A kind word printed above an amount inside an amount column's cell (a stacked carry-over column).
STACKED_KIND = re.compile(r'(翌年度)?(繰越明許費?|事故繰越し?|継続費逓次繰越|不用額)')
# A total row ends in 合計・総計 (`歳出合計`); a name that contains the letters (`長期総合計画に要する経費`) is not one.
TOTAL = re.compile(r'(合計|総計)$|^計$')
# A reserve's remark that names where it went: `…へ`, `…へ充当`.
RESERVE_DESTINATION = re.compile(r'へ(?:予備費)?(?:充当|充用)?$')


@dataclass
class Group:
    bands: list[Band]
    axis: str
    subject: bool
    mode: str = 'bands'  # how the subject group marks its levels (see SUBJECT_PATTERNS)
    levels: int | None = None  # number of subject levels

    @property
    def x0(self) -> float:
        return self.bands[0].x0

    @property
    def x1(self) -> float:
        return self.bands[-1].x1


@dataclass
class Item:
    group: Group
    page: int
    lines: list[list[Glyph]]
    code: str | None
    name: str
    indent: float
    level: int | None = None  # subject level index (0 = 款)
    level_name: str | None = None  # printed level name when it is not a band header
    amounts: list[tuple[str, list[Glyph]]] = field(default_factory=list)  # (header path, glyphs)
    role: str = 'node'  # node | note | total
    key: str | None = None
    parent: 'Item | None' = None
    depth: int | None = None
    fixed_anchor: float | None = None
    decided: bool = False  # role chosen by a judgment, not by the geometric rules
    hint: str | None = None  # the kind of the note whose parts this item prints (`note_breakdown`)
    kinds: list[tuple[list[Glyph], list[Glyph], str]] = field(default_factory=list)  # (label, amount run, heading) of kind lines

    @property
    def glyphs(self) -> list[Glyph]:
        return [g for line in self.lines for g in line]

    @property
    def y0(self) -> float:
        return min(g.y0 for g in self.glyphs)

    @property
    def y1(self) -> float:
        return max(g.y1 for g in self.glyphs)

    @property
    def anchor(self) -> float:
        """Vertical centre of the line that carries the code (or the first line)."""
        if self.fixed_anchor is not None:
            return self.fixed_anchor
        for line in self.lines:
            if self.code is not None and CODE.match(normalize(text(line))):
                return sum((g.y0 + g.y1) / 2 for g in line) / len(line)
        line = self.lines[0]
        return sum((g.y0 + g.y1) / 2 for g in line) / len(line)


# How a document marks subject (款・項・目) levels. Each is tried on every
# document and the tree that closes best wins (build.choose_pattern).
SUBJECT_PATTERNS = ('bands', 'names', 'indent')
# A header cell that names the subject column: 科目, or the levels themselves (`款`, `項・目`, `(款)(項)(目)`).
# A cell that only contains 項目 inside a longer name (`予備費充当項目`) names something else.
SUBJECT_CELL = re.compile(r'(?:[(（]?[款項目][)）]?[・･、,，]?)+')


def subject_header(header: tuple[str, ...]) -> bool:
    cells = [re.sub(r'\s+', '', cell) for cell in header]
    return any('科目' in cell or SUBJECT_CELL.fullmatch(cell) for cell in cells)


def _breakdown_axis(band: Band, bands: list[Band]) -> str:
    """The lowest header cell spanning this band and a neighbouring amount band.

    A cell that the page edge cuts (a heading printed across a spread, 131148's
    節 over 区分 | 金額) counts as spanning the amount band on the other page.
    """
    if band.axis_header:
        return band.axis_header
    axis = band.header[-1] if band.header else '備考'
    page_end = max(b.x1 for b in bands if b.page == band.page)
    column = _column(band, bands)
    for x0, x1, label in reversed(band.spans[:-1]):
        covered = [b for b in bands if x0 - 1 <= b.center <= x1 + 1]
        if not all(any(b is c for c in column) or b.kind != 'label' for b in covered):
            continue
        if any(b.kind == 'amount' for b in covered) or (x1 >= page_end - 1 and band.x1 >= page_end - 1):
            return label
    return axis


def _column(band: Band, bands: list[Band]) -> list[Band]:
    """The label bands that are one column with this one: a column that a rule splits in two (the numbers
    of the 節 left of their names) has the same heading over both parts, and they touch."""
    ordered = sorted((b for b in bands if b.kind == 'label' and b.page == band.page and b.header == band.header),
                     key=lambda b: b.x0)
    if band not in ordered:
        return [band]
    start = end = ordered.index(band)
    while start > 0 and abs(ordered[start - 1].x1 - ordered[start].x0) < 1.5:
        start -= 1
    while end + 1 < len(ordered) and abs(ordered[end].x1 - ordered[end + 1].x0) < 1.5:
        end += 1
    return ordered[start:end + 1]


def groups(logical: Logical, pattern: str = 'bands') -> list[Group]:
    """Label bands into groups; `pattern` decides which bands carry the subject and how.

    bands  – 款・項・目 each have a band; the band where a code starts is the level.
    names  – as bands, plus the neighbouring name band that the codes share.
    indent – one subject column; levels by indentation (codes optional).
    """
    bands = sorted((b for b in logical.bands), key=lambda b: b.x0)
    labels = [b for b in bands if b.kind == 'label']
    subject_bands: list[Band] = []
    mode, count = pattern, None
    if pattern in ('bands', 'names'):
        for index, band in enumerate(bands):
            if band.kind == 'label' and band.header and band.header[-1] in SUBJECT_LEVELS:
                if subject_bands and subject_bands[-1] is not bands[index - 1]:
                    break
                subject_bands.append(band)
        count = len(subject_bands)
        if pattern == 'names' and subject_bands:
            following = bands.index(subject_bands[-1]) + 1
            if following < len(bands) and bands[following].kind == 'label' and not (
                    bands[following].header and bands[following].header[-1] in SUBJECT_LEVELS) and (
                    not bands[following].header or subject_header(bands[following].header)):
                subject_bands.append(bands[following])
            else:
                subject_bands = []
    elif pattern == 'indent':
        # Every neighbouring label band headed by 款・項・目 (or 科目) is one subject
        # column; a staircase of narrow level columns is read by indentation too.
        for band in labels:
            if band.header and subject_header(band.header):
                subject_bands = [band]
                index = bands.index(band)
                while index + 1 < len(bands) and bands[index + 1].kind == 'label' and (
                        bands[index + 1].header == band.header
                        or (bands[index + 1].header and subject_header(bands[index + 1].header))):
                    index += 1
                    subject_bands.append(bands[index])
                break
    result: list[Group] = []
    for band in bands:
        if band in subject_bands:
            if band is subject_bands[0]:
                result.append(Group(list(subject_bands), '科目', True, mode, count))
            continue
        if band.kind != 'label':
            continue
        last = result[-1] if result else None
        if (last is not None and not last.subject and any(last.bands[-1] is b for b in _column(band, bands))
                and last.bands[-1] is not band):
            # A column that a rule splits in two (the numbers of the 節 left of its names): one column.
            last.bands.append(band)
            continue
        result.append(Group([band], _breakdown_axis(band, bands), False))
    return result


BULLET = re.compile(r'^[〇○●◎□■◇◆]')
# The words that qualify a printed amount as carried over (`一部繰越明許`, `逓次繰越`), printed after it.
CARRY_OVER_TAG = re.compile(r'[(（]?(?:一部)?(?:繰越明許費?|逓次繰越|事故繰越し?)[)）]?')
# Every parenthesised remark at the end of a name (`委託料（…へ流用△280,000）（…から流用1,815,000）`).
PAREN_TAIL = re.compile(r'(?:[(（][^()（）]*[)）])+$')
# A number printed against a counter word (`110番`, `3歳児`, `3階`, `2025年`) is a count in a name.
# An item number glued to a year it is followed by (`42025年…`: 4 and 2025年).
YEAR_LED = re.compile(r'^([0-9]{1,2})(?:19|20)[0-9]{2}年')
COUNTED = re.compile(r'^[0-9０-９]+(?:番(?!号)|歳|階|年|か月|ヶ月|箇所|世帯|ミリ|キロ|メートル|インチ)')
GROUPED = re.compile(r'[△▲]?[0-9]{1,3}(?:,[0-9]{3})+')
YEN_AMOUNT = re.compile(r'[△▲]?[0-9]{1,3}(?:,[0-9]{3})+円')
# An amount printed against text spilling in from the next band (`44,406,439,217明許`).
LEADING_AMOUNT = re.compile(r'([△▲]?[0-9]{1,3}(?:,[0-9]{3})+)(?=[^0-9,])')


def has_text(name: str) -> bool:
    """Whether a name has a letter (kana, kanji, latin)."""
    return any(c.isalpha() for c in normalize(name))


def is_account_code(name: str) -> bool:
    """A printed account code (`・020601【010261】`): digits and punctuation only, four digits or more. A
    lone `)` that closes a wrapped name and an amount with grouping or a negative mark are no codes."""
    value = normalize(name)
    return (not has_text(value) and not value.startswith('-') and not any(c in value for c in ',△▲')
            and sum(c.isdigit() for c in value) >= 4)


def note_breakdown(items: list['Item'], subject_starts: tuple[float, ...] = (), min_parts: int = 2) -> None:
    """Lines printed under a note that add up to its amount are its parts, not items of the breakdown.

    `繰越事業費不用額 308,157,706 円` over `役務費 3,897,706 円` and `負担金、補助及び交付金 304,260,000 円`:
    the two lines are the note's own breakdown. They take the note's kind (a wrapped line of a note's cell
    inherits it, ADR 0024). Two or more lines whose sum is exactly the note's amount: a single line of the
    same amount could as well be an item that costs what the note says. A document that prints one
    part per note says so in its layout settings (`single_part_notes`: `min_parts` is 1).
    """
    for index, note in enumerate(items):
        if note.role != 'annotation' or note.code is not None or len(note.amounts) != 1:
            continue
        header, run = note.amounts[0]
        total = number(normalize(text(run)))
        kind = kind_of(PAREN_TAIL.sub('', note.name), words=True)
        if not total or total < 0 or kind is None:
            continue
        taken, running = [], 0
        subject = bisect_right(subject_starts, note.anchor)
        previous = note
        for follower in items[index + 1:]:
            if follower.role != 'node' or follower.code is not None or len(follower.amounts) != 1 \
                    or follower.amounts[0][0] != header or follower.kinds or not has_text(follower.name):
                break
            if (bisect_right(subject_starts, follower.anchor) != subject or follower.page != previous.page
                    or follower.y0 - previous.y1 > 1.8 * max(g.y1 - g.y0 for g in follower.glyphs)):
                break
            value = number(normalize(text(follower.amounts[0][1])))
            if value is None or value < 0 or running + value > total:
                break
            taken.append(follower)
            previous = follower
            running += value
            if running == total:
                break
        if running == total and len(taken) >= min_parts:
            for follower in taken:
                follower.role = 'annotation'
                follower.hint = kind


def _split_code(line_text: str) -> tuple[str | None, str]:
    """A leading item number and the name. Numbers start from 1, so a leading 0 is a
    bullet drawn as a digit; bullet marks (〇) mark a level and are not part of the name."""
    found = CODE.match(line_text)
    if not found or int(unicodedata.normalize('NFKC', found.group(1))) == 0:
        if found:
            line_text = line_text[found.end():].strip()
        return None, BULLET.sub('', line_text)
    return found.group(1), line_text[found.end():].strip()


def _cell(band: Band, y: float) -> tuple[float, float]:
    above = [r for r in band.rows if r <= y + .5]
    below = [r for r in band.rows if r > y + .5]
    return (above[-1] if above else band.body_top, below[0] if below else band.body_bottom)


def _split_line(line: list[Glyph], amount_brackets: bool = False) -> tuple[list[Glyph], list[list[Glyph]]]:
    parts = runs(line)
    if amount_brackets and normalize(text(line)).endswith(')'):
        for start in range(len(parts) - 1, -1, -1):
            tail = [g for part in parts[start:] for g in part]
            shown = normalize(text(tail))
            if shown.startswith('(') and shown.endswith(')') and number(shown) is not None:
                return [g for part in parts[:start] for g in part], [tail]
    # The unit mark printed after an amount (`12,409,365 円`, or touching it: `393,230円`) is not part of the
    # name and not a digit: the amount stays the line's last run.
    if parts and len(parts[-1]) == 1 and YEN_AMOUNT.fullmatch(normalize(parts[-1][0].text)):
        glyph = parts[-1][0]
        width = (glyph.x1 - glyph.x0) / len(glyph.text)
        keep = len(glyph.text) - 1
        parts[-1] = [Glyph(glyph.text[:keep], glyph.x0, glyph.y0, glyph.x0 + keep * width, glyph.y1, glyph.page, glyph.offset)]
    # The carry-over a printed amount partly is (`通信運搬費 597,301 一部繰越明許`): a word after the amount that
    # is no part of the item's name or of the amount. The amount stays the line's last run.
    if len(parts) >= 3 and CARRY_OVER_TAG.fullmatch(normalize(text(parts[-1]))) and is_amount(text(parts[-2])):
        parts.pop()
    while parts and len(parts[-1]) > 1 and normalize(parts[-1][-1].text) == '円' and is_amount(text(parts[-1][:-1])):
        parts[-1] = parts[-1][:-1]
    while len(parts) > 1 and normalize(text(parts[-1])) == '円' and is_amount(text(parts[-2])):
        parts.pop()
    money = []
    while parts and is_amount(text(parts[-1])) and len(parts) > 1:
        money.insert(0, parts.pop())
    if len(parts) == 1 and normalize(text(parts[0])) == '0':
        return [], [parts[0]]  # a line that is only `0` is a printed zero amount: no item is numbered 0
    if len(parts) == 1 and GROUPED.fullmatch(normalize(text(parts[0]))):
        # A line that is only a grouped amount (`10,000` under a long name) is the
        # amount of the item above, not an item numbered 10. A bare `10` stays a label.
        return [], [parts[0]]
    if not money and parts:
        # A grouped amount printed flush against the name (`…】112,408,043`),
        # possibly starting inside a Poppler word: split that word proportionally.
        last = parts[-1]
        joined = text(last)
        found = re.match(r'^(.*[^0-9,△▲])([△▲]?[0-9]{1,3}(?:,[0-9]{3})+)$', joined)
        if found:
            cut, consumed = len(found.group(1)), 0
            for index, glyph in enumerate(last):
                if consumed + len(glyph.text) > cut:
                    inner = cut - consumed
                    if inner:
                        width = (glyph.x1 - glyph.x0) / len(glyph.text)
                        x = glyph.x0 + inner * width
                        head = Glyph(glyph.text[:inner], glyph.x0, glyph.y0, x, glyph.y1, glyph.page, glyph.offset)
                        tail = Glyph(glyph.text[inner:], x, glyph.y0, glyph.x1, glyph.y1, glyph.page, glyph.offset)
                        parts[-1], money = last[:index] + [head], [[tail] + last[index + 1:]]
                    else:
                        parts[-1], money = last[:index], [last[index:]]
                    break
                consumed += len(glyph.text)
    return [g for part in parts for g in part], money


def _leading_amount(glyph: Glyph) -> Glyph:
    """The amount part of a word in an amount band that runs on into text; other words unchanged."""
    found = LEADING_AMOUNT.match(glyph.text)
    if not found:
        return glyph
    width = (glyph.x1 - glyph.x0) / len(glyph.text)
    return Glyph(found.group(1), glyph.x0, glyph.y0, glyph.x0 + len(found.group(1)) * width, glyph.y1, glyph.page, glyph.offset)


# Headings of an amount column that sort by source of funds: names of items as well (`保険料` under `通信運搬費`).
FUNDING_HEADINGS = {'その他', '一般会計繰入金', '一般財源', '国庫支出金', '国都支出金', '都支出金', '地方債', '市債', '保険料'}


def is_amount_kind(label: str) -> bool:
    """A printed amount kind (支出済額・繰越明許費・不用額…) rather than an item name."""
    known = {header for _, header in phase_dictionary()} - FUNDING_HEADINGS
    return label in known or re.fullmatch(r'(翌年度)?(繰越明許費?|事故繰越し?|継続費逓次繰越|不用額|本年度支出額|支出済額)', label) is not None


def code_margins(logicals: list[Logical]) -> dict[str, set[int]]:
    """Left margins (rounded x) where printed codes start, per non-subject axis.

    A leading number counts as a code only at a margin where most lines start
    with one, so a name that begins with a digit (`3歳児…`) stays a name.
    """
    votes: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    for logical in logicals:
        for group in groups(logical):
            if group.subject:
                continue
            for line in lines([w for band in group.bands for w in band.words]):
                label, _ = _split_line(line)
                if label:
                    coded = _split_code(normalize(text(label)))[0] is not None
                    for margin in _margins(label):
                        votes[group.axis, margin][0 if coded else 1] += 1
    margins: dict[str, set[int]] = defaultdict(set)
    for (axis, x), (coded, plain) in votes.items():
        if coded > plain:
            margins[axis].update({x - 1, x, x + 1})
    return margins


def _margins(label: list[Glyph]) -> tuple[int, int]:
    """Where a line starts, and where a leading number would end (codes align either way)."""
    first = label[0]
    raw = normalize(first.text)
    digits = len(raw) - len(raw.lstrip('0123456789'))
    # The number's own width: a half-width digit is half the line height. (The word's average character
    # width is a kanji's: it put the end of `1` in `1歳児…` where `02` of `02管理用備品` ends, 132276.)
    height = first.y1 - first.y0
    full = sum(1 for c in first.text[:max(digits, 1)] if not c.isascii())
    width = (max(digits, 1) - full) * height / 2 + full * height
    return round(first.x0), 10000 + round(first.x0 + width)


def strip_ancestor_codes(group: Group) -> list[Glyph]:
    """The ancestors' codes a page prints before an item's own (`10 10 徴税費`: 款 10, then 項 10; `10 5 10 (文書広報課)`:
    款, 項, then the 目 that the page goes on with; `10 1 2` alone, the name left out). Each is a bare number word of its own on the line's left;
    all but the last are removed from the band words and returned, so the line reads as its own code and name."""
    removed: list[Glyph] = []
    for line in lines([w for band in group.bands for w in band.words]):
        label = sorted(line, key=lambda w: w.x0)
        leading = 0
        while leading < len(label) and BARE_CODE.match(normalize(label[leading].text)):
            leading += 1
        if leading >= 2 and all(
                label[i + 1].x0 - label[i].x1 >= 2 and label[i + 1].x0 > label[i].x0 for i in range(leading - 1)):
            removed.extend(label[:leading - 1])
    gone = {id(g) for g in removed}
    for band in group.bands:
        band.words = [w for w in band.words if id(w) not in gone]
    return removed


def entries_of(group: Group, margins: set[int] | None = None, amount_brackets: bool = False) -> list[tuple]:
    """Printed lines of a label group as (label glyphs, amount runs, code, name)."""
    entries = []
    for line in lines([w for band in group.bands for w in band.words]):
        label, money = _split_line(line, amount_brackets)
        line_text = normalize(text(label))
        code, name = _split_code(line_text)
        raw_text = text(label).strip()
        if code is not None and len(name) > 1 and re.match(r'[０-９]{3,}', raw_text):
            code, name = None, line_text  # `２０３０ビジョン…`: three or more full-width digits begin a name, not an item number (a one-character name stays `161`/`人`)
        script = re.match(r'([0-9]+)(?=[０-９])', raw_text)
        if script and label and re.fullmatch(r'[0-9]+[０-９]+', label[0].text) and (
                len(label) == 1 or label[1].x0 - label[0].x1 >= 2):
            script = None  # `1０` `需用費`: a number printed in two widths, a word of its own (281000)
        if script and margins is not None and margins & set(_margins(label)):
            # `11３歳児健康診査事業`: half-width digits are the number and the full-width ones start the name.
            code, name = script.group(1), normalize(raw_text[len(script.group(1)):])
        if (not script and len(label) > 1 and margins is not None and margins & set(_margins(label))
                and re.fullmatch(r'[0-9]{1,3}', normalize(label[0].text)) and re.match(r'[0-9０-９]', label[1].text)
                and label[1].x0 - label[0].x1 >= 2):
            # `8` `2歳児歯科健診事業`: the number is a word of its own, and the name begins with a count.
            code, name, script = normalize(label[0].text), normalize(text(label[1:])), True
        if code is not None and margins is not None and not margins & set(_margins(label)):
            code, name = None, line_text  # a name that begins with a digit
        if code is None and label and margins is not None and margins & set(_margins(label)):
            year = YEAR_LED.match(line_text)
            if year:  # `42025年農林業センサス費` is item `4` and `2025年…`
                code, name = year.group(1), line_text[len(year.group(1)):]
        spaced = (len(label) > 1 and re.fullmatch(r'[0-9]{1,4}', normalize(label[0].text)) is not None
                  and label[1].x0 - label[0].x1 >= 2)  # the number is a word of its own, set apart from the name
        if code is not None and COUNTED.match(line_text) and not YEAR_LED.match(line_text) and not script and not spaced:
            code, name = None, line_text  # `110番非常通報装置`, `3歳児健康診査`: a count, not an item number
        if code is not None and not name and money:
            code = None  # a lone number left of an amount is not a code
        if code is not None and re.match(r'[0-9]{1,3}(?:,[0-9]{3})+', line_text):
            code, name = None, line_text  # `66,000)`: the end of a bracketed amount (`(翌年度へ繰越明許費`), not an item `66`
        entries.append((label, money, code, name))
    return entries


def line_limits(logicals: list[Logical]) -> dict[str, float]:
    """Per breakdown axis, the right end of the longest label line printed anywhere in the document.

    A name wraps because it reached the right limit of its column, so a first line that went on to a
    second runs up to that limit (within a character or two). A short line followed by an indented line
    with an amount is two items, not a wrapped name (`02 管理用備品` / `ICカードリーダーライター 5,280`).
    """
    ends: dict[str, list[float]] = defaultdict(list)
    for logical in logicals:
        for group in groups(logical):
            if group.subject:
                continue
            for line in lines([w for band in group.bands for w in band.words]):
                label, money = _split_line(line)
                # A unit printed alone at the top of a cell (`円`, 132101) is no name: it would set the limit
                # at the cell's right edge, and no wrapped line would ever reach it.
                if label and not UNIT_CELL.match(normalize(text(label))):
                    ends[group.axis].append(max(g.x1 for g in label))
    # Printed text: the longest line. OCR: `scan.dense_limit`, past a few misread lines (132101).
    if any(logical.ocr for logical in logicals):
        from ingestion.generic.scan import dense_limit
        return {axis: dense_limit(values) for axis, values in ends.items()}
    return {axis: max(values) for axis, values in ends.items()}


def items(group: Group, header: str, margins: set[int] | None = None,
          roles: dict[int, str] | None = None, limit: float | None = None, ocr: bool = False,
          amount_brackets: bool = False, settings: dict | None = None) -> list[Item]:
    """Lines of a label group into items; amounts printed inside the group stay on their item.

    `roles` (variant B) replaces the geometric decisions for codeless lines.
    """
    entries = entries_of(group, margins, amount_brackets)
    settings = settings or {}
    kind_names = bool(settings.get('names_end_with_kind_words'))
    remainder = bool(settings.get('bracketed_remainder'))
    # A name that begins with a count, glued to its number (`82歳児歯科健診事業` = `8` + `2歳児…`,
    # `42025年農林業センサス費` = `4` + `2025年…`): the number is the one that follows the number before it
    # in this list. Only a line at a number's margin with a counter after its digits is read so.
    last_at: dict[int, int] = {}  # the last number printed at each start (one slot of 6pt)
    for index, (label, money, code, name) in enumerate(entries):
        raw = normalize(text(label)) if label else ''
        run = re.match(r'[0-9]+', raw)
        slot = round(label[0].x0 / 6) if label else None
        previous_code = max((last_at[s] for s in (slot - 1, slot, slot + 1) if s in last_at), default=None) if label else None
        if (run and len(run.group()) >= 2 and COUNTED.match(raw) and previous_code is not None
                and (margins is None or margins & set(_margins(label)) or code is not None)):
            digits = run.group()
            for cut in range(1, len(digits)):
                if int(digits[:cut]) == previous_code + 1 and digits[cut] != '0':
                    entries[index] = (label, money, digits[:cut], raw[cut:])
                    code = digits[:cut]
                    break
        if label and code is not None and code.isdigit():
            last_at[slot] = int(code)
    result: list[Item] = []
    # A rule-bounded cell with exactly one code is one item.
    band_of = lambda g: next(b for b in group.bands if b.x0 <= (g.x0 + g.x1) / 2 <= b.x1 or b is group.bands[-1])
    cells: dict[tuple, list[int]] = defaultdict(list)
    for index, (label, money, code, name) in enumerate(entries):
        anchor = label[0] if label else money[0][0]
        y = (anchor.y0 + anchor.y1) / 2
        cells[_cell(band_of(anchor), y)].append(index)
    def wraps(index: int, ix: list[int]) -> bool:
        """Whether every codeless line of the cell starts where its one code's name can wrap: from the
        code's own start to the start of its name. A line indented past the name (a 内訳 of the item above,
        `有料道路通行料` over `18 負担金…`) or left of the code (the next 事業 name over `03 複写機使用料`)
        is another item, even in a cell with no rule between them (132276)."""
        code = next(i for i in ix if entries[i][2] is not None)
        label = entries[code][0]
        if not label:
            return True
        raw = normalize(''.join(g.text for g in label))
        found = CODE.match(raw)
        start, consumed, name_start = label[0].x0, 0, label[-1].x1
        for glyph in label:
            if found and consumed + len(glyph.text) > found.end():
                # The number's own width: a half-width digit is half the line height. (The word's
                # average character width is a kanji's, and puts the name a digit too far right.)
                inside = glyph.text[:found.end() - consumed]
                height = glyph.y1 - glyph.y0
                name_start = glyph.x0 + sum(height / 2 if c.isascii() else height for c in inside)
                break
            consumed += len(glyph.text)
        ordered = sorted(ix)
        # `name_column`: names are set in a column of their own a space right of the numbers, so a name
        # wrapped above or below a line printing only its number starts up to a character past it (281000).
        slack = 3 + (label[0].y1 - label[0].y0 if settings.get('name_column') else 0)
        for position, i in enumerate(ordered):
            if entries[i][2] is not None or not entries[i][0]:
                continue
            if not start - 3 <= entries[i][0][0].x0 <= name_start + slack:
                return False
            # A name goes on a second line because it did not fit with the amount: the line before runs up
            # to where the amount is printed. A short line over an indented line with an amount is two items.
            if entries[i][1] and position and limit is not None:
                before = entries[ordered[position - 1]][0]
                if before and max(g.x1 for g in before) < limit - 4 * (before[0].y1 - before[0].y0):
                    return False
        return True

    single = {i: tuple(ix) for ix in cells.values()
              if sum(entries[i][2] is not None for i in ix) == 1 and len(ix) > 1
              and sum(bool(entries[i][1]) for i in ix) <= 1 and wraps(0, ix) for i in ix}
    if settings.get('name_column'):
        # A name wrapped above and below a line printing only its number, set tighter than the rows: a line
        # without a number whose middle is within a line height of a number's line is that number's name,
        # even where no row rule bounds the cell (281000's image-ruled pages draw none between 節).
        middle = lambda i: sum((g.y0 + g.y1) / 2 for g in entries[i][0]) / len(entries[i][0])
        numbered = [i for i, entry in enumerate(entries) if entry[2] is not None and entry[0]]
        attached: dict[int, list[int]] = defaultdict(list)
        for i, (label, money, code, _) in enumerate(entries):
            if code is not None or not label or money or i in single or not numbered:
                continue
            nearest = min(numbered, key=lambda n: abs(middle(n) - middle(i)))
            if abs(middle(nearest) - middle(i)) <= label[0].y1 - label[0].y0:
                attached[nearest].append(i)
        for number, lines_ in attached.items():
            members = tuple(sorted({*single.get(number, (number,)), *lines_}))
            single.update({i: members for i in members})
    done: set[int] = set()
    for index, (label, money, code, name) in enumerate(entries):
        if index in done:
            continue
        if index in single:
            members = single[index]
            done.update(members)
            code_index = next(i for i in members if entries[i][2] is not None)
            # A bracketed department (`(市民生活課)`) printed on a line of its own above the number ends the
            # name of the item before it, not the name of this one.
            while (result and members[0] != code_index and not entries[members[0]][1] and entries[members[0]][0]
                   and re.fullmatch(r'[(（][^()（）]+[)）]', normalize(text(entries[members[0]][0])))):
                result[-1].lines.append(entries[members[0]][0])
                result[-1].name += normalize(text(entries[members[0]][0]))
                members = members[1:]
            all_lines = [entries[i][0] for i in members if entries[i][0]]
            name = ''.join(entries[i][3] if i == code_index else normalize(text(entries[i][0])) for i in members)
            item = Item(group, all_lines[0][0].page, all_lines, entries[code_index][2], name, 0)
            for i in members:
                for run in entries[i][1]:
                    item.amounts.append((header, run))
            _measure(item, entries[code_index][0], entries[code_index][2], ocr)
            result.append(item)
            continue
        previous = result[-1] if result else None
        if roles is not None and code is None and index in roles and label:
            role = roles[index]
            label_text = normalize(text(label))
            if role in ('continuation', 'amount_kind') and previous is not None:
                previous.lines.append(label)
                if role == 'continuation':
                    previous.name += label_text
                for run in money:
                    previous.amounts.append((header if role == 'continuation' else f'{header}／{label_text}', run))
                    if role == 'amount_kind':
                        previous.kinds.append((label, run, f'{header}／{label_text}'))
                continue
            item = Item(group, label[0].page, [label], None, name, 0, decided=True)
            item.role = 'annotation' if role == 'note' else 'node'
            for run in money:
                item.amounts.append((header, run))
            _measure(item, label, None)
            result.append(item)
            continue
        whole = normalize(text(line_of(label, money)))
        if (previous is not None and code is None and whole[:1] in '(（' and whole[-1:] in ')）'
                and not (amount_brackets and money)):
            previous.lines.append(label + [g for run in money for g in run])
            previous.name += whole  # a parenthesised remark on the previous item, not an amount of it
            continue
        label_text = normalize(text(label))
        if (previous is not None and label and not money and previous.code is None and previous.amounts
                and is_account_code(previous.name) and kind_of(label_text, words=True) is not None):
            # An account code printed with the amount of a transfer (`・020601【010261】 △28,800`) and the
            # words that say where it went on the line below (`020000へ予算流用減`): one note.
            previous.lines.append(label)
            previous.name += label_text
            continue
        # OCR: `scan.total_row` (a lone `計` closing a 備考 is a total, 132055); printed text keeps it a kind.
        if ocr:
            from ingestion.generic.scan import total_row
        total_row_here = ocr and total_row(label_text)
        if (previous is not None and code is None and money and is_amount_kind(label_text) and not total_row_here
                and (previous.amounts or not kind_names)):  # with the setting, an item with no amount yet is a wrapped name ending in `計` (`…実施設` / `計 9,900,000`)
            for run in money:  # `繰越明許費 302,000`: an amount kind of the item above
                previous.amounts.append((f'{header}／{label_text}', run))
                previous.kinds.append((label, run, f'{header}／{label_text}'))
            previous.lines.append(label)
            continue
        # The name goes on in a bracket (`（地域振興課、建築課）`) on the next line, with the amount: the item's own.
        shown = normalize(text(label)) if label else ''
        bracketed = shown[:1] in ('（', '(', '【', '[') and shown[-1:] in ('）', ')', '】', ']')
        # A wrapped line never starts left of the item it continues (the next 事業's name under an item
        # of the level below, `03 複写機使用料` over `0102420公共施設等…`).
        # A name goes on a second line because it did not fit: its first line runs up to where the amount
        # is printed, or to the right edge of the name column when the amount has a column of its own. A short line followed by an indented line with an amount is two items
        # (`02 管理用備品` / `ICカードリーダーライター 5,280`, 132276).
        reaches = (previous is not None and bool(money) and bool(previous.lines)
                   and (limit is None or max(g.x1 for g in previous.lines[-1]) >= limit - 4 * (previous.lines[-1][0].y1 - previous.lines[-1][0].y0)))
        # A line led by a mark (`○あそべえ事業 222,656,920` under its heading, 132039) is an item of its own.
        marked = bool(label) and re.match(r'[〇○●◎□■◇◆]', label[0].text) is not None
        # Numbers are right-aligned in their column: a wrapped line starts at the column's left edge, which is
        # half a character left of a one-digit number (a half-width digit is half the line height).
        left_slack = max(3, (label[0].y1 - label[0].y0) / 2 + .5) if label and remainder else 3
        wrapped = (previous is not None and code is None and label and not previous.amounts and not marked
                   and label[0].x0 >= previous.lines[0][0].x0 - left_slack
                   and (not money or bracketed
                        or (reaches and (abs(label[0].x0 - previous.indent) <= 3
                                         or abs(label[0].x0 - _name_start(previous)) <= 3)))
                   and _cell(band_of(label[0]), label[0].y0) == _cell(band_of(previous.lines[-1][0]), previous.lines[-1][0].y0))
        # (Not only the rule-bounded cell: the name and the amount of a 備考 can have grids of their own.)
        wrapped = wrapped or (previous is not None and code is None and bool(label) and bool(money) and previous.code is not None
                              and not previous.amounts and label[0].x0 >= previous.lines[0][0].x0 - left_slack
                              and closes_parts(entries, index, previous, remainder))
        # A bracketed remainder (`（選挙管理委員会事務局）`) that did not fit on the line of the name above: the name
        # would have run past the right limit of the column with it.
        wrapped = wrapped or (remainder and previous is not None and code is None and bool(label) and bool(money) and bracketed
                              and previous.code is not None and not previous.amounts and limit is not None
                              and label[0].x0 >= previous.lines[0][0].x0 - left_slack
                              and max(g.x1 for g in previous.lines[-1]) + (label[-1].x1 - label[0].x0) > limit)
        if wrapped:  # a wrapped name; its amount may be printed on the last line
            previous.lines.append(label)
            previous.name += normalize(text(label))
            for run in money:
                previous.amounts.append((header, run))
            continue
        if not label:  # an amount alone on its line: a wrapped item's amount
            following = entries[index + 1] if index + 1 < len(entries) else None
            # The amount belongs to the line above when that one is a name still waiting for its amount
            # (`第３款総務費へ充用` / `△152,462,000` / `第７款…へ充用`, 131148).
            waiting = bool(result) and result[-1].code is None and not result[-1].amounts
            if (following is not None and not waiting and index + 1 not in done and following[0] and not following[1]
                    and following[2] is None and reads_as_note(following[3])
                    and 0 < following[0][0].y0 - money[0][0].y0 <= 1.8 * (money[0][0].y1 - money[0][0].y0)):
                # An amount printed above the word that names it (`12,409,365 円` / `流用`): the note's
                # amount, not the amount of the item above.
                done.add(index + 1)
                item = Item(group, following[0][0].page, [following[0]], None, following[3], 0)
                for run in money:
                    item.amounts.append((header, run))
                _measure(item, following[0], None)
                result.append(item)
                continue
            if result:
                for run in money:
                    result[-1].amounts.append((header, run))
            elif settings.get('wrap') == 'amount_on_last_line':
                # The first line of a page carries the amount of a label that ended the page before:
                # `apply_layout` joins the two. It stays a nameless item if there is no such label.
                item = Item(group, money[0][0].page, [[g for run in money for g in run]], None, '', money[0][0].x0)
                for run in money:
                    item.amounts.append((header, run))
                result.append(item)
            continue
        item = Item(group, label[0].page, [label], code, name, 0)
        for run in money:
            item.amounts.append((header, run))
        _measure(item, label, code, ocr)
        result.append(item)
    return result


def closes_parts(entries: list[tuple], index: int, previous: Item, right_aligned: bool = False) -> bool:
    """Whether the amount printed on this codeless line is the amount of the numbered item above, whose
    name goes on (`9 …運営` / `・補助事業費 38,343,659` / `（地域福祉課）`): the item above prints no amount,
    and the numbered items under it, at their own margin, add up to this amount. A sub-heading of its own
    would also have parts that add up to it; the item above that prints nothing is then no item."""
    amount = number(normalize(text(entries[index][1][0]))) if entries[index][1] else None
    if amount is None or not entries[index][0]:
        return False
    start = previous.lines[0][0].x0
    parts: list[tuple[float, int]] = []
    for label, money, code, _ in entries[index + 1:]:
        if not label:
            continue
        if label[0].x0 <= start + 3 and (code is not None or not money):
            break
        if code is not None and money:
            value = number(normalize(text(money[0])))
            if value is not None:
                parts.append((label[0].x0, value))
    if not parts:
        return False
    margin = min(x for x, _ in parts)
    # Right-aligned numbers: a one-digit number starts half a character right of a two-digit one.
    slack = max(3, (previous.lines[0][0].y1 - previous.lines[0][0].y0) / 2 + .5) if right_aligned else 3
    return sum(v for x, v in parts if x <= margin + slack) == amount


def line_of(label: list[Glyph], money: list[list[Glyph]]) -> list[Glyph]:
    return sorted(label + [g for run in money for g in run], key=lambda g: g.x0)


def _name_start(item: Item) -> float:
    """Where the name of an item with a long number (a 7-digit 事業番号, which is no `code`) begins; its
    wrapped lines start there. Without such a number, where the item starts."""
    first = item.lines[0]
    head = normalize(first[0].text)
    if re.match(r'[〇○●◎□■◇◆・]', first[0].text):
        # The wrapped lines of a bulleted name hang under the text, one character past the mark.
        if len(first[0].text) == 1 and len(first) > 1:
            return first[1].x0
        return first[0].x0 + (first[0].y1 - first[0].y0)
    if len(head) >= 5 and head.isdigit():
        if len(first) > 1 and first[1].x0 - first[0].x1 < 12:
            return first[1].x0
    glued = re.match(r'[0-9０-９]{5,}', first[0].text)
    if glued and len(first[0].text) > glued.end():
        height = first[0].y1 - first[0].y0
        digits = sum(1 for c in glued.group() if c.isascii())
        # A half-width digit is half the line height; the word's average character width is a kanji's.
        return first[0].x0 + digits * height / 2 + (len(glued.group()) - digits) * height
    return item.indent


def _measure(item: Item, label: list[Glyph], code: str | None, ocr: bool = False) -> None:
    """Indentation is where the name starts; subject level is the band of the first glyph."""
    first = label[0]
    if code is not None:
        consumed, offset = 0, None
        raw = ''.join(g.text for g in label)
        found = CODE.match(normalize(raw))
        length = found.end() if found else 0
        head = normalize(first.text)
        if (len(label) > 1 and re.fullmatch(r'[0-9]{1,4}', head) and length > len(head)
                and label[1].x0 - first.x1 >= 2):
            length = len(head)  # a number set apart from a name that begins with digits (`11 ２０歳のつどい事業`)
        for glyph in label:
            if consumed + len(glyph.text) > length:
                width = (glyph.x1 - glyph.x0) / max(len(glyph.text), 1)
                if ocr and any(not c.isascii() for c in glyph.text) and all(c.isascii() and c.isdigit() for c in glyph.text[:length - consumed]):
                    # An OCR word that joins the code and the name (`10需用費`): half-width digits are half a
                    # kanji wide, so the name starts after the digits' own width, not after an even share.
                    wide = sum(1 for c in glyph.text if not c.isascii())
                    width = (glyph.x1 - glyph.x0) / (len(glyph.text) - wide + 2 * wide) if wide else width
                offset = glyph.x0 + (length - consumed) * width
                break
            consumed += len(glyph.text)
        item.indent = offset if offset is not None else label[-1].x1
    else:
        item.indent = first.x0
    if item.group.subject:
        cx = first.x0 + 1
        for index, band in enumerate(item.group.bands):
            if band.x0 - 1 <= cx <= band.x1:
                item.level = index
        item.level = item.level if item.level is not None else len(item.group.bands) - 1


def join_transfer_tails(items_: list[Item], layout: dict | None) -> list[Item]:
    """A transfer remark that prints its amount on its first line and ends on the next (`共済費から職員手当等・
    時間外勤務手` `10,000` / `当へ流用`): the tail is the rest of that name, not a note of its own."""
    result: list[Item] = []
    for item in items_:
        previous = result[-1] if result else None
        if (previous is not None and item.code is None and not item.amounts and previous.code is None
                and previous.amounts and not previous.kinds and item.lines and previous.lines
                and abs(item.lines[0][0].x0 - previous.lines[0][0].x0) <= 2
                and 0 < item.lines[0][0].y0 - previous.lines[-1][0].y0 <= 2.5 * (previous.lines[-1][0].y1 - previous.lines[-1][0].y0)
                and not TRANSFER.search(PAREN_TAIL.sub('', previous.name))
                and TRANSFER.search(PAREN_TAIL.sub('', previous.name + item.name))
                and not is_plain_name(layout, previous)):
            previous.name += item.name
            previous.lines += item.lines
            continue
        result.append(item)
    return result


def note_prefixes(settings: dict) -> tuple[str, ...]:
    """The words a configured note line starts with: `notes` and the words of `note_kinds`."""
    return tuple(normalize(prefix) for prefix in [*settings.get('notes', []), *settings.get('note_kinds', {})])


def is_plain_name(layout: dict | None, item: Item) -> bool:
    """A name the document's settings declare to be an item although it contains a note word
    (`補充用備品` holds `充用`)."""
    names = (layout or {}).get(item.group.axis, {}).get('plain_names')
    return bool(names) and any(normalize(name) in normalize(item.name) for name in names)


def number_edges(logicals: list[Logical], pattern: str = 'bands') -> set[int]:
    """Where printed numbers end (original x, rounded), over the subject columns of the whole document."""
    edges: set[int] = set()
    for logical in logicals:
        for group in groups(logical, pattern):
            if not group.subject or group.mode == 'indent':
                continue
            for band in group.bands:
                for word in band.words:
                    found = re.match(r'[0-9]+(?=[^0-9\s]|$)', word.text)
                    if found:
                        edges.add(round(word.original[0] + len(found.group()) * (word.y1 - word.y0) / 2))
    return edges


def split_glued_numbers(words: list[Glyph], edges: set[int]) -> list[Glyph]:
    """Numbers of two columns printed as one run (`110車両管理費`: 項 `1` and 目 `10`, each right-aligned in
    its own column). A run of digits is cut where a column's number ends, as other rows show."""
    result = []
    for word in words:
        found = re.match(r'[0-9]{2,}(?=[^0-9\s])', word.text)
        if found is None:
            result.append(word)
            continue
        half = (word.y1 - word.y0) / 2
        for cut in range(1, len(found.group())):
            at = round(word.original[0] + cut * half)
            if {at - 1, at, at + 1} & edges:
                break
        else:
            result.append(word)
            continue
        middle = word.x0 + cut * half
        result += [Glyph(word.text[:cut], word.x0, word.y0, middle, word.y1, word.page, word.offset),
                   Glyph(word.text[cut:], middle, word.y0, word.x1, word.y1, word.page, word.offset)]
    return result


def subject_items(group: Group) -> list[Item]:
    """Subject (款・項・目) items: a code printed in a level band starts an item.

    A line splits where a glyph run that starts with a code begins in a new
    band (`3 2 1`, `7 1商工費`), or where the next band's text starts a line
    height away across a rule drawn at that height; text without a code continues
    the current run across a band edge (`1 議 会 費`). Name-only lines in the same rule-bounded
    cell belong to the deepest code of that cell (a name wrapped above and
    below its code); a cell without a code continues the previous item.
    """
    deepest = group.bands[-1]

    def band_index(g: Glyph) -> int:
        index = next((i for i, b in enumerate(group.bands)
                      if b.x0 <= g.x0 + min(2, (g.x1 - g.x0) / 2) <= b.x1), len(group.bands) - 1)
        # In a staircase a level's cell runs right over the deeper columns until their rule starts below it
        # (281000: the 項 code printed right of the 目 rule, on a row above where that rule begins).
        y = (g.y0 + g.y1) / 2
        while index > 0 and group.bands[index].staircase and not any(
                top - 1 <= y <= bottom + 1 for top, bottom in group.bands[index].left_rules):
            index -= 1
        return index
    centre = lambda piece: sum((g.y0 + g.y1) / 2 for g in piece) / len(piece)
    cells: dict[tuple, list[list[Glyph]]] = defaultdict(list)
    order: list[tuple] = []
    for line in lines([w for band in group.bands for w in band.words]):
        cell = _cell(deepest, centre(line))
        if cell not in cells:
            order.append(cell)
        cells[cell].append(line)
    parsed: dict[tuple, tuple[list[tuple[int, list[Glyph]]], list[list[Glyph]]]] = {}
    for cell in order:
        tokens: list[tuple[int, list[Glyph]]] = []
        names: list[list[Glyph]] = []
        for line in cells[cell]:
            pieces: list[tuple[int, list[Glyph]]] = []
            for glyph in line:
                band = band_index(glyph)
                starts_code = CODE.match(normalize(glyph.text)) is not None
                # A name that crosses a band edge stays one piece; the names of two neighbouring columns on
                # one line do not (a full line height apart, with the rule between them).
                apart = bool(pieces) and glyph.x0 - pieces[-1][1][-1].x1 > glyph.y1 - glyph.y0 and any(
                    top <= (glyph.y0 + glyph.y1) / 2 <= bottom for edge in group.bands[pieces[-1][0] + 1:band + 1]
                    for top, bottom in edge.left_rules)
                if pieces and not (band != pieces[-1][0] and (starts_code or apart)):
                    pieces[-1][1].append(glyph)
                else:
                    pieces.append((band, [glyph]))
            for band, piece in pieces:
                if CODE.match(normalize(text(piece))):
                    tokens.append((band, piece))
                else:
                    names.append(piece)
        parsed[cell] = (tokens, names)
    # A name-only line belongs to the one code printed in its own column and the rule-bounded cell of that
    # column, even when a rule of a deeper column cuts between them: `4 その他公共 / 施設、公用 / 災害復旧費`
    # (項) wraps through the row of `1 その他公共 / 施設、公用…` (目), 132241. Otherwise, to the deepest code
    # of its cell (a name wrapped above and below its code); a cell without a code continues the previous item.
    in_column: dict[int, list[tuple[tuple, int]]] = defaultdict(list)
    for cell, (tokens, _) in parsed.items():
        for index, (band, piece) in enumerate(tokens):
            in_column[band].append((cell, index))
    claimed: dict[tuple, tuple[tuple, int]] = {}
    for cell, (tokens, names) in parsed.items():
        for position, piece in enumerate(names):
            column = band_index(piece[0])
            span = _cell(group.bands[column], centre(piece))
            found = [(c, i) for c, i in in_column[column]
                     if _cell(group.bands[column], centre(parsed[c][0][i][1])) == span]
            if len(found) == 1:
                claimed[cell, position] = found[0]
    extra: dict[tuple, list[list[Glyph]]] = defaultdict(list)
    for (cell, position), owner_token in claimed.items():
        extra[owner_token].append(parsed[cell][1][position])
    result: list[Item] = []
    for cell in order:
        tokens, names = parsed[cell]
        free = [piece for position, piece in enumerate(names) if (cell, position) not in claimed]
        if not tokens:
            if result and free and result[-1].role == 'node' and _cell(deepest, result[-1].anchor) == cell:
                for piece in free:
                    result[-1].lines.append(piece)
                    result[-1].name += normalize(text(piece))
                continue
            for piece in free:  # a printed line without a code (a total row)
                item = Item(group, piece[0].page, [piece], None, normalize(text(piece)), 0)
                _measure(item, piece, None)
                result.append(item)
            continue
        deepest_token = max(range(len(tokens)), key=lambda i: tokens[i][0])
        owner_of: dict[int, int] = {}
        for position, piece in enumerate(names):
            if (cell, position) in claimed:
                continue
            same = [i for i, (band, _) in enumerate(tokens) if band == band_index(piece[0])]
            owner_of[position] = same[0] if len(same) == 1 else deepest_token
        for index, (band, piece) in enumerate(tokens):
            code, name = _split_code(normalize(text(piece)))
            own = [piece]
            mine = [names[p] for p, i in owner_of.items() if i == index] + extra.get((cell, index), [])
            if mine:
                y = centre(piece)
                parts = sorted([(y, name, piece)] + [(centre(n), normalize(text(n)), n) for n in mine],
                               key=lambda p: p[0])
                name = ''.join(part[1] for part in parts)
                own = [part[2] for part in parts]
            item = Item(group, piece[0].page, own, code, name, 0, level=band, fixed_anchor=centre(piece))
            item.indent = piece[0].x0
            result.append(item)
    return result


# `（決算額 △1,000 円）`: the kind, then everything up to an optional unit and the closing bracket
# (or the end), so a broken amount (`1,000O0円）`) is read whole and fails, not cut to `1,000`.
TITLE_AMOUNT = re.compile(r'[(（]([^0-9△▲\-()（）]+?)([△▲\-]?[0-9][^()（）]*?)(?:百万円|千円|円)?(?:[)）]|$)')


def title_amount(line: list[Glyph]) -> tuple[str | None, list[Glyph]]:
    """The amount kind and the glyphs of the signed amount in a 款 title (`（決算額 △1,000 円）`).

    The amount is cut out of the words that print it, by character position, so a sign printed
    as its own word or a word that runs on into `円）` still gives just the number.
    """
    found = TITLE_AMOUNT.search(normalize(text(line)))
    if not found:
        return None, []
    kind, amount = found.group(1).strip(), found.group(2)
    if not is_amount(amount):
        return kind, []  # printed but unreadable: reported as such by the caller
    # Positions of the amount in the concatenated glyph texts (NFKC keeps one character per character here).
    texts = [unicodedata.normalize('NFKC', g.text) for g in line]
    joined = ''.join(t.replace(' ', '').replace('\u3000', '') for t in texts)
    start = joined.find(amount, joined.find(kind) + len(kind))
    if start < 0:
        return kind, []
    run, position = [], 0
    for glyph, raw in zip(line, texts):
        compact = raw.replace(' ', '').replace('\u3000', '')
        lo, hi = max(start, position), min(start + len(amount), position + len(compact))
        if lo < hi:
            width = (glyph.x1 - glyph.x0) / max(len(compact), 1)
            a, b = lo - position, hi - position
            run.append(Glyph(compact[a:b], glyph.x0 + a * width, glyph.y0, glyph.x0 + b * width, glyph.y1, glyph.page, glyph.offset))
        position += len(compact)
    return kind, run


def untitled(group: Group) -> bool:
    """A subject group whose 款 is printed as a title: its first column is not 款, or one header spans the
    columns (`款項目`) and the 款 column prints nothing."""
    if not group.bands or not group.bands[0].header:
        return False
    first = group.bands[0]
    if group.mode in ('bands', 'names') and first.header[-1] in SUBJECT_LEVELS[1:]:
        return True
    return first.header[-1] == '款項目' and not first.words


def title_shift(group: Group) -> bool:
    """Whether the group's columns sit one level below a title's 款 (an `indent` group's columns include the 款's)."""
    return untitled(group) and group.mode != 'indent'


def heading_names(logical: Logical) -> dict[tuple[str, str], str]:
    """Running headings above a table (`款（7）商工費`, `(項) 1 総務管理費`): level and code to name."""
    found = {}
    for line in lines(logical.outside):
        value = normalize(text(line))
        match = re.match(r'^[(（]?(款|項|目)[)）]?[(（]?([0-9]+)[)）]?(.+)$', value)
        if match:
            found[match.group(1), match.group(2)] = match.group(3)
    return found


def owner(amount: list[Glyph], band: Band, ordered: list[Group], found: dict[int, list[Item]],
          roles: tuple[str, ...] = ('node', 'repeat', 'total'), *, ocr: bool = False) -> Item | None:
    """The item printed on the amount's own line in the nearest label group to its left;
    failing that, the item in its rule-bounded row (a label centred in a tall cell).

    The line comes first: when sub-rows carry no rules (131172 prints the 節 of a 目
    inside the 目's ruled cell), the cell alone would hand the 目's amount to a 節.
    """
    digits = [g for g in amount if g.text not in ('△', '▲')] or amount
    y = sum((g.y0 + g.y1) / 2 for g in digits) / len(digits)
    reach = .6 * max(g.y1 - g.y0 for g in digits)
    if ocr:
        from ingestion.generic.scan import line_reach
    line_limit = lambda line: line_reach(digits, line) if ocr else reach
    left = sorted((g for g in ordered if g.x1 <= band.x0 + 1), key=lambda g: -g.x0)
    for group in left:
        same_line = [i for i in found[id(group)] if i.role in roles
                     and abs(i.anchor - y) <= line_limit(i.lines[0])]
        if same_line:
            return max(same_line, key=lambda i: (i.level or 0, -abs(i.anchor - y)))
    # The name may be printed on a line below its code (`1` / `議会費 82,694,000`): any line of the item.
    centre = lambda line: sum((g.y0 + g.y1) / 2 for g in line) / len(line)
    for group in left:
        same_line = [i for i in found[id(group)] if i.role in roles
                     and any(line and abs(centre(line) - y) <= line_limit(line) for line in i.lines)]
        if same_line:
            return max(same_line, key=lambda i: (i.level or 0, -abs(i.anchor - y)))
    top, bottom = _cell(band, y)
    if bottom - top > 80:  # unruled: fall back to the printed line
        top, bottom = y - 4, y + 4
    for group in left:
        candidates = [i for i in found[id(group)] if top - .5 <= i.anchor <= bottom + .5 and i.role in roles]
        if candidates:
            return max(candidates, key=lambda i: (i.level or 0, -abs(i.anchor - y)))
    # A name printed on two lines with its amount at the height between them (`1衛生施設災` / `害復旧費`)
    # in a cell too tall to count as ruled: the item whose lines span the amount, with no rule across them.
    span = lambda i: (min(g.y0 for g in i.lines[0]), max(g.y1 for g in i.lines[-1]))
    for group in left:
        spanning = [i for i in found[id(group)] if i.role in roles and len(i.lines) > 1 and i.lines[0] and i.lines[-1]
                    and span(i)[0] <= y <= span(i)[1]
                    and not any(span(i)[0] < rule < span(i)[1] for rule in band.rows)]
        if spanning:
            return max(spanning, key=lambda i: (i.level or 0, -abs(i.anchor - y)))
    # Amounts printed on the line below their item (`1. 議会費` / `142,678,000 …`, 133051):
    # the nearest item whose last line ends within one line above the amount, in the same
    # ruled cell (no rule of the amount's column between them). Across a rule it stays unowned.
    height = max(g.y1 - g.y0 for g in digits)
    for group in left:
        above = [i for i in found[id(group)] if i.role in roles and i.lines and i.lines[-1]
                 and 0 < y - centre(i.lines[-1]) <= 1.8 * height
                 and not any(centre(i.lines[-1]) < rule < y for rule in band.rows)]
        if above:
            return min(above, key=lambda i: y - centre(i.lines[-1]))
    return None


@dataclass
class Built:
    nodes: list[dict]
    amounts: list[dict]
    unowned: list[dict]
    notes: list[dict]
    # Amounts printed as notes. A remark on an account's own line (`annotation`: node_key = the account the
    # note belongs to) and an amount kind inside an item (`kind line`: node_key = the item that holds it, `heading`
    # is the header it carries in `amounts`). `label` is the printed words and `run` the amount's own glyphs;
    # `convert` decides which of them are 注記 (shared annotation dictionary) and lays them on the 注記 axis.
    annotations: list[dict] = field(default_factory=list)
    # Logical pages that are not expenditure detail (no 款・項・目 column and no amount column the shared
    # dictionary knows): not read; `convert` declares their frames as excluded regions.
    skipped: list = field(default_factory=list)
    # The printed code of a subject heading that a continuation page prints again (the same code and name as
    # the one above it): no node of its own, its digits are the adopted heading's.
    repeated_codes: list = field(default_factory=list)
    # Glyphs of a row with no name whose every printed amount equals the amount of the account row above it in
    # the same column (the 節 row of a 予備費, which prints no 節 name): the parent's amounts again, not new ones.
    repeated_amounts: list = field(default_factory=list)


def node_key(item: Item) -> str:
    x0, y0, _, _ = item.glyphs[0].original
    return 'n-' + hashlib.sha256(f'{item.page}:{x0:.2f}:{y0:.2f}:{item.group.axis}'.encode()).hexdigest()[:24]


DETAIL_PATTERNS = ('indent', 'shape', 'position')
# Numbering shapes of breakdown items (事業・説明), in the order they are tried.
SHAPES = (('bullet', re.compile(r'^[○〇●◎□■◇◆]')), ('paren', re.compile(r'^[(（][0-9]+[)）]')),
          ('circled', re.compile(r'^[⓪①-⑳㉑-㉟㊱-㊿❶-❿⓫-⓴]')), ('kana-paren', re.compile(r'^[(（][ア-ン][)）]')),
          ('kana', re.compile(r'^[ア-ン](?=[\s　]|[^ぁ-ゟァ-ヶー])')), ('number', re.compile(r'^[0-9]+')))


def shape_of(item: Item) -> str | None:
    raw = unicodedata.normalize('NFKC', text(item.lines[0])) if item.lines else ''
    raw = raw.strip()
    for name, pattern in SHAPES:
        if pattern.match(raw if name not in ('circled',) else text(item.lines[0]).strip()):
            # A name that begins with a digit (`３階ホール…`, `30歳・35歳健康診査委託料`) is no number:
            # the item reading had already left its code empty.
            if name == 'number' and item.code is None:
                return None
            return name
    return None


def number_span(glyph: Glyph) -> tuple[float, float, int]:
    """Where a leading number starts and ends, and its digit count. The end comes from the
    digits' own widths (a half-width digit is half the line height, a full-width one the
    height), not from the word's average character width, which a name joined to the number
    (`13使用料…`) widens. An opening bracket (`(1)`) is not part of the number: it starts where the digits do."""
    height = glyph.y1 - glyph.y0
    text = glyph.text
    lead = 1 if text[:1] in ('(', '（') else 0
    start = glyph.x0 + (height / 2 if lead and text[0].isascii() else height if lead else 0)
    body = text[lead:]
    digits = len(body) - len(body.lstrip('0123456789０１２３４５６７８９'))
    full = sum(1 for c in body[:digits] if not c.isascii())
    return start, start + (digits - full) * height / 2 + full * height, digits


# An end that fits is a weaker sign of one position than a start that fits (points).
END_PENALTY = 2.0


def position_gap(number: tuple[float, float, int], anchor: tuple[float, float, int], glyph: Glyph) -> float | None:
    """How far two numbers of one shape are from standing at one position, or None when they do not.

    They stand together when their starts align (left-aligned 4 and 18), or their ends align with at most
    one digit more or less (right-aligned 1 and 10; a 7-digit 事業番号 ending where a 2-digit number ends is
    not aligned with it). Tolerance: one digit, from the line height (事業「2」 at x 936 and 節「10」 at 941
    are two levels, 132209). A digit is about .6 of the line height wide (a smaller number font, `11` at
    6.0pt, is 3.5pt a digit).

    The gap is the start difference, or the end difference plus a penalty: an end that fits is a weaker
    sign than a start that fits (a left-aligned `99` starts 2.8 from a 事業's number and ends 1.4 from a
    節's, 132217, while a right-aligned `26` starts 3.8 from one and ends 0.2 from the other, 132209)."""
    tolerance = .6 * (glyph.y1 - glyph.y0)
    gaps = []
    if abs(number[0] - anchor[0]) <= tolerance:
        gaps.append(abs(number[0] - anchor[0]))
    if abs(number[1] - anchor[1]) <= tolerance and abs(number[2] - anchor[2]) <= 1:
        gaps.append(abs(number[1] - anchor[1]) + END_PENALTY)
    return min(gaps) if gaps else None


def same_position(number: tuple[float, float, int], anchor: tuple[float, float, int], glyph: Glyph) -> bool:
    return position_gap(number, anchor, glyph) is not None


def circled_continuation(number: tuple[float, float, int], matched, circled, glyph: Glyph):
    """Circled numbers end at ⑳, so a series goes on in plain digits (`⑨宿日直手当` then `23災害急患対応手当`).
    A plain number that fits a plain position only by where it ends, and starts where a circled number
    starts, is that series' next item. Returns that circled key, or None."""
    tolerance = .6 * (glyph.y1 - glyph.y0)
    if matched is not None and abs(number[0] - matched[0]) <= tolerance:
        return None
    fits = [(abs(number[0] - anchor[0]), index, key) for index, (key, anchor) in enumerate(circled)
            if abs(number[0] - anchor[0]) <= tolerance]
    return min(fits)[2] if fits else None


def nearest_position(number: tuple[float, float, int], anchors, glyph: Glyph):
    """The key among `anchors` (key, anchor) whose position the number fits best; the first among equals."""
    fits = [(gap, index, key) for index, (key, anchor) in enumerate(anchors)
            if (gap := position_gap(number, anchor, glyph)) is not None]
    return min(fits)[2] if fits else None


def shape_depth(item: Item, indent_depth: int, order: list[str], open_items: list,
                anchors: dict[str, tuple[float, float, int]] | None = None) -> int:
    """Depth by numbering shape: each shape keeps the level where it first appeared on the
    axis (numbering restarts under each parent); unnumbered lines sit under the last open item
    when indented deeper, otherwise they keep the indentation level.

    A shape is one level where its numbers start or end at one position (left-aligned 4 and
    18 start together, right-aligned 1 and 10 end together). The same shape whose start and
    end are not at `same_position` as any position seen for it is another level
    (事業「1 …」 and 節「8 旅費」 indented below it)."""
    shape = shape_of(item)
    if shape is None:
        last = next((p for p in reversed(open_items) if p is not None), None)
        if last is not None and item.indent > last.indent + 2:
            return len(open_items) + 1
        return indent_depth
    if anchors is not None and item.lines and item.lines[0]:
        first = item.lines[0][0]
        number = number_span(first)
        seen = nearest_position(number, [(key, anchor) for key, anchor in anchors.items() if key.split('@')[0] == shape], first)
        if shape == 'number':
            circled = [(key, anchor) for key, anchor in anchors.items() if key.split('@')[0] == 'circled']
            seen = circled_continuation(number, anchors.get(seen), circled, first) or seen
        if seen is not None:
            shape = seen
        else:
            if any(key.split('@')[0] == shape for key in anchors):
                shape = f'{shape}@{len(anchors)}'
            anchors[shape] = number
    if shape not in order:
        order.append(shape)
    return order.index(shape) + 1


def position_levels(all_items, levels: dict[str, list[float]], depth_of) -> tuple[dict, dict]:
    """Levels of breakdown items by numbering shape and position (pattern position).

    A numbered item's level is its shape at one aligned position (its numbers start or end
    at `same_position`, as in `shape_depth`); a codeless item's level is its
    indentation level. Levels rank by the x where their lines start, so a codeless 事業 line
    (x 254) sits above 節「13 …」 (263), 細節「03 …」 (273) and the codeless lines under them
    (282) (132276)."""
    starts: dict[str, dict[tuple, float]] = defaultdict(dict)
    numbers: dict[str, dict[tuple, tuple[float, float, int]]] = defaultdict(dict)
    keys: dict[int, tuple] = {}
    for _, ordered, found in all_items:
        for group in ordered:
            if group.subject or not levels.get(group.axis):
                continue
            for item in found[id(group)]:
                if item.role not in ('node', 'note') or not item.lines or not item.lines[0]:
                    continue
                first = item.lines[0][0]
                shape = shape_of(item)
                if shape is None:
                    key = ('plain', depth_of(item))
                    starts[group.axis].setdefault(key, levels[group.axis][key[1] - 1])
                else:
                    number = number_span(first)
                    key = nearest_position(number, [(k, numbers[group.axis][k]) for k in starts[group.axis] if k[0] == shape], first)
                    if shape == 'number':
                        circled = [(k, numbers[group.axis][k]) for k in starts[group.axis] if k[0] == 'circled']
                        key = circled_continuation(number, numbers[group.axis].get(key), circled, first) or key
                    if key is None:
                        key = (shape, len(starts[group.axis]))
                        starts[group.axis][key], numbers[group.axis][key] = number[0], number
                keys[id(item)] = key
    # Levels whose lines start within a couple of points are ranked by which was met first (outer first):
    # `3 …` and `(1) …` below it start together once the bracket is taken off.
    ranks = {axis: {key: rank for rank, key in enumerate(
        sorted(found, key=lambda k: (round(found[k] / 3), list(found).index(k))))} for axis, found in starts.items()}
    return ranks, keys


INDENT_SPAN = 6.0  # one indentation step is a character (about 10pt); a level is narrower than this


def split_wide(cluster: list[float]) -> list[list[float]]:
    """Split a chain of starts wider than one indentation step at its emptiest point between two peaks.

    Starts within 3pt chain into one level. Printed text gives each level one x; OCR spreads a level over a
    few points and a handful of lines in between (a bracket, a letter-spaced name) can bridge two levels
    10pt apart (`補助金` at 856 and its parts at 866, 132055), so a chain that spans more than a step is cut
    at the least-used whole point between its most used start and the most used one a step away from it."""
    if cluster[-1] - cluster[0] <= INDENT_SPAN:
        return [cluster]
    counts = Counter(round(v) for v in cluster)
    peak = max(counts, key=lambda b: (counts[b], -b))
    far = [b for b in counts if abs(b - peak) >= INDENT_SPAN]
    if not far:
        return [cluster]
    other = max(far, key=lambda b: (counts[b], -abs(b - peak)))
    low, high = sorted((peak, other))
    middle = (low + high) / 2
    valley = min(range(low + 1, high), key=lambda b: (counts.get(b, 0), abs(b - middle)))
    left = [v for v in cluster if v < valley + .5]
    right = [v for v in cluster if v >= valley + .5]
    if not left or not right:
        return [cluster]
    return split_wide(left) + split_wide(right)


def same_heading(first: str, second: str) -> bool:
    """Two printings of one subject name: equal, or (names of three characters or more) one character apart.

    A continuation page repeats the subject heading; OCR may misread a character of it (`秘書広银費` for
    秘書広報費, 132055). The codes already agree, so one character is the misread, not another subject."""
    a, b = (normalize(name or '') for name in (first, second))
    # A page that goes on with the 目 prints its name in brackets (`10 (文書広報費)` under `10 文書広報費`).
    a, b = (re.sub(r'^[(（]|[)）]$', '', name) for name in (a, b))
    if a == b:
        return True
    if min(len(a), len(b)) < 3 or abs(len(a) - len(b)) > 1:
        return False
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        row = [i]
        for j, cb in enumerate(b, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (ca != cb)))
        previous = row
    return previous[-1] <= 1


def repeats(previous: Item, item: Item, ocr: bool = False) -> bool:
    """Whether a subject line repeats the open heading of its level on a continuation page.

    Printed text repeats the code (and the name). For OCR (`scan.near_code`), a line of codes only (`10 2 3`
    at the top of a page) repeats the open heading when its code is near, and a line with a name of three
    characters or more repeats it when its code is near and its name agrees to one character."""
    if previous.code == item.code and (not item.name or same_heading(previous.name, item.name)):
        return True
    if not ocr:
        return False
    from ingestion.generic.scan import misread_repeat
    return misread_repeat(previous.code, previous.name, item.code, item.name)


def stacked_columns(logicals: list[Logical]) -> set[str]:
    """Amount columns (by heading) that print two or more amounts in one cell somewhere in the document.

    Such a column tells its amounts apart by a kind word above each (`継続費逓次繰越` / `73,871,000` /
    `繰越明許費` / `102,288,855`, 132241); there every kind word is part of the amount's heading. A column
    that never stacks keeps its own heading under a kind word (立川's `繰越明許` over one amount).
    """
    found: set[str] = set()
    for logical in logicals:
        for band in logical.bands:
            if band.kind != 'amount':
                continue
            counts = Counter(_cell(band, sum((g.y0 + g.y1) / 2 for g in line) / len(line))
                             for line in lines(band.words)
                             if line and any(is_amount(_leading_amount(g).text) for g in line))
            if any(count >= 2 for count in counts.values()):
                found.add('／'.join(band.header))
    return found


def department_heading(item: Item) -> bool:
    """A line that is only a department in brackets with an amount of its own (`(財政課) 138,154,166`): the
    items printed under it at its indentation are its parts (`22 償還金利子及び割引料 138,154,166`)."""
    return (item.code is None and bool(item.amounts)
            and re.fullmatch(r'[（(][^()（）]+[)）]', normalize(item.name)) is not None)


def closing_department_headings(ordered: list[Item]) -> set[int]:
    """The department headings whose parts sum to them: `(財政課) 138,154,166` over `22 …… 138,154,166`.

    A bracketed department line with an amount is read as the parent of the items printed under it at its
    own indentation only when those items add up to its amount; otherwise the line is an item like the
    others. (A volume that begins in the middle of a 事業 cannot close its first heading, and must not
    be made to look as if a sum were missing.)"""
    closing: set[int] = set()
    for index, item in enumerate(ordered):
        if item.group.subject or not department_heading(item):
            continue
        parts = []
        for other in ordered[index + 1:]:
            if other.group.subject or other.group.axis != item.group.axis:
                break
            start = lambda it: it.lines[0][0].x0  # where the line starts, its number included
            if start(other) < start(item) - 3:
                break
            if department_heading(other):
                break
            if abs(start(other) - start(item)) <= 3 and other.role in ('node', 'note') and other.amounts:
                parts.append(other)
        first = lambda it: number(normalize(text(it.amounts[0][1]))) or 0
        if parts and sum(first(p) for p in parts) == first(item):
            closing.add(id(item))
    return closing


def prints_phase(logical: Logical) -> bool:
    """Whether a logical page has an amount column whose heading the shared dictionary knows (支出済額,
    予算現額, 当初予算額…): the sign of an expenditure detail even when its 款・項・目 column is on another page."""
    known = {label for _, label in phase_dictionary()}
    return any(band.kind == 'amount' and (('／'.join(band.header) in known) or (band.header and band.header[-1] in known)
                                           or any(part in known for part in band.header))
               for band in logical.bands)


def layout_name_start(item: Item, hang_chars: int | None = None) -> float:
    """A configured hanging name starts after its printed code, including its punctuation. `hang_chars` is
    the document's own hang: its wrapped lines start that many characters right of the numbered line's start,
    whatever the number's width (a two-digit code is not one character wider)."""
    if item.code is None:
        return _name_start(item)
    if hang_chars:
        first = item.lines[0][0]
        return first.x0 + (first.y1 - first.y0) * hang_chars
    found = CODE.match(normalize(text(item.lines[0])))
    if found is None:
        return _name_start(item)
    remaining = len(found.group())
    for glyph in item.lines[0]:
        if remaining < len(glyph.text):
            prefix = glyph.text[:remaining]
            return glyph.x0 + (glyph.y1 - glyph.y0) * sum(.5 if c.isascii() else 1 for c in prefix)
        remaining -= len(glyph.text)
    return item.indent


def apply_layout(items: list[Item], settings: dict, column_amount_items: set[int],
                 subject_starts: tuple[float, ...] = ()) -> list[Item]:
    """Apply declared hints after money ownership is known, before learning breakdown levels."""
    result = []
    marks = settings.get('marks', {})
    ordered_marks = sorted(marks, key=lambda mark: (-len(normalize(mark)), mark))
    shapes = {'1': 'number', '(1)': 'paren', 'ア': 'kana', '①': 'circled'}
    note_kinds = {normalize(prefix): kind for prefix, kind in settings.get('note_kinds', {}).items()}
    prefixes = note_prefixes(settings)
    for item in items:
        if settings.get('wrap'):
            item.indent = layout_name_start(item, settings.get('hang_chars'))
        raw = normalize(text(item.lines[0]))
        note = raw.startswith(prefixes)
        mark = next((m for m in ordered_marks
                     if (shape_of(item) == shapes[m] if m in shapes else raw.startswith(normalize(m)))), None)
        if note:
            item.hint = next((kind for prefix, kind in note_kinds.items() if raw.startswith(prefix)), item.hint)
            if id(item) in column_amount_items:
                raise ValueError(f'Configured note carries separate-column money: p{item.page} {item.name!r}')
            item.role = 'annotation'
        elif mark is not None and item.role in ('node', 'note'):
            if marks[mark] == '説明':
                if item.amounts or id(item) in column_amount_items:
                    raise ValueError(f'Configured explanation carries money: p{item.page} {item.name!r}')
                item.role = 'note'
            else:
                item.level = marks[mark] - 1
        previous = result[-1] if result else None
        if (previous and not previous.amounts and id(previous) not in column_amount_items and item.code is None and mark is None and not note
                and item.role in ('node', 'note') and previous.role in ('node', 'note', 'annotation')
                and (settings.get('wrap') == 'amount_on_last_line' or normalize(text(previous.lines[0])).startswith(prefixes))
                and item.page == previous.page and abs(item.indent - previous.indent) <= 3
                and bisect_right(subject_starts, previous.anchor) == bisect_right(subject_starts, item.anchor)
                and 0 <= item.y0 - previous.y1 <= max(g.y1 - g.y0 for g in item.glyphs)):
            if previous.role == 'annotation' and id(item) in column_amount_items:
                raise ValueError(f'Configured note carries separate-column money: p{item.page} {item.name!r}')
            if item.role == 'node' and previous.role == 'note':
                previous.role = 'node'
            previous.name += item.name
            previous.lines += item.lines
            previous.amounts += item.amounts
            previous.kinds += item.kinds
            continue
        result.append(item)
    fitted = settings.get('fitted_names')
    columned: list[tuple[Item, Item]] = []
    if settings.get('name_columns'):
        # A name set in columns (`給　料` | `市長　１人`): the next lines start at the second column and
        # carry no first part (`副市長　１人`). They are siblings of the line that opened the columns.
        base = None
        for item in result:
            if item.code is not None or item.role != 'node':
                base = None
                if item.code is None:
                    continue
                continue
            if base is not None and any(abs(item.lines[0][0].x0 - word.x0) <= 1.5 for word in base.lines[0][1:]):
                columned.append((item, base))
            elif len(item.lines[0]) > 2:
                base = item
            else:
                base = None
    for item in result:
        if fitted and item.role == 'node' and len(item.name) > fitted['chars']:
            item.indent += fitted['overflow_left_chars'] * (item.lines[0][0].y1 - item.lines[0][0].y0)
    for item, base in columned:
        item.indent = base.indent
    return result


def build(logicals: list[Logical], judge=None, pattern: str = 'bands', detail: str | dict = 'indent',
          layout: dict | None = None) -> Built:
    """`detail` is one breakdown pattern for every axis, or a mapping axis → pattern."""
    """`judge(lines) -> {line id: (role, confidence)}` replaces the codeless-line rules (variant B)."""
    shapes: dict[str, list[str]] = {}  # numbering shapes per breakdown axis, in order of first use
    anchors: dict[str, dict[str, tuple[float, float, int]]] = {}  # where each shape's numbers start and end, per axis
    stack: list[Item] = []  # open subject items by depth
    branch: dict[str, list[Item]] = {}  # open items per other axis
    levels: dict[str, list[float]] = {}
    nodes, amounts, unowned, notes = [], [], [], []
    repeated_codes: list = []
    for logical in logicals:
        for group in groups(logical, pattern):
            if (group.subject and group.mode == 'indent') or (not group.subject and group.axis == '款項目'):
                repeated_codes.extend(strip_ancestor_codes(group))
    unowned_runs: list[tuple[dict, list[Glyph]]] = []  # an amount no row owns, with its glyphs
    annotations: list[tuple[Item, str, list[Glyph], str | None]] = []
    remarks: list[dict] = []  # `Built.annotations` before the items have keys
    all_items: list[tuple[Logical, list[Group], dict[int, list[Item]]]] = []
    column_amount_items: set[int] = set()
    margins = code_margins(logicals)
    edges = number_edges(logicals, pattern)
    limits = line_limits(logicals)
    stacking = stacked_columns(logicals)
    skipped: list[Logical] = []
    open_headings: dict[str, int] = {}  # per axis: the depth of the department heading line that is open
    for logical in logicals:
        ordered = groups(logical, pattern)
        if not any(g.subject for g in ordered) and not prints_phase(logical):
            # A frame with no 款・項・目 column and no column of a budget or settlement amount is no
            # expenditure detail but a list of its own (a table of 流用, a summary of carry-overs): it is
            # left out and declared as such (`Built.skipped`), never read as items without a parent.
            skipped.append(logical)
            continue
        found = {}
        for group in ordered:
            header = '／'.join(group.bands[0].header) if not group.subject else group.axis
            if not group.subject:
                header = group.axis if group.axis in group.bands[0].header else header
                header = '／'.join(group.bands[0].header[:group.bands[0].header.index(group.axis) + 1]) \
                    if group.axis in group.bands[0].header else header
            roles = None
            if judge is not None and not group.subject:
                roles = judged_roles(judge, group, margins.get(group.axis))
            if not group.subject:
                group_items = items(group, header, margins.get(group.axis), roles, limits.get(group.axis), logical.ocr,
                                    bool(layout and layout.get(group.axis, {}).get('amount_brackets')),
                                    (layout or {}).get(group.axis))
            elif group.mode == 'indent':
                group_items = items(group, group.axis)
            else:
                for band in group.bands:
                    band.words = split_glued_numbers(band.words, edges)
                group_items = subject_items(group)
            if not group.subject:
                group_items = join_transfer_tails(group_items, layout)
            for item in group_items:
                # 01.01.01.01から流用 starts with digits. A parenthesised remark joined to an item's
                # name (`需用費（同事業、委託料へ流用 △1,815,000）`) does not make the item a note.
                if (TRANSFER.search(PAREN_TAIL.sub('', item.name)) and not group.subject
                        and not is_plain_name(layout, item)):
                    item.role = 'annotation'  # a transfer note annotates the subject row
                elif item.code is None and TOTAL.search(item.name):
                    item.role = 'total'
                elif item.code is None and not item.amounts and not group.subject:
                    item.role = 'note'
                elif (item.code is None and item.amounts and not group.subject and not item.kinds
                      and not is_plain_name(layout, item)
                      and (kind_of(PAREN_TAIL.sub('', item.name)) is not None or is_account_code(item.name))):
                    item.role = 'annotation'  # An amount note or a transfer's account code, no item of the breakdown.
            found[id(group)] = group_items
        subject = next((g for g in ordered if g.subject), None)
        if subject is not None and untitled(subject):
            # A table without a 款 column under a title naming its 款: the title is the 款 item.
            for code, name, line in logical.titles:
                # An indent group reads levels from where a code starts: the title stands where a 款 code would
                # (one character inside the 款 column), not where its own text starts.
                indent = subject.bands[0].x0 + (line[0].y1 - line[0].y0) if subject.mode == 'indent' else line[0].x0
                title = Item(subject, line[0].page, [line], code, name, indent, level=-1, level_name='款')
                kind, run = title_amount(line)
                if kind and run and is_amount(normalize(text(run))):  # `（決算額 4,764,369,474 円）`
                    title.amounts.append((kind, run))
                elif kind:
                    unowned.append({'kind': 'unreadable amount', 'page': line[0].page, 'text': normalize(text(line))})
                found[id(subject)].insert(0, title)
        # A codeless line whose row holds amounts in an amount band is an item
        # (a 節 column printed without numbers), not a note.
        for band in logical.bands:
            if band.kind != 'amount':
                continue
            for line in lines(band.words):
                money = [g for g in line if is_amount(g.text)]
                if not money:
                    continue
                target = owner(money, band, ordered, found, roles=('node', 'repeat', 'total', 'note'))
                if target is not None:
                    column_amount_items.add(id(target))
                if target is not None and target.role == 'note':
                    target.role = 'node'
                if layout:
                    note_target = owner(money, band, ordered, found, roles=('node', 'repeat', 'total', 'note', 'annotation'))
                    prefixes = note_prefixes(layout.get(note_target.group.axis, {})) if note_target is not None else ()
                    if note_target is not None and normalize(text(note_target.lines[0])).startswith(prefixes):
                        column_amount_items.add(id(note_target))
        all_items.append((logical, ordered, found))
    # A subject's name can cross a rule of its narrow name column while its amount cell stays whole.
    # The next line without a code or amount is still the name, not a deeper subject (`センタ－費`).
    # Codes set right in their column: a one-digit and a two-digit code of one level start a digit apart (4–6pt).
    # A wider spread is names or other levels sharing the column, not alignment.
    code_starts: dict[int, list[float]] = defaultdict(list)
    digit_widths: dict[int, list[float]] = defaultdict(list)
    for _, ordered, found in all_items:
        for group in ordered:
            if group.subject and group.mode == 'indent':
                for item in found[id(group)]:
                    if item.code is not None and item.role == 'node' and item.glyphs:
                        code_starts[item.level].append(item.glyphs[0].x0)
                        if len(item.glyphs[0].text) == 1:
                            digit_widths[item.level].append(item.glyphs[0].x1 - item.glyphs[0].x0)
    right_set = set()
    for level, xs in code_starts.items():
        common = [x for x, n in Counter(round(x) for x in xs).items() if n >= 3]  # a stray start is not a column
        # Set right, a one-digit code starts one digit (as wide as the font sets it) after a two-digit one.
        digit = max(digit_widths[level], default=0)
        gap = max(common) - min(common) if common else 0
        if common and 3 < gap and (gap <= 6.5 or abs(gap - digit) <= .6):
            right_set.add(level)
    for logical, ordered, found in all_items:
        for group in ordered:
            if not group.subject:
                continue
            kept = []
            for item in found[id(group)]:
                previous = kept[-1] if kept else None
                if (previous is not None and previous.code is not None and previous.name
                        and previous.role == item.role == 'node' and item.code is None and item.name
                        and not item.amounts and id(item) not in column_amount_items
                        and not TOTAL.search(item.name) and item.page == previous.page
                        and (abs(item.indent - previous.indent) <= 3 if group.mode == 'indent' else
                             group.bands[item.level].header[-1] == group.bands[previous.level].header[-1])
                        and 0 <= item.y0 - previous.y1 <= max(g.y1 - g.y0 for g in item.glyphs)):
                    previous.name += item.name
                    previous.lines += item.lines
                    continue
                kept.append(item)
            if group.mode == 'indent':
                # Join at the name's position before learning subject levels from the code's start.
                for item in kept:
                    # The code leads the item: a name set a few points above its code's line (OCR) is not the start.
                    item.indent = min(g.x0 for g in item.glyphs) if logical.ocr else item.glyphs[0].x0
                    band = group.bands[item.level] if 0 <= item.level < len(group.bands) else None
                    narrow = len(group.bands) >= 3 and all(b.x1 - b.x0 < 20 for b in group.bands[:-1])
                    if band is not None and item.code is not None and narrow and item.level in right_set:
                        # A staircase of narrow level columns with the codes set right: the column is the level,
                        # not where the digits start (`5` and `10` of one 目 start 5pt apart).
                        item.indent = band.x0
            found[id(group)] = kept
    # A subject name cut at the foot of a page continues without a number or amount at the next page's
    # start (`8 市立社会福祉` / `センター費`). Keep its first-page position; a box cannot span two pages.
    for (_, ordered, found), (_, next_ordered, next_found) in zip(all_items, all_items[1:]):
        for group in ordered:
            tail = found[id(group)][-1] if group.subject and found[id(group)] else None
            if tail is None or tail.role != 'node' or tail.code is None or not tail.name:
                continue
            tail_band = group.bands[tail.level or 0]
            if abs(_cell(tail_band, tail.anchor)[1] - tail_band.body_bottom) > .5:
                continue
            for other in next_ordered:
                if not other.subject or not next_found[id(other)]:
                    continue
                previous_head = None
                for head in list(next_found[id(other)]):
                    if (head.code is not None or head.amounts or id(head) in column_amount_items
                            or head.role != 'node' or not head.name or TOTAL.search(head.name)
                            or not 0 < head.page - tail.page <= 2
                            or [b.header for b in other.bands] != [b.header for b in group.bands]):
                        break
                    head_band = other.bands[head.level or 0]
                    if previous_head is None and abs(_cell(head_band, head.anchor)[0] - head_band.body_top) > .5:
                        break
                    if previous_head is not None and (head.page != previous_head.page
                            or head.level != previous_head.level
                            or not 0 <= head.y0 - previous_head.y1 <= max(g.y1 - g.y0 for g in head.glyphs)):
                        break
                    tail.name += head.name
                    next_found[id(other)].remove(head)
                    previous_head = head
                break
    # An account code printed with the amount of a transfer at the foot of a page and the words that say where
    # it went on the first line of the next table page (`030201【111412】 △33,630` / `020000へ予算流用減`; a
    # page of headings only may lie between): the kind is the next page's. (Joining the two lines would put one
    # item's glyphs on two pages.)
    for (_, ordered, found), (_, next_ordered, next_found) in zip(all_items, all_items[1:]):
        for group in ordered:
            tail = found[id(group)][-1] if not group.subject and found[id(group)] else None
            if tail is None or tail.role != 'annotation' or tail.code is not None or tail.hint is not None \
                    or not is_account_code(tail.name):
                continue
            for other in next_ordered:
                head = next_found[id(other)][0] if not other.subject and other.axis == group.axis \
                    and next_found[id(other)] else None
                if head is not None and head.code is None and not head.amounts and 0 <= head.page - tail.page <= 2:
                    tail.hint = kind_of(head.name, words=True)
                    break
    # Use the subject events after name continuations have been joined: a fragment is not a new
    # subject boundary. A note's parts still cannot cross into another subject with a matching sum.
    for logical, ordered, found in all_items:
        subject_starts = tuple(sorted({subject_row(i, logical)[0] for g in ordered if g.subject
                                       for i in found[id(g)] if i.role == 'node'}))
        for group in ordered:
            if not group.subject:
                if layout and group.axis in layout:
                    found[id(group)] = apply_layout(found[id(group)], layout[group.axis], column_amount_items,
                                                   subject_starts)
                note_breakdown(found[id(group)], subject_starts,
                               1 if (layout or {}).get(group.axis, {}).get('single_part_notes') else 2)
    # The amount of a label that ends a page is the first line of the next page, under the subject's row
    # repeated at its top (`wrap: amount_on_last_line`, `items` keeps that line as a nameless item).
    tails: dict[str, Item] = {}
    for _, ordered, found in all_items:
        for group in ordered:
            if group.subject:
                continue
            mine = found[id(group)]
            previous = tails.get(group.axis)
            if ((layout or {}).get(group.axis, {}).get('wrap') == 'amount_on_last_line' and previous is not None
                    and mine and not mine[0].name and mine[0].amounts and mine[0].code is None
                    and not previous.amounts and previous.name
                    and previous.role in ('node', 'note', 'annotation') and mine[0].page == previous.page + 1):
                first = mine.pop(0)
                previous.lines += first.lines
                previous.amounts += first.amounts
            if mine:
                tails[group.axis] = mine[-1]
    for axis, hints in (layout or {}).items():
        if not (chars := hints.get('indent_chars')):
            continue
        axis_items = [i for _, ordered, found in all_items for g in ordered if not g.subject and g.axis == axis
                      for i in found[id(g)] if i.role == 'node']
        # Codes are set a whole step apart at every level, however wide the number (a name's start is not).
        # The number's line places the item: a name wrapped above it (`使用料及` / `13` / `賃借料`) starts
        # in the name column.
        first = lambda i: next((line[0] for line in i.lines if line and line[0].text[:1].isdigit()), i.lines[0][0])
        start = lambda i: first(i).x0
        origin = min((start(i) - i.group.x0 for i in axis_items), default=0)
        # A character is the axis's usual line height: OCR that read only the top half of a line
        # (`4土` 2.4pt high among 6pt lines, 281000) must not make its step that small.
        heights = sorted(first(i).y1 - first(i).y0 for i in axis_items)
        usual = heights[len(heights) // 2] if heights else 0
        for item in axis_items:
            if item.level is None:
                # A level is a whole step: an item set half a character right of its siblings (`98 …（再配当用）`
                # among `14 …`) is one of them, so only a shift of more than 60% of a step is a deeper level.
                height = max(first(item).y1 - first(item).y0, usual)
                steps = (start(item) - item.group.x0 - origin) / (chars * height)
                item.level = floor(steps + .4)
    # Subject levels by indentation, learned over the document (pattern indent).
    starts = sorted(i.indent for _, ordered, found in all_items for g in ordered if g.subject and g.mode == 'indent'
                    for i in found[id(g)] if i.role == 'node')
    subject_levels: list[list[float]] = []
    for value in starts:
        if subject_levels and value - subject_levels[-1][-1] <= 3:
            subject_levels[-1].append(value)
        else:
            subject_levels.append([value])
    subject_levels = [c for c in subject_levels if len(c) >= max(2, len(starts) // 100)]
    centres = [sum(c) / len(c) for c in subject_levels]
    for _, ordered, found in all_items:
        for group in ordered:
            if group.subject and group.mode == 'indent':
                group.levels = len(centres) or 1
                for item in found[id(group)]:
                    item.level = min(range(len(centres)), key=lambda i: abs(centres[i] - item.indent)) if centres else 0
                    item.level_name = SUBJECT_LEVELS[item.level] if item.level < len(SUBJECT_LEVELS) else None
    # Indentation levels per non-subject axis, learned over the document.
    indents: dict[str, list[float]] = defaultdict(list)
    for _, ordered, found in all_items:
        for group in ordered:
            if not group.subject:
                indents[group.axis] += [i.indent for i in found[id(group)] if i.role == 'node']
    for axis, values in indents.items():
        clusters: list[list[float]] = []
        for value in sorted(values):
            if clusters and value - clusters[-1][-1] <= 3:
                clusters[-1].append(value)
            else:
                clusters.append([value])
        clusters = [part for cluster in clusters for part in split_wide(cluster)]
        minimum = max(2, len(values) // 200)
        kept = [c for c in clusters if len(c) >= minimum]
        centres = [sum(c) / len(c) for c in kept]
        # A level met once in a small document is still a level when it is clearly apart (half a
        # character or more) from every frequent one: `上・下水道代` under `光熱水費` (132292).
        for c in clusters:
            if len(c) < minimum and all(abs(sum(c) / len(c) - centre) >= 6 for centre in centres):
                kept.append(c)
                centres.append(sum(c) / len(c))
        levels[axis] = sorted(sum(c) / len(c) for c in kept)
    depth_of = lambda item: 1 + min(range(len(levels[item.group.axis])),
                                    key=lambda i: abs(levels[item.group.axis][i] - item.indent))
    # Right-aligned amount columns also mark the level: learn which column each
    # indentation level prints its amount in, then read a codeless line whose
    # amount sits in the column of the amountless item above as that item's
    # wrapped last line (`【所管課】 299,161,329`).
    columns: dict[str, dict[int, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for _, ordered, found in all_items:
        for group in ordered:
            if group.subject or not levels.get(group.axis):
                continue
            for item in found[id(group)]:
                if item.role == 'node' and item.amounts:
                    columns[group.axis][round(item.amounts[0][1][-1].x1 - item.amounts[0][1][-1].offset)][depth_of(item)] += 1
    amount_depth = lambda item: next((c.most_common(1)[0][0] for x, c in columns[item.group.axis].items()
                                      if abs(x - round(item.amounts[0][1][-1].x1 - item.amounts[0][1][-1].offset)) <= 2), None)
    for _, ordered, found in all_items:
        for group in ordered:
            if group.subject or not levels.get(group.axis):
                continue
            kept: list[Item] = []
            for item in found[id(group)]:
                previous = kept[-1] if kept else None
                if (previous is not None and previous.role in ('node', 'note') and not previous.amounts
                        and item.role == 'node' and item.code is None and item.amounts and not item.decided
                        and amount_depth(item) == depth_of(previous) and depth_of(item) > depth_of(previous)):
                    previous.role = 'node'
                    previous.lines += item.lines
                    previous.name += item.name
                    previous.amounts += item.amounts
                    continue
                kept.append(item)
            found[id(group)] = kept
    # Pattern position: a level is a numbering shape at one aligned position, or the
    # indentation of codeless lines; levels rank by where their lines start.
    position_rank, position_key = position_levels(all_items, levels, depth_of)
    # 款 come from titles in this document: the 項・目 columns of untitled tables sit one level down.
    titled = any(i.level == -1 for _, ordered, found in all_items for g in ordered if g.subject for i in found[id(g)])
    for logical, ordered, found in all_items:
        # A subject item opens at the top of its rule-bounded row: its label may be
        # centred lower than the first remark of its block.
        events = sorted(((subject_row(item, logical)[0] if group.subject else item.anchor,
                          ordered.index(group), item.level or 0, item.anchor, item)
                         for group in ordered for item in found[id(group)]), key=lambda e: e[:4])
        events = [(e[0], e[1], e[4]) for e in events]
        closing_headings = closing_department_headings([item for _, _, item in events])
        headings = heading_names(logical)
        subject_depth = max((g.levels or len(g.bands) for g in ordered if g.subject), default=3) \
            + any(titled and title_shift(g) for g in ordered if g.subject)
        row = None  # (subject item, top, bottom) of the latest subject row
        for _, _, item in events:
            if not item.group.subject and item.role in ('node', 'note') and row is not None \
                    and (row[0].depth < subject_depth or item.code is None) \
                    and row[1] - .5 <= item.anchor <= row[2] + .5 \
                    and (not item.amounts or (kind_of(item.name, words=True) is not None
                                              and not is_plain_name(layout, item))):
                # A line in a subject's row annotates it when it prints no amount (a list of 議決 numbers) or
                # reads as a note (流用・充用・不用額…). A line with an amount that does not is an item, even
                # when the row is as tall as the subject's whole breakdown and the subject's name is centred
                # next to it: `(企画調整課) 4,021,547` is a department of the 事業 above it (132225).
                item.role = 'annotation'
            if (item.role in ('node', 'note') and not item.group.subject and stack
                    and normalize(stack[-1].name) == '予備費' and RESERVE_DESTINATION.search(normalize(item.name))):
                item.role = 'annotation'  # `02-01-04-03-14-01へ 1,630,000`: where the reserve was used (ADR 0024)
            if item.role == 'annotation':
                target = row[0] if row is not None else (stack[-1] if stack else None)
                notes.append({'kind': 'annotation', 'page': item.page, 'text': item.name,
                              'amounts': [text(r) for _, r in item.amounts]})
                if target is not None:
                    label = normalize(text([g for g in item.glyphs if not any(g in r for _, r in item.amounts)]))
                    for header, run in item.amounts:
                        annotations.append((target, f'{header}／注記／{label}', run, logical.unit))
                    remarks.append({'kind': 'annotation', 'target': target, 'heading': None,
                                    # A name that is only an account code (`・040102【151502】 400`) is the
                                    # counterpart of a transfer: its words (`1200へ予算流用増`) may sit on the
                                    # next page, so the amount is a 流用 note whichever way they read.
                                    'hint': item.hint or ('充用' if normalize(target.name) == '予備費'
                                                          else '流用' if is_account_code(item.name) else None),
                                    'label': [g for g in item.glyphs if not any(g in r for _, r in item.amounts)],
                                    'runs': [run for _, run in item.amounts], 'unit': logical.unit})
                continue
            if item.role == 'total':
                notes.append({'kind': 'total', 'page': item.page, 'text': item.name}); continue
            if item.role == 'note':
                notes.append({'kind': 'note', 'page': item.page, 'text': item.name,
                              'amounts': [text(r) for _, r in item.amounts]})
                continue
            if item.group.subject:
                depth = 1 if item.level == -1 else item.level + 1 + (titled and title_shift(item.group))
                previous = stack[depth - 1] if len(stack) >= depth else None
                if previous is None:  # bands that skip a level (a name band between the codes): find the open one by band
                    previous = next((s for s in stack if s.level == item.level), None)
                if previous is not None and repeats(previous, item, logical.ocr):
                    item.key = previous.key  # a repeated subject heading on a continuation page
                    item.role = 'repeat'
                    shown = next((g for g in item.glyphs[:3] if CODE.match(normalize(g.text))), None)
                    if shown is not None:  # `(1議会費)`: the bracket is a word of its own, the code follows it
                        repeated_codes.append(shown)
                    continue
                if not item.name:
                    level = item.level_name or (item.group.bands[item.level].header[-1]
                                                if item.group.mode in ('bands', 'names') else '')
                    item.name = headings.get((level, normalize(item.code or '')), '')
                if depth > len(stack) + 1:
                    unowned.append({'kind': 'subject depth gap', 'page': item.page, 'text': item.name})
                del stack[depth - 1:]
                item.parent = stack[-1] if stack else None
                item.depth = depth
                stack.append(item)
                branch.clear()
                open_headings.clear()
                row = (item, *subject_row(item, logical))
            else:
                ranks = levels[item.group.axis]
                depth = 1 + min(range(len(ranks)), key=lambda i: abs(ranks[i] - item.indent)) if ranks else 1
                mode = detail if isinstance(detail, str) else detail.get(item.group.axis, 'indent')
                if mode == 'position' and id(item) in position_key:
                    depth = position_rank[item.group.axis][position_key[id(item)]] + 1
                if mode == 'shape':
                    depth = shape_depth(item, depth, shapes.setdefault(item.group.axis, []),
                                        branch.get(item.group.axis, []), anchors.setdefault(item.group.axis, {}))
                if item.level is not None:
                    depth = item.level + 1  # the configured mark names a breakdown level
                axis = item.group.axis
                if id(item) in closing_headings:
                    open_headings[axis] = depth  # its parts follow one level down
                elif axis in open_headings:
                    if depth < open_headings[axis] or department_heading(item):
                        del open_headings[axis]  # shallower than the heading, or another department
                    else:
                        depth += 1  # under the department's heading line, one level down
                open_items = branch.setdefault(item.group.axis, [])
                del open_items[depth - 1:]
                while len(open_items) < depth - 1:
                    open_items.append(open_items[-1] if open_items else None)
                parent = next((p for p in reversed(open_items) if p is not None), None)
                item.parent = parent or (stack[-1] if stack else None)
                item.depth = (parent.depth + 1) if parent is not None else 1
                open_items.append(item)
                if item.parent is None:
                    unowned.append({'kind': 'no subject parent', 'page': item.page, 'text': item.name})
            item.key = node_key(item)
            x0, y0, x1, y1 = _bbox(item.glyphs)
            nodes.append({'node_key': item.key, 'parent_node_key': item.parent.key if item.parent else None,
                          'axis_header': item.group.axis, 'depth': item.depth,
                          'level_header': (item.level_name or (item.group.bands[item.level].header[-1]
                                                               if item.group.mode in ('bands', 'names') else None)
                                           if item.group.subject else None),
                          'code_text': item.code, 'name_text': item.name or None, 'physical_page': item.page,
                          'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1})
        for logical_, ordered_, found_ in [(logical, ordered, found)]:
            for item in (i for g in ordered for i in found[id(g)]):
                if item.role not in ('node', 'repeat') or item.key is None:
                    continue
                for header, run in item.amounts:
                    amounts.append(_amount(item.key, header, run, logical.unit))
                for label, run, heading in item.kinds:
                    remarks.append({'kind': 'kind line', 'target': item, 'heading': heading, 'label': label,
                                    'runs': [run], 'unit': logical.unit})
            for band in logical.bands:
                if band.kind != 'amount':
                    continue
                sign = None
                stacked = None  # (kind word, rule-bounded cell) of the last kind word printed in this column
                previous = None  # (item, rule-bounded cell) of the last amount this column gave to an item
                for line in lines(band.words):
                    printed = {}  # the amount of a word that runs on into text, by the word it was cut from
                    cut = [_leading_amount(g) for g in line]
                    printed.update({id(new): old for new, old in zip(cut, line)})
                    line = cut
                    money = [g for g in line if is_amount(g.text) or re.fullmatch(r'[0-9,△▲\-]+', g.text)]
                    if [g.text for g in money] in (['△'], ['▲']):
                        sign = money[0]  # a minus sign printed above its number
                        continue
                    if not money:
                        # A kind word inside an amount cell (`継続費逓次繰越` / `73,871,000` / `繰越明許費` /
                        # `102,288,855`): the amount printed below it, in the same cell, carries it (132241).
                        word = normalize(text(line))
                        if line and STACKED_KIND.fullmatch(word):
                            cell = _cell(band, sum((g.y0 + g.y1) / 2 for g in line) / len(line))
                            stacked = (word, cell) if '／'.join(band.header) in stacking else None
                        continue
                    if sign is not None and money[0].y0 - sign.y0 < 14 and not money[0].text.startswith(('△', '▲')):
                        money = [sign] + money
                    sign = None
                    candidate = ''.join(g.text for g in money)
                    if not is_amount(candidate):
                        unowned.append({'kind': 'unreadable amount', 'page': money[0].page, 'text': candidate}); continue
                    target = owner(money, band, ordered, found, ocr=logical.ocr)
                    if target is None and stacked is not None and previous is not None:
                        # `事故繰越` / `19,968,000` printed two lines below its 節 under `31,321,000`: the amount
                        # under a kind word, in the same cell as the amount above it, belongs to that amount's item.
                        cell = _cell(band, sum((g.y0 + g.y1) / 2 for g in money) / len(money))
                        if stacked[1] == cell and previous[1] == cell:
                            target = previous[0]
                    if target is not None and target.role == 'total':
                        notes.append({'kind': 'total amount', 'page': money[0].page, 'text': candidate,
                                      'header': '／'.join(band.header), 'unit': logical.unit, 'label': target.name,
                                      'box': _bbox([printed.get(id(g), g) for g in money])})
                        continue
                    if target is None or target.key is None:
                        record = {'kind': 'amount without row', 'page': money[0].page, 'text': candidate,
                                  'header': '／'.join(band.header)}
                        unowned.append(record)
                        centre = sum((g.y0 + g.y1) / 2 for g in money) / len(money)
                        if stacked is None or stacked[1] != _cell(band, centre):  # a kind word names it otherwise
                            unowned_runs.append((record, money))
                        continue
                    header = '／'.join(band.header)
                    y = sum((g.y0 + g.y1) / 2 for g in money) / len(money)
                    if stacked is not None and stacked[1] == _cell(band, y):
                        header = f'{header}／{stacked[0]}'
                    amounts.append(_amount(target.key, header, money, logical.unit))
                    previous = (target, _cell(band, y))
    for target, header, run, unit in annotations:
        amounts.append(_amount(target.key, header, run, unit))
    marked = []
    for remark in remarks:
        # The account a note belongs to: a remark's own target, or the item's nearest account ancestor.
        cursor = remark['target']
        while cursor is not None and not cursor.group.subject:
            cursor = cursor.parent
        if cursor is None or cursor.key is None or remark['target'].key is None:
            continue
        marked.append({'kind': remark['kind'], 'node_key': remark['target'].key, 'parent_node_key': cursor.key,
                       'heading': remark['heading'], 'label': remark['label'], 'runs': remark['runs'],
                       'unit': remark['unit'], 'hint': remark.get('hint')})
    repeated_amounts = repeated_parent_rows(nodes, amounts, unowned, unowned_runs)
    return Built(nodes, _dedupe(amounts, unowned), unowned, notes, marked, skipped, repeated_codes, repeated_amounts)


def judged_roles(judge, group: Group, margins: set[int] | None) -> dict[int, str]:
    """Features of each printed line for a judgment: text, indentation and amount column in characters."""
    entries = entries_of(group, margins)
    labelled = [e for e in entries if e[0]]
    if not labelled:
        return {}
    heights = sorted(g.y1 - g.y0 for e in labelled for g in e[0])
    char = heights[len(heights) // 2] or 9
    left = min(e[0][0].x0 for e in labelled)
    right = group.bands[-1].x1
    features = []
    for index, (label, money, code, name) in enumerate(entries):
        if not label:
            continue
        features.append({'id': f'L{index}', 'text': normalize(text(label)), 'code': code,
                         'indent': round((label[0].x0 - left) / char),
                         'amount': normalize(text(money[-1])) if money else None,
                         'amount_inset': round((right - money[-1][-1].x1) / char) if money else None})
    return {int(key[1:]): role for key, (role, _) in judge(features).items()}


def subject_row(item: Item, logical: Logical) -> tuple[float, float]:
    """The narrowest rule-bounded row around a subject label among the amount bands whose body
    holds the label's height. (The other half of a spread may still be in its taller header at
    that height and would give a cell of no height, 132276.)"""
    y = item.anchor
    cells = [_cell(b, y) for b in logical.bands if b.kind == 'amount' and b.body_top < y < b.body_bottom]
    cells = [c for c in cells if c[1] - c[0] <= 80]
    return min(cells, key=lambda c: c[1] - c[0]) if cells else (y - 4, y + 4)


def _bbox(glyphs: list[Glyph]) -> tuple[float, float, float, float]:
    boxes = [g.original for g in glyphs]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def repeated_parent_rows(nodes: list[dict], amounts: list[dict], unowned: list[dict],
                         runs: list[tuple[dict, list[Glyph]]]) -> list[Glyph]:
    """The unowned amount rows that print the amounts of the account row above them again.

    A row has no name and no row of its own, and each of its printed amounts is equal, to the yen and in the
    same column, to the amount of the nearest 款・項・目 row above it on the page. One amount that differs keeps
    the whole row unowned (the check stops). The row is recorded, not dropped: its glyphs become an excluded
    region of kind `親の繰り返し`.
    """
    if not runs:
        return []
    subject = {n['node_key'] for n in nodes if n['axis_header'] == '科目'}
    rows: dict[tuple, list] = defaultdict(list)
    for record, run in runs:
        x0, y0, x1, y1 = _bbox(run)
        rows[record['page'], round((y0 + y1) / 2)].append((record, run, y0))
    repeated: list[Glyph] = []
    for (page, _), row in rows.items():
        matched = []
        for record, run, y0 in row:
            above = [a for a in amounts if a['node_key'] in subject and a['physical_page'] == page
                     and a['header_path'] == record['header'] and a['y1'] is not None and a['y1'] <= y0 + 1]
            nearest = max(above, key=lambda a: a['y1'], default=None)
            same = nearest is not None and normalize(nearest['amount_text']) == normalize(record['text'])
            matched.append(same)
        if all(matched):
            for record, run, _ in row:
                repeated += run
                unowned.remove(record)
    return repeated


def _amount(key: str, header: str, run: list[Glyph], unit: str | None) -> dict:
    x0, y0, x1, y1 = _bbox(run)
    return {'node_key': key, 'header_path': header, 'amount_text': ''.join(g.text for g in run),
            'unit_text': unit, 'physical_page': run[0].page, 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1}


def _dedupe(amounts: list[dict], unowned: list[dict]) -> list[dict]:
    """A repeated subject heading reprints its amounts; keep one, flag differences."""
    seen: dict[tuple, dict] = {}
    for amount in amounts:
        identity = (amount['node_key'], amount['header_path'])
        if identity in seen:
            if normalize(seen[identity]['amount_text']) != normalize(amount['amount_text']):
                unowned.append({'kind': 'conflicting amount', 'page': amount['physical_page'],
                                'text': f"{seen[identity]['amount_text']} / {amount['amount_text']}",
                                'header': amount['header_path'],
                                'sources': [{k: source[k] for k in ('physical_page', 'amount_text', 'unit_text',
                                                                   'x0', 'y0', 'x1', 'y1')}
                                            for source in (seen[identity], amount)]})
            continue
        seen[identity] = amount
    return list(seen.values())
