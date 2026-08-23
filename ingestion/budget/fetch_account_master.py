"""法定の科目マスタを、地方自治法施行規則 別記の原文から起こす。

別記「歳入歳出予算の款項の区分及び目の区分」（第15条関係）の**市町村・歳出**の表を
e-Gov の添付 PDF から抽出し、`dbt/seeds/budget/account_master.csv` を生成する。

**なぜマスタが要るか。** 款のコードは団体ごとにずれている。法定の款11は災害復旧費だが、
災害復旧費を持たない三鷹市・狛江市はどちらも 11 が公債費で、以降が詰まっている。
つまり**コードでは団体をまたいで比較できない**。マスタと団体ごとの対応表
（`account_map.csv`）を介して初めて「同じ款」が言える。

⚠️ **e-Gov の法令 XML にこの別記は入っていない**（該当の `<Fig src="">` が空。
2026-08-23 実測。API v1/v2・HTML・docx すべてに表の中身が無い）。
添付 PDF の直リンクだけが原文で、「正準が壊れているので原文から起こして commit する」
`fetch:fdp-taxonomy` と同じ型にあたる。

⚠️ **この PDF は `pdftotext -bbox-layout` をクラッシュさせる**（std::out_of_range）。
`pdftocairo -pdf` で再蒸留すると通る（`ingestion/lib/pdf.py` の `redistill=True`）。

適用範囲（表の備考から。抽出した本文と同じ PDF にある）:
- 備考1: 行政権能の差により款・項を**追加できる** — 法定に無い科目は誤りとは限らない。
  対応表に「団体固有の追加」として明示登録させ、黙って通さない
- 備考2: **※印を付した目**は一般職の給料・職員手当等・共済費を計上する目（`is_personnel_moku`）
- 備考6: **特別会計は長が定めた区分による** — マスタの適用範囲は一般会計だけ
"""

from __future__ import annotations

import csv
import pathlib
import re
import tempfile
import unicodedata

from ingestion.lib.http import http_get
from ingestion.lib.pdf import chars_of, column_of, rows_of

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "dbt" / "seeds" / "budget" / "account_master.csv"

# 地方自治法施行規則（昭和22年内務省令第29号）別記の添付 PDF。
# 現行の法令 XML から辿れる src が空のため、e-Gov のデータ直リンクを指す。
URL = "https://laws.e-gov.go.jp/data/MinisterialOrdinance/322M40000008029/608139_1/pict/2FH00000040617.pdf"
SHA256 = "181ab2fde4b7bcb82a0dc6951603dd29e4c78228bba30c12667f310c657b535b"
BASIS = "地方自治法施行規則 別記「歳入歳出予算の款項の区分及び目の区分」（第15条関係）市町村・歳出"

# 市町村・歳出の表のページと、市町村側の列の x 範囲（2026-08-23 実測）。
# 左半分（x<285）は都道府県の表なので読まない。
FIRST_PAGE, LAST_PAGE = 13, 25
# ⚠️ 境界は列見出しではなく**実際の語の端**から取る。見出しの中間で切ると、
# 「災害復旧費」の3文字目（x=341.6）が款列から漏れて「災害旧費」になった。
# 款名の語の右端は 352.5、項コードの左端は 360 なので、その間の 355 で切る。
COLUMNS = {"kan": (285.0, 355.0), "kou": (355.0, 425.0), "moku": (425.0, 545.0)}
MARK = "※"


