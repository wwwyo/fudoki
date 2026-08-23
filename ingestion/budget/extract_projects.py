"""歳出事項別明細の PDF から「事業名」を起こして `data/budget/raw/` へ Parquet で落とす。

**なぜ要るか。** 狛江市のオープンデータ CSV は款・項・目・大事業を数字コードでしか持たず、
名称の列が無い。名称は市が公開している決算資料 PDF にしかない（カタログには無く、
2026-08-22 に狛江市の 399 データセットを全件走査して確認した）。
名称が無いと「その事業が何か」を原典から引けず、fudoki の出発点が成立しない。

⚠️ **PDF そのものは保存しない。** ここが落とすのは抽出結果だけで、
原典のバイト列は毎回取得元から取る。証跡（URL・SHA-256・取得時刻）は残すので、
「いつ時点のどのバイト列から起こしたか」は追える。

⚠️ **「無加工」を主張しない。** CSV の取り込みは復元一致（原文へ戻して突合）で
無加工を検査にできるが、**レイアウトから表を起こす操作は不可逆で、同じ検査ができない**。
代わりに PDF が同じ数字を階層ごとに重複して印刷していることを使い、
款・項・目の合計と事業の合計が一致するかを毎回確かめる（`reconciled` に記録）。
これは復元一致より弱い（同じ誤りが両側に入れば通る）。強さの違いを証跡に明記する。

## 抽出の仕組み

⚠️ **単語の x では列を分けられない。** 主管課（縦書き。1行1文字）・事業名・事業説明が
空白なしで隣り合うため、pdftotext は列をまたぐ1語として吐く（例:「護制度関係費行政不服」）。
CJK が等幅なのを使い、語の xMin..xMax を文字数で割って**文字ごとの x** を出してから列へ振る。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import unicodedata
from collections import defaultdict

from ingestion.budget.sources import load_project_names
from ingestion.lib.http import http_get
from ingestion.lib.pdf import chars_of as _chars, column_of, rows_of as _rows_of

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "data" / "budget" / "raw" / "project-names"
# 抽出器の版。**出力を変える修正をしたら上げる。**
# (PDF の SHA-256, この版) で出力が決まる、という再現性の主張がここに乗る。
EXTRACTOR_VERSION = "3"

NUMBER = re.compile(r"^[\d,]+$")


def extract(pdf: pathlib.Path, first: int, last: int,
            columns: dict[str, tuple[float, float]],
            tolerance: float = 1.0) -> tuple[list[dict], dict]:
    """(款, 項, 目, 事業名, 金額千円) を出現順に、目の見出し金額と一緒に返す。

    目の見出し金額は突合の相手になる。**PDF は同じ数字を階層ごとに重複して印刷している**ので、
    目の合計とその目に属する事業の合計が一致すれば、行を落としていないと言える。
    """
    kan = kou = moku = None
    kan_name = kou_name = moku_name = None
    label_open: str | None = None
    rows: list[dict] = []
    moku_totals: dict[tuple, int] = {}
    pending: dict | None = None
    name_open = False
    for page in _chars(pdf, first, last):
        for line in _rows_of(page, tolerance):
            cells = defaultdict(str)
            for x, c in sorted(line):
                col = column_of(x, columns)
                if col:
                    cells[col] += c
            name, amount = cells["mei"].strip(), cells["kingaku"].strip()
            if name in ("事業名", "事業説明") or amount == "金額":
                continue
            # ⚠️ `[\d,]+` は "," 単体にも当たる。int("") で落ちるので数字を要求する。
            if not NUMBER.match(amount.replace(" ", "")) or not any(ch.isdigit() for ch in amount):
                amount = ""

            # 款・項・目の見出し。**1行に3つ並ぶ**ので、どの階層かは x で決まる。
            # ⚠️ **コードの後ろに科目の名称が続く。** 以前ここは数字だけを拾って
            # 名称を捨てており、その結果「款・項・目の名称は決算書 PDF にも無い」と
            # 誤って結論していた。**抽出結果の欠落を資料の性質だと読み替えていた**
            # （原則3「資料名ではなく中身の粒度で判定する」を自分で破っていた）。
            found, buf, bx = [], "", None
            for x, c in sorted(line):
                if column_of(x, columns) != "code":
                    continue
                if bx is None:
                    bx = x
                buf += c
                if c == ".":
                    digits = unicodedata.normalize("NFKC", buf).rstrip(".")
                    # 科目の列に数字でないものが来ることがある（見出しの名称など）。落とさず捨てる。
                    if digits.isdigit():
                        found.append([bx, int(digits), ""])
                    buf, bx = "", None
                elif found and not unicodedata.normalize("NFKC", buf).isdigit():
                    # コードを1つ読んだ後の非数字は、そのコードの名称。
                    # 次のコードが始まると buf は数字に戻り、ここへは来ない。
                    found[-1][2] += c
                    buf, bx = "", None
            # ⚠️ **科目の名称は次の行へ折り返す。**
            # `１.保健衛生` の続きが次行の `総務費` にあり、繋げないと
            # 「保健衛生」という実在しない科目名になる。**規則を当てる相手なので、
            # 切れた名前は静かに当たらないか、悪くすると別の科目に当たる。**
            if not found and label_open:
                cont = "".join(c for x, c in sorted(line) if column_of(x, columns) == "code").strip()
                if cont and not any(ch.isdigit() for ch in unicodedata.normalize("NFKC", cont)):
                    if label_open == "kan":
                        kan_name = (kan_name or "") + cont
                    elif label_open == "kou":
                        kou_name = (kou_name or "") + cont
                    else:
                        moku_name = (moku_name or "") + cont
                else:
                    label_open = None      # 科目の列が空なら、そこで名前は閉じる

            if found:
                if pending:
                    rows.append(pending)
                    pending = None
                # ⚠️ **持ち越しは行に入る前の状態から引く。**
                # 文脈行（`２. １. １１.`）は款・項・目を1行に並べるので、
                # 款の枝で項の名称を消してから項の枝が持ち越そうとすると、
                # 消したばかりの None を引く（実測で項の命名率が 10.7% に落ちていた）。
                was = (kan, kou, moku, kan_name, kou_name, moku_name)
                for x, n, label in found:
                    label = label.strip()
                    # ⚠️ **継続ページの見出しはコードだけで名称を持たない。**
                    # 無条件に上書きすると、そのページ以降の事業が名称を失う。
                    if x < 30:
                        kan_name = label or (was[3] if was[0] == n else None)
                        kan, kou, moku = n, None, None
                        kou_name = moku_name = None
                    elif x < 48:
                        kou_name = label or (was[4] if was[1] == n else None)
                        kou, moku = n, None
                        moku_name = None
                    else:
                        moku_name = label or (was[5] if was[2] == n else None)
                        moku = n
                    # 折返しを受け取る先。**この行で名称が付いた階層だけ**開けておく。
                    label_open = ("kan" if x < 30 else "kou" if x < 48 else "moku") if label else None
                # 目の見出しには目の合計が並ぶ。**最初に出たものだけを採る** —
                # 継続ページでは同じ見出しが繰り返され、そこには金額が無いことも金額が
                # 並ぶこともあるが、合計は変わらない。
                if moku is not None and amount and not name:
                    moku_totals.setdefault((kan, kou, moku), int(amount.replace(",", "")))
                # ⚠️ **見出し行が同時に事業行でもある。** 継続ページの先頭では、文脈の見出し
                # （２. １. １.）とそのページ最初の事業が同じ行に並ぶ。ここで打ち切ると
                # ページごとに1事業ずつ落ちる（実測で 65 件、命名率が 87.5% → 94.8% に変わった）。
                # ⚠️ ここは `not (name and amount)` だけでよい。
                # 以前あった `len(found) >= 3 and not name` は前段に含まれる死んだ条件だった。
                if not (name and amount):
                    continue

            if amount:                       # 事業の開始行
                if pending:
                    rows.append(pending)
                pending = {"kan_code": kan, "kou_code": kou, "moku_code": moku,
                           "kan_name": kan_name, "kou_name": kou_name, "moku_name": moku_name,
                           "project_name": name, "amount_thousand_yen": int(amount.replace(",", ""))}
                name_open = True
            elif pending and name and name_open:   # 事業名の折返し
                pending["project_name"] += name
            elif pending and not name:
                # ⚠️ **名前は連続した行にしか続かない。** 名前の列が空の行が来たらそこで閉じる。
                # 閉じないと、次の事業の名前（金額行より前に始まることがある）を
                # 前の事業が吸い込み、**2つの事業名が繋がった1つの名前**として配布物に出る
                # （実測で「学校プール指導員配置学校ボランティア協力員」のような行が出ていた）。
                name_open = False
    if pending:
        rows.append(pending)
    return ([r for r in rows if r["kan_code"] and r["kou_code"] and r["moku_code"]], moku_totals)


def reconcile(rows: list[dict], moku_totals: dict) -> dict:
    """**抽出漏れの検査。** 目の合計と、その目に属する事業の合計を突き合わせる。

    ⚠️ **以前ここは合計を計算しているだけで、突合していなかった。**
    証跡に `verification: hierarchy-totals` と書きながら実際には何も確かめておらず、
    目の途中から全行落とす・金額を読み違える・別の目へ紐づける、のどれも検出できなかった。
    宣言はあるが誰も検査していない、というこのプロジェクトが繰り返し踏んでいる形そのもの。

    ⚠️ **復元一致より弱いことは変わらない。** PDF が印刷している合計と抽出の合計が
    両方とも同じように誤っていれば通る。強さの違いは証跡に書く。
    """
    by_moku: dict[tuple, int] = defaultdict(int)
    for r in rows:
        by_moku[(r["kan_code"], r["kou_code"], r["moku_code"])] += r["amount_thousand_yen"]

    # ⚠️ **突合が落ちた目からは名前を採らない。** 全体を止めるのでも黙って通すのでもなく、
    # 目ごとに合否を付けて下流へ渡す（パーサ設計の原則6: 捨てずに状態として残す）。
    # 「名前が付く事業と付かない事業の境界に理由がある」状態にするのが目的。
    ok = 0
    for r in rows:
        key = (r["kan_code"], r["kou_code"], r["moku_code"])
        printed = moku_totals.get(key)
        extracted = by_moku[key]
        # 目の見出しも事業も千円で印刷されるので、丸めの積み上がりを事業数まで許す
        allowed = max(1, sum(1 for x in rows
                             if (x["kan_code"], x["kou_code"], x["moku_code"]) == key))
        r["moku_reconciled"] = printed is not None and abs(printed - extracted) <= allowed
        ok += r["moku_reconciled"]

    bad = sorted({(r["kan_code"], r["kou_code"], r["moku_code"])
                  for r in rows if not r["moku_reconciled"]})
    return {
        "projects": len(rows),
        "projectsReconciled": ok,
        "moku": len(by_moku),
        "mokuHeadersFound": len(moku_totals),
        "mokuNotReconciled": len(bad),
        "totalThousandYen": sum(r["amount_thousand_yen"] for r in rows),
        "notReconciled": [{"moku": "-".join(str(k) for k in key),
                           "printedThousandYen": moku_totals.get(key),
                           "extractedThousandYen": by_moku[key]} for key in bad][:20],
    }


def ingest(key: str) -> None:
    spec = load_project_names()[key]
    code, year = key.split(":")
    got = http_get(spec["url"])
    if got.status != 200:
        raise RuntimeError(f"HTTP {got.status}: {spec['url']}")

    out_dir = OUT / f"jurisdiction={code}" / f"year={year}"
    prov_path = out_dir / "provenance.json"
    # ⚠️ **冪等にする。抽出の前に決める。** 原典の SHA-256 と抽出器の版が同じなら何もしない。
    # 書き直すと `fetched_at` だけが動いて作業ツリーが毎回汚れ、
    # 「再生成しても同じか」を見る CI の判定が意味を失う（CSV 側は既にこうしてある）。
    # 抽出は1本あたり数十秒かかるので、走らせる前に判定する。
    if prov_path.exists() and (out_dir / "data.parquet").exists():
        old = json.loads(prov_path.read_text())
        if old.get("sha256") == got.sha256 and old.get("extractor", "").endswith(f"@{EXTRACTOR_VERSION}"):
            print(f"skip  {key}  同じ原典・同じ抽出器の版で既に抽出済み")
            return

    # pdftotext がファイルを要求するので一時ファイルに落とす。**処理後に必ず消す。**
    import tempfile  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(got.body)
        tmp = pathlib.Path(f.name)
    try:
        columns = {k: (float(lo), float(hi)) for k, (lo, hi) in spec["columns"].items()}
        rows, moku_totals = extract(tmp, spec["first_page"], spec["last_page"], columns)
        # ⚠️ **行のまとめ方に結果が依存していないことを確かめる。**
        # 固定グリッドで丸めていた頃は、1つの視覚行が2つに割れて名前の先頭1文字が
        # 前の行へ落ちていた（2020年度の 528 行のうち 66 行が壊れていた）。
        # 金額は動かないので合計突合では検出できない。許容幅を変えて同じ名前が出るかで見る。
        alt, _ = extract(tmp, spec["first_page"], spec["last_page"], columns, tolerance=2.0)
    finally:
        tmp.unlink(missing_ok=True)      # **PDF は残さない**

    if not rows:
        raise RuntimeError(f"{key}: 事業を1件も抽出できなかった")
    summary = reconcile(rows, moku_totals)
    unstable = [a["project_name"] for a, b in zip(rows, alt, strict=False)
                if a["project_name"] != b["project_name"]]
    summary["nameStable"] = len(rows) == len(alt) and not unstable
    # ⚠️ **科目の名称は全行に付くはず。** 継続ページの持ち越しが壊れると静かに欠ける
    # （金額は動かないので合計突合では出ない）。欠けたら止める。
    for level in ("kan_name", "kou_name", "moku_name"):
        missing = sum(1 for r in rows if not r[level])
        summary[level] = len(rows) - missing
        if missing:
            raise RuntimeError(f"{key}: {level} が {missing}/{len(rows)} 行で欠けている。"
                               "継続ページの見出しから名称を持ち越せていない")
    summary["unstableNames"] = unstable[:10]
    if not summary["nameStable"]:
        raise RuntimeError(
            f"{key}: 行のまとめ方を変えると事業名が変わる（{len(unstable)} 件）。"
            f"抽出が行の境界に乗っている: {unstable[:5]}"
        )
    # ⚠️ **全部落ちたら書き出さない。** 一部が落ちるのは目ごとに印を付けて下流へ渡すが、
    # 1つも突合できないのはレイアウトを読み違えている合図なので止める。
    if summary["projectsReconciled"] == 0:
        raise RuntimeError(f"{key}: 目の合計と1件も突合できなかった。抽出器がレイアウトを読めていない")

    out_dir.mkdir(parents=True, exist_ok=True)

    import duckdb  # noqa: PLC0415

    con = duckdb.connect()
    con.execute("CREATE TABLE t (ordinal BIGINT, kan_code VARCHAR, kou_code VARCHAR, "
                "moku_code VARCHAR, kan_name VARCHAR, kou_name VARCHAR, moku_name VARCHAR, "
                "project_name VARCHAR, amount_thousand_yen BIGINT, "
                "moku_reconciled BOOLEAN)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(i, str(r["kan_code"]), str(r["kou_code"]), str(r["moku_code"]),
                      r["kan_name"], r["kou_name"], r["moku_name"],
                      r["project_name"], r["amount_thousand_yen"], r["moku_reconciled"])
                     for i, r in enumerate(rows)])
    con.execute(f"COPY (SELECT * FROM t ORDER BY ordinal) TO '{out_dir / 'data.parquet'}' "
                f"(FORMAT parquet, COMPRESSION zstd)")
    con.close()

    prov_path.write_text(json.dumps({
        "jurisdiction_code": code,
        "fiscal_year": int(year),
        "document_title": spec["document_title"],
        "request_url": got.url,
        "status": got.status,
        "bytes": len(got.body),
        "sha256": got.sha256,
        "fetched_at": got.fetched_at,
        "pages": [spec["first_page"], spec["last_page"]],
        "extractor": f"ingestion/budget/extract_projects.py@{EXTRACTOR_VERSION}",
        # ⚠️ **CSV の取り込みと保証の強さが違う。** 復元一致は成立しない。
        "verification": "hierarchy-totals + name-stability",
        "verification_note": "PDF のバイト列は保存していない（再配布の判断が別のため）。"
                             "無加工であることは検査できないので、階層の合計突合と、"
                             "dbt 側の原典 CSV との結合率で縛る",
        "roundtrip_verified": False,
        "extracted": summary,
        # ⚠️ **原文は置いていない。** raw_form でそれを機械可読にする（sources.py の枠と同じ語彙）。
        "raw_form": spec.get("raw_form", "extracted"),
        "redistribute": spec.get("redistribute", "review"),
        "redistribute_basis": spec.get("redistribute_basis", ""),
        "license_id": spec.get("license_id", "NOASSERTION"),
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"ok    {key}  {summary['projects']} 事業（突合 {summary['projectsReconciled']}）  "
          f"{summary['moku']} 目（突合できず {summary['mokuNotReconciled']}）  "
          f"sha256={got.sha256[:16]}…")


if __name__ == "__main__":
    keys = sys.argv[1:] or sorted(load_project_names())
    for k in keys:
        print(f"--- {k}")
        ingest(k)
