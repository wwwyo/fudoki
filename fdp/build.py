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
def licenses_of(srcs: list) -> list[dict]:
    """配布物に貼るライセンス。**取得元の宣言から決める。定数を貼らない。**

    ⚠️ 以前はここが定数の直書きだった。`rights_of` が値域を守っていたので今のところ
    結果は同じだったが、**この PR が直そうとした「勝手にライセンスを付ける」そのもの**である。
    宣言が変わっても配布物が変わらない状態を残してはいけない。

      原典が CC BY を付けている        → それを素通しする
      原典に利用許諾が無い（NOASSERTION）→ 事実には原典のライセンスが付いてこないので、
                                          選択と構成にあたる部分を fudoki が CC BY 4.0 で配る

    後者が成り立つのは**抽出した事実だけ**である。原文そのものは `Source` が
    `verbatim` + `NOASSERTION` を宣言時点で弾いているので、ここへ到達しない。
    """
    known = sorted({s.license_id for s in srcs} - {"NOASSERTION"})
    if any(lic != "CC-BY-4.0" for lic in known):
        raise SystemExit(
            f"原典のライセンスに {known} が含まれる。CC BY 4.0 以外は継承条件が違いうるので、"
            f"配布物のライセンスを決め直してから配ること"
        )
    return [LICENSE_CC_BY_4]


def rights_of(srcs: list) -> dict:
    """**利用者の行動が変わることだけを書く。** 変わらないなら何も書かない。

    ⚠️ 以前はここに「そのライセンスを誰が決めたか（原典 / fudoki）」を出していたが、
    それを知っても利用者のすることは変わらない（`licenses` と `attribution` で足りる）。
    fudoki が自分の正しさを確認するための情報であって、配布物に載せるものではない。
    その整理は data/LICENSE にある。

    残るのは1つだけ。**利用許諾の無い資料から事実を抽出した部分があるか。**
    事実に原典のライセンスは付いてこないが、利用者が原典そのものに当たり直すときは
    条件が違うので、出所を知らせる必要がある。
    """
    if not srcs:
        raise SystemExit("取得元が空。権利の判断ができない")
    unlicensed = sorted({s.attribution for s in srcs if s.license_id == "NOASSERTION"})
    return {"factsFrom": unlicensed} if unlicensed else {}


# CC BY 4.0 §3(a)(1)(B) が求める「改変した旨」の表示。
# ⚠️ **やっていない改変を書かない。** 一度、原典1行が複数の予算段階を持つ団体のための
# 「段階ごとの行へ展開した」を全団体共通のリストへ入れており、1行1金額の三鷹市にも付いていた。
# 改変の明示は CC BY が求めているものなので、嘘を書くと表示そのものの信用が落ちる。
# 団体で改変が変わるなら、そのときリストを団体ごとに分けること。
CANONICAL_MODIFICATIONS = [
    "セルの前後の空白を除去した",
    "コードと名称が同居するセルを分けた",
    "金額を円へ正規化した（原典の値と単位も残してある）",
]
DERIVED_MODIFICATIONS = [
    "原典の各行に COFOG の分類と連結の判断を付け加えた（自治体が言っていないこと）",
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
        # CC BY 4.0 §3(a)(1)(B) が求める「改変した旨」の表示。
        # ⚠️ `modified` と `attribution` は FDP の標準プロパティに無い（実測で確認）。
        # 帰属と改変の明示は CC BY の義務なのに標準側に置き場が無いので、独自で持つほかない。
        "modified": True,
        "modifications": modifications,
    }


def build_jurisdiction(code: str) -> None:
    """正本。**団体ごと・全年度で1パッケージ。** 判断を含まない。"""
    d = PACKAGES / code
    # ⚠️ **`redistribute` で絞らない。** 原文を置けない取得元でも、そこから抽出した事実は
    # 配布物に入る。絞ると、PDF から起こした団体の配布物が丸ごと空になる。理屈は data/LICENSE。
    srcs = [s for s in load_sources().values() if s.jurisdiction_code == code]
    if not srcs:
        raise RuntimeError(f"団体 {code} の取得元が sources.toml に無い")
    # ⚠️ **抽出した事実を配る経路は、下流がまだ原文前提のままである。**
    # dbt の原典突合（staging_is_one_to_one / canonical_preserves_source /
    # package_preserves_source）は raw が原文であることを前提にしており、
    # extracted に当てると誤って落ちるか、誤って通る。
    # 文書だけ先に整えて実装が追いつかない状態を、黙って通さないために止める。
    extracted = sorted({s.key for s in srcs if s.raw_form == "extracted"})
    if extracted:
        raise SystemExit(
            f"{code}: raw_form=extracted の取得元がある（{extracted}）。"
            f"dbt の原典突合の検査が原文前提のままなので、分岐させるまで配布物を作らない"
        )
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
    pkg["licenses"] = licenses_of(srcs)
    pkg["attribution"] = srcs[0].attribution
    if rights := rights_of(srcs):
        pkg["fudoki"] = {**pkg["fudoki"], "rights": rights}
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
    pkg["licenses"] = licenses_of(srcs)
    pkg["attribution"] = (
        "fudoki（COFOG の割当と規則表）。"
        "原典: " + "／".join(sorted({s.attribution for s in srcs}))
    )
    pkg["sources"] = [{"title": s.attribution, "path": s.landing_page} for s in srcs]
    if rights := rights_of(srcs):
        pkg["fudoki"] = {**pkg["fudoki"], "rights": rights}
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