def extract(pdf: pathlib.Path) -> list[dict]:
    """(款, 項, 目) を出現順に返す。名称の折返し（`農林水/産業費`）は次行から繋ぐ"""
    rows: list[dict] = []
    kan = kou = None
    kan_name = kou_name = ""
    started = False
    open_level: str | None = None    # 名称の折返しを受け取る階層
    pending_mark = False             # ※は目の1行上に単独で印字される。次の目に付ける
    for page in chars_of(pdf, FIRST_PAGE, LAST_PAGE, redistill=True):
        for line in rows_of(page, tolerance=2.0):
            cells: dict[str, str] = {}
            for x, c in sorted(line):
                col = column_of(x, COLUMNS)
                if col:
                    cells[col] = cells.get(col, "") + c
            text = "".join(cells.values())
            # 歳出の表は市町村側の「款1 議会費」から始まる。それより上（歳入の備考の
            # 右端など）と、表の後の備考は読まない。
            if not started:
                started = cells.get("kan", "").startswith("1議会費")
                if not started:
                    continue
            if text.startswith("備考"):
                return rows

            # ⚠️ **※は目と同じ行にない。** 目の1行上に単独で印字される（実測 y差 -17）。
            # 「この行は※だけ」を保留にして、次に出た目へ付ける。
            if text.strip() == MARK:
                pending_mark = True
                continue

            emitted = False
            for level in ("kan", "kou", "moku"):
                cell = cells.get(level, "").strip()
                if not cell:
                    continue
                m = re.match(r"^(\d+)(.*)$", unicodedata.normalize("NFKC", cell))
                if m:
                    code, name = int(m.group(1)), m.group(2)
                    mark = MARK in name
                    name = name.replace(MARK, "")
                    if level == "kan":
                        kan, kan_name, kou, kou_name = code, name, None, ""
                    elif level == "kou":
                        kou, kou_name = code, name
                    else:
                        rows.append({"kan_code": kan, "kou_code": kou, "moku_code": code,
                                     "moku_name": name,
                                     "is_personnel_moku": mark or pending_mark,
                                     "_kan_name": kan_name, "_kou_name": kou_name})
                        pending_mark = False
                    open_level = level
                    emitted = True
                elif open_level and not emitted:
                    # コードの無いセルは、直前に開いた階層の名称の折返し
                    cont = cell.replace(MARK, "")
                    if MARK in cell and rows and open_level == "moku":
                        rows[-1]["is_personnel_moku"] = True
                    if open_level == "kan":
                        kan_name += cont
                        # 折返し確定後の名前を、その款でまだ目が出ていない場合に備えて保持
                    elif open_level == "kou":
                        kou_name += cont
                    elif rows:
                        rows[-1]["moku_name"] += cont
                    emitted = True
            if not emitted:
                open_level = None
            # 折返しで確定した親名を、既に積んだ行へも反映する
            for r in rows:
                if r["kan_code"] == kan and r["_kan_name"] != kan_name:
                    r["_kan_name"] = kan_name
                if r["kan_code"] == kan and r["kou_code"] == kou and r["_kou_name"] != kou_name:
                    r["_kou_name"] = kou_name
    return rows


def verify(rows: list[dict]) -> None:
    """抽出漏れの検査。**款は連番で名称が欠けないこと。**"""
    kans = sorted({(r["kan_code"], r["_kan_name"]) for r in rows})
    codes = [k for k, _ in kans]
    if codes != list(range(1, len(codes) + 1)):
        raise RuntimeError(f"款が連番でない: {kans}")
    missing = [r for r in rows if not (r["_kan_name"] and r["_kou_name"] and r["moku_name"])]
    if missing:
        raise RuntimeError(f"名称の欠けた行が {len(missing)} 件: {missing[:3]}")


def main() -> None:
    got = http_get(URL)
    if got.sha256 != SHA256:
        raise RuntimeError(
            f"原文の SHA-256 が変わっている（{got.sha256}）。改正を確認してから SHA256 を更新すること"
        )
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(got.body)
        f.flush()
        rows = extract(pathlib.Path(f.name))
    verify(rows)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["direction", "kan_code", "kan_name", "kou_code", "kou_name",
                    "moku_code", "moku_name", "is_personnel_moku", "basis"])
        for r in rows:
            w.writerow(["expenditure", r["kan_code"], r["_kan_name"], r["kou_code"],
                        r["_kou_name"], r["moku_code"], r["moku_name"],
                        str(r["is_personnel_moku"]).lower(), BASIS])
    kans = sorted({(r["kan_code"], r["_kan_name"]) for r in rows})
    print(f"ok  {len(rows)} 目 / {len(kans)} 款  →  {OUT.relative_to(ROOT)}")
    for k, n in kans:
        print(f"    {k:>2} {n}")


if __name__ == "__main__":
    main()
