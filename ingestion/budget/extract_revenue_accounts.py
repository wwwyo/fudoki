"""歳入の科目名称を決算資料の歳入事項別明細から起こす。

原典 CSV に款・項・目の名称が無い団体で、歳入の科目名を補う経路。
歳出の事業名（extract_projects）と同じ「PDF から起こした判断」だが、
**歳入は PDF に科目コードが書いてある**ので、金額での対応づけは要らず、
コードで直接 join できる。金額（調定額）は対応づけではなく**検証**に使う。

⚠️ **経路が2つあり、保証の強さが違う。**
- text: PDF のテキストをそのまま読む（歳出の抽出と同じ強さ）。誤読が原理的に起きない
- ocr:  文字がアウトライン化された PDF を llama.cpp + GLM-OCR で読む。
  **誤読が混ざる前提**の経路で、調定額が原典 CSV と一致した科目からだけ
  名称を採る（下流の dbt がこの突合を行う。ここでは調定額を運ぶだけ）

⚠️ **どちらを使うかは宣言せず、ページごとに実測で決める（text 優先）。**
以前は `sources.toml` の `mode` が文書単位で宣言していたが、
資料名ではなく中身で判定するという原則と逆を向いていた（宣言が実物と食い違っても
誰も気づかない）。しかも実物はページ単位で割れている — 狛江 R2 の PDF は
p1 だけ見出しのテキストを持ち、p2 以降は表ごとアウトライン化されている。
**text で表の行が取れたページは text、取れなかったページだけ OCR** へ落とす。
⚠️ **1ページの中で混ぜない。** 座標ベースの行と HTML の表から復元した行を
同じページで突き合わせると、行の対応づけが破綻する。

⚠️ **text だけで済む文書は OCR エンジンを要求しない。** 狛江 2023 は全ページ text で
取れるので、llama.cpp も GGUF も無い環境で処理できる。

冪等: 原典の SHA-256 と抽出器の版（OCR へ落ちたページがあればエンジン版と重みを含む）
が同じなら何もしない。
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unicodedata

from ingestion.budget.sources import load_revenue_accounts
from ingestion.lib import html_table, ocr
from ingestion.lib import pdf as pdftext
from ingestion.lib.http import http_get

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "data" / "budget" / "raw" / "revenue-accounts"
# 抽出器の版。**出力を変える修正をしたら上げる。**
EXTRACTOR_VERSION = "8"

AMOUNT = re.compile(r"^[\d,]+$")
CODE_AND_NAME = re.compile(r"^(\d+)(\D.*)?$")
# OCR 経路の科目セル。**名称を必須にする。** 「46,182,434」は `\D` にカンマが当たって
# CODE_AND_NAME に通るので、金額のセルを科目と読み違える
SUBJECT = re.compile(r"^(\d+)\s*([^\d,.\s].*)$")
LEVELS = ("kan", "kou", "moku")
# text 経路を採るのに要る行数。**見出しだけ拾えた状態を「取れた」と呼ばない。**
# 狛江 R2 の p1 は「（1）歳入」の3語だけを持つが、表の行は1つも無い
MIN_TEXT_ROWS = 3


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


def _text_chars(pdf_path: pathlib.Path, first: int, last: int) -> dict[int, list]:
    """ページ番号 → 文字と座標。取れなければ空。

    ⚠️ **`pdftotext -bbox-layout` は落ちる PDF がある。** 狛江 R2〜R4 は
    SIGABRT で落ちる（アウトライン化と同じ理由かは未確認）。`pdftocairo` で
    再蒸留すれば通るので、落ちたら蒸留して1度だけやり直す。
    ⚠️ **落ちたことを「テキストが無い」と即断しない** — 再蒸留すると
    狛江 R2 の p1 は実際に3語取れる（それでも表の行は無いので OCR へ落ちる）。
    """
    for redistill in (False, True):
        try:
            pages = list(pdftext.chars_of(pdf_path, first, last, redistill=redistill))
        except subprocess.CalledProcessError:
            continue
        if any(pages):
            return dict(zip(range(first, last + 1), pages))
    return {}


def _text_items(page, spec: dict) -> list[dict]:
    """座標から (段, コード, 名称, 調定額) と折返しを組む。**text 経路**。

    ⚠️ **ページの見出し（「一般会計歳入 科目 款項目…」）を読ませない。**
    見出しを行として流すと、折返し処理がページをまたいだとき見出しを
    科目名の続きとして吸い込む（実際に「環境性能割一般会計歳入科目款項目当初」が名称に出た）。
    ⚠️ **見出しは固定の y では切れない。** 本文の1行目が見出しより高い位置に来るページがあり、
    固定 y は款の行ごと切り落とした（実際に款 1, 5, 9, 11, 14, 21 が消えた）。
    「款・項・目が1行に並び、数字を含まない行」を見出しとして検出し、その行より上だけを捨てる。
    """
    name_end = float(spec["name_end"])
    amt_lo, amt_hi = (float(v) for v in spec["amount"])
    bands = {lv: (float(lo), float(hi)) for lv, (lo, hi) in spec["bands"].items()}
    rows = _rows_with_y(page, 1.0)
    header_bottom = max((y for y, row in rows
                         if (lambda s: "款" in s and "項" in s and "目" in s
                             and not any(ch.isdigit() for ch in s))("".join(c for x, c in row))),
                        default=-1.0)
    items: list[dict] = []
    for y, row in rows:
        if y <= header_bottom:
            continue
        chars = sorted(row)
        subject = [(x, c) for x, c in chars if x < name_end]
        if not subject:
            continue
        text = unicodedata.normalize("NFKC", "".join(c for x, c in subject))
        amount = _amount("".join(c for x, c in chars if amt_lo <= x < amt_hi))
        m = CODE_AND_NAME.match(text)
        first_x = subject[0][0]
        level = next((lv for lv, (lo, hi) in bands.items() if lo <= first_x < hi), None)
        if m and level:
            items.append({"kind": "entry", "level": level, "code": int(m.group(1)),
                          "name": (m.group(2) or "").strip(), "amount": amount})
        elif not m:
            items.append({"kind": "cont", "text": text.strip()})
    return items


def _ocr_items(html: str) -> list[dict]:
    """OCR が返した HTML の表から (格子の列, コード, 名称, 調定額) を組む。**ocr 経路**。

    切り出して渡した列の順（款・項・目 / 調定額）がそのまま格子の列になる。
    ⚠️ **段は列だけでは決まらない。** 列は概ね正しいが、上の行から伸びた rowspan の
    都合で1段浅く出ることがある（実測: 目の行が項の列に出た）。
    段の確定は extract() が番号の連続と突き合わせて行う。
    """
    items: list[dict] = []
    for section, cells in html_table.grid(html):
        if section != "tbody":
            continue
        subject = next(((col, SUBJECT.match(_clean(t))) for col, t in cells
                        if SUBJECT.match(_clean(t))), None)
        if subject is None:
            continue                     # 節だけの行。科目の名前を持たない
        # ⚠️ **金額を列番号で拾わない。** 科目の列が2列に潰れる版が実在し、
        # そのとき調定額の列番号が1つ手前へずれる。科目のセルは名称を持つので
        # 数字だけのセルと取り違えようがなく、「最後の数字のセル」で足りる
        amounts = [t for col, t in cells if AMOUNT.match(t.strip())]
        items.append({"kind": "entry", "col": subject[0], "code": int(subject[1].group(1)),
                      "name": subject[1].group(2).strip(),
                      "amount": _amount(amounts[-1] if amounts else "")})
    return items


def _clean(text: str) -> str:
    """OCR は科目名の中に空白を入れることがある（「2 自動車重量譲与税」）"""
    return unicodedata.normalize("NFKC", text).replace(" ", "")


def _amount(text: str) -> int | None:
    text = text.replace(" ", "")
    return int(text.replace(",", "")) if AMOUNT.match(text) and any(
        ch.isdigit() for ch in text) else None


def _level_from_codes(col: int, code: int, current: dict[str, int]) -> str | None:
    """OCR の列が言う段を、番号の連続で検証する。合わなければ番号が続く段を採る。

    ⚠️ **列だけを信じない。** 実測で、款の直後の項が「項」の列に出て、
    その次の目も同じ列に出た（rowspan の持ち越し）。番号だけでも決まらない —
    款の直後は項も目も 1 から始まるので、両方が候補になる。**両方を使う。**

    ⚠️ **候補が複数なら、列が言う段に近いほうを採り、同点なら深いほうを採る。**
    実測した誤りは片方向で、OCR は段を**浅い側へ**外す（上の行から伸びた rowspan が
    セルを右へ押し出せないため）。同点で浅い側へ倒すと、目が款に化けて
    そこから後ろの款番号が全部ずれた（2020年度で 81 目中 41 目しか一致しなかった）。
    逆に近さを見ずに常に深いほうを採ると、款の列に出た項が目になって同じことが起きる。
    """
    want = LEVELS[col] if col < len(LEVELS) else None
    fits = [lv for lv in LEVELS if code == current[lv] + 1]
    if want in fits:
        return want
    if not fits or want is None:
        return want                       # どれとも続かない。列の言い分を残して突合に任せる
    return min(fits, key=lambda lv: (abs(LEVELS.index(lv) - LEVELS.index(want)),
                                     -LEVELS.index(lv)))


def plan(pdf_path: pathlib.Path, spec: dict) -> tuple[dict[int, list[dict]], dict[int, str]]:
    """ページごとに text 経路を試し、経路を決める。**OCR エンジンを要求しない。**

    判定は文字数ではなく**抽出できた表の行**で行う（原則3: 中身で判定する）。
    見出しだけ拾えた状態は「取れた」に数えない。
    """
    first, last = int(spec["first_page"]), int(spec["last_page"])
    chars = _text_chars(pdf_path, first, last)
    per_page: dict[int, list[dict]] = {}
    modes: dict[int, str] = {}
    for page_no in range(first, last + 1):
        items = _text_items(chars[page_no], spec) if page_no in chars else []
        entries = [i for i in items if i["kind"] == "entry" and i["amount"] is not None]
        if len(entries) >= MIN_TEXT_ROWS:
            per_page[page_no], modes[page_no] = items, "text"
        else:
            modes[page_no] = "ocr"
    return per_page, modes


def extract(pdf_path: pathlib.Path, spec: dict, per_page: dict[int, list[dict]],
            modes: dict[int, str]) -> list[dict]:
    """(款, 項, 目, 名称, 調定額) を出現順に返す。

    段の親子は出現順で決まる（款の下に項、項の下に目）。名称は科目欄の続きで、
    折返しは次行から繋ぐ。⚠️ **折返しはページをまたがない。**
    """
    first, last = int(spec["first_page"]), int(spec["last_page"])
    ocr_pages = [p for p in sorted(modes) if modes[p] == "ocr" and p not in per_page]
    if ocr_pages:
        cols = [(0.0, float(spec["name_end"])), tuple(float(v) for v in spec["amount"])]
        for page_no, html in zip(ocr_pages, ocr.tables_of(pdf_path, ocr_pages, cols)):
            per_page[page_no] = _ocr_items(html)

    rows: list[dict] = []
    current = {"kan": 0, "kou": 0, "moku": 0}
    names = {"kan": "", "kou": ""}
    # 折返しの反映範囲。**コードで探さない** — 同じ款コードが文書内で2度出ることがあり
    # （抽出が段を外した行を含む）、コードで探すと無関係な行の親名を上書きする
    start = {"kan": 0, "kou": 0}
    for page_no in range(first, last + 1):
        open_level: str | None = None
        for item in per_page[page_no]:
            if item["kind"] == "cont":
                if open_level == "moku" and rows:
                    rows[-1]["moku_name"] += item["text"]
                elif open_level:
                    names[open_level] += item["text"]
            else:
                level = (item["level"] if modes[page_no] == "text"
                         else _level_from_codes(item["col"], item["code"], current))
                if level is None:
                    continue
                current[level] = item["code"]
                for deeper in LEVELS[LEVELS.index(level) + 1:]:
                    current[deeper] = 0   # 親が変われば子の番号は 1 に戻る
                if level == "moku":
                    rows.append({"kan_code": current["kan"], "kou_code": current["kou"],
                                 "moku_code": item["code"], "moku_name": item["name"],
                                 "choutei_yen": item["amount"], "mode": modes[page_no],
                                 "_kan_name": names["kan"], "_kou_name": names["kou"]})
                else:
                    names[level] = item["name"]
                    start[level] = len(rows)
                    if level == "kan":
                        names["kou"] = ""
                        start["kou"] = len(rows)
                open_level = level
            # ⚠️ **折返しで伸びた親の名前を、既に出した子の行へ反映する。**
            # 行を出した時点の名前で固定すると、款名が2行に折り返している間に
            # 出た目だけ名前が欠ける
            for r in rows[start["kan"]:]:
                r["_kan_name"] = names["kan"]
            for r in rows[start["kou"]:]:
                r["_kou_name"] = names["kou"]
    return [r for r in rows if r["kan_code"] and r["kou_code"]]


def summarize(rows: list[dict]) -> dict:
    named = sum(1 for r in rows if r["_kan_name"] and r["_kou_name"] and r["moku_name"])
    keys = [(r["kan_code"], r["kou_code"], r["moku_code"]) for r in rows]
    return {
        "moku": len(rows),
        "named": named,
        "withAmount": sum(1 for r in rows if r["choutei_yen"] is not None),
        "kan": len({r["kan_code"] for r in rows}),
        # 保証範囲を機械可読に。OCR 経路はここが弱い（金額を読めない行・コードの重複）ことが
        # そのまま「名称に使わない」判断の根拠になる
        "duplicateKeys": len(keys) - len(set(keys)),
    }


def ingest(key: str) -> None:
    spec = load_revenue_accounts()[key]
    code, year = key.split(":")
    got = http_get(spec["url"])
    if got.status != 200:
        raise RuntimeError(f"HTTP {got.status}: {spec['url']}")

    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(got.body)
        f.flush()
        pdf_path = pathlib.Path(f.name)
        # ⚠️ **抽出（OCR は数分かかる）の前に冪等を判定する。** そのために
        # 経路の判定だけ先に済ませる — text で足りるかはテキスト抽出だけで分かり、
        # OCR エンジンを要求しない
        per_page, modes = plan(pdf_path, spec)
        needs_ocr = "ocr" in modes.values()
        extractor = f"ingestion/budget/extract_revenue_accounts.py@{EXTRACTOR_VERSION}"
        engine_missing = False
        if needs_ocr:
            try:
                extractor += f"+{ocr.engine_version()}"
            except (FileNotFoundError, subprocess.CalledProcessError):
                # エンジンが無い環境では llama.cpp の版を確定できないので、
                # extractor 文字列をそのまま突き合わせる冪等判定が成立しない。
                # 再抽出も物理的にできないため、確定できる材料（原典の SHA-256・
                # 抽出器の版・重みと DPI の指紋）だけで判定する
                engine_missing = True

        out_dir = OUT / f"jurisdiction={code}" / f"year={year}"
        prov_path = out_dir / "provenance.json"
        if prov_path.exists() and (out_dir / "data.parquet").exists():
            old = json.loads(prov_path.read_text())
            if engine_missing:
                # 版で比較できない代わりに、原典が既存の抽出物と同じ SHA-256 なら
                # 抽出結果も変わらないはずなので保全する。違えば再抽出が必要だが
                # エンジンが無くて実行できないので、黙って古い抽出物を使わず止める
                #
                # ⚠️ 抽出器の版と**重み・DPI の指紋**はエンジンが無くても分かるので、
                # そこは比較を落とさない。落とすと、抽出の規則やモデルを変えたのに
                # 古い抽出物が黙って生き残る（版が確定できないのは llama.cpp の
                # バイナリの版だけで、`ocr.weights_version()` はバイナリを呼ばない）
                old_extractor = str(old.get("extractor", ""))
                if (old.get("sha256") == got.sha256
                        and old_extractor.startswith(f"{extractor}+")
                        and old_extractor.endswith(ocr.weights_version())):
                    print(f"skip  {key}  OCR エンジンが見つからないため版を確認できないが、"
                          f"原典は既存の抽出物（extractor={old.get('extractor')}）と同じ SHA-256 "
                          "なのでそれを使う")
                    return
                raise RuntimeError(
                    f"{key}: OCR エンジンが見つからず、かつ既存の抽出物が現在の原典・"
                    f"抽出器（{extractor}）・重み（{ocr.weights_version()}）と一致しない"
                    f"（既存: sha256={old.get('sha256')}, extractor={old_extractor}）。"
                    "再抽出できないため停止する"
                    "（OCR エンジンをインストールしてから再実行すること）")
            if old.get("sha256") == got.sha256 and old.get("extractor") == extractor:
                print(f"skip  {key}  同じ原典・同じ抽出器の版で既に抽出済み")
                return

        rows = extract(pdf_path, spec, per_page, modes)
    if not rows:
        raise RuntimeError(f"{key}: 科目を1件も抽出できなかった")
    summary = summarize(rows)
    # ⚠️ **OCR の妥当性はここでは確定しない。** 名称の欠けや金額の誤読は下流の
    # CSV 突合（dbt）が科目単位に判定する。ここで止めるのは「ほぼ何も読めていない」だけ。
    if summary["named"] < summary["moku"] * 0.5:
        raise RuntimeError(f"{key}: 名称が付いた科目が半分未満（{summary}）。レイアウトを読めていない")
    # ⚠️ 見出しの混入検査。**金額の突合は名称の汚れを検出しない**（実際に 79/79 一致の裏で
    # 名称に見出しが食い込んでいた）ので、名称そのものを見る。
    # OCR 経路は見出しを表の外に出すので、text 経路の行だけを見る。
    dirty = [r for r in rows if r["mode"] == "text" and re.search(
        r"科目|款項目|当初|歳入歳出", r["_kan_name"] + r["_kou_name"] + r["moku_name"])]
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
                      r["mode"])
                     for i, r in enumerate(rows)])
    con.execute(f"COPY (SELECT * FROM t ORDER BY ordinal) TO '{out_dir / 'data.parquet'}' "
                f"(FORMAT parquet, COMPRESSION zstd)")
    con.close()

    by_mode = {m: sum(1 for v in modes.values() if v == m) for m in sorted(set(modes.values()))}
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
        # ⚠️ **経路は観測であって宣言ではない。** ページごとに text を試した結果が入る
        "pages_by_mode": by_mode,
        "text_pages": sorted(p for p, m in modes.items() if m == "text"),
        # ⚠️ OCR は誤読が混ざる前提の経路。ここの保証は「レイアウトを読めた」まで。
        # 科目単位の妥当性は dbt の調定額突合（CSV と円単位で一致）が決める。
        "verification": ("text-extraction" if by_mode.get("ocr", 0) == 0
                         else "ocr + downstream-amount-reconciliation"
                         if by_mode.get("text", 0) == 0
                         else "text-extraction (一部) + ocr + downstream-amount-reconciliation"),
        "roundtrip_verified": False,
        "extracted": summary,
        "raw_form": spec.get("raw_form", "extracted"),
        "redistribute": spec.get("redistribute", "review"),
        "redistribute_basis": spec.get("redistribute_basis", ""),
        "license_id": spec.get("license_id", "NOASSERTION"),
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"ok    {key}  {summary['moku']} 目 / {summary['kan']} 款  "
          f"名称 {summary['named']}  金額 {summary['withAmount']}  ページ {by_mode}")


if __name__ == "__main__":
    keys = sys.argv[1:] or sorted(load_revenue_accounts())
    for k in keys:
        print(f"--- {k}")
        ingest(k)
