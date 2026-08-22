"""狛江市の原典が何を持っているかを実測して `data/budget/observations/` へ残す。

**AGENTS.md の主張の出所になる。** 「大事業に名称が無い」「中事業・小事業は全行 `0`」
「階層だけでは行が一意にならない」「款コードが法定の款番号と一致する」は
どれもこのスクリプトの出力が根拠で、要約ではなく数字を残す。

⚠️ **原典（`data/budget/raw/`）を読む。ネットワークを叩かない。**
取得は ingestion.budget.fetch の仕事で、そこが証跡（URL・SHA-256・取得時刻）を既に残している。
ここを取得込みにすると、同じものを2通りの経路で取ってきて食い違う余地を作る。
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter, defaultdict

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "budget" / "raw" / "jurisdiction=132195"
OUT = ROOT / "data" / "budget" / "observations" / "komae-budget-structure.json"

# 地方自治法施行規則別記の歳出款。**狛江市の原典はコードしか持たない**ので、
# コードがこの番号だと言えるかを裏づけるための対照表。ここが違えば COFOG がまるごとずれる。
STATUTORY_KAN = {
    1: "議会費", 2: "総務費", 3: "民生費", 4: "衛生費", 5: "労働費", 6: "農林水産業費",
    7: "商工費", 8: "土木費", 9: "消防費", 10: "教育費", 11: "公債費", 12: "諸支出金", 13: "予備費",
}

LEVELS = {
    "expenditure": ["会計", "款", "項", "目", "大事業", "中事業", "小事業", "節", "細節", "細々節"],
    "revenue": ["会計", "款", "項", "目", "節", "細節", "細々節"],
}
EXTRA_KEYS = {"expenditure": ["所属", "予算区分"], "revenue": ["所属コード", "予算区分"]}


def rows(direction: str) -> list[dict]:
    con = duckdb.connect()
    pattern = f"{RAW}/year=*/phase=*/direction={direction}/data.parquet"
    got = con.execute(f"select * from read_parquet('{pattern}', hive_partitioning=true)").fetchall()
    cols = [d[0] for d in con.description]
    return [dict(zip(cols, r, strict=True)) for r in got]


def survey(direction: str) -> dict:
    data = rows(direction)
    levels, extra = LEVELS[direction], EXTRA_KEYS[direction]

    # その階層が実際に使われているか。列があることは使われていることを意味しない。
    used = {
        lv: {"rows": len(data), "nonPlaceholder": sum(1 for d in data if d[lv] != "0")}
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
    def distinct(cols: list[str]) -> int:
        return len({tuple(d[c] for c in cols) for d in data if d["年度"] == "2023"})

    y2023 = [d for d in data if d["年度"] == "2023"]
    identity = {
        "scope": "2023年度",
        "rows": len(y2023),
        "byLevelsOnly": distinct(levels),
        "byLevelsAndExtra": distinct(levels + extra),
        "extraColumns": extra,
    }
    # 名称の列がどの階層に対応するか（年度ごとに見る。節の番号は2020年度改正で変わった）。
    leaf = "節" if direction == "expenditure" else "細節"
    by_year: dict[str, dict[str, int]] = defaultdict(dict)
    for d in data:
        by_year[d["年度"]].setdefault(d[leaf], set()).add(d["科目名称"])  # type: ignore[arg-type]
    name_map = {
        y: {"codes": len(m), "codesWithMultipleNames": sum(1 for v in m.values() if len(v) > 1)}
        for y, m in sorted(by_year.items())
    }
    return {
        "direction": direction,
        "rows": len(data),
        "years": sorted({d["年度"] for d in data}),
        "columns": [c for c in data[0] if c not in ("source_row", "jurisdiction", "year", "phase", "direction")],
        "levelUsage": used,
        "codeReuse": reuse,
        "rowIdentity": identity,
        "leafLabelColumn": {"level": leaf, "column": "科目名称", "byYear": name_map},
        "funds": {
            y: sorted({d["会計名称"] for d in data if d["年度"] == y})
            for y in sorted({d["年度"] for d in data})
        },
    }


def kan_evidence() -> dict:
    """款コードが法定の款番号だと言える根拠。**原典は名称を書いていない。**"""
    data = [d for d in rows("expenditure") if d["会計"] == "1" and d["年度"] == "2023"]
    ev = {}
    for code, name in STATUTORY_KAN.items():
        rs = [d for d in data if d["款"] == str(code)]
        ev[str(code)] = {
            "statutoryName": name,
            "rows": len(rs),
            "amountYen": sum(int(d["予算計(円)"]) for d in rs),
            "topDepartments": [x for x, _ in Counter(d["所属名称"] for d in rs).most_common(3)],
            "topSetsuNames": [x for x, _ in Counter(d["科目名称"] for d in rs).most_common(4)],
        }
    return {
        "note": "款コードに対応する名称は原典に無い。地方自治法施行規則別記の歳出款の番号だと"
                "言えるかを、所属名称と節名称から裏づける。⚠️ 原典が明示しているわけではない",
        "scope": "2023年度 一般会計",
        "byKan": ev,
    }


def balance() -> list[dict]:
    """歳出の予算計と歳入の予算現額が年度・会計別に一致するか。**外部資料ではなく内部整合。**"""
    e, r = rows("expenditure"), rows("revenue")
    out = []
    for year in sorted({d["年度"] for d in e}):
        for fund in sorted({d["会計名称"] for d in e if d["年度"] == year}):
            paid = sum(int(d["予算計(円)"]) for d in e if d["年度"] == year and d["会計名称"] == fund)
            got = sum(int(d["予算現額(千円)"]) * 1000 for d in r if d["年度"] == year and d["会計名称"] == fund)
            out.append({"year": year, "fund": fund, "expenditureYen": paid,
                        "revenueYen": got, "differenceYen": paid - got})
    return out


if __name__ == "__main__":
    OUT.write_text(json.dumps({
        "note": "狛江市の原典が何を持っているかの実測。**判定は列名ではなく中身で行う**"
                "（パーサ設計の原則3）。カタログの列構成には大事業・中事業・小事業が並ぶが、"
                "実際に使われているのは大事業だけで、名称の列は存在しない。",
        "generatedBy": "ingestion/budget/survey_komae.py（bun run survey:komae）",
        "reads": "data/budget/raw/jurisdiction=132195/（取得の証跡は provenance.json）",
        "directions": [survey(d) for d in ("expenditure", "revenue")],
        "kanCodeEvidence": kan_evidence(),
        "expenditureRevenueBalance": {
            "note": "歳出の予算計と歳入の予算現額の差。歳入は千円単位なので円未満は原理的に合わない。"
                    "**原典の内部整合であって、外部資料による裏づけではない。**",
            "byYearAndFund": balance(),
        },
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"ok  {OUT.relative_to(ROOT)}")
