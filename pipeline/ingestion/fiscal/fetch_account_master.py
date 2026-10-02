"""法定の科目マスタを、地方自治法施行規則 別記の原文から起こす。

別記「歳入歳出予算の款項の区分及び目の区分」（第15条関係）の**市町村**の表（歳入・歳出）を
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
BASIS = "地方自治法施行規則 別記「歳入歳出予算の款項の区分及び目の区分」（第15条関係）市町村"

# 表ごとの宣言（2026-08-23〜24 実測）。
# ⚠️ **歳入と歳出で都道府県欄の張り出しが違う。** 歳出の都道府県欄は x<290 に収まるが、
# 歳入は目のコードが x=348、名称が x=364〜425 まで来て、市町村欄の款・項の帯と重なる。
# 固定の x 境界では欄を切れないので、**両欄のコード位置を追跡して行を欄に帰属させる**。
# code_bands はコード（数字）の開始 x の帯。名称はコードの後ろ、次のコード帯の手前まで。
TABLES = {
    "revenue": {
        "pages": (1, 12),
        "start": "1市",           # 市町村欄の最初の款「1 市（町村）税」
        # ⚠️ コードは中央寄せで、**2桁になると1桁より左から始まる**（項10 の実測 x=357.6、
        # 項9 は 361.1）。帯の境界を1桁の実測で引くと2桁が隣の帯に食われる。
        "pref_bands": {"kan": (140.0, 158.0), "kou": (240.0, 258.0), "moku": (343.0, 356.5)},
        "muni_bands": {"kan": (290.0, 315.0), "kou": (356.5, 372.0), "moku": (425.0, 445.0)},
    },
    "expenditure": {
        "pages": (13, 25),
        "start": "1議会費",
        "pref_name_cut": 290.0,
        "pref_bands": {"kan": (110.0, 125.0), "kou": (168.0, 182.0), "moku": (240.0, 255.0)},
        "muni_bands": {"kan": (290.0, 325.0), "kou": (355.0, 370.0), "moku": (425.0, 445.0)},
    },
}
MARK = "※"


def _segments(line: list[tuple[float, str]], spec: dict):
    """1行を (欄, 階層, コード, 名称) のセグメントへ割る。

    コード（数字）の開始 x がどの帯に入るかで欄と階層が決まり、
    名称はその後ろ、次のコード帯に入る数字の手前まで。
    **x の固定境界で名称を切らない** — 名称の右端は階層ごとに揺れ、
    歳入では都道府県の名称が市町村の帯まで張り出す。
    """
    bands = [("pref", lv, lo, hi) for lv, (lo, hi) in spec["pref_bands"].items()] + \
            [("muni", lv, lo, hi) for lv, (lo, hi) in spec["muni_bands"].items()]
    # ⚠️ **都道府県のセグメントの名称の打ち切り方は表で違う。**
    # 歳出は都道府県欄が丸ごと市町村欄の左にあるので、市町村欄の開始 x で切ってよい。
    # 歳入は帯が交互に重なる（都道府県の目 343〜 > 市町村の款 290〜）ので、
    # x で切ると都道府県のセグメントが開始した瞬間に壊れる。切らずに、
    # 次のコード帯の数字が来た時点で自然に切れることに任せる。
    muni_lo = spec.get("pref_name_cut", float("inf"))
    chars = sorted(line)
    segs: list[dict] = []
    cur: dict | None = None
    prev_digit = False
    for x, c in chars:
        if cur is not None and cur["side"] == "pref" and x >= muni_lo:
            cur = None
        is_digit = unicodedata.normalize("NFKC", c).isdigit()
        if is_digit and not prev_digit:
            hit = next(((side, lv) for side, lv, lo, hi in bands if lo <= x < hi), None)
            if hit:
                cur = {"side": hit[0], "level": hit[1], "code": c, "name": "", "x": x}
                segs.append(cur)
                prev_digit = True
                continue
        if cur is None:
            prev_digit = False
            continue
        if is_digit and prev_digit:
            cur["code"] += c
        else:
            prev_digit = False
            if c != ".":
                cur["name"] += c
    return segs


def extract(pdf: pathlib.Path, direction: str) -> list[dict]:
    """(款, 項, 目) を出現順に返す。名称の折返し（`農林水/産業費`）は次行から繋ぐ"""
    spec = TABLES[direction]
    first, last = spec["pages"]
    rows: list[dict] = []
    kan = kou = None
    kan_name = kou_name = ""
    started = False
    open_side: str | None = None     # 名称の折返しを受け取る欄（pref / muni）
    open_level: str | None = None
    pending_mark = False             # ※は目の1行上に単独で印字される。次の目に付ける
    kou_lo = spec["muni_bands"]["kou"][0]
    moku_lo = spec["muni_bands"]["moku"][0]
    for page in chars_of(pdf, first, last, redistill=True):
        for line in rows_of(page, tolerance=2.0):
            text = "".join(c for x, c in sorted(line))
            if text.startswith("備考"):
                return rows
            segs = _segments(line, spec)
            muni = [s for s in segs if s["side"] == "muni"]
            if not started:
                started = any(s["level"] == "kan" and (s["code"] + s["name"]).startswith(spec["start"])
                              for s in muni)
                if not started:
                    continue

            # ⚠️ **判定は市町村欄の文字だけで行う。** 2段組は左右の行が同じ y に整列するので、
            # 行の全文字で見ると都道府県欄の内容が混ざり、※の単独行判定が壊れる
            # （実際に※が 32→10 個へ減った）。
            muni_text = "".join(c for x, c in sorted(line) if x >= spec["muni_bands"]["kan"][0])
            if muni_text.strip() == MARK:
                pending_mark = True
                continue

            if muni:
                for s in muni:
                    code, name = int(s["code"]), s["name"].strip()
                    mark = MARK in name
                    name = name.replace(MARK, "")
                    if s["level"] == "kan":
                        kan, kan_name, kou, kou_name = code, name, None, ""
                    elif s["level"] == "kou":
                        kou, kou_name = code, name
                    else:
                        rows.append({"kan_code": kan, "kou_code": kou, "moku_code": code,
                                     "moku_name": name,
                                     "is_personnel_moku": mark or pending_mark,
                                     "_kan_name": kan_name, "_kou_name": kou_name})
                        pending_mark = False
                # コードを出した階層が折返しを受け取る
                open_side, open_level = "muni", muni[-1]["level"]
            # ⚠️ **判定は市町村セグメントの有無。** `not segs` にすると、同じ行に
            # 都道府県のセグメントがあるだけで市町村の折返しが捨てられ、名称の末尾が欠ける
            # （2段組は左右の行が同じ y に整列するので、この同居は普通に起きる）。
            elif open_side == "muni" and open_level and not muni:
                # ⚠️ **折返しの帰属は x で決める。** 歳入では都道府県の目の名称（x=364〜425）が
                # 市町村の項の名称域と重なるが、都道府県の折返しは open_side が pref のときに
                # ここへ来ない（上の分岐で捨てられる）。市町村の折返しとして受けるのは、
                # 開いている階層の名称域より右の文字だけ。
                lo = {"kan": 300.0, "kou": kou_lo, "moku": moku_lo}[open_level]
                cont = "".join(c for x, c in sorted(line) if x >= lo)
                if MARK in cont and rows and open_level == "moku":
                    rows[-1]["is_personnel_moku"] = True
                cont = cont.replace(MARK, "").strip()
                if cont:
                    if open_level == "kan":
                        kan_name += cont
                    elif open_level == "kou":
                        kou_name += cont
                    elif rows:
                        rows[-1]["moku_name"] += cont
            # 折返しで確定した親名を、既に積んだ行へも反映する
            for r in rows:
                if r["kan_code"] == kan and r["_kan_name"] != kan_name:
                    r["_kan_name"] = kan_name
                if r["kan_code"] == kan and r["kou_code"] == kou and r["_kou_name"] != kou_name:
                    r["_kou_name"] = kou_name
    return rows


def verify(rows: list[dict]) -> None:
    """抽出漏れの検査。**款・項・目が連番で、名称が欠けないこと。**

    ⚠️ 連番は款だけでは足りない。2桁の項コードが帯からはみ出して隣の欄に食われたとき、
    款は揃ったまま**項が欠番**になった（歳入の項10〜13 が消え、その目が項9 に付いた）。
    """
    kans = sorted({(r["kan_code"], r["_kan_name"]) for r in rows})
    codes = [k for k, _ in kans]
    if codes != list(range(1, len(codes) + 1)):
        raise RuntimeError(f"款が連番でない: {kans}")
    for level, parent in (("kou_code", ("kan_code",)), ("moku_code", ("kan_code", "kou_code"))):
        groups: dict[tuple, set] = {}
        for r in rows:
            groups.setdefault(tuple(r[k] for k in parent), set()).add(r[level])
        for parent_key, seen in groups.items():
            if sorted(seen) != list(range(1, len(seen) + 1)):
                raise RuntimeError(f"{level} が連番でない（親 {parent_key}）: {sorted(seen)}")
    missing = [r for r in rows if not (r["_kan_name"] and r["_kou_name"] and r["moku_name"])]
    if missing:
        raise RuntimeError(f"名称の欠けた行が {len(missing)} 件: {missing[:3]}")
    # ⚠️ 備考の文が名称に混入していないか。実際に最終行の目名へ「…ること。(退職手当を除」が
    # 食い込んでいたことがある（名称の空でないことしか見ない verify はこれを通した）
    import re
    noisy = [r for r in rows if re.search(r"[。．]|ること|については",
             r["_kan_name"] + r["_kou_name"] + r["moku_name"])]
    if noisy:
        raise RuntimeError(f"名称に本文の断片が混入: {noisy[:3]}")


def main() -> None:
    got = http_get(URL)
    if got.sha256 != SHA256:
        raise RuntimeError(
            f"原文の SHA-256 が変わっている（{got.sha256}）。改正を確認してから SHA256 を更新すること"
        )
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["direction", "kan_code", "kan_name", "kou_code", "kou_name",
                    "moku_code", "moku_name", "is_personnel_moku", "basis"])
        with tempfile.NamedTemporaryFile(suffix=".pdf") as pf:
            pf.write(got.body)
            pf.flush()
            for direction in ("revenue", "expenditure"):
                rows = extract(pathlib.Path(pf.name), direction)
                verify(rows)
                for r in rows:
                    w.writerow([direction, r["kan_code"], r["_kan_name"], r["kou_code"],
                                r["_kou_name"], r["moku_code"], r["moku_name"],
                                str(r["is_personnel_moku"]).lower(), BASIS])
                kans = sorted({(r["kan_code"], r["_kan_name"]) for r in rows})
                print(f"ok  {direction}  {len(rows)} 目 / {len(kans)} 款")
                for k, n in kans:
                    print(f"    {k:>2} {n}")


if __name__ == "__main__":
    main()
