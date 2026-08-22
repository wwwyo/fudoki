"""dbt の出力を Fiscal Data Package として配れる形にする。

（配布物そのものは data/budget/packages/ にある。ここはそれを組み立てる側）

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

import yaml

from ingestion.budget.sources import load_sources

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "data" / "budget" / "packages"
RAW = ROOT / "data" / "budget" / "raw"
TYPES = json.loads((pathlib.Path(__file__).parent / "field_types.json").read_text())
# ⚠️ **列の構造と金額の宣言の正本は `dbt/dbt_project.yml` の vars。**
# ここへ写すと、モデルを直したのに descriptor が古い前提のまま出る
# （このプロジェクトが繰り返し踏んでいる「宣言はあるが誰も検査していない」と同じ形）。
DBT_VARS = yaml.safe_load((ROOT / "dbt" / "dbt_project.yml").read_text())["vars"]
# FDP の ColumnType 一覧。**仕様が「正準」と宣言する URL は 404** なので、
# 仕様の原文（Markdown）から起こして持っている（scripts/fetch-fdp-taxonomy.ts）。
# 「止まったら自分で維持する」が保険ではなく既定の運用だという方針の実例。
TAXONOMY = json.loads((pathlib.Path(__file__).parent / "budget-taxonomy.json").read_text())
STANDARD_COLUMN_TYPES = {c["name"] for c in TAXONOMY["columnTypes"]}
# FDP に無い概念のために自作したもの。**宣言から引く**（ハードコードすると
# 宣言と食い違い、自作した覚えのない名前が通ってしまう）。
# 自作は最小限に留める — 標準に載ること自体が相互運用性の主張なので、
# 増やすほど主張が弱くなる。
DECLARED_CUSTOM = {c["name"] for c in TYPES["columnTypes"][1]}


def header_of(body: bytes) -> list[str]:
    """既に読んだバイト列からヘッダを切り出す。同じファイルを2回開かない"""
    first = body.split(b"\n", 1)[0].decode("utf-8")
    return next(csv.reader([first]))


def schema_for(path: pathlib.Path, body: bytes, primary_key: list[str]) -> dict:
    """列に意味づけを与える。**宣言の無い列は配らない。**"""
    fields = []
    for name in header_of(body):
        spec = TYPES["fields"].get(name)
        if spec is None:
            raise RuntimeError(
                f"{path.name} の列「{name}」に ColumnType の宣言が無い。"
                f"fdp/field_types.json に定義を足すこと"
            )
        fields.append(spec)

    # Table Schema への適合。型が無い列や主キーに無い列があれば配らない。
    for f in fields:
        if "type" not in f:
            raise RuntimeError(f"{path.name} の列「{f['name']}」に type が無い（Table Schema 違反）")
    missing = [k for k in primary_key if k not in {f["name"] for f in fields}]
    if missing:
        raise RuntimeError(f"{path.name} の primaryKey {missing} が列に無い（Table Schema 違反）")

    # ColumnType への適合。標準の語彙にも自作の宣言にも無いものは、意味が誰にも伝わらない。
    for f in fields:
        ct = f.get("columnType")
        if ct is None or ct in STANDARD_COLUMN_TYPES or ct in DECLARED_CUSTOM:
            continue
        raise RuntimeError(
            f"{path.name} の列「{f['name']}」の columnType「{ct}」が "
            f"Budget Standard Taxonomy にも自作の宣言にも無い"
        )
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
        "schema": schema_for(path, body, primary_key),
    }


def latest_fetch(pattern: str = "**/provenance.json") -> str:
    """収録した原典のうち最も新しい取得時刻。パッケージの版がいつ時点かを表す。

    ⚠️ **団体ごとのパッケージでは、その団体の証跡だけを見る。**
    全体の最大を入れると、別の団体を取り直しただけで無関係なパッケージの
    `created` が動き、中身が同じなのに差分が出る（実際に三鷹市でそうなった）。
    """
    stamps = [json.loads(p.read_text())["fetched_at"] for p in RAW.glob(pattern)]
    if not stamps:
        raise RuntimeError(f"証跡が1つも無い（{pattern}）。先に ingestion を回すこと")
    return max(stamps)


def base(name: str, title: str, description: str, created: str) -> dict:
    return {
        "profile": "tabular-data-package",
        "name": name,
        "title": title,
        "description": description,
        "version": "0.1.0",
        # 生成した時刻ではなく**原典を取得した時刻**を入れる。
        # 実行した瞬間を入れると、中身が同じでも回すたびに差分が出る。
        # 意味としても「いつ時点の原典から作られたか」のほうが利用者に要る。
        "created": created,
        "countryCode": "JP",
        "columnTypes": TYPES["columnTypes"],
        "fudoki": TYPES["fudoki"],
    }


def amounts_of(code: str, direction: str) -> list[dict]:
    """そのリソースが持つ金額の宣言（段階・単位・倍率）。

    **正本は `dbt/dbt_project.yml` の `budget_amounts`。** ここへ写すと、
    モデルの倍率や段階を直したのに descriptor が古い前提のまま出る。
    宣言どおりに書けているかは `verify_against_csv` が配布物そのものを見て確かめる。
    """
    return DBT_VARS["budget_amounts"][code][direction]


def verify_against_csv(path: pathlib.Path, amounts: list[dict]) -> None:
    """宣言と配布物が食い違っていないか。**descriptor だけ正しい状態を作らない。**

    ⚠️ ヘッダは `DictReader.fieldnames` から取る。**同じファイルを読み直さない**
    （`header_of` の docstring が言っている不変条件を、呼び出し側が破っていた）。
    """
    multi = len(amounts) > 1
    with path.open(encoding="utf-8", newline="") as f:
        rows = csv.DictReader(f)
        header = rows.fieldnames or []
        if "phase_id" not in header:
            raise RuntimeError(f"{path.name}: phase_id の列が無い")
        if multi and "source_amount_unit" not in header:
            raise RuntimeError(
                f"{path.name}: 予算段階が {len(amounts)} 種類あるのに source_amount_unit の列が無い"
            )
        seen: set[tuple[str, str]] = set()
        for r in rows:
            unit = r.get("source_amount_unit", amounts[0]["unit"])
            seen.add((r["phase_id"], unit))
            src, val = int(r["source_amount"]), int(r["value"])
            expected = next((a["multiplier"] for a in amounts if a["phase"] == r["phase_id"]), None)
            if expected is None:
                raise RuntimeError(f"{path.name}: 宣言に無い予算段階「{r['phase_id']}」が配布物にある")
            if val != src * expected:
                raise RuntimeError(f"{path.name}: value {val} が source_amount {src} × {expected} と違う")
    declared = {(a["phase"], a["unit"]) for a in amounts}
    if seen != declared:
        raise RuntimeError(
            f"{path.name}: 配布物の (段階, 単位) {sorted(seen)} が宣言 {sorted(declared)} と違う"
        )


def build_jurisdiction(code: str) -> None:
    """正本。**団体ごと・全年度で1パッケージ。** 判断を含まない。"""
    d = PACKAGES / code
    srcs = [s for s in load_sources().values() if s.jurisdiction_code == code]
    if not srcs:
        raise RuntimeError(f"団体 {code} の取得元が sources.toml に無い")
    years = sorted(s.fiscal_year for s in srcs)

    # 原典の文書そのものの種類（当初予算 / 決算）。**行が持つ予算段階とは別の軸。**
    # 「予算（事業単位）」と決め打ちすると、決算書から作った狛江市のパッケージが嘘になる。
    document = sorted({s.phase_label for s in srcs})
    resources = [(d / "expenditure.csv", "expenditure", "歳出"), (d / "revenue.csv", "revenue", "歳入")]
    amounts = {name: amounts_of(code, name) for _, name, _ in resources}
    phases = sorted({(a["phase"], a["phase_label"]) for v in amounts.values() for a in v})
    units = sorted({(a["unit"], a["multiplier"]) for v in amounts.values() for a in v})

    pkg = base(
        f"fudoki-budget-{code}",
        f"{srcs[0].jurisdiction_name} {'・'.join(document)}（事業単位）",
        f"自治体が公開した{'・'.join(document)}データを Fiscal Data Package の形にしたもの。"
        "**fudoki の判断は含まない**（分類・名寄せ・推定を一切していない）。"
        "COFOG の割当は派生パッケージ derived/ にあり、budget_line_id で join する。"
        "原典そのものは data/budget/raw/ に Parquet で入っている。",
        # ⚠️ **その団体の証跡だけを見る。** 全体の最大を入れると、
        # 別の団体を取り直しただけで無関係なパッケージの created が動く。
        latest_fetch(f"jurisdiction={code}/**/provenance.json"),
    )
    pkg["fiscalPeriod"] = {"start": f"{years[0]}-04-01", "end": f"{years[-1] + 1}-03-31"}
    pkg["licenses"] = [{"name": srcs[0].license_id, "path": "https://creativecommons.org/licenses/by/4.0/"}]
    pkg["attribution"] = srcs[0].attribution
    pkg["sources"] = [{"title": s.attribution, "path": s.landing_page} for s in srcs]
    # 全行同じ値のものだけをリソースの列から外し、ここに定数として持たせる。
    # ⚠️ **phase と単位を定数にしてよいのは、実際に1種類しか無いときだけ。**
    # 決算書は1行が複数段階の金額を持ち（狛江市は予算額 / 予算計 / 執行累計）、
    # 段階ごとに単位も違う（歳入の予算現額だけ千円）。定数にすると descriptor が嘘になる。
    pkg["constants"] = {"jurisdictionCode": code, "jurisdictionName": srcs[0].jurisdiction_name}
    if len(phases) == 1:
        pkg["constants"]["phase"] = {"id": phases[0][0], "label": phases[0][1]}
    pkg["constants"]["currency"] = "JPY"
    if len(units) == 1:
        pkg["constants"]["sourceAmountUnit"] = {"label": units[0][0], "multiplier": units[0][1]}
    pkg["fudokiSourceDocument"] = document
    # 証跡は取得物の隣にある（data/budget/raw/.../provenance.json）
    pkg["provenance"] = [
        json.loads(p.read_text())
        for p in sorted(RAW.glob(f"jurisdiction={code}/**/provenance.json"))
    ]
    # ⚠️ **主キーは段階の数で変わる。** 決算書は原典1行を段階ごとの行へ展開するので、
    # budget_line_id だけでは一意でない（Table Schema の primaryKey が嘘になる）。
    pkg["resources"] = []
    for path, name, title in resources:
        multi = len(amounts[name]) > 1
        r = resource(
            path, name, title,
            ("原典1行が1行。判断を含まない" if not multi
             else "原典1行を予算段階ごとの行へ展開している。判断を含まない"),
            ["budget_line_id", "phase_id"] if multi else ["budget_line_id"],
        )
        if multi:
            # 段階の表示名は direction で違う（歳出は執行済額、歳入は収入済額）ので、
            # パッケージ全体ではなくリソースに置く。
            r["fudokiPhases"] = [{"id": a["phase"], "label": a["phase_label"],
                                  "sourceColumn": a["source"], "sourceAmountUnit": a["unit"]}
                                 for a in amounts[name]]
        verify_against_csv(path, amounts[name])
        pkg["resources"].append(r)
    (d / "datapackage.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n")
    print(f"ok  {code}  {len(pkg['resources'])} リソース  {sum(r['bytes'] for r in pkg['resources']):,} バイト")


def build_derived() -> None:
    """派生。**東京全体で1パッケージ。** ここから先は fudoki の判断。"""
    d = PACKAGES / "derived"
    pkg = base(
        "fudoki-budget-cofog",
        "予算の COFOG 割当（派生）",
        "**fudoki の判断**。自治体が言っていないことを付け加えている。"
        "正本とは budget_line_id で join する。"
        "根拠は cofog_rules に規則として出してあり、cofog_rule_id で引ける。"
        "分類不能の割合の低さは品質の指標ではない（成立範囲を正直に調べるのが目的）。",
        # 派生は全団体をまたぐので、証跡も全体の最大を見る
        latest_fetch(),
    )
    pkg["resources"] = [
        resource(d / "cofog.csv", "cofog", "COFOG の割当",
                 "識別子と判断だけ。正本の列を複製しない", ["budget_line_id"]),
        resource(d / "cofog_rules.csv", "cofog_rules", "割り当て規則",
                 "判断の中身そのもの。規則表を読めば何をどう決めたか確かめられる", ["rule_id"]),
    ]
    (d / "datapackage.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n")
    print(f"ok  derived  {len(pkg['resources'])} リソース  {sum(r['bytes'] for r in pkg['resources']):,} バイト")


if __name__ == "__main__":
    # **団体の一覧を手で持たない。** 取得元（sources.toml）と変換の宣言（dbt_project.yml）が
    # それぞれ正本なので、生成対象はその一致として決まる。
    # ⚠️ 以前は3つ目の手書きリスト（IMPLEMENTED）があり、団体を足すたびに
    # 3箇所へ登録することになっていた。しかも突き合わせは sources.toml とだけで、
    # **dbt の宣言との食い違いは誰も見ていなかった**（KeyError で落ちるだけ）。
    registered = {s.jurisdiction_code for s in load_sources().values()}
    declared = set(DBT_VARS["budget_levels"])
    if registered != declared:
        raise SystemExit(
            f"取得元（sources.toml）の団体 {sorted(registered)} と "
            f"変換の宣言（dbt_project.yml の budget_levels）{sorted(declared)} が一致しない。"
            f"配布物を欠けたまま書き出さないため停止する"
        )
    for code in sorted(registered):
        build_jurisdiction(code)
    build_derived()
