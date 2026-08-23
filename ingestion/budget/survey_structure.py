"""原典が何を持っているかを実測して `ingestion/budget/observations/` へ残す。

**AGENTS.md の主張の出所になる。** 「大事業に名称が無い」「中事業・小事業は全行 `0`」
「階層だけでは行が一意にならない」「款コードが法定の款番号と一致する」は
どれもこのスクリプトの出力が根拠で、要約ではなく数字を残す。

⚠️ **原典（`data/budget/raw/`）を読む。ネットワークを叩かない。**
取得は ingestion.budget.fetch の仕事で、そこが証跡（URL・SHA-256・取得時刻）を既に残している。
ここを取得込みにすると、同じものを2通りの経路で取ってきて食い違う余地を作る。

⚠️ **列の並びを手で持たない。** 正本は `dbt/dbt_project.yml` の vars で、
dbt のモデルも検査も配布物の descriptor もそこを見ている。
ここへ写すと、原典のスキーマが変わったとき**観測だけが古い列を測り続ける**。
出力は AGENTS.md が主張の根拠として指しているファイルなので、
そこだけ古いのは要約が嘘になるより悪い。

⚠️ **最初の1団体は宣言より先に調べることになる**（何を宣言すべきかがまだ分からない）。
その段階では手元で測ってよい。ここが受け持つのは、宣言した後に
「宣言どおりのものが原典に入っているか」を残し続けるほうである。
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter, defaultdict

import duckdb
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "budget" / "raw"
# ⚠️ **観測は commit しない**（原典・証跡・配布物だけを data/ へ置く方針）。
# スクリプトの隣に書き出し、主張に使うときは実測日を添える。
OBSERVATIONS = pathlib.Path(__file__).resolve().parent / "observations"
# 列の構造の正本。fdp/build.py と report/budget/build.ts も同じ場所を読む。
VARS = yaml.safe_load((ROOT / "dbt" / "dbt_project.yml").read_text())["vars"]

# 地方自治法施行規則別記の歳出款。**狛江市の原典はコードしか持たない**ので、
# コードがこの番号だと言えるかを裏づけるための対照表。ここが違えば COFOG がまるごとずれる。
STATUTORY_KAN = {
    1: "議会費", 2: "総務費", 3: "民生費", 4: "衛生費", 5: "労働費", 6: "農林水産業費",
    7: "商工費", 8: "土木費", 9: "消防費", 10: "教育費", 11: "公債費", 12: "諸支出金", 13: "予備費",
}

def levels_of(code: str, direction: str) -> list[str]:
    return VARS["budget_source_columns"][code][direction]


def extra_keys_of(code: str, direction: str) -> list[str]:
    return VARS["budget_extra_key_source_columns"][code][direction]


def primary_amount(code: str, direction: str) -> dict:
    """集計に使う段階の金額の宣言。決算書は1行に複数段階あるのでどれかを選ぶ必要がある"""
    hit = [a for a in VARS["budget_amounts"][code][direction] if a.get("primary")]
    if len(hit) != 1:
        raise SystemExit(f"{code}/{direction}: budget_amounts の primary が {len(hit)} 件")
    return hit[0]


def absent_marker(code: str) -> str:
    """その階層を持たない行のプレースホルダ。団体ごとに違いうる"""
    markers = VARS["budget_absent_level_markers"][code]
    if len(markers) != 1:
        raise SystemExit(f"{code}: プレースホルダが {len(markers)} 種類ある。1つを前提にしている")
    return str(markers[0])


def rows(code: str, direction: str) -> list[dict]:
    con = duckdb.connect()
    pattern = f"{RAW}/jurisdiction={code}/year=*/phase=*/direction={direction}/data.parquet"
    got = con.execute(f"select * from read_parquet('{pattern}', hive_partitioning=true)").fetchall()
    cols = [d[0] for d in con.description]
    return [dict(zip(cols, r, strict=True)) for r in got]


def survey(code: str, direction: str) -> dict:
    data = rows(code, direction)
    levels, extra = levels_of(code, direction), extra_keys_of(code, direction)
    absent = absent_marker(code)

    # その階層が実際に使われているか。列があることは使われていることを意味しない。
    used = {
        lv: {"rows": len(data), "nonPlaceholder": sum(1 for d in data if d[lv] != absent)}
        for lv in levels
    }
    # 兄弟間でコードが一意か。完全修飾のほうが多ければ、別の親の下で再利用されている。
    reuse = {}
    for i, lv in enumerate(levels):
        path = levels[: i + 1]
        reuse[lv] = {
            "distinctCodes": len({d[lv] for d in data}),
            "distinctPaths": len({tuple(d[p] for p in path) for d in data}),
            "maxCodeDigits": max(len(d[lv]) for d in data),
        }
    # 行の同一性。階層だけで足りるか、追加の列が要るか。
    # 一意性は**単一年度で見る**。全年度を混ぜると年度の違いだけで一意になってしまい、
    # 「階層だけで行が決まるか」という問いに答えられない。年度は原典の最新を採る。
    latest = max(d["year"] for d in data)
    scope = [d for d in data if d["year"] == latest]

    def distinct(cols: list[str]) -> int:
        return len({tuple(d[c] for c in cols) for d in scope})

    identity = {
        "scope": f"{latest}年度",
        "rows": len(scope),
        "byLevelsOnly": distinct(levels),
        "byLevelsAndExtra": distinct(levels + extra),
        "extraColumns": extra,
    }
    # 名称の列がどの階層に対応するか（年度ごとに見る。節の番号は2020年度改正で変わった）。
    # 対応の宣言は budget_label_columns にあり、そこが指す最下位の階層を見る。
    labels = VARS.get("budget_label_columns", {}).get(code, {}).get(direction, {})
    machine_levels = VARS["budget_levels"][code][direction]
    leaf_key = max(labels, key=machine_levels.index) if labels else None
    if leaf_key is None:
        return {
            "direction": direction, "rows": len(data),
            "years": sorted({d["year"] for d in data}),
            "levelUsage": used, "codeReuse": reuse, "rowIdentity": identity,
            "leafLabelColumn": None,
        }
    leaf = levels[machine_levels.index(leaf_key)]
    label_column = labels[leaf_key]
    by_year: dict[str, dict[str, set]] = defaultdict(dict)
    for d in data:
        by_year[d["year"]].setdefault(d[leaf], set()).add(d[label_column])
    name_map = {
        y: {"codes": len(m), "codesWithMultipleNames": sum(1 for v in m.values() if len(v) > 1)}
        for y, m in sorted(by_year.items())
    }
    return {
        "direction": direction,
        "rows": len(data),
        "years": sorted({d["year"] for d in data}),
        "columns": [c for c in data[0] if c not in ("source_row", "jurisdiction", "year", "phase", "direction")],
        "declaredLevels": levels,
        "levelUsage": used,
        "codeReuse": reuse,
        "rowIdentity": identity,
        "leafLabelColumn": {"level": leaf, "column": label_column, "byYear": name_map},
    }


def kan_evidence(code: str) -> dict:
    """款コードが法定の款番号だと言える根拠。**原典は名称を書いていない。**

    ⚠️ **裏づけであって証明ではない。** 原典が「款2は総務費」と書いているわけではないので、
    所属名称と節名称が款ごとに整合することを数字で出し、読んだ者が judge できる形にする。
    """
    data = rows(code, "expenditure")
    if not data:
        return {}
    latest = max(d["year"] for d in data)
    # 一般会計に絞る。特別会計は款の体系が別なので混ぜると対照にならない。
    funds = Counter(d["会計名称"] for d in data if d["year"] == latest)
    general = funds.most_common(1)[0][0]
    scope = [d for d in data if d["year"] == latest and d["会計名称"] == general]
    amount = primary_amount(code, "expenditure")["source"]

    ev = {}
    for kan, name in STATUTORY_KAN.items():
        rs = [d for d in scope if d["款"] == str(kan)]
        ev[str(kan)] = {
            "statutoryName": name,
            "rows": len(rs),
            "amountYen": sum(int(d[amount]) for d in rs),
            "topDepartments": [x for x, _ in Counter(d["所属名称"] for d in rs).most_common(3)],
            "topSetsuNames": [x for x, _ in Counter(d["科目名称"] for d in rs).most_common(4)],
        }
    return {
        "note": "款コードに対応する名称は原典に無い。地方自治法施行規則別記の歳出款の番号だと"
                "言えるかを、所属名称と節名称から裏づける。⚠️ 原典が明示しているわけではない",
        "scope": f"{latest}年度 {general}",
        "amountColumn": amount,
        "byKan": ev,
    }


def balance(code: str) -> list[dict]:
    """歳出と歳入の合計が年度・会計別に一致するか。**外部資料ではなく内部整合。**

    比べる金額と倍率は `budget_amounts` の primary から引く
    （歳入だけ単位が千円、という団体があるので決め打ちできない）。
    """
    spec = {d: primary_amount(code, d) for d in ("expenditure", "revenue")}
    data = {d: rows(code, d) for d in spec}
    out = []
    for year in sorted({d["year"] for d in data["expenditure"]}):
        for fund in sorted({d["会計名称"] for d in data["expenditure"] if d["year"] == year}):
            totals = {
                direction: sum(
                    int(d[spec[direction]["source"]]) * spec[direction]["multiplier"]
                    for d in data[direction] if d["year"] == year and d["会計名称"] == fund
                )
                for direction in spec
            }
            out.append({
                "year": year, "fund": fund,
                "expenditureYen": totals["expenditure"], "revenueYen": totals["revenue"],
                "differenceYen": totals["expenditure"] - totals["revenue"],
            })
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: python -m ingestion.budget.survey_structure <団体コード>\n"
                         f"宣言済み: {sorted(VARS['budget_levels'])}")
    code = sys.argv[1]
    if code not in VARS["budget_levels"]:
        raise SystemExit(f"団体 {code} は dbt_project.yml の budget_levels に宣言が無い")
    out = OBSERVATIONS / f"{code}-budget-structure.json"
    out.write_text(json.dumps({
        "note": "原典が何を持っているかの実測。**判定は列名ではなく中身で行う**"
                "（パーサ設計の原則3）。列があることは、その階層が使われていることも"
                "名称を持っていることも意味しない。",
        "generatedBy": "ingestion/budget/survey_structure.py（bun run survey:structure <団体コード>）",
        "reads": f"data/budget/raw/jurisdiction={code}/（取得の証跡は provenance.json）",
        "declarationSource": "dbt/dbt_project.yml の vars（列の構造と金額の正本）",
        "jurisdictionCode": code,
        "directions": [survey(code, d) for d in ("expenditure", "revenue")],
        "kanCodeEvidence": kan_evidence(code),
        "expenditureRevenueBalance": {
            "note": "歳出と歳入の合計の差。単位が違う場合は円へ揃えてから比べる"
                    "（狛江市は歳入の予算現額が千円単位なので円未満は原理的に合わない）。"
                    "**原典の内部整合であって、外部資料による裏づけではない。**",
            "byYearAndFund": balance(code),
        },
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"ok  {out.relative_to(ROOT)}")
