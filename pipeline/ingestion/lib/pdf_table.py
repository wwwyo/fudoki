"""Build tables from words and OCR observations using caller-declared geometry.

Coordinates on a canvas are separate from the original page boxes. No fiscal
roles, missing values or heading identities are inferred here.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Mapping, Sequence


def _finite(*values: float) -> None:
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Coordinates must be finite numbers")


@dataclass(frozen=True)
class Box:
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        _finite(self.left, self.top, self.right, self.bottom)
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("Box must have positive width and height")

    def x(self, anchor: str) -> float:
        return {"left": self.left, "center": (self.left + self.right) / 2,
                "right": self.right}[anchor]

    def y(self, anchor: str) -> float:
        return {"top": self.top, "center": (self.top + self.bottom) / 2,
                "bottom": self.bottom}[anchor]


@dataclass(frozen=True)
class Token:
    id: str
    origin_id: str
    page: int
    raw_text: str
    bbox: Box | None
    unit: str = "pt"
    kind: str = "word"
    confidence: float | None = None
    parent_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.origin_id or type(self.page) is not int or self.page < 1:
            raise ValueError("Token requires an id, origin and positive physical page")
        if not isinstance(self.raw_text, str) or self.unit not in ("pt", "px"):
            raise ValueError("Token requires original text and an explicit pt/px unit")
        if self.bbox is not None and not isinstance(self.bbox, Box):
            raise ValueError("Token bbox must be a Box or None")


@dataclass(frozen=True)
class Placement:
    """Map one upright, top-left page into a shared canvas (including spreads)."""

    canvas_id: str
    input_unit: str = "pt"
    output_unit: str = "pt"
    scale_x: float = 1
    scale_y: float = 1
    offset_x: float = 0
    offset_y: float = 0

    def __post_init__(self) -> None:
        _finite(self.scale_x, self.scale_y, self.offset_x, self.offset_y)
        if (not self.canvas_id or self.scale_x <= 0 or self.scale_y <= 0
                or self.input_unit not in ("pt", "px") or self.output_unit not in ("pt", "px")):
            raise ValueError("Placement requires a canvas, positive scales and pt/px units")

    def apply(self, box: Box) -> Box:
        return Box(box.left * self.scale_x + self.offset_x,
                   box.top * self.scale_y + self.offset_y,
                   box.right * self.scale_x + self.offset_x,
                   box.bottom * self.scale_y + self.offset_y)


@dataclass(frozen=True)
class PlacedToken:
    token: Token
    canvas_id: str
    bbox: Box | None
    unit: str


def place_tokens(tokens: Sequence[Token],
                 placements: Mapping[tuple[str, int], Placement]) -> tuple[PlacedToken, ...]:
    """Keep original boxes while restoring scale and explicitly aligning pages."""
    result = []
    for token in tokens:
        placement = placements[(token.origin_id, token.page)]
        if token.unit != placement.input_unit:
            raise ValueError("Token and placement coordinate units differ")
        result.append(PlacedToken(token, placement.canvas_id,
                                  placement.apply(token.bbox) if token.bbox else None,
                                  placement.output_unit))
    return tuple(result)


def tokens_from_bbox_layout(xml: str | bytes, *, origin_id: str,
                            first_page: int = 1) -> tuple[Token, ...]:
    """Read Poppler bbox-layout XML without splitting words or dropping duplicates."""
    if type(first_page) is not int or first_page < 1:
        raise ValueError("first_page must be a positive physical page")
    pages = ET.fromstring(xml).findall(".//{*}page")
    if not pages:
        raise ValueError("bbox-layout XML contains no pages")
    result = []
    for offset, page in enumerate(pages):
        number = first_page + offset
        for index, word in enumerate(page.findall(".//{*}word")):
            box = Box(*(float(word.attrib[k]) for k in ("xMin", "yMin", "xMax", "yMax")))
            result.append(Token(f"p{number}:w{index}", origin_id, number,
                                "".join(word.itertext()), box))
    return tuple(result)


def tokens_from_vision(result: dict, *, kind: str, region_ids: Sequence[str],
                       unit: str = "pt") -> tuple[Token, ...]:
    """Select exactly one observation level to avoid parent/child double counting."""
    if kind not in ("region", "word", "number") or unit not in ("pt", "px"):
        raise ValueError("Choose one Vision kind and pt/px coordinates")
    selected = set(region_ids)
    if not selected or len(selected) != len(region_ids):
        raise ValueError("Choose distinct region ids explicitly")
    origin_id = result["origin"]["sha256"]
    key = "bbox_pdf_pt" if unit == "pt" else "bbox_px"
    tokens = []
    for page in result["pages"]:
        if unit == "pt" and page.get("displayed_pdf_size_pt") is None:
            raise ValueError("Image inputs require pixel coordinates")
        if not selected <= {region["id"] for region in page["regions"]}:
            raise ValueError("A selected region is absent from a page")
        for region in page["regions"]:
            if region["id"] not in selected:
                continue
            for item in region["observations"]:
                if item["kind"] == kind:
                    bbox = item[key]
                    tokens.append(Token(item["id"], origin_id, page["page_number"],
                                        item["raw_text"], Box(*bbox) if bbox is not None else None,
                                        unit, kind, item.get("confidence"), item.get("parent_id")))
    return tuple(tokens)


@dataclass(frozen=True)
class Column:
    name: str
    left: float
    right: float
    anchor: str = "center"
    separator: str = ""

    def __post_init__(self) -> None:
        _finite(self.left, self.right)
        if not self.name or self.left >= self.right or self.anchor not in ("left", "center", "right"):
            raise ValueError("Column requires a name, increasing bounds and an x anchor")
        if not isinstance(self.separator, str):
            raise ValueError("Column separator must be a string")

    def contains(self, box: Box) -> bool:
        x = box.x(self.anchor)
        return self.left < x <= self.right if self.anchor == "right" else self.left <= x < self.right


@dataclass(frozen=True)
class RowBand:
    top: float
    bottom: float

    def __post_init__(self) -> None:
        _finite(self.top, self.bottom)
        if self.top >= self.bottom:
            raise ValueError("Row band requires increasing bounds")


@dataclass(frozen=True)
class TableLayout:
    columns: tuple[Column, ...]
    row_tolerance: float = 1
    row_anchor: str = "center"
    row_bands: tuple[RowBand, ...] = ()

    def __post_init__(self) -> None:
        _finite(self.row_tolerance)
        if (not self.columns or len({c.name for c in self.columns}) != len(self.columns)
                or self.row_tolerance < 0 or self.row_anchor not in ("top", "center", "bottom")):
            raise ValueError("Layout requires unique columns and a nonnegative row tolerance")
        if any(a.bottom > b.top for a, b in zip(self.row_bands, self.row_bands[1:])):
            raise ValueError("Row bands must be ordered and non-overlapping")


@dataclass(frozen=True)
class Cell:
    column: str
    text: str | None
    tokens: tuple[PlacedToken, ...]

    @property
    def status(self) -> str:
        return "observed" if self.tokens else "unobserved"


@dataclass(frozen=True)
class TableRow:
    cells: tuple[Cell, ...]
    source_rows: tuple[int, ...]

    def cell(self, name: str) -> Cell:
        return next(cell for cell in self.cells if cell.column == name)


@dataclass(frozen=True)
class TableResult:
    rows: tuple[TableRow, ...]
    unassigned: tuple[PlacedToken, ...]


def assemble_table(tokens: Sequence[PlacedToken], layout: TableLayout) -> TableResult:
    """Group a single canvas; leave uncertain column/row assignments explicit.

    Dynamic rows use bounded y spread, rather than a transitive proximity chain.
    Declared row bands also retain completely unobserved rows.
    """
    if len({(t.canvas_id, t.unit) for t in tokens}) > 1:
        raise ValueError("Assemble one canvas in one coordinate unit at a time")
    ids = [(t.token.origin_id, t.token.id) for t in tokens]
    if len(set(ids)) != len(ids):
        raise ValueError("Repeated observation ids require explicit deduplication")
    unassigned = [token for token in tokens if token.bbox is None]
    located = sorted((t for t in tokens if t.bbox is not None),
                     key=lambda t: (t.bbox.y(layout.row_anchor), t.bbox.left, t.token.id))
    groups: list[list[PlacedToken]] = []
    if layout.row_bands:
        groups = [[] for _ in layout.row_bands]
        for token in located:
            y = token.bbox.y(layout.row_anchor)
            index = next((i for i, band in enumerate(layout.row_bands) if band.top <= y < band.bottom), None)
            if index is None:
                unassigned.append(token)
            else:
                groups[index].append(token)
    else:
        for token in located:
            y = token.bbox.y(layout.row_anchor)
            if not groups or y - groups[-1][0].bbox.y(layout.row_anchor) > layout.row_tolerance:
                groups.append([])
            groups[-1].append(token)
    rows = []
    for index, group in enumerate(groups):
        by_column: dict[str, list[PlacedToken]] = {column.name: [] for column in layout.columns}
        for token in group:
            matches = [column.name for column in layout.columns if column.contains(token.bbox)]
            if len(matches) == 1:
                by_column[matches[0]].append(token)
            else:
                unassigned.append(token)
        cells = []
        for column in layout.columns:
            words = tuple(sorted(by_column[column.name], key=lambda t: (t.bbox.left, t.bbox.top, t.token.id)))
            text = column.separator.join(t.token.raw_text for t in words) if words else None
            cells.append(Cell(column.name, text, words))
        rows.append(TableRow(tuple(cells), (index + 1,)))
    return TableResult(tuple(rows), tuple(unassigned))


def join_wrapped_rows(rows: Sequence[TableRow], *, columns: Sequence[str],
                      separator: str = "") -> TableRow:
    """Join caller-confirmed continuations; reject merging other populated cells."""
    if not rows:
        raise ValueError("Choose at least one row")
    names = tuple(c.column for c in rows[0].cells)
    if any(tuple(c.column for c in row.cells) != names for row in rows) or not set(columns) <= set(names):
        raise ValueError("Continuation rows must have the same columns")
    row_cells = []
    for row in rows:
        lookup: dict[str, Cell] = {}
        for cell in row.cells:
            lookup.setdefault(cell.column, cell)
        row_cells.append(lookup)
    cells = []
    for name in names:
        observed = [lookup[name] for lookup in row_cells if lookup[name].tokens]
        if name not in columns and len(observed) > 1:
            raise ValueError(f"Multiple populated cells in non-continuation column {name}")
        text = separator.join(cell.text for cell in observed) if observed else None
        cells.append(Cell(name, text, tuple(t for cell in observed for t in cell.tokens)))
    return TableRow(tuple(cells), tuple(index for row in rows for index in row.source_rows))


@dataclass(frozen=True)
class Heading:
    value: str
    token_ids: tuple[str, ...] = ()


class HierarchyContext:
    """Inherit explicitly identified headings; reset at table/account boundaries."""

    def __init__(self, levels: Sequence[str]):
        if not levels or any(not isinstance(level, str) or not level for level in levels) or len(set(levels)) != len(levels):
            raise ValueError("Hierarchy levels must be distinct nonempty names")
        self.levels = tuple(levels)
        self._values: list[Heading | None] = [None] * len(self.levels)

    def update(self, level: str, heading: Heading) -> None:
        if not isinstance(heading, Heading) or not isinstance(heading.value, str) or not heading.value:
            raise ValueError("Update requires a nonempty, source-confirmed heading")
        index = self.levels.index(level)
        previous = self._values[index]
        if previous is None or previous.value != heading.value:
            self._values[index:] = [None] * (len(self.levels) - index)
        self._values[index] = heading

    def snapshot(self) -> dict[str, Heading | None]:
        return dict(zip(self.levels, self._values))

    def reset(self) -> None:
        self._values = [None] * len(self.levels)
