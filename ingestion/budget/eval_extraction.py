"""PDF 抽出器がどれだけ拾えているか（recall）を、正解のある団体で測る。

**これは各団体のデータを検証する機構ではない。抽出器を較正する場所である。**
正解（原典 CSV と突き合わせられる状態）が存在するのは 62 団体中 2 団体だけで、
残り 60 団体は PDF しか無く突き合わせる相手がいない。ここで測った数字は、
**正解の無い団体で同じコードを回したときの見積もり**として使う。

⚠️ **しきい値で落とす門にしない。** 60 団体で動かないものを門にすると、
通らない団体を足せなくなる。CI では回さない（観測を残すだけ）。

⚠️ **`dbt/tests/revenue_accounts_reconcile.sql` と目的が違う。**
あちらは PDF → CSV の一方向（抽出できた行が正しいか）で、配布物の安いチェック。
こちらは CSV → PDF の向きを足す — **原典にあって抽出できなかったものを数える**。
片方だけでは「1 目だけ抽出して 100% 一致」が満点に見える。

⚠️ **原典（`data/budget/raw/`）を読むだけでネットワークを叩かない**
（survey_structure と同じ約束）。取得と抽出は ingestion の仕事で、
ここが取得を兼ねると同じものを2経路で取ってきて食い違う余地を作る。
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter, defaultdict

import duckdb

from ingestion.budget.sources import all_sources, load_revenue_accounts, load_statements

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "budget" / "raw"
OBSERVATIONS = pathlib.Path(__file__).resolve().parent / "observations"

# 抽出物のキー。**歳入事項別明細は目までしか持たない**ので、節以下は比較の対象外。
KEY = ("kan_code", "kou_code", "moku_code")
# 原典 CSV 側の同じ3段。
SOURCE_KEY = ("款", "項", "目")
# 突合に使う金額の列。歳入事項別明細が載せているのは調定額で、収入額ではない。
SOURCE_AMOUNT = "調定累計(円)"
# 落とした目の一覧に添える節名称の件数。全部載せると読めないが、0 だと何を落としたか分からない。
SAMPLE_SETSU = 3


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def _general_fund(code: str) -> str:
    """一般会計の会計コード。**番号を決め打ちしない** — 団体ごとに違いうる。

    歳入事項別明細（PDF）が載せているのは一般会計だけなので、
    ここを取り違えると分母が別の会計になって recall が意味を失う。
    """
    con = _con()
    got = con.execute(
        f"select distinct 会計, 会計名称 from read_parquet("
        f"'{RAW}/jurisdiction={code}/year=*/phase=*/direction=revenue/data.parquet', "
        f"hive_partitioning=true)"
    ).fetchall()
    hit = [fund for fund, name in got if name == "一般会計"]
    if len(hit) != 1:
        raise SystemExit(f"{code}: 会計名称が「一般会計」の会計が {len(hit)} 件（{got}）")
    return hit[0]


def source_moku(code: str, fund: str) -> dict[int, dict[tuple, dict]]:
    """原典 CSV の目。**これが分母**。年度 → キー → 金額と節名称"""
    con = _con()
    cols = ", ".join(f'"{c}"' for c in SOURCE_KEY)
    rows = con.execute(
        f"select year, {cols}, sum(cast(\"{SOURCE_AMOUNT}\" as bigint)) as yen, "
        f"list(distinct 科目名称) as setsu, count(*) as source_rows "
        f"from read_parquet("
        f"'{RAW}/jurisdiction={code}/year=*/phase=*/direction=revenue/data.parquet', "
        f"hive_partitioning=true) where 会計 = '{fund}' group by all"
    ).fetchall()
    out: dict[int, dict[tuple, dict]] = defaultdict(dict)
    for year, kan, kou, moku, yen, setsu, source_rows in rows:
        out[year][(kan, kou, moku)] = {
            "yen": int(yen), "setsu": sorted(setsu), "sourceRows": source_rows,
        }
    return out


def extracted(code: str) -> dict[int, list[dict]]:
    """抽出物。年度 → 行。**行のまま持つ** — 重複キーは潰さず数える"""
    path = RAW / "revenue-accounts" / f"jurisdiction={code}"
    if not path.exists():
        return {}
    con = _con()
    rows = con.execute(
        f"select year, {', '.join(KEY)}, moku_name, choutei_yen, mode "
        f"from read_parquet('{path}/year=*/data.parquet', hive_partitioning=true)"
    ).fetchall()
    out: dict[int, list[dict]] = defaultdict(list)
    for year, kan, kou, moku, name, yen, mode in rows:
        out[year].append({"key": (kan, kou, moku), "name": name,
                          "yen": None if yen is None else int(yen), "mode": mode})
    return out


def evaluate_year(year: int, source: dict[tuple, dict], rows: list[dict]) -> dict:
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by_key[r["key"]].append(r)

    matched = {k: v for k, v in by_key.items() if k in source}
    spurious = {k: v for k, v in by_key.items() if k not in source}
    missed = {k: v for k, v in source.items() if k not in by_key}

    # 金額の一致は**キーが当たった目の中で**見る。重複キーはどれか1行が合えば一致とする
    # （重複そのものは duplicateKeys で別に数える。畳んで見えなくしない）。
    agreed = {k: v for k, v in matched.items()
              if any(r["yen"] == source[k]["yen"] for r in v)}

    total_yen = sum(v["yen"] for v in source.values())
    matched_yen = sum(source[k]["yen"] for k in matched)
    agreed_yen = sum(source[k]["yen"] for k in agreed)

    def ratio(part: int, whole: int) -> float | None:
        return None if whole == 0 else round(part / whole, 4)

    modes = Counter(r["mode"] for r in rows)
    return {
        "year": year,
        # 経路は宣言ではなく観測（抽出器がページごとに決める）。年度で1つとは限らない。
        "modes": dict(sorted(modes.items())),
        "sourceMoku": len(source),
        "sourceAmountYen": total_yen,
        "extractedRows": len(rows),
        "extractedDistinctKeys": len(by_key),
        # ⚠️ **抽出した行数を recall と呼ばない。** 原典に無いキーを抽出した行も
        # 行数には入る（実測: 2022 は 57 行のうち 7 行が原典に無いキー）。
        "recall": {
            "moku": len(matched), "ratio": ratio(len(matched), len(source)),
            "amountYen": matched_yen, "amountRatio": ratio(matched_yen, total_yen),
        },
        # キーが当たったうえで金額まで一致した割合。**原典に対する割合も併記する** —
        # 抽出できた中での割合だけを言うと、落としたものが分母から消える。
        "amountAgreement": {
            "moku": len(agreed),
            "ratioOfMatched": ratio(len(agreed), len(matched)),
            "ratioOfSource": ratio(len(agreed), len(source)),
            "amountYen": agreed_yen,
            "amountRatioOfSource": ratio(agreed_yen, total_yen),
        },
        "duplicateKeys": [
            {"key": list(k), "rows": len(v), "names": [r["name"] for r in v]}
            for k, v in sorted(by_key.items()) if len(v) > 1
        ],
        # ⚠️ **落としたものを見えなくしない**（原則6）。件数だけでは、どの領域が
        # 落ちているのか（＝正解の無い団体で何が起きるか）が読めない。
        "missedMoku": [
            {"key": list(k), "amountYen": v["yen"], "setsuNames": v["setsu"][:SAMPLE_SETSU]}
            for k, v in sorted(missed.items(), key=lambda kv: -kv[1]["yen"])
        ],
        # 原典に無いキーを作った行。誤読が「取りこぼし」ではなく「捏造」に出た分。
        "spuriousKeys": [
            {"key": list(k), "names": [r["name"] for r in v],
             "amountsYen": [r["yen"] for r in v]}
            for k, v in sorted(spurious.items())
        ],
    }


def by_mode(years: list[dict]) -> dict:
    """経路ごとの集計。**経路が割れた年度は足さない。**

    落とした目には経路が付かない（抽出物に現れないので mode 列が無い）。
    1年度が単一経路なら分母をその経路に帰属できるが、混在した年度では
    どの経路が落としたのか原理的に決まらない。畳むと数字が嘘になるので分けて残す。
    """
    single = [y for y in years if len(y["modes"]) == 1]
    mixed = [y["year"] for y in years if len(y["modes"]) > 1]
    out: dict[str, dict] = {}
    for y in single:
        mode = next(iter(y["modes"]))
        acc = out.setdefault(mode, {"years": [], "sourceMoku": 0, "sourceAmountYen": 0,
                                    "recallMoku": 0, "recallAmountYen": 0,
                                    "agreedMoku": 0, "agreedAmountYen": 0})
        acc["years"].append(y["year"])
        acc["sourceMoku"] += y["sourceMoku"]
        acc["sourceAmountYen"] += y["sourceAmountYen"]
        acc["recallMoku"] += y["recall"]["moku"]
        acc["recallAmountYen"] += y["recall"]["amountYen"]
        acc["agreedMoku"] += y["amountAgreement"]["moku"]
        acc["agreedAmountYen"] += y["amountAgreement"]["amountYen"]
    for acc in out.values():
        acc["recallRatio"] = round(acc["recallMoku"] / acc["sourceMoku"], 4)
        acc["recallAmountRatio"] = round(acc["recallAmountYen"] / acc["sourceAmountYen"], 4)
        acc["agreedRatioOfSource"] = round(acc["agreedMoku"] / acc["sourceMoku"], 4)
        acc["agreedAmountRatioOfSource"] = round(
            acc["agreedAmountYen"] / acc["sourceAmountYen"], 4)
    return {
        "note": "経路が単一の年度だけを足した。落とした目には経路が付かないので、"
                "経路が混在した年度は分母を帰属できない。",
        "byMode": out,
        "excludedMixedModeYears": mixed,
    }


def evaluate(code: str) -> dict:
    declared = sorted(k.split(":")[1] for k in load_revenue_accounts() if k.startswith(f"{code}:"))
    fund = _general_fund(code)
    source = source_moku(code, fund)
    rows = extracted(code)
    missing_output = [y for y in declared if int(y) not in rows]

    years = [evaluate_year(int(y), source.get(int(y), {}), rows.get(int(y), []))
             for y in declared if int(y) in rows]
    all_years = sorted(source)
    return {
        "jurisdictionCode": code,
        "scope": {
            "target": "歳入の科目名（決算資料の歳入事項別明細 PDF）",
            "fund": f"会計 {fund}（一般会計）のみ。**PDF が一般会計しか載せていない**",
            "level": "目（款・項・目の3段。節以下は PDF に無い）",
            "amountColumn": SOURCE_AMOUNT,
            "declaredYears": declared,
            "sourceYears": all_years,
            # ⚠️ **測れた範囲を明示する**（原則4）。原典に年度があっても取得元の宣言が
            # 無ければ測れない。狛江は市の決算ページが 2018〜2019 に存在しない。
            "yearsWithoutSource": [y for y in all_years if str(y) not in declared],
            "yearsDeclaredButNotExtracted": missing_output,
        },
        "byYear": years,
        "byModeAcrossYears": by_mode(years),
    }


def evaluate_statement(code: str) -> dict:
    """事項別明細書の抽出器を測る。**正解は資料が自分で印字している合計。**

    ⚠️ **`evaluate` とは分母が違う。** あちらは原典 CSV という外の正解と突き合わせるが、
    事項別明細書を原典とする団体には突き合わせる CSV が無い（それが PDF から起こす理由である）。
    使えるのは、様式が同じ数字を階層ごとに重複して印字しているという性質だけで、
    **同じ誤りが両側に入れば通る**ぶん外の正解より弱い。強さの違いを観測に書く。

    ⚠️ **取得の判定をここで作り直さない。** 抽出時の突合は
    `extract_statement.reconcile` が既に計算して証跡へ書いているので、それを読む。
    ここが足すのは、証跡が持たない**名称の欠け**（配布物の使い勝手に直結し、
    金額の突合では動かないので合計突合では検出できない）と、年度をまたいだ集約である。
    """
    con = _con()
    years: list[dict] = []
    for path in sorted(RAW.glob(f"jurisdiction={code}/**/provenance.json")):
        prov = json.loads(path.read_text())
        if "extract_statement" not in prov.get("extractor", ""):
            continue
        e = prov["extracted"]
        parquet = path.parent / "data.parquet"
        blank = con.execute(
            f"select count(*) filter (where 款名称 = '') , count(*) filter (where 項名称 = ''), "
            f"count(*) filter (where 目名称 = ''), count(*) "
            f"from read_parquet('{parquet}')"
        ).fetchone()
        years.append({
            "year": prov["fiscal_year"],
            "direction": prov["direction"],
            "pages": prov["pages"],
            "leaves": e["leaves"],
            "moku": e["moku"],
            "mokuHeadersFound": e["mokuHeadersFound"],
            "mokuNotReconciled": e["mokuNotReconciled"],
            "setsuColumnNotReconciled": e["setsuColumnNotReconciled"],
            "mokuWithoutExplanation": e["mokuWithoutExplanation"],
            # 説明欄の段ごとの合計。歳出は3段が同じ額を重複して印字しているので、
            # ここが割れていれば段の判定（金額の右端）を読み違えている
            "explanationLevelTotals": e["explanationLevelTotals"],
            "annotationsDropped": e["annotationsDropped"],
            "total": e["total"],
            # ⚠️ **名称の欠けは合計突合では動かない。** 継続頁の見出しから名称を
            # 持ち越せていないと静かに欠けるので、別に数える。
            "blankNames": {"kan": blank[0], "kou": blank[1], "moku": blank[2], "rows": blank[3]},
            "recall": {
                "mokuRatio": (e["moku"] / e["mokuHeadersFound"]) if e["mokuHeadersFound"] else 0.0,
                "reconciledRatio": (e["leavesReconciled"] / e["leaves"]) if e["leaves"] else 0.0,
            },
        })
    return {
        "jurisdictionCode": code,
        "scope": {
            "target": "事項別明細書（PDF）から起こした正本そのもの",
            "truth": "**資料が自分で印字している合計**（目の本年度予算額・節の区分欄）。"
                     "外の正解ではないので、同じ誤りが両側に入れば通る",
            "level": "説明欄の葉（歳出は 目→事業→節→細節、歳入は 目→節→説明）",
        },
        "byYear": years,
    }


def statement_targets() -> list[str]:
    return sorted({k.split(":")[0] for k in load_statements()})


def targets() -> tuple[list[str], list[str]]:
    """測れる団体と、測れない団体。**「無い」を黙って落とさない。**"""
    have = {k.split(":")[0] for k in load_revenue_accounts()}
    every = {s.jurisdiction_code for s in all_sources().values()}
    return sorted(have), sorted(every - have)


def _report_statements(codes: list[str]) -> None:
    # ⚠️ **書く前に作る。** 観測は commit しないので、clone 直後や観測を消した後は
    # このディレクトリが存在しない。呼ぶ側の mkdir に頼ると、呼ぶ順を変えた瞬間に落ちる。
    OBSERVATIONS.mkdir(parents=True, exist_ok=True)
    for code in codes:
        result = evaluate_statement(code)
        out = OBSERVATIONS / f"{code}-statement-recall.json"
        out.write_text(json.dumps({
            "note": "事項別明細書の抽出器を、**資料が自分で印字している合計**を正解として測った観測。"
                    "原典 CSV という外の正解が無い団体（62 団体中 59）で使える唯一の測り方で、"
                    "同じ誤りが両側に入れば通るぶん evaluate() の recall より弱い。",
            "generatedBy": "ingestion/budget/eval_extraction.py"
                           "（bun run eval:extraction [団体コード...]）",
            "reads": f"data/budget/raw/jurisdiction={code}/（抽出物と証跡）",
            **result,
        }, ensure_ascii=False, indent=2) + "\n")
        print(f"--- {code}  {out.relative_to(ROOT)}")
        print(f"{'年度':>6} {'方向':>12} {'葉':>7} {'目':>5} {'見出し':>6} "
              f"{'目突合外':>8} {'節列突合外':>10} {'説明無し目':>10} {'名称欠け':>8} {'注記落ち':>8}")
        for y in result["byYear"]:
            b = y["blankNames"]
            blank = b["kan"] + b["kou"] + b["moku"]
            print(f"{y['year']:>6} {y['direction']:>12} {y['leaves']:>7} {y['moku']:>5} "
                  f"{y['mokuHeadersFound']:>6} {y['mokuNotReconciled']:>8} "
                  f"{y['setsuColumnNotReconciled']:>10} {y['mokuWithoutExplanation']:>10} "
                  f"{blank:>8}{'  ⚠️' if blank else ''} {y['annotationsDropped']:>8}")
            # ⚠️ **段ごとの合計が割れていること自体は誤りではない。**
            # 昭島市の歳出のように段が完全な内訳になっている形では3段とも同じ額になるが、
            # 千代田区のように内訳の段が任意の形では、浅い段のほうが大きくなる。
            # 割当の正しさは目の突合が見ているので、ここは値を出すだけにする。
            print(f"       説明欄の段ごとの合計: {y['explanationLevelTotals']}")


if __name__ == "__main__":
    have, without = targets()
    statements = statement_targets()
    codes = sys.argv[1:] or have
    if not sys.argv[1:]:
        _report_statements(statements)
    else:
        _report_statements([c for c in codes if c in statements])
        codes = [c for c in codes if c not in statements]
    unknown = [c for c in codes if c not in have]
    if unknown:
        raise SystemExit(
            f"団体 {unknown} は sources.toml の [revenue_accounts] に取得元が無い。"
            f"測れる団体: {have}")

    OBSERVATIONS.mkdir(parents=True, exist_ok=True)
    for code in codes:
        result = evaluate(code)
        out = OBSERVATIONS / f"{code}-extraction-recall.json"
        out.write_text(json.dumps({
            "note": "PDF 抽出器の recall を、原典 CSV という正解のある団体で測った観測。"
                    "**抽出器の較正が目的**であって、団体ごとのデータ検証ではない。"
                    "しきい値で落とす門にしていない（60 団体で動かないものを門にすると"
                    "通らない団体を足せなくなる）。",
            "generatedBy": "ingestion/budget/eval_extraction.py"
                           "（bun run eval:extraction [団体コード...]）",
            "reads": f"data/budget/raw/jurisdiction={code}/（原典 CSV）と "
                     f"data/budget/raw/revenue-accounts/jurisdiction={code}/（抽出物）",
            "measurableJurisdictions": have,
            "jurisdictionsWithoutRevenueAccountSource": without,
            "notCovered": "歳出の事業名（extract_projects）は別の抽出器で、ここでは測っていない",
            **result,
        }, ensure_ascii=False, indent=2) + "\n")

        print(f"--- {code}  {out.relative_to(ROOT)}")
        print(f"{'年度':>6} {'経路':>10} {'原典の目':>8} {'抽出行':>7} {'recall':>14} "
              f"{'金額 recall':>13} {'金額一致':>14} {'一致 金額比':>12} {'原典に無い':>10}")
        for y in result["byYear"]:
            r, a = y["recall"], y["amountAgreement"]
            modes = "/".join(f"{m}:{n}" for m, n in y["modes"].items())
            # ⚠️ **原典に無いキーを表にも出す。** 取りこぼしは配布物から欠けるだけだが、
            # これは存在しない科目が正しそうな名前と金額を持って現れる。
            # 実測（2022）で款が 15→3・17→5 と巻き戻り、段の状態が壊れていた
            spurious = len(y["spuriousKeys"])
            print(f"{y['year']:>6} {modes:>10} {y['sourceMoku']:>8} {y['extractedRows']:>7} "
                  f"{r['moku']:>4} ({r['ratio']:>6.1%}) {r['amountRatio']:>12.1%} "
                  f"{a['moku']:>4} ({a['ratioOfSource']:>6.1%}) "
                  f"{a['amountRatioOfSource']:>11.1%} "
                  f"{spurious:>10}{'  ⚠️' if spurious else ''}")
        for mode, acc in result["byModeAcrossYears"]["byMode"].items():
            print(f"  経路 {mode}: 年度 {acc['years']}  recall {acc['recallRatio']:.1%} "
                  f"(金額 {acc['recallAmountRatio']:.1%})  "
                  f"金額一致 {acc['agreedRatioOfSource']:.1%} "
                  f"(金額 {acc['agreedAmountRatioOfSource']:.1%})")
        sc = result["scope"]
        if sc["yearsWithoutSource"]:
            print(f"  取得元が無く測れない年度: {sc['yearsWithoutSource']}")
    if without:
        print(f"歳入科目名の取得元が無く測れない団体: {without}")
