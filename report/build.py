"""ダッシュボードが読む報告を組み立てる。

**系統（どの段がどの段に依存するか、どの検査がどのノードを守るか）は
dbt の `manifest.json` から取る。手で書かない。**
以前は `topology.ts` が段・ノード・辺を宣言しており、パイプラインを変えても
図が変わらない状態を2度作った。系統はツールが持っている情報なので、そこから引く。

数値は core への問い合わせで作る。**集計はここ1箇所だけ**で行う
（画面側でも集計すると、同じ数字が2通りに計算されていずれ食い違う）。

判断・調査・宣言（Caveats、可搬性、年度調査）は実行結果から導けないので
`static.json` に手で書く。
"""

from __future__ import annotations

import json
import pathlib

import duckdb

from ingestion.sources import resolve

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "dbt" / "target"
WAREHOUSE = ROOT / "data" / "fudoki.duckdb"
STATIC = json.loads((pathlib.Path(__file__).parent / "static.json").read_text())

# 段。**dbt のディレクトリがそのまま段になる。** 名前も並びもここでしか宣言しない。
STAGES = [
    ("ingestion", "ingestion", "取得元から取り、無加工のまま Parquet で置く。取得 URL・status・SHA-256・取得時刻を添える",
     "解釈・整形・結合", False),
    ("staging", "staging", "原典と1対1。列名の付け替えと型付けだけ", "判断（分類・名寄せ・推定）。行を増減させること", False),
    ("core", "core", "判断が入る段。COFOG 写像、連結の消去", "取得", True),
    ("package", "package", "配布物へ。Fiscal Data Package の形にする", "判断", False),
]
STAGE_OF_KIND = {"source": "ingestion", "seed": "core"}


def stage_of(node: dict) -> str:
    """段はノードの置き場から決まる。宣言と実装がずれないのはこれが理由"""
    if node["resource_type"] in STAGE_OF_KIND:
        return STAGE_OF_KIND[node["resource_type"]]
    path = node.get("path", "")
    for sid, *_ in STAGES:
        if path.startswith(sid + "/"):
            return sid
    return "core"


def build_topology(manifest: dict, results: dict, con: duckdb.DuckDBPyConnection,
                   provenance: list[dict]) -> dict:
    """ノードと辺を dbt の DAG から導く"""
    nodes, edges = [], []
    all_nodes = {**manifest["nodes"], **manifest["sources"]}
    models = {k: v for k, v in all_nodes.items()
              if v["resource_type"] in ("model", "source", "seed")}

    for uid, n in models.items():
        stage = stage_of(n)
        if n["resource_type"] == "source":
            # 原典は DuckDB にテーブルとして存在しない（Parquet を直接読む）ので証跡から取る
            rows = sum(p["rows"] for p in provenance if p["direction"] == n["name"])
        else:
            try:
                rows = con.execute(f'select count(*) from "{n["name"]}"').fetchone()[0]
            except duckdb.Error:
                rows = None
        nodes.append({
            "id": uid,
            "label": n["name"],
            "kind": n["resource_type"],
            "stage": stage,
            "rows": rows,
            "description": (n.get("description") or "").strip(),
            "introducesJudgment": stage == "core",
            "artifact": (n.get("config") or {}).get("location"),
        })
        for dep in n.get("depends_on", {}).get("nodes", []):
            if dep in models:
                edges.append({"from": dep, "to": uid, "kind": "flow"})

    return {
        "stages": [{"id": s, "label": l, "responsibility": r, "excludes": x, "introducesJudgment": j}
                   for s, l, r, x, j in STAGES],
        "nodes": sorted(nodes, key=lambda n: ([s[0] for s in STAGES].index(n["stage"]), n["label"])),
        "edges": edges,
        "source": "dbt/target/manifest.json（手書きではない）",
    }


def build_checks(manifest: dict, results: dict) -> list[dict]:
    """検査とその紐づけを run_results.json から取る。

    **どの検査がどのノードを守っているかも dbt が知っている**（test の depends_on）。
    以前は `Check.binds` として手で書いており、書き忘れても誰も気づかなかった。
    """
    by_uid = {r["unique_id"]: r for r in results["results"]}
    out = []
    for uid, n in manifest["nodes"].items():
        if n["resource_type"] != "test":
            continue
        r = by_uid.get(uid)
        status = (r or {}).get("status", "未実行")
        failures = (r or {}).get("failures")
        out.append({
            "name": n["name"],
            "description": (n.get("description") or "").strip(),
            "binds": [d for d in n.get("depends_on", {}).get("nodes", [])],
            "ok": status == "pass",
            "severity": "warn" if status == "warn" else "error",
            "status": status,
            "failures": failures,
            "detail": (r or {}).get("message") or "",
        })
    return sorted(out, key=lambda c: (c["ok"], c["name"]))


