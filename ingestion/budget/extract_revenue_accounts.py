"""歳入の科目名称を決算資料の歳入事項別明細から起こす。

原典 CSV に款・項・目の名称が無い団体で、歳入の科目名を補う経路。
歳出の事業名（extract_projects）と同じ「PDF から起こした判断」だが、
**歳入は PDF に科目コードが書いてある**ので、金額での対応づけは要らず、
コードで直接 join できる。金額（調定額）は対応づけではなく**検証**に使う。

⚠️ **経路が2つあり、保証の強さが違う。**
- mode = "text": PDF のテキストをそのまま読む（歳出の抽出と同じ強さ）
- mode = "ocr": 文字がアウトライン化された PDF を Tesseract で読む。
  **誤読が混ざる前提**の経路で、調定額が原典 CSV と一致した科目からだけ
  名称を採る（下流の dbt がこの突合を行う。ここでは調定額を運ぶだけ）

冪等: 原典の SHA-256 と抽出器の版（OCR は エンジン版 + DPI を含む）が同じなら何もしない。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import tempfile
import unicodedata

from ingestion.budget.sources import SOURCES_TOML
from ingestion.lib import ocr
from ingestion.lib import pdf as pdftext
from ingestion.lib.http import http_get

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "data" / "budget" / "raw" / "revenue-accounts"
# 抽出器の版。**出力を変える修正をしたら上げる。**
EXTRACTOR_VERSION = "6"

AMOUNT = re.compile(r"^[\d,]+$")


def load_declarations() -> dict[str, dict]:
    import tomllib
    return tomllib.loads(SOURCES_TOML.read_text(encoding="utf-8")).get("revenue_accounts", {})


def _rows_with_y(page, tolerance: float):
    """(y代表値, [(x, 文字)]) の行リスト。見出し行の y を判定に使うため y を保つ"""
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
    return [(g[0], row) for g, row in zip(groups, rows)]


def _lines(pdf_path: pathlib.Path, spec: dict):
    """視覚行ごとに (先頭x, 科目欄の文字列, 調定額の文字列) を返す。経路の差はここで吸収する。

    ⚠️ **ページの見出し（「一般会計歳入 科目 款項目…」）を読ませない。**
    見出しを行として流すと、折返し処理がページをまたいだとき見出しを
    科目名の続きとして吸い込む（実際に「環境性能割一般会計歳入科目款項目当初」が名称に出た）。
    ⚠️ **見出しは固定の y では切れない。** 本文の1行目が見出しより高い位置に来るページがあり、
    固定 y は款の行ごと切り落とした（実際に款 1, 5, 9, 11, 14, 21 が消えた）。
    text 経路は「款・項・目が1行に並び、数字を含まない行」を見出しとして検出し、
    その行より上だけを捨てる。OCR 経路は組版が固定なので宣言の header_end で切る。

    ⚠️ **OCR はページ全体を読まない。** 科目欄と金額欄を別々に切り出して読む
    （全体を読むと語の融合で座標が壊れ、実測で科目の8割を落とした）。
    """
    name_end = float(spec["name_end"])
    amt_lo, amt_hi = (float(v) for v in spec["amount"])
    if spec["mode"] == "text":
        for page in pdftext.chars_of(pdf_path, int(spec["first_page"]), int(spec["last_page"])):
            rows = _rows_with_y(page, 1.0)
            header_bottom = max((y for y, row in rows
                                 if (lambda s: "款" in s and "項" in s and "目" in s
                                     and not any(ch.isdigit() for ch in s))
                                    ("".join(c for x, c in row))), default=-1.0)
            for y, row in rows:
                if y <= header_bottom:
                    continue
                chars = sorted(row)
                subject = [(x, c) for x, c in chars if x < name_end]
                if not subject:
                    continue
                amount = "".join(c for x, c in chars if amt_lo <= x < amt_hi)
                yield subject[0][0], "".join(c for x, c in subject), amount
    else:
        top = float(spec.get("header_end", 0))
        cols = {"subject": (0.0, name_end), "amount": (amt_lo, amt_hi)}
        for page in ocr.column_words_of(pdf_path, int(spec["first_page"]), int(spec["last_page"]),
                                        cols, digits={"amount"}, top=top):
            merged = [(x, y, "subject", w) for x, y, w in page["subject"]] + \
                     [(x, y, "amount", w) for x, y, w in page["amount"]]
            # 語を y でクラスタする（rows_of は文字粒度の想定なのでここで直に組む）
            merged.sort(key=lambda t: t[1])
            rows: list[list] = []
            for x, y, col, w in merged:
                if rows and y - rows[-1][-1][1] <= 6.0:
                    rows[-1].append((x, y, col, w))
                else:
                    rows.append([(x, y, col, w)])
            for row in rows:
                subject = sorted(((x, w) for x, y, col, w in row if col == "subject"))
                if not subject:
                    continue
                amount = "".join(w for x, y, col, w in sorted(row) if col == "amount")
                yield subject[0][0], "".join(w for x, w in subject), amount


def extract(pdf_path: pathlib.Path, spec: dict) -> list[dict]:
    """(款, 項, 目, 名称, 調定額円) を出現順に返す。

    行の先頭コード（数字）の x がどの帯に入るかで階層が決まる。
    名称は科目欄の続きで、折返しは次行から繋ぐ。
    """
    bands = {lv: (float(lo), float(hi)) for lv, (lo, hi) in spec["bands"].items()}
    rows: list[dict] = []
    kan = kou = None
    kan_name = kou_name = ""
    open_level: str | None = None
    for first_x, subject_text, amount_s in _lines(pdf_path, spec):
        text = unicodedata.normalize("NFKC", subject_text)
        m = re.match(r"^(\d+)(\D.*)?$", text)
        level = next((lv for lv, (lo, hi) in bands.items() if lo <= first_x < hi), None)
        amount_s = amount_s.replace(" ", "")
        amount = int(amount_s.replace(",", "")) if AMOUNT.match(amount_s) and any(
            ch.isdigit() for ch in amount_s) else None

        if m and level:
            code, name = int(m.group(1)), (m.group(2) or "").strip()
            if level == "kan":
                kan, kan_name, kou, kou_name = code, name, None, ""
            elif level == "kou":
                kou, kou_name = code, name
            else:
                rows.append({"kan_code": kan, "kou_code": kou, "moku_code": code,
                             "moku_name": name, "choutei_yen": amount,
                             "_kan_name": kan_name, "_kou_name": kou_name})
            open_level = level
        elif open_level and not m:
            cont = text.strip()
            if cont:
                if open_level == "kan":
                    kan_name += cont
                elif open_level == "kou":
                    kou_name += cont
                elif rows:
                    rows[-1]["moku_name"] += cont
        for r in rows:
            if r["kan_code"] == kan and r["_kan_name"] != kan_name:
                r["_kan_name"] = kan_name
            if r["kan_code"] == kan and r["kou_code"] == kou and r["_kou_name"] != kou_name:
                r["_kou_name"] = kou_name
    return [r for r in rows if r["kan_code"] and r["kou_code"]]


def summarize(rows: list[dict]) -> dict:
    named = sum(1 for r in rows if r["_kan_name"] and r["_kou_name"] and r["moku_name"])
    return {
        "moku": len(rows),
        "named": named,
        "withAmount": sum(1 for r in rows if r["choutei_yen"] is not None),
        "kan": len({r["kan_code"] for r in rows}),
    }


def ingest(key: str) -> None:
    spec = load_declarations()[key]
    code, year = key.split(":")
    got = http_get(spec["url"])
    if got.status != 200:
        raise RuntimeError(f"HTTP {got.status}: {spec['url']}")

    extractor = f"ingestion/budget/extract_revenue_accounts.py@{EXTRACTOR_VERSION}"
    if spec["mode"] == "ocr":
        extractor += f"+{ocr.engine_version()}"

    out_dir = OUT / f"jurisdiction={code}" / f"year={year}"
    prov_path = out_dir / "provenance.json"
    # 冪等。抽出（OCR は数分かかる）の前に判定する
    if prov_path.exists() and (out_dir / "data.parquet").exists():
        old = json.loads(prov_path.read_text())
        if old.get("sha256") == got.sha256 and old.get("extractor") == extractor:
            print(f"skip  {key}  同じ原典・同じ抽出器の版で既に抽出済み")
            return

    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(got.body)
        f.flush()
        rows = extract(pathlib.Path(f.name), spec)
    if not rows:
        raise RuntimeError(f"{key}: 科目を1件も抽出できなかった")
    summary = summarize(rows)
    # ⚠️ **OCR の妥当性はここでは確定しない。** 名称の欠けや金額の誤読は下流の
    # CSV 突合（dbt）が科目単位に判定する。ここで止めるのは「ほぼ何も読めていない」だけ。
    if summary["named"] < summary["moku"] * 0.5:
        raise RuntimeError(f"{key}: 名称が付いた科目が半分未満（{summary}）。レイアウトを読めていない")
    # ⚠️ 見出しの混入検査。**金額の突合は名称の汚れを検出しない**（実際に 79/79 一致の裏で
    # 名称に見出しが食い込んでいた）ので、名称そのものを見る。
    if spec["mode"] == "text":
        dirty = [r for r in rows if re.search(r"科目|款項目|当初|歳入歳出",
                 r["_kan_name"] + r["_kou_name"] + r["moku_name"])]
        if dirty:
            raise RuntimeError(f"{key}: 名称に見出しが混入: {dirty[:3]}")

    out_dir.mkdir(parents=True, exist_ok=True)
    import duckdb  # noqa: PLC0415

    con = duckdb.connect()
    con.execute("CREATE TABLE t (ordinal BIGINT, kan_code VARCHAR, kou_code VARCHAR, "
                "moku_code VARCHAR, kan_name VARCHAR, kou_name VARCHAR, moku_name VARCHAR, "
                "choutei_yen BIGINT, mode VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(i, str(r["kan_code"]), str(r["kou_code"]), str(r["moku_code"]),
                      r["_kan_name"], r["_kou_name"], r["moku_name"], r["choutei_yen"],
                      spec["mode"])
                     for i, r in enumerate(rows)])
    con.execute(f"COPY (SELECT * FROM t ORDER BY ordinal) TO '{out_dir / 'data.parquet'}' "
                f"(FORMAT parquet, COMPRESSION zstd)")
    con.close()

    prov_path.write_text(json.dumps({
        "jurisdiction_code": code,
        "fiscal_year": int(year),
        "direction": "revenue",
        "document_title": spec["document_title"],
        "request_url": got.url,
        "status": got.status,
        "bytes": len(got.body),
        "sha256": got.sha256,
        "fetched_at": got.fetched_at,
        "pages": [spec["first_page"], spec["last_page"]],
        "extractor": extractor,
        "mode": spec["mode"],
        # ⚠️ OCR は誤読が混ざる前提の経路。ここの保証は「レイアウトを読めた」まで。
        # 科目単位の妥当性は dbt の調定額突合（CSV と円単位で一致）が決める。
        "verification": ("text-extraction" if spec["mode"] == "text"
                         else "ocr + downstream-amount-reconciliation"),
        "roundtrip_verified": False,
        "extracted": summary,
        "raw_form": spec.get("raw_form", "extracted"),
        "redistribute": spec.get("redistribute", "review"),
        "redistribute_basis": spec.get("redistribute_basis", ""),
        "license_id": spec.get("license_id", "NOASSERTION"),
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"ok    {key}  {summary['moku']} 目 / {summary['kan']} 款  "
          f"名称 {summary['named']}  金額 {summary['withAmount']}  mode={spec['mode']}")


if __name__ == "__main__":
    keys = sys.argv[1:] or sorted(load_declarations())
    for k in keys:
        print(f"--- {k}")
        ingest(k)
