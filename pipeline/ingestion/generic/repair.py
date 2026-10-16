"""Stage 1b: repair the text layer before bands. No jurisdiction, page or coordinate is configured.

1. Invisible glyphs: a text object drawn outside its clipping path leaves no
   ink. Some PDFs draw a spread twice and clip each copy to one half
   (131172), so Poppler reports every glyph twice. pdfium exposes each text
   object's clip; a character is dropped when the only objects drawing it at
   its position are clipped away. Exact repeats at the same position collapse.
2. Position repairs: single glyphs overlapping at one position are one printed
   character split by the font (分 as 八 + 刀); digits, commas and minus signs
   touching on one line are one amount (`1 3 , 4 6 3` drawn glyph by glyph).
3. Known misreadings: `pipeline/ingestion/lib/text_repairs.csv` (wrong, right,
   optional context regex, reason). They are applied only to documents judged
   broken by `is_broken`, whose criterion and threshold live here, so a
   legitimate word elsewhere is not rewritten. Every hit is counted with
   examples for review.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import ctypes
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
import re
import unicodedata

from ingestion.generic.observe import Page, Rule, Word

REPAIRS = Path(__file__).resolve().parents[1] / 'lib/text_repairs.csv'
NUMERIC = re.compile(r'^[0-9,△▲\-]+$')
# A note's words with its amount set against them (`繰越事業費不用額55,753,516円`): the words and the amount.
GLUED_AMOUNT = re.compile(r'^(.*[^0-9,０-９△▲\s])([△▲]?[0-9]{1,3}(?:,[0-9]{3})+円?)$')
SIGN_INSIDE = re.compile(r'(?<=[^\s△▲(（\[「［])[△▲](?=[0-9])')
# Health criteria (one place). A document is broken when known multi-character
# misreadings are frequent. Pages without the common column headings are
# recorded but do not decide: a narrative report (132012) has none, and judging
# it broken rewrote correct words (捕獲→捕護, 関連動画→関運動画, 大栗川→大票川).
CORE_HEADINGS = ('支出済額', '不用額', '予算現額', '当初予算額', '予算額', '決算額', '備考', '説明')
MISREADINGS_PER_10K = 2.0      # multi-character dictionary misreadings per 10,000 characters
REBUILD_SHARE = 0.2            # invisible share of a page's glyphs above which words are rebuilt from glyphs


@dataclass
class Report:
    hidden_glyphs: int = 0
    hidden_rules: int = 0
    vertical_words: int = 0
    invisible_error: str | None = None
    pattern: dict = field(default_factory=dict)
    unit: dict = field(default_factory=dict)
    duplicate_words: int = 0
    composite_glyphs: int = 0
    letterspaced_glyphs: int = 0
    joined_numbers: int = 0
    off_page_rules: int = 0
    cropped_words: int = 0
    health: dict = field(default_factory=dict)
    broken: bool = False
    skipped_pages: list = field(default_factory=list)  # pages printed as the other direction
    hits: Counter = field(default_factory=Counter)
    examples: dict = field(default_factory=lambda: defaultdict(list))

    def as_dict(self) -> dict:
        return {'hidden_glyphs': self.hidden_glyphs, 'hidden_rules': self.hidden_rules,
                'vertical_words': self.vertical_words, 'invisible_error': self.invisible_error, 'pattern': self.pattern, 'unit': self.unit, 'duplicate_words': self.duplicate_words,
                'composite_glyphs': self.composite_glyphs, 'letterspaced_glyphs': self.letterspaced_glyphs, 'joined_numbers': self.joined_numbers,
                'off_page_rules': self.off_page_rules, 'cropped_words': self.cropped_words,
                'health': self.health, 'broken': self.broken, 'skipped_pages': self.skipped_pages, 'repairs': sum(self.hits.values()),
                'hits': dict(self.hits.most_common()), 'examples': {k: v[:5] for k, v in self.examples.items()}}


@cache
def rules() -> tuple[tuple[str, str, re.Pattern | None], ...]:
    with REPAIRS.open() as stream:
        return tuple((row['wrong'], row['right'], re.compile(row['context']) if row['context'] else None)
                     for row in csv.DictReader(stream))


# --- 1. invisible glyphs -----------------------------------------------------

def _glyphs(pdf, number: int, form_clips: bool = False):
    """(box, character, visible) of every drawn character, in Poppler's top-left coordinates.

    Visibility belongs to the text object that draws the character: visible
    when it has no clip or its bounds meet the clip. `form_clips` (the layout setting
    `text_layer.form_clips`): text drawn inside a form gives its clip in the form's space, where the
    object's own bounds are too, so either the character box or the object's bounds meeting it is visible
    (281000 draws each page as a form scaled from 72×72).
    """
    import pypdfium2.raw as raw
    page = pdf[number - 1]
    left, _, _, top = page.get_cropbox()
    textpage = page.get_textpage()
    clips: dict[int, tuple | None] = {}

    def clip_of(handle):
        """The clip rectangle of an object (page space), or None when it has none."""
        address = ctypes.cast(handle, ctypes.c_void_p).value
        if address not in clips:
            clip = raw.FPDFPageObj_GetClipPath(handle)
            box = None
            if clip and raw.FPDFClipPath_CountPaths(clip) > 0:
                xs, ys = [], []
                for i in range(raw.FPDFClipPath_CountPaths(clip)):
                    for j in range(raw.FPDFClipPath_CountPathSegments(clip, i)):
                        segment = raw.FPDFClipPath_GetPathSegment(clip, i, j)
                        x, y = ctypes.c_float(), ctypes.c_float()
                        raw.FPDFPathSegment_GetPoint(segment, x, y)
                        xs.append(x.value); ys.append(y.value)
                box = (min(xs), min(ys), max(xs), max(ys)) if xs else None
            clips[address] = box
        return clips[address]

    def inside(box, clip) -> bool:
        # box and clip as (left, bottom, right, top) in PDF space
        return clip is None or (box[0] < clip[2] and box[2] > clip[0] and box[1] < clip[3] and box[3] > clip[1])

    paths = []
    for index in range(raw.FPDFPage_CountObjects(page.raw)):
        handle = raw.FPDFPage_GetObject(page.raw, index)
        if raw.FPDFPageObj_GetType(handle) == raw.FPDF_PAGEOBJ_PATH:
            l, b, r, t = (ctypes.c_float() for _ in range(4))
            raw.FPDFPageObj_GetBounds(handle, l, b, r, t)
            paths.append(((l.value - left, top - t.value, r.value - left, top - b.value),
                          inside((l.value, b.value, r.value, t.value), clip_of(handle))))
    found = []
    for index in range(textpage.count_chars()):
        code = raw.FPDFText_GetUnicode(textpage.raw, index)
        if code in (0, 10, 13, 32, 0x3000):
            continue
        l, r, b, t = (ctypes.c_double() for _ in range(4))
        if not raw.FPDFText_GetCharBox(textpage.raw, index, l, r, b, t):
            continue
        handle = raw.FPDFText_GetTextObject(textpage.raw, index)
        # The character box is in page space; compare it, not the object's bounds,
        # with the clip (object bounds come back in another space on some PDFs).
        visible = inside((l.value, b.value, r.value, t.value), clip_of(handle)) if handle else True
        if not visible and form_clips:
            ol, ob, orr, ot = (ctypes.c_float() for _ in range(4))
            raw.FPDFPageObj_GetBounds(handle, ol, ob, orr, ot)
            visible = inside((ol.value, ob.value, orr.value, ot.value), clip_of(handle))
        found.append(((l.value - left, top - t.value, r.value - left, top - b.value), chr(code), visible))
    textpage.close(); page.close()
    return found, paths


def _drawn(rule, paths) -> bool:
    """A rule is ink unless clipped-away strokes are almost all that cover it.

    Only strokes thin across the rule count; a path whose bounds span the whole
    grid says nothing about one line.
    """
    length = {True: 0.0, False: 0.0}
    for (x0, y0, x1, y1), visible in paths:
        if rule.vertical:
            if x1 - x0 < 6 and x0 - 1.5 <= rule.x0 <= x1 + 1.5:
                length[visible] += max(0.0, min(y1, rule.y1) - max(y0, rule.y0))
        elif y1 - y0 < 6 and y0 - 1.5 <= rule.y0 <= y1 + 1.5:
            length[visible] += max(0.0, min(x1, rule.x1) - max(x0, rule.x0))
    # A ghost line has no visible stroke at all; a real line merged with its
    # shifted ghost keeps a visible share.
    return not length[False] or length[True] > .1 * (length[True] + length[False])


def words_from_glyphs(glyphs: list[tuple[tuple[float, float, float, float], str]], report: Report,
                      rules: list | None = None) -> list[Word]:
    """Glyphs into words: neighbours that overlap vertically and sit close, never across a vertical rule."""
    verticals = [r for r in rules or [] if r.vertical]
    unique: list[tuple[tuple[float, float, float, float], str]] = []
    for box, char in sorted(glyphs, key=lambda g: ((g[0][1] + g[0][3]) / 2, g[0][0])):
        if any(char == other and abs(box[0] - b[0]) < 1 and abs(box[1] - b[1]) < 1 for b, other in unique[-8:]):
            report.duplicate_words += 1  # a glyph struck twice (bold by overprint)
            continue
        unique.append((box, char))
    # Glyphs that are horizontally close and overlap vertically form one word
    # (union of neighbours). Small marks such as commas sit low but still overlap.
    order = sorted(range(len(unique)), key=lambda i: unique[i][0][0])
    parent = list(range(len(unique)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for position, i in enumerate(order):
        a = unique[i][0]
        for j in order[position + 1:]:
            b = unique[j][0]
            height = max(a[3] - a[1], b[3] - b[1], 1)
            if b[0] - a[2] > .8 * height:
                break
            if min(a[3], b[3]) - max(a[1], b[1]) >= .3 * min(a[3] - a[1], b[3] - b[1]) and not any(
                    a[2] - .5 <= r.x0 <= b[0] + .5 and r.y0 <= (a[1] + a[3]) / 2 <= r.y1 for r in verticals):
                parent[root(j)] = root(i)
    groups: dict[int, list] = defaultdict(list)
    for i in order:
        groups[root(i)].append(unique[i])
    return [_word(members) for members in groups.values()]


def _word(glyphs: list) -> Word:
    return Word(''.join(char for _, char in glyphs), min(b[0] for b, _ in glyphs), min(b[1] for b, _ in glyphs),
                max(b[2] for b, _ in glyphs), max(b[3] for b, _ in glyphs))


def _without_hidden(words: list[Word], glyphs) -> list[Word]:
    """Remove from Poppler's words the characters whose nearest drawing of the same character is invisible."""
    grid: dict[int, list] = defaultdict(list)
    for glyph in glyphs:
        grid[int(((glyph[0][0] + glyph[0][2]) / 2) // 20)].append(glyph)
    kept: list[Word] = []
    for word in words:
        width = (word.x1 - word.x0) / max(len(word.text), 1)
        flags = []
        for index, char in enumerate(word.text):
            cx, cy = word.x0 + (index + .5) * width, (word.y0 + word.y1) / 2
            near = [(abs((x0 + x1) / 2 - cx), visible) for cell in (-1, 0, 1)
                    for (x0, y0, x1, y1), value, visible in grid[int(cx // 20) + cell]
                    if value == char and abs((x0 + x1) / 2 - cx) <= max(2.0, width) and y0 - 2 <= cy <= y1 + 2]
            flags.append(not near or min(near)[1])
        start = None
        for index, flag in enumerate(flags + [False]):
            if flag and start is None:
                start = index
            elif not flag and start is not None:
                kept.append(Word(word.text[start:index], word.x0 + start * width, word.y0, word.x0 + index * width, word.y1))
                start = None
    return kept


def drop_invisible(pdf_path: Path, pages: list[Page], report: Report, form_clips: bool = False) -> None:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for page in pages:
            glyphs, paths = _glyphs(pdf, page.number, form_clips)
            # Glyphs placed off the page are not on it at all (Poppler skips them);
            # only invisible glyphs on the page call for a rebuild.
            glyphs = [g for g in glyphs if g[0][2] > 0 and g[0][0] < page.width and g[0][3] > 0 and g[0][1] < page.height]
            if all(visible for _, _, visible in glyphs):
                continue  # rules are filtered only on pages that draw invisible text
            drawn = [rule for rule in page.rules if _drawn(rule, paths)]
            report.hidden_rules += len(page.rules) - len(drawn)
            page.rules = drawn
            hidden = sum(1 for _, _, visible in glyphs if not visible)
            report.hidden_glyphs += hidden
            if hidden >= REBUILD_SHARE * len(glyphs):
                # Most of the page is drawn twice: rebuild its words from the visible
                # glyphs, whose boxes are exact, instead of Poppler's words.
                page.words = words_from_glyphs([(box, char) for box, char, visible in glyphs if visible], report, page.rules)
            else:
                page.words = _without_hidden(page.words, glyphs)
    finally:
        pdf.close()


# --- 2. position repairs -----------------------------------------------------

def _same_line(a: Word, b: Word) -> bool:
    overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
    return overlap >= .5 * min(a.y1 - a.y0, b.y1 - b.y0)


def _amount_start(text: str) -> int:
    """Where an amount starts inside a word that sets it against other characters, or 0."""
    found = SIGN_INSIDE.search(text)
    if found:
        return found.start()
    glued = GLUED_AMOUNT.match(text)
    if glued:
        from ingestion.generic.notes import kind_of  # only the words of a note keep an amount apart from them
        if kind_of(glued.group(1)) is not None:
            return glued.start(2)
    return 0


def repair_positions(page: Page, report: Report) -> None:
    # A minus sign starts a number, it is never inside one: `0△22,990,000` is `0` and `△22,990,000`, and
    # `…へ流用△100,325円` is the words of a note and its amount, set without a gap.
    split: list[Word] = []
    for word in page.words:
        # The last character of a letter-spaced line (`増　減`) comes out of the text layer with its box
        # stretched across the spacing, into the next cell. A character is not wider than two of its heights.
        height = word.y1 - word.y0
        if len(word.text) == 1 and ord(word.text) >= 0x2E80 and height > 0 and word.x1 - word.x0 > 2 * height:
            word = Word(word.text, word.x0, word.y0, word.x0 + height, word.y1)
            report.letterspaced_glyphs += 1
        at = _amount_start(word.text)
        if at:
            width = (word.x1 - word.x0) / len(word.text)
            cut = word.x0 + at * width
            split += [Word(word.text[:at], word.x0, word.y0, cut, word.y1),
                      Word(word.text[at:], cut, word.y0, word.x1, word.y1)]
        else:
            split.append(word)
    words = sorted(split, key=lambda w: (round((w.y0 + w.y1) / 2), w.x0))
    result: list[Word] = []
    for word in words:
        twin = next((w for w in result[-6:] if w.text == word.text and abs(w.x0 - word.x0) < .6
                     and abs(w.y0 - word.y0) < .6), None)
        if twin is not None:
            report.duplicate_words += 1  # the same glyph struck twice
            continue
        previous = result[-1] if result else None
        if previous is not None and _same_line(previous, word):
            overlap = min(previous.x1, word.x1) - max(previous.x0, word.x0)
            narrow = min(previous.x1 - previous.x0, word.x1 - word.x0)
            if (len(previous.text) == 1 and len(word.text) == 1 and not NUMERIC.match(previous.text + word.text)
                    and overlap >= .6 * narrow):
                result[-1] = Word(previous.text + word.text, min(previous.x0, word.x0), min(previous.y0, word.y0),
                                  max(previous.x1, word.x1), max(previous.y1, word.y1))
                report.composite_glyphs += 1  # one printed character drawn as two glyphs
                continue
            if _continues(previous, word):
                result[-1] = Word(previous.text + word.text, previous.x0, min(previous.y0, word.y0),
                                  max(previous.x1, word.x1), max(previous.y1, word.y1))
                report.joined_numbers += 1
                continue
        result.append(word)
    # Numbers again, over the words of one printed line left to right. A line is the words that share the
    # vertical extent of its first word, not the same rounded centre: a smaller digit group (`11,148,` +
    # `119`) can centre half a point off, round to the next line, and sit before the digits it continues
    # (132209).
    rows: list[list[Word]] = []
    for word in sorted(result, key=lambda w: ((w.y0 + w.y1) / 2, w.x0)):
        if rows and _same_line(rows[-1][0], word):
            rows[-1].append(word)
        else:
            rows.append([word])
    joined: list[Word] = []
    for row in rows:
        for word in sorted(row, key=lambda w: w.x0):
            if joined and _same_line(joined[-1], word) and _continues(joined[-1], word):
                previous = joined[-1]
                joined[-1] = Word(previous.text + word.text, previous.x0, min(previous.y0, word.y0),
                                  max(previous.x1, word.x1), max(previous.y1, word.y1))
                report.joined_numbers += 1
            else:
                joined.append(word)
    page.words = joined


def _continues(previous: Word, word: Word) -> bool:
    """Whether `word` is the rest of the number `previous` ends: a word that starts with a comma continues the
    number on its left even across a printed space (`2 ,181 ,817`: no number begins with a comma), a number
    ending with a comma continues on its right (`5,` `184,344`, 132209), and touching digit groups join. A minus
    sign never continues a number."""
    comma_gap = 1.2 * (word.y1 - word.y0) if word.text.startswith(',') or previous.text.endswith(',') else 1.0
    return bool(NUMERIC.match(previous.text) and NUMERIC.match(word.text) and word.x0 > previous.x0
                and not (word.text[:1] in '△▲' and previous.text[-1:] not in '△▲')
                and -.5 * (word.x1 - word.x0) <= word.x0 - previous.x1 <= comma_gap)


# --- 3. health and known misreadings --------------------------------------------

def _lines(page: Page) -> list[str]:
    rows: list[list[Word]] = []
    for word in sorted(page.words, key=lambda w: ((w.y0 + w.y1) / 2, w.x0)):
        if rows and _same_line(rows[-1][-1], word):
            rows[-1].append(word)
        else:
            rows.append([word])
    return [''.join(w.text for w in sorted(row, key=lambda w: w.x0)) for row in rows]


def health(pages: list[Page]) -> dict:
    text = [re.sub(r'\s+', '', unicodedata.normalize('NFKC', line)) for page in pages for line in _lines(page)]
    without = sum(1 for page in pages
                  if not any(h in re.sub(r'\s+', '', ''.join(_lines(page))) for h in CORE_HEADINGS))
    characters = sum(len(line) for line in text) or 1
    misreadings = sum(line.count(wrong) for line in text for wrong, _, context in rules() if len(wrong) > 1 and not context)
    return {'pages': len(pages), 'pages_without_headings': without,
            'missing_headings_ratio': round(without / max(len(pages), 1), 3),
            'misreadings': misreadings, 'misreadings_per_10k': round(misreadings * 10000 / characters, 2)}


def is_broken(measure: dict) -> bool:
    return measure['misreadings_per_10k'] >= MISREADINGS_PER_10K


def apply_dictionary(page: Page, report: Report) -> None:
    repaired = []
    for word in page.words:
        value = word.text
        for wrong, right, context in rules():
            if wrong not in value:
                continue
            if context is None:
                count = value.count(wrong)
                fixed = value.replace(wrong, right)
            else:
                spans = [m.span() for m in context.finditer(value)]
                pieces, cursor, count = [], 0, 0
                for found in re.finditer(re.escape(wrong), value):
                    if any(a <= found.start() and found.end() <= b for a, b in spans):
                        pieces.append(value[cursor:found.start()] + right)
                        cursor = found.end(); count += 1
                fixed = ''.join(pieces) + value[cursor:]
            if count:
                key = f'{wrong}→{right}'
                report.hits[key] += count
                if len(report.examples[key]) < 5:
                    report.examples[key].append({'page': page.number, 'before': value, 'after': fixed})
                value = fixed
        repaired.append(Word(value, word.x0, word.y0, word.x1, word.y1) if value != word.text else word)
    page.words = repaired


def join_vertical(page: Page, report: Report) -> None:
    """Single characters stacked tightly in one column with no neighbour on their line are one
    vertically printed word (款・項 names in a narrow column); read it top to bottom."""
    singles = [w for w in page.words if len(w.text) == 1 and not NUMERIC.match(w.text) and w.text.strip()]
    others = [w for w in page.words if w not in singles]
    horizontals = [r for r in page.rules if not r.vertical]

    verticals = [r for r in page.rules if r.vertical]

    def walled(a: Word, b: Word) -> bool:
        left, right = (a, b) if a.x0 < b.x0 else (b, a)
        middle = (a.y0 + a.y1) / 2
        return any(left.x1 - .5 <= r.x0 <= right.x0 + .5 and r.y0 <= middle <= r.y1 for r in verticals)

    def alone(word: Word) -> bool:
        """No neighbour on its line, unless a vertical rule separates them (another column)."""
        reach = 1.5 * (word.x1 - word.x0)
        return not any(_same_line(word, other) and other is not word and not walled(word, other) and
                       (abs(other.x0 - word.x1) < reach or abs(word.x0 - other.x1) < reach)
                       for other in page.words)

    stacks: list[list[Word]] = []
    for word in sorted(singles, key=lambda w: (round(w.x0), w.y0)):
        if stacks:
            last = stacks[-1][-1]
            height = last.y1 - last.y0
            if (abs(word.x0 - last.x0) <= 1.0 and 0 <= word.y0 - last.y1 <= .6 * height
                    and not any(r.x0 <= word.x0 <= r.x1 and last.y1 <= r.y0 <= word.y0 for r in horizontals)):
                stacks[-1].append(word)
                continue
        stacks.append([word])
    result = list(others)
    for stack in stacks:
        if len(stack) >= 2 and all(alone(w) for w in stack):
            result.append(Word(''.join(w.text for w in stack), min(w.x0 for w in stack), stack[0].y0,
                               max(w.x1 for w in stack), stack[-1].y1))
            report.vertical_words += 1
        else:
            result.extend(stack)
    page.words = result


def crop_to_box(pdf_path: Path, pages: list[Page], report: Report) -> None:
    """Drop words and rules outside the page's CropBox.

    Some PDFs cut one A3 spread into two pages by CropBox only (left half, right half),
    each page still holding the whole spread (132080・132047). A viewer shows one half;
    Poppler's words cover both, so every row would be read twice. The words are in the
    displayed (rotated) page measured from its top-left; the CropBox is mapped there.
    Applied only when the CropBox is smaller than the MediaBox and words lie outside it.
    """
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        for page in pages:
            handle = document[page.number - 1]
            ml, mb, mr, mt = handle.get_mediabox()
            cl, cb, cr, ct = handle.get_cropbox()
            rotation = handle.get_rotation()
            handle.close()
            if (cr - cl) * (ct - cb) >= .9 * (mr - ml) * (mt - mb):
                continue
            x0, x1, y0, y1 = {0: (cl - ml, cr - ml, mt - ct, mt - cb), 90: (cb - mb, ct - mb, cl - ml, cr - ml),
                              180: (mr - cr, mr - cl, cb - mb, ct - mb), 270: (mt - ct, mt - cb, mr - cr, mr - cl)}[rotation % 360]
            inside = lambda x, y: x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1
            words = [w for w in page.words if inside((w.x0 + w.x1) / 2, (w.y0 + w.y1) / 2)]
            if len(words) == len(page.words):
                continue  # the words already keep to the box
            report.cropped_words += len(page.words) - len(words)
            page.words = words
            page.rules = [Rule(max(r.x0, x0), max(r.y0, y0), min(r.x1, x1), min(r.y1, y1)) for r in page.rules
                          if r.x0 <= x1 and r.x1 >= x0 and r.y0 <= y1 and r.y1 >= y0
                          and (not r.vertical or x0 <= r.x0 <= x1) and (r.vertical or y0 <= r.y0 <= y1)]
    finally:
        document.close()


def display_size(pdf_path: Path, numbers: list[int]) -> dict[int, tuple[float, float]]:
    """Width and height of each page as displayed: the MediaBox, turned by the page's rotation."""
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        sizes = {}
        for number in numbers:
            handle = document[number - 1]
            left, bottom, right, top = handle.get_mediabox()
            rotation = handle.get_rotation() % 180
            handle.close()
            sizes[number] = (top - bottom, right - left) if rotation else (right - left, top - bottom)
        return sizes
    finally:
        document.close()


def clip_to_page(page: Page, report: Report, width: float, height: float) -> None:
    """Keep the parts of rules inside the displayed page box (`display_size`).

    A spread cut into two pages may keep the whole spread's drawing on each page, the other
    half lying off the page (x < 0 or beyond the width, 132276). Poppler drops the words there;
    the rules drawn there would make empty bands and break the spread's pairing. The box comes
    from the PDF's MediaBox and rotation, not from where words happen to lie.
    """
    kept = []
    for rule in page.rules:
        x0, x1 = max(rule.x0, 0.0), min(rule.x1, width)
        y0, y1 = max(rule.y0, 0.0), min(rule.y1, height)
        if x0 > x1 + .5 or y0 > y1 + .5 or (rule.vertical and not 0 <= rule.x0 <= width) \
                or (not rule.vertical and not 0 <= rule.y0 <= height):
            report.off_page_rules += 1
            continue
        kept.append(rule if (x0, y0, x1, y1) == (rule.x0, rule.y0, rule.x1, rule.y1) else Rule(x0, y0, x1, y1))
    page.rules = kept


def repair(pdf_path: Path | None, pages: list[Page], form_clips: bool = False) -> tuple[list[Page], Report]:
    report = Report()
    if pdf_path is not None and pdf_path.exists():
        sizes = display_size(pdf_path, [page.number for page in pages])
        for page in pages:
            clip_to_page(page, report, *sizes[page.number])
        crop_to_box(pdf_path, pages, report)
        try:
            drop_invisible(pdf_path, pages, report, form_clips)
        except Exception as error:  # pdfium's raw API failed: keep Poppler's words as they are
            report.invisible_error = f'{type(error).__name__}: {error}'
            report.hidden_glyphs = report.hidden_rules = 0
    for page in pages:
        repair_positions(page, report)
        join_vertical(page, report)
    report.health = health(pages)
    report.broken = is_broken(report.health)
    if report.broken:
        for page in pages:
            apply_dictionary(page, report)
    return pages, report