def q(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def build_transform(con: duckdb.DuckDBPyConnection) -> dict:
    """COFOG の判断。**ここが fudoki が自治体の言っていないことを付け加えた唯一の場所**なので、
    何をどこへ割り当て、なぜそう決めたかを根拠まで出す。

    ⚠️ 分類不能の割合の低さは合否に使わない。成立範囲を正直に調べるのが目的で、
    割合を目標にすると分類不能を減らす方向へ判断が歪む。
    """
    rules = q(con, """select count(*) as "n",
                      count(*) filter (where coalesce(applies_to, '') = '') as "shared" from cofog_rules""")[0]
    return {
        "cofogVersion": "COFOG 1999",
        "cofogSource": {"name": "UNSD Classification of the Functions of Government (COFOG)",
                        "url": "https://unstats.un.org/unsd/classifications/Family/Detail/4"},
        "ruleCount": rules["n"],
        "ruleScope": {"shared": rules["shared"], "jurisdictionSpecific": rules["n"] - rules["shared"]},
        "byState": q(con, """
            select c.cofog_status "status", c.cofog_division "division", c.cofog_consolidation "consolidation",
                   count(*) "count", sum(s.source_amount) * 1000 "sum"
            from core_budget_cofog c join stg_132047__expenditure s using (source_row)
            group by all order by sum desc"""),
        "byKan": q(con, """
            select s.fund_source "fund", s.kan_source "kan", c.cofog_division "division", c.cofog_status "status",
                   c.cofog_decided_at_level "decidedAtLevel", c.cofog_rule_id "ruleId",
                   sum(s.source_amount) * 1000 "sum", any_value(r.basis) "basis"
            from core_budget_cofog c join stg_132047__expenditure s using (source_row)
            left join cofog_rules r on r.rule_id = c.cofog_rule_id
            -- **規則ごとに分ける。** 併合すると basis が合計に対応しなくなる
            -- （国民健康保険への繰出と後期高齢者医療への繰出が1行に潰れ、
            -- 片方の根拠だけが両方の金額に付いた状態になっていた）。
            group by 1, 2, 3, 4, 5, 6 order by sum desc"""),
        "byLevel": q(con, """
            select c.cofog_decided_at_level "level", count(*) "count", sum(s.source_amount) * 1000 "sum"
            from core_budget_cofog c join stg_132047__expenditure s using (source_row)
            group by 1 order by sum desc"""),
        "notAssigned": q(con, """
            select c.cofog_status "status", s.fund_source "fund", s.kan_source "kan",
                   c.cofog_rule_id "ruleId", sum(s.source_amount) * 1000 "sum", any_value(r.basis) "basis"
            from core_budget_cofog c join stg_132047__expenditure s using (source_row)
            left join cofog_rules r on r.rule_id = c.cofog_rule_id
            where c.cofog_status <> 'assigned' group by 1, 2, 3, 4 order by sum desc"""),
        "consolidationPairs": q(con, """
            with paid as (
                select e.fund_label "frm", c.cofog_counterpart_fund "it", sum(e.source_amount) * 1000 "amt"
                from core_budget_cofog c join stg_132047__expenditure e using (source_row)
                where c.cofog_consolidation = 'eliminated' group by 1, 2),
            got as (
                select c.cofog_counterpart_fund "frm", r.fund_label "it",
                       sum(r.source_amount) * 1000 "amt", count(*) "cnt"
                from core_revenue_consolidation c join stg_132047__revenue r using (source_row)
                where c.cofog_consolidation = 'eliminated' group by 1, 2)
            select p.frm "from", p.it "to", p.amt "eliminated", g.amt "counterpart",
                   g.cnt "counterpartCount", p.amt = g.amt "ok"
            from paid p join got g on p.frm = g.frm and p.it = g.it order by eliminated desc"""),
        "consolidationScope": "三鷹市の全会計（本パッケージ収録分。下水道事業会計を除く）",
    }


def build_levels(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """階層ごとのコードの異なり数と完全修飾の異なり数。

    完全修飾のほうが大きければ、**同じコードが別の親の下で再利用されている**。
    識別子をコードのパスで作れない根拠がこれ。
    """
    out = []
    for direction, levels in [
        ("expenditure", [("fund", "会計"), ("kan", "款"), ("kou", "項"), ("moku", "目"),
                         ("jikou", "事項"), ("setsu", "節"), ("saisaisetsu", "細々節")]),
        ("revenue", [("fund", "会計"), ("kan", "款"), ("kou", "項"), ("moku", "目"),
                     ("setsu", "節"), ("saisetsu", "細節"), ("saisaisetsu", "細々節")]),
    ]:
        items = []
        for i, (lv, label) in enumerate(levels):
            path = " || ".join(f"{p}_source" for p, _ in levels[: i + 1])
            r = q(con, f"""select count(distinct {lv}_code) "codes", count(distinct {path}) "paths"
                           from stg_132047__{direction}""")[0]
            items.append({"sourceColumn": label, "distinctCodes": r["codes"], "distinctPaths": r["paths"],
                          "codeReusedUnderDifferentParents": r["paths"] > r["codes"]})
        out.append({"direction": direction, "items": items})
    return out


def build(code: str = "132047") -> dict:
    manifest = json.loads((TARGET / "manifest.json").read_text())
    results = json.loads((TARGET / "run_results.json").read_text())
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        src = resolve(f"{code}:2024")
        provenance = [json.loads(p.read_text())
                      for p in sorted((ROOT / "data" / "provenance").glob(f"{code}-*-*.json"))]
        checks = build_checks(manifest, results)
        report = {
            "meta": {
                "jurisdictionCode": code,
                "jurisdictionName": src.jurisdiction_name,
                "fiscalYears": sorted({p["fiscal_year"] for p in provenance}),
                "phase": {"id": src.phase_id, "label": src.phase_label},
                "license": {"id": src.license_id, "url": "https://creativecommons.org/licenses/by/4.0/"},
                "attribution": src.attribution,
                "landingPage": src.landing_page,
                # 実行時刻ではなく原典の取得時刻。回すたびに差分が出ないようにする。
                "generatedAt": max(p["fetched_at"] for p in provenance),
            },
            "summary": {
                "total": len(checks),
                "passed": sum(1 for c in checks if c["ok"]),
                "failed": sum(1 for c in checks if not c["ok"] and c["severity"] == "error"),
                "warned": sum(1 for c in checks if c["status"] == "warn"),
            },
            "topology": build_topology(manifest, results, con, provenance),
            "ingestion": provenance,
            "levels": build_levels(con),
            "transform": build_transform(con),
            "checks": checks,
            **{k: v for k, v in STATIC.items() if not k.startswith("_")},
        }
    finally:
        con.close()
    return report


def columnar(con: duckdb.DuckDBPyConnection, csv_path: pathlib.Path) -> dict:
    """明細。**配布する CSV そのものを読む。**

    DuckDB のテーブル経由にすると、画面が見ているものと配られるものがずれうる。
    列指向で運ぶ（行ごとにキーを繰り返すとファイルの大半が列名になる）。
    """
    cur = con.execute("select * from read_csv(?, header = true, all_varchar = true)", [str(csv_path)])
    cols = [d[0] for d in cur.description]
    return {"columns": cols, "rows": [[("" if v is None else str(v)) for v in r] for r in cur.fetchall()]}


if __name__ == "__main__":
    out_dir = ROOT / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build()
    (out_dir / "132047.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        bundle = {
            "code": "132047",
            "report": report,
            "expenditure": columnar(con, ROOT / "data/packages/132047/expenditure.csv"),
            "revenue": columnar(con, ROOT / "data/packages/132047/revenue.csv"),
            "cofog": columnar(con, ROOT / "data/packages/derived/cofog.csv"),
        }
    finally:
        con.close()
    (ROOT / "web" / "public" / "pipeline.json").write_text(json.dumps(bundle, ensure_ascii=False) + "\n")
    s = report["summary"]
    print(f"ok  検査 {s['passed']}/{s['total']}（警告 {s['warned']}）  "
          f"ノード {len(report['topology']['nodes'])}  辺 {len(report['topology']['edges'])}")
