"""PDF から文字とその座標を取り出す。**層に依存しない。**

`pdftotext -bbox-layout` の語の bbox を文字単位へ割る。CJK の PDF は語の中が
等幅なので、語の幅を文字数で割れば各文字の x が出る（狛江市の決算資料で実測済み）。

⚠️ **bbox-layout がクラッシュする PDF がある。** e-Gov の法令様式 PDF
（地方自治法施行規則 別記）で `std::out_of_range` を出して落ちた。
`pdftocairo -pdf` で再蒸留すると通る。`redistill=True` で回避する。
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile

Char = tuple[float, float, str]     # (x, y, 1文字)
Word = tuple[float, float, float, float, str]   # (x0, y0, x1, y1, 語)
PageWords = tuple[float, float, list[Word]]     # (幅, 高さ, 語のリスト)


def pages_of(pdf: pathlib.Path, first: int, last: int, *, redistill: bool = False) -> list[PageWords]:
    """ページごとに (幅, 高さ, 語の bbox) を返す。

    検証画面の文字層（選択可能なテキスト・行への紐づけ）が語の座標を要るため、
    `chars_of` とは別に語のまま返す経路。`pdftotext -bbox-layout` を使うのは同じ。
    """
    if redistill:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            subprocess.run(["pdftocairo", "-pdf", str(pdf), f.name], check=True)  # noqa: S603
            return pages_of(pathlib.Path(f.name), first, last)
    xml = subprocess.run(  # noqa: S603
        ["pdftotext", "-bbox-layout", "-f", str(first), "-l", str(last), str(pdf), "-"],
        capture_output=True, check=True,
    ).stdout.decode()
    pages: list[PageWords] = []
    for page in xml.split("<page ")[1:]:
        m = re.match(r'width="([\d.]+)" height="([\d.]+)"', page)
        w, h = float(m[1]), float(m[2])
        seen: set = set()
        words: list[Word] = []
        for wm in re.finditer(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)"[^>]*>(.*?)</word>', page
        ):
            x0, y0, x1, y1 = (float(wm[i]) for i in range(1, 5))
            text = wm[5]
            key = (x0, y0, text)
            if key in seen:   # bbox は同じ語を2回吐くことがある
                continue
            seen.add(key)
            words.append((x0, y0, x1, y1, text))
        pages.append((w, h, words))
    return pages


def chars_of(pdf: pathlib.Path, first: int, last: int, *, redistill: bool = False):
    """ページごとに (x, y, 1文字) を返す。語を文字数で割って文字の x を出す"""
    if redistill:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            subprocess.run(["pdftocairo", "-pdf", str(pdf), f.name], check=True)  # noqa: S603
            yield from chars_of(pathlib.Path(f.name), first, last)
        return
    xml = subprocess.run(  # noqa: S603
        ["pdftotext", "-bbox-layout", "-f", str(first), "-l", str(last), str(pdf), "-"],
        capture_output=True, check=True,
    ).stdout.decode()
    for page in xml.split("<page ")[1:]:
        seen: set = set()
        out: list[Char] = []
        for m in re.finditer(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)"[^>]*>(.*?)</word>', page
        ):
            x0, y, x1, text = float(m[1]), float(m[2]), float(m[3]), m[4]
            if (x0, y, text) in seen:   # bbox は同じ語を2回吐くことがある
                continue
            seen.add((x0, y, text))
            width = (x1 - x0) / max(len(text), 1)
            out.extend((x0 + width * i, y, c) for i, c in enumerate(text))
        yield out


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
    rows: list[list[tuple[float, str]]] = [[] for _ in groups]
    for x, y, c in page:
        rows[centers[y]].append((x, c))
    return rows


def column_of(x: float, columns: dict[str, tuple[float, float]]) -> str | None:
    """x 座標がどの列か。範囲は呼び出し側の宣言から来る（組版はコードの定数ではない）"""
    for name, (lo, hi) in columns.items():
        if lo <= x < hi:
            return name
    return None
