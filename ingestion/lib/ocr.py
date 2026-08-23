"""アウトライン化された PDF を OCR で読む。**層に依存しない。**

⚠️ **これはテキスト抽出より保証が一段弱い。** 狛江市の歳入事項別明細（2020〜2022）は
文字がベクタパスへアウトライン化されており（Tj が1つも無く、グリフが曲線として
描かれている）、テキスト抽出が原理的に成立しない。OCR はその代替で、
**誤読が混ざる前提**で使う。誤読の検出は呼び出し側の責務 —
金額を原典 CSV と突合し、一致した科目からだけ名称を採る（fudoki の取り込みの柱
「切り捨てを成功として扱わない」の OCR 版）。実測でも数字の誤読が出た
（954 → 994。数字ホワイトリストでも防げない）。

⚠️ **ページ全体を一度に OCR しない。** 表の罫線と列をまたぐ語の融合で
語の座標が信頼できなくなり、階層の判定が混線する（実測で科目の8割を落とした）。
**列ごとに画像を切り出してから OCR する** — 融合の相手がいなければ融合しない。

座標は PDF ポイント系（y はページ共通、x は列内相対 + 列の開始）で返すので、
`ingestion/lib/pdf.py` の行クラスタ（rows_of）がそのまま使える。

エンジンは Tesseract（Apache-2.0）。provenance には版と DPI を記録すること —
エンジンや版が変わると同じ原典から違う抽出物が出るため、冪等判定の材料になる。
"""

from __future__ import annotations

import csv
import io
import pathlib
import subprocess
import tempfile

DPI = 600
LANG = "jpn"


def engine_version() -> str:
    """provenance に記録する識別子（例: `tesseract-5.5.3@600dpi`）"""
    proc = subprocess.run(["tesseract", "--version"], capture_output=True, check=True)  # noqa: S603
    out = (proc.stderr or proc.stdout).decode()
    ver = out.splitlines()[0].split()[-1] if out else "unknown"
    return f"tesseract-{ver}@{DPI}dpi"


def column_words_of(pdf: pathlib.Path, first: int, last: int,
                    columns: dict[str, tuple[float, float]], *,
                    digits: set[str] | None = None, top: float = 0.0):
    """列ごとにクロップして OCR し、ページごとに {列名: [(x_pt, y_pt, 語)]} を返す。

    columns は列名 → (x 開始, x 終了) の PDF ポイント。y はページ共通なので、
    別の列どうしでも y で同じ視覚行に対応づけられる。
    digits に列名を入れると、その列は数字とカンマだけを許すホワイトリストで読む
    （⚠️ ホワイトリストは誤読を防がない — 5 が 9 になる。検出は突合で行う）。
    top はページ上部の切り捨て（pt）。⚠️ 表の見出し行を入れたまま読むと、
    見出しの字が本文1行目と融合して壊す（実測で「2 種別割」が「列。割」になった）。
    """
    scale = DPI / 72.0
    for page_no in range(first, last + 1):
        result: dict[str, list[tuple[float, float, str]]] = {}
        with tempfile.TemporaryDirectory() as td:
            for name, (lo, hi) in columns.items():
                base = pathlib.Path(td) / f"c-{name}"
                subprocess.run(  # noqa: S603
                    ["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-r", str(DPI),
                     "-gray", "-png", "-x", str(int(lo * scale)), "-y", str(int(top * scale)),
                     "-W", str(int((hi - lo) * scale)), str(pdf), str(base)],
                    check=True,
                )
                png = next(pathlib.Path(td).glob(f"c-{name}-*.png"))
                cmd = ["tesseract", str(png), "-", "-l", LANG, "--psm", "6", "tsv"]
                if digits and name in digits:
                    cmd += ["-c", "tessedit_char_whitelist=0123456789,"]
                tsv = subprocess.run(cmd, capture_output=True, check=True).stdout.decode()  # noqa: S603
                words: list[tuple[float, float, str]] = []
                for r in csv.DictReader(io.StringIO(tsv), delimiter="\t"):
                    text = (r.get("text") or "").strip()
                    if not text or float(r["conf"]) <= 0:
                        continue
                    words.append((lo + float(r["left"]) / scale, top + float(r["top"]) / scale, text))
                result[name] = words
        yield result
