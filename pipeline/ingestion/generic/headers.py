"""Amount headings as the shared dictionary knows them.

The builder keeps the heading path as it is printed (`予算現額／節／金額`, `支出済額(B)`, a column whose
stacked kinds the text layer joined: `翌年度繰越額継続費逓次繰越繰越明許費事故繰越し`). The amount contract
(`dbt/tests/fiscal_amounts_contract.sql`) wants the path, or its last segment, to be a heading of
`shared/fiscal_amount_map.csv`. A path that fails it is brought to the heading it prints, by rules that
read the printed words only:

1. the symbols a heading carries (`(A)`, `(B)-(C)`, `(逓)`, the minus mark of `流用増△減`) are not part of the heading;
2. the longest suffix of two or more segments the dictionary knows (`予算現額／節／金額` → `節／金額`), or,
   for a bare `金額` column, the axis of the item it belongs to (`節／金額`);
3. the headings a cell prints joined together (`継続費逓次繰越繰越明許費事故繰越し`) are one column of those
   kinds: the heading of the group above it when there is one, the first of them otherwise;
4. `…との比較` is `比較`; a column whose last segment the dictionary knows is that segment; a path whose
   last segment is none but whose first segments are a heading is that heading.

5. a column heading printed in a narrow cell, one character or two to a line, comes out of the text layer
   with its characters in the order of the cells (`不額／用`, `翌年度越額／繰／越／繰明／許／費`): when the
   characters of the whole path, taken together, are exactly the characters of one known heading or of two,
   the path is that heading (`不用額`, `翌年度繰越額／繰越明許費`). The match is on the characters as a set
   with their counts; it is tried last, and only for a path that none of the rules above reads. Where the
   layout setting `header.kind_by_characters` is set, before a path falls back to its first segments
   (rule 4), its last segment alone is matched so: a stacked kind whose two lines were read across
   (`翌年度繰越額／継逓繰続費次越`) is that kind, not its group.

A path that the dictionary already knows (or whose last segment it knows) is never touched.
"""
from __future__ import annotations

from collections import Counter
from functools import cache, lru_cache
import re

SYMBOL = re.compile(r'(?:[（(][A-ZＡ-Ｚ][)）][-－−]?)+|[（(][^0-9０-９()（）][)）]')
SEPARATOR = '／'


def clean(segment: str) -> str:
    return SYMBOL.sub('', segment).replace('△', '').replace('▲', '').strip()


def parse(text: str, known: set[str]) -> list[str] | None:
    """The known headings a text is made of, joined (`繰越明許費事故繰越し`), or None."""
    if not text:
        return []
    for end in range(len(text), 0, -1):
        if text[:end] in known:
            rest = parse(text[end:], known)
            if rest is not None:
                return [text[:end], *rest]
    return None


@cache
def _letters(heading: str) -> tuple:
    return tuple(sorted(Counter(c for c in heading if c not in SEPARATOR and not c.isspace()).items()))


@lru_cache(maxsize=256)
def by_characters(path: str, known: frozenset[str]) -> str | None:
    """The known heading (or two joined) whose characters, counted, are the path's. The path's own
    separators fall away. One whole heading precedes pairs; an ambiguous decomposition is unreadable."""
    wanted = _letters(path)
    if sum(count for _, count in wanted) < 2:
        return None
    ordered = sorted(known, key=lambda h: (-len(h), h))
    whole = [heading for heading in ordered if _letters(heading) == wanted]
    if whole:
        return whole[0] if len(whole) == 1 else None
    singles = [h for h in ordered if SEPARATOR not in h]
    pairs = set()
    for first in singles:
        rest = Counter(dict(wanted))
        rest.subtract(dict(_letters(first)))
        if any(count < 0 for count in rest.values()):
            continue
        remaining = tuple(sorted((c, n) for c, n in rest.items() if n))
        for second in singles:
            if _letters(second) == remaining:
                pairs.add(tuple(sorted((first, second), key=lambda h: (-len(h), h))))
    if len(pairs) != 1:
        return None
    # The group heading is the one whose characters start the path.
    first, second = next(iter(pairs))
    text = path.replace(SEPARATOR, '')
    where = lambda h: min(text.find(c) for c in set(h) if c in text)
    a, b = (first, second) if where(first) <= where(second) else (second, first)
    return f'{a}{SEPARATOR}{b}'


def canonical(path: str, axis: str | None, known: set[str], kind_by_characters: bool = False) -> str:
    segments = path.split(SEPARATOR)
    if path in known or segments[-1] in known:
        return path
    segments = [clean(s) for s in segments]
    joined = SEPARATOR.join(segments)
    if joined in known or segments[-1] in known:
        return joined if joined in known else segments[-1]
    for start in range(1, len(segments) - 1):
        suffix = SEPARATOR.join(segments[start:])
        if suffix in known:
            return suffix
    if segments[-1] == '金額' and axis and f'{axis}{SEPARATOR}金額' in known:
        return f'{axis}{SEPARATOR}金額'
    for index in range(len(segments) - 1, -1, -1):
        parts = parse(segments[index], known)
        if parts and len(parts) >= 2:
            above = SEPARATOR.join(segments[:index])
            if above and above in known:
                return above
            if index == 0:
                return parts[0]
            return SEPARATOR.join([*segments[:index], parts[0]])
    if segments[-1].endswith('比較') and '比較' in known:
        return '比較'
    # A stacked kind under its group, its two printed lines read across (`翌年度繰越額／継逓繰続費次越`, 281000):
    # the last segment's characters are one known heading, which a fall back to the group would lose.
    # Only where the layout setting `header.kind_by_characters` says the document prints its kinds so.
    found = by_characters(segments[-1], frozenset(known)) if kind_by_characters and len(segments) > 1 else None
    if found is not None and SEPARATOR not in found:
        return found
    for end in range(len(segments) - 1, 0, -1):
        prefix = SEPARATOR.join(segments[:end])
        if prefix in known:
            return prefix
    found = by_characters(joined, frozenset(known))
    return found if found is not None else joined
