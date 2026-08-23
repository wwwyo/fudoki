"""dbt の出力を Fiscal Data Package として配れる形にする。

（配布物そのものは data/budget/datapackages/ にある。ここはそれを組み立てる側）

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

from ingestion.budget.sources import load_sources

ROOT = pathlib.Path(__file__).resolve().parent.parent
# ライセンスの表示。**1箇所で持つ** — 正本（素通し）と派生（fudoki の選択）で
# 意味は違うが、表示する内容が食い違うと利用者はどちらを信じるか決められない。
LICENSE_CC_BY_4 = {
    "name": "CC-BY-4.0",
    "title": "Creative Commons Attribution 4.0 International",
    "path": "https://creativecommons.org/licenses/by/4.0/",
}
def rights_of(srcs: list) -> dict:
    """この配布物にどのライセンスが付くか、そしてそれは誰が決めたのか。

    **2通りある。** 混ぜて1つの表示にすると、利用者はどちらか分からない。

      素通し   原典が CC BY で提供している。fudoki は選んでいないし、選べない
      fudoki   原典に利用許諾が無い（PDF など）。だが**抽出した事実は著作物ではない**ので、
               原典のライセンスは付いてこない。配布物の選択と構成は fudoki のものなので、
               fudoki が CC BY 4.0 を選んでいる

    ⚠️ 後者で配れるのは**事実だけ**である。原文の散文（事業説明など）を持ってくると
    表現の複製になり、この整理は成り立たない。抽出する側がそこを守る必要がある。
    """
    licensed = sorted({s.license_id for s in srcs if s.license_id != "NOASSERTION"})
    unlicensed = sorted({s.attribution for s in srcs if s.license_id == "NOASSERTION"})
    if any(lic not in ("CC-BY-4.0",) for lic in licensed):
        raise SystemExit(
            f"原典のライセンスに {licensed} が含まれる。CC BY 4.0 以外は継承条件が違いうるので、"
            f"配布物のライセンスを決め直してから配ること"
        )
    if licensed and not unlicensed:
        return {"basis": "素通し", "upstream": licensed,
                "note": "原典のライセンスをそのまま表示している。**fudoki が選んだものではない**。"
                        "fudoki は原典の著作権を持たないので、付け替えることはできない"}
    return {"basis": "fudoki の選択", "upstream": licensed,
            "factsFrom": unlicensed,
            "note": "利用許諾の無い資料から**事実**（事業名・金額・コード）を抽出した部分を含む。"
                    "事実は著作物ではない（著作権法2条1項1号）ので原典のライセンスは付いてこず、"
                    "選択と構成にあたる部分を fudoki が CC BY 4.0 で配っている。"
                    "原文そのものはリポジトリに置いていない"}


# CC BY 4.0 §3(a)(1)(B) が求める「改変した旨」の表示。
# ⚠️ **正本と派生で内容が違う。** 同じ文言を使い回すと、派生が単位換算をしたことになる。
CANONICAL_MODIFICATIONS = [
    "セルの前後の空白を除去した（原典に全角スペースが混じるため）",
    "コードと名称が同居するセルを分けた（分けたものを繋ぐと原文に戻ることを検査している）",
    "金額を円へ正規化した（原典の値と単位も併せて残してある）",
    "1行が複数の予算段階を持つ原典を、段階ごとの行へ展開した",
]
DERIVED_MODIFICATIONS = [
    "原典の各行に COFOG の分類と連結の判断を付け加えた（自治体が言っていないこと）",
    "識別子は原典の階層のセル全文から導いており、原典そのものは複製していない",
]
PACKAGES = ROOT / "data" / "budget" / "datapackages"
RAW = ROOT / "data" / "budget" / "raw"
TYPES = json.loads((pathlib.Path(__file__).parent / "field_types.json").read_text())
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


def latest_fetch() -> str:
    """収録した原典のうち最も新しい取得時刻。パッケージの版がいつ時点かを表す"""
    stamps = [json.loads(p.read_text())["fetched_at"] for p in RAW.glob("**/provenance.json")]
    if not stamps:
        raise RuntimeError("証跡が1つも無い。先に ingestion を回すこと")
    return max(stamps)


def base(name: str, title: str, description: str, modifications: list[str]) -> dict:
    created = latest_fetch()
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
        # ⚠️ **CC BY 4.0 は改変したらその旨を示すことを求める（§3(a)(1)(B)）。**
        # fudoki は原典を改変している（前後空白の除去、コードと名称の分離、
        # 円への正規化、予算段階ごとの行への展開）ので、黙って配らない。
        # 何をどう変えたかは AGENTS.md と dbt のモデルに書いてある。
        "modified": True,
        "modifications": modifications,
    }


def build_jurisdiction(code: str) -> None:
    """正本。**団体ごと・全年度で1パッケージ。** 判断を含まない。"""
    d = PACKAGES / code
    # ⚠️ **`redistribute` で絞らない。** 原文を置けない取得元でも、そこから抽出した
    # 事実は配布物に入る（事業名と金額は著作物ではない）。絞ると、PDF から起こした
    # 団体の配布物が丸ごと空になる。止めるべきなのは原文の複製だけで、それは取得側が見ている。
    srcs = [s for s in load_sources().values() if s.jurisdiction_code == code]
    if not srcs:
        raise RuntimeError(f"団体 {code} の取得元が sources.toml に無い")
    years = sorted(s.fiscal_year for s in srcs)

    pkg = base(
        f"fudoki-budget-{code}",
        f"{srcs[0].jurisdiction_name} 予算（事業単位）",
        "自治体が公開した予算データを Fiscal Data Package の形にしたもの。"
        "**fudoki の判断は含まない**（分類・名寄せ・推定を一切していない）。"
        "COFOG の割当は派生パッケージ derived/ にあり、budget_line_id で join する。"
        "原典そのものは data/budget/raw/ に Parquet で入っている。",
        CANONICAL_MODIFICATIONS,
    )
    pkg["fiscalPeriod"] = {"start": f"{years[0]}-04-01", "end": f"{years[-1] + 1}-03-31"}
    pkg["licenses"] = [LICENSE_CC_BY_4]
    pkg["attribution"] = srcs[0].attribution
    pkg["fudoki"] = {**pkg["fudoki"], "rights": {
        **rights_of(srcs),
        "holder": srcs[0].jurisdiction_name,
        # 再配布可と判断した根拠。**判断の中身を読めるようにする** —
        # 「allow だから配った」だけでは、誰も判断を検討できない。
        "redistributionBasis": sorted({s.redistribute_basis for s in srcs}),
        "repositoryLicense": "リポジトリ直下の LICENSE（MIT）はコードに対するもので、この配布物には及ばない",
        # `raw/` の保証は団体で違う。原文を置いた団体だけ「原典と1対1」が成立する。
        "rawForm": sorted({s.raw_form for s in srcs}),
    }}
    pkg["sources"] = [{"title": s.attribution, "path": s.landing_page} for s in srcs]
    # 全行同じ値なのでリソースの列から外し、ここに持たせた定数。
    # ⚠️ **phase を package 全体の定数にしてよいのは1つしか無いときだけ。**
    # 補正予算を足すと行ごとに phase が違うので、定数にすると descriptor が嘘になる。
    phases = {(s.phase_id, s.phase_label) for s in srcs}
    if len(phases) != 1:
        raise SystemExit(
            f"{code} に予算段階が {len(phases)} 種類ある（{sorted(p[0] for p in phases)}）。"
            f"descriptor は単一 phase を前提にしているので、複数を許す構造へ変えてから配る"
        )
    pkg["constants"] = {
        "jurisdictionCode": code,
        "jurisdictionName": srcs[0].jurisdiction_name,
        "phase": {"id": srcs[0].phase_id, "label": srcs[0].phase_label},
        "currency": "JPY",
        "sourceAmountUnit": {"label": "千円", "multiplier": 1000},
    }
    # 証跡は取得物の隣にある（data/budget/raw/.../provenance.json）
    pkg["provenance"] = [
        json.loads(p.read_text())
        for p in sorted(RAW.glob(f"jurisdiction={code}/**/provenance.json"))
    ]
    pkg["resources"] = [
        resource(d / "expenditure.csv", "expenditure", "歳出", "原典1行が1行。判断を含まない", ["budget_line_id"]),
        resource(d / "revenue.csv", "revenue", "歳入", "原典1行が1行。判断を含まない", ["budget_line_id"]),
    ]
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
        DERIVED_MODIFICATIONS,
    )
    srcs = list(load_sources().values())
    # **派生は fudoki 自身の著作物なので、ライセンスを選ぶのは fudoki である。**
    # ⚠️ ただし選べる範囲は原典に縛られる。CC BY は継承を求めないので今は CC BY 4.0 を選べるが、
    # 原典に CC BY-SA の団体が入った時点で派生も BY-SA にするほかなくなる。
    # だから「fudoki は CC BY 4.0 と決めた」ではなく「原典が許す範囲で CC BY 4.0 を選んでいる」
    # と読めるように、原典のライセンス一覧を併記する。
    pkg["licenses"] = [LICENSE_CC_BY_4]
    pkg["attribution"] = (
        "fudoki（COFOG の割当と規則表）。"
        "原典: " + "／".join(sorted({s.attribution for s in srcs}))
    )
    pkg["sources"] = [{"title": s.attribution, "path": s.landing_page} for s in srcs]
    pkg["fudoki"] = {**pkg["fudoki"], "rights": {
        **rights_of(srcs),
        "thisPackage": "COFOG の割当と規則そのものは fudoki の判断で、CC BY 4.0 で配布する",
        "note2": "⚠️ 原典に継承（ShareAlike）を求めるライセンスが混ざった場合、"
                 "この選択は成り立たなくなる（rights_of が停止する）。"
                 "原典のライセンスは団体ごとに ingestion/budget/sources.toml が持つ",
    }}
    pkg["resources"] = [
        resource(d / "cofog.csv", "cofog", "COFOG の割当",
                 "識別子と判断だけ。正本の列を複製しない", ["budget_line_id"]),
        resource(d / "cofog_rules.csv", "cofog_rules", "割り当て規則",
                 "判断の中身そのもの。35行読めば何をどう決めたか確かめられる", ["rule_id"]),
    ]
    (d / "datapackage.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n")
    print(f"ok  derived  {len(pkg['resources'])} リソース  {sum(r['bytes'] for r in pkg['resources']):,} バイト")


# 実装済みの団体。**`sources.toml` の集合と一致しない状態で書き出さない。**
# 一致を見ないと、2団体目を登録しても三鷹市だけを生成して正常終了し、
# 欠けたまま配布物が出来上がる（パイプライン全体は後段の report で止まるが、
# `python -m fdp.build` を単体で回すと気づけない）。
IMPLEMENTED = {"132047"}

if __name__ == "__main__":
    # 配布物を作る対象は「再配布可と判定した取得元を持つ団体」。
    registered = {s.jurisdiction_code for s in load_sources().values()}
    if registered != IMPLEMENTED:
        raise SystemExit(
            f"sources.toml の団体 {sorted(registered)} と実装済み {sorted(IMPLEMENTED)} が一致しない。"
            f"配布物を欠けたまま書き出さないため停止する"
        )
    for code in sorted(IMPLEMENTED):
        build_jurisdiction(code)
    build_derived()
