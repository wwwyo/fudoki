"""dbt の出力を Fiscal Data Package として配れる形にする。

**データは dbt が既に書いている**（`materialized: external`）。
ここが足すのは datapackage.json だけ、つまり**列の意味づけと出所**である。

列の ColumnType は `field_types.json` の宣言から引く。
未宣言の列があれば落とす（意味づけの無い列を配らないため）。
仕様が「正準」と呼ぶ taxonomy の URL は 404 なので、宣言を自分で持つのが既定の運用。
"""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib
from datetime import UTC, datetime

from ingestion.sources import load_sources

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "data" / "packages"
PROVENANCE = ROOT / "data" / "provenance"
TYPES = json.loads((pathlib.Path(__file__).parent / "field_types.json").read_text())


def header_of(path: pathlib.Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as f:
        return next(csv.reader(f))


def schema_for(path: pathlib.Path, primary_key: list[str]) -> dict:
    fields = []
    for name in header_of(path):
        spec = TYPES["fields"].get(name)
        if spec is None:
            raise RuntimeError(
                f"{path.name} の列「{name}」に ColumnType の宣言が無い。"
                f"package/field_types.json に定義を足すこと"
            )
        fields.append(spec)
    return {"fields": fields, "primaryKey": primary_key}


def resource(path: pathlib.Path, name: str, title: str, description: str, primary_key: list[str]) -> dict:
    body = path.read_bytes()
    return {
        "name": name,
        "path": path.name,
        "profile": "tabular-data-resource",
        "title": title,
        "description": description,
        "format": "csv",
        "mediatype": "text/csv",
        "encoding": "utf-8",
        "bytes": len(body),
        "hash": "sha256:" + hashlib.sha256(body).hexdigest(),
        "dialect": {"delimiter": ",", "header": True},
        "schema": schema_for(path, primary_key),
    }


def base(name: str, title: str, description: str) -> dict:
    return {
        "profile": "tabular-data-package",
        "name": name,
        "title": title,
        "description": description,
        "version": "0.1.0",
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "countryCode": "JP",
        "columnTypes": TYPES["columnTypes"],
        "fudoki": TYPES["fudoki"],
    }


def build_jurisdiction(code: str) -> None:
    """正本。**団体ごと・全年度で1パッケージ。** 判断を含まない。"""
    d = PACKAGES / code
    srcs = [s for s in load_sources().values() if s.jurisdiction_code == code]
    if not srcs:
        raise RuntimeError(f"団体 {code} の取得元が sources.toml に無い")
    years = sorted(s.fiscal_year for s in srcs)

    pkg = base(
        f"fudoki-budget-{code}",
        f"{srcs[0].jurisdiction_name} 予算（事業単位）",
        "自治体が公開した予算データを Fiscal Data Package の形にしたもの。"
        "**fudoki の判断は含まない**（分類・名寄せ・推定を一切していない）。"
        "COFOG の割当は派生パッケージ tokyo/ にあり、budget_line_id で join する。"
        "原典そのものは data/raw/ に Parquet で入っている。",
    )
    pkg["fiscalPeriod"] = {"start": f"{years[0]}-04-01", "end": f"{years[-1] + 1}-03-31"}
    pkg["licenses"] = [{"name": srcs[0].license_id, "path": "https://creativecommons.org/licenses/by/4.0/"}]
    pkg["attribution"] = srcs[0].attribution
    pkg["sources"] = [{"title": s.attribution, "path": s.landing_page} for s in srcs]
    # 全行同じ値なのでリソースの列から外し、ここに持たせた定数。
    pkg["constants"] = {
        "jurisdictionCode": code,
        "jurisdictionName": srcs[0].jurisdiction_name,
        "phase": {"id": srcs[0].phase_id, "label": srcs[0].phase_label},
        "currency": "JPY",
        "sourceAmountUnit": {"label": "千円", "multiplier": 1000},
    }
    pkg["provenance"] = [
        json.loads(p.read_text()) for p in sorted(PROVENANCE.glob(f"{code}-*-*.json"))
    ]
    pkg["resources"] = [
        resource(d / "expenditure.csv", "expenditure", "歳出", "原典1行が1行。判断を含まない", ["budget_line_id"]),
        resource(d / "revenue.csv", "revenue", "歳入", "原典1行が1行。判断を含まない", ["budget_line_id"]),
    ]
    (d / "datapackage.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n")
    print(f"ok  {code}  {len(pkg['resources'])} リソース  {sum(r['bytes'] for r in pkg['resources']):,} バイト")


def build_derived() -> None:
    """派生。**東京全体で1パッケージ。** ここから先は fudoki の判断。"""
    d = PACKAGES / "tokyo"
    pkg = base(
        "fudoki-budget-tokyo-cofog",
        "東京都区市町村 予算の COFOG 割当（派生）",
        "**fudoki の判断**。自治体が言っていないことを付け加えている。"
        "正本とは budget_line_id で join する。"
        "根拠は cofog_rules に規則として出してあり、cofog_rule_id で引ける。"
        "分類不能の割合の低さは品質の指標ではない（成立範囲を正直に調べるのが目的）。",
    )
    pkg["resources"] = [
        resource(d / "cofog.csv", "cofog", "COFOG の割当",
                 "識別子と判断だけ。正本の列を複製しない", ["budget_line_id"]),
        resource(d / "cofog_rules.csv", "cofog_rules", "割り当て規則",
                 "判断の中身そのもの。35行読めば何をどう決めたか確かめられる", ["rule_id"]),
    ]
    (d / "datapackage.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n")
    print(f"ok  tokyo  {len(pkg['resources'])} リソース  {sum(r['bytes'] for r in pkg['resources']):,} バイト")


if __name__ == "__main__":
    build_jurisdiction("132047")
    build_derived()
