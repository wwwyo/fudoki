from __future__ import annotations
Char = tuple[float, float, str]

class PositionedRow(list):
    """A visual row retaining the original word baselines for cell provenance."""

    def __init__(self, ys: list[float]) -> None:
        super().__init__()
        self.ys = set(ys)

def rows_of(page: list[Char], tolerance: float = 1.0) -> list[list[tuple[float, str]]]:
    """視覚的な行へまとめる。**固定グリッドで丸めない** — 近接する y を束ねる。

    ⚠️ `round(y / 2)` のような固定グリッドは、1つの視覚行を2つに割る。
    狛江市の実測で 528 行のうち 66 行（12.5%）の名前が壊れていた。
    """
    if not page:
        return []
    ys = sorted({y for _, y, _ in page})
    groups: list[list[float]] = [[ys[0]]]
    for y in ys[1:]:
        if y - groups[-1][-1] > tolerance:
            groups.append([])
        groups[-1].append(y)
    centers = {y: i for i, g in enumerate(groups) for y in g}
    rows: list[list[tuple[float, str]]] = [PositionedRow(g) for g in groups]
    for x, y, c in page:
        rows[centers[y]].append((x, c))
    return rows
