"""dbt の出力を Fiscal Data Package として配れる形にする。

（配布物そのものは data/budget/datapackages/ にある。ここはそれを組み立てる側）

**データは dbt が既に書いている**（`materialized: external`）。
ここが足すのは datapackage.json だけ、つまり**列の意味づけと出所**である。

列の ColumnType は `field_types.json` の宣言から引く。
未宣言の列があれば落とす（意味づけの無い列を配らないため）。
仕様が「正準」と呼ぶ taxonomy の URL は 404 なので、宣言を自分で持つのが既定の運用。

⚠️ **独自フィールドを積まない。** descriptor に独自の property を足すほど、
標準しか読まない実装から見える情報が減る（読み手は property の名前を知らない）。
足す前に仕様本文を当たること。実際、当初 `constants` として独自に持っていたものは
仕様の `extraFields` + `constant` そのものだったし、`provenance` は取得物の隣の
provenance.json と同じ内容を descriptor へ写しただけだった。

⚠️ **1.0.0 に対応する profile JSON は存在しない**（2026-08-23 実測）。
仕様本文が Profile として挙げる fiscal.datapackage.org/profiles/fiscal-data-package.json は
0.3 世代のままで、1.0.0 が廃止した `model`（measures / dimensions）を required に持つ。
検査に使えないので descriptor の `profile` には下層の Tabular Data Package v1 を宣言し、
この事実は AGENTS.md に記録してある（配布物には載せない — 利用者の行動が変わらないため）。
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

    ⚠️ 以前はここが定数の直書きだった。別の関数が値域を守っていたので今のところ
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


# CC BY 4.0 §3(a)(1)(B) が求める「改変した旨」の表示。**descriptor の `description` に書く。**
# ⚠️ 以前は独自の `modified` / `modifications` を足していたが、`modified` は
# **fudoki の配布物がすべて加工物なので常に true** で、情報量が無かった。
# 中身のあるリストのほうは標準の `description`（Markdown 可）に書けば
# 標準しか読まない実装からも読める。義務の伝達を独自フィールドに預けない。
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
# 配布物から fudoki 本体へ戻る道。標準の `homepage` に入れる。
# 取得の証跡（provenance.json）を descriptor へ写すのをやめた代わりに、
# **どこを見れば証跡があるか**を利用者へ伝える経路がここになる。
HOMEPAGE = "https://github.com/wwwyo/fudoki"
# ⚠️ **正本にしか成り立たない一文を混ぜない。** 派生のリソースは `sources` を持たないので、
# 「`sources[].path` が取得 URL」と書くと存在しないフィールドを案内することになる。
CANONICAL_SOURCES_NOTE = (
    "リソースの `sources[].path` は、その証跡が記録している取得 URL そのものである。"
    "正本は団体ごと・全年度で1リソースなので、年度の数だけ並ぶ。"
)
PROVENANCE_NOTE = (
    "取得の証跡（取得 URL・HTTP status・SHA-256・取得時刻・ヘッダ・行数）は、"
    "原典の隣（`data/budget/raw/**/provenance.json`）にある。"

)
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


def field_spec(path: pathlib.Path, name: str) -> dict:
    spec = TYPES["fields"].get(name)
    if spec is None:
        raise RuntimeError(
            f"{path.name} の列「{name}」に ColumnType の宣言が無い。"
            f"fdp/field_types.json に定義を足すこと"
        )
    return dict(spec)


def schema_for(path: pathlib.Path, body: bytes, primary_key: list[str],
               constants: dict[str, object] | None = None) -> dict:
    """列に意味づけを与える。**宣言の無い列は配らない。**

    `constants` は全行同じ値なので CSV の列から外したもの。仕様の
    **Constant Fields**（`extraFields` の各項目に `constant` を持たせる）で表す。
    ⚠️ 独自の `constants` プロパティで持っていたときは、標準しか読まない実装から
    「団体コードも通貨も direction も分からない配布物」に見えていた。
    `extraFields` は定義上「非正規化した形には現れるが原典には無い列」なので、
    **CSV の列は1つも変わらない**（`budget_line_id` を含め公開済みの参照は無傷）。
    """
    fields = [field_spec(path, name) for name in header_of(body)]
    extra = []
    for name, value in (constants or {}).items():
        spec = field_spec(path, name)
        if name in {f["name"] for f in fields}:
            raise RuntimeError(f"{path.name} の「{name}」は実在の列。定数として二重に宣言できない")
        extra.append({**spec, "constant": value})
    declared = fields + extra  # 型と ColumnType の検査は実在の列と同じに掛ける

    # Table Schema への適合。型が無い列や主キーに無い列があれば配らない。
    for f in declared:
        if "type" not in f:
            raise RuntimeError(f"{path.name} の列「{f['name']}」に type が無い（Table Schema 違反）")
    missing = [k for k in primary_key if k not in {f["name"] for f in fields}]
    if missing:
        raise RuntimeError(f"{path.name} の primaryKey {missing} が列に無い（Table Schema 違反）")

    # ColumnType への適合。標準の語彙にも自作の宣言にも無いものは、意味が誰にも伝わらない。
    for f in declared:
        ct = f.get("columnType")
        if ct is None or ct in STANDARD_COLUMN_TYPES or ct in DECLARED_CUSTOM:
            continue
        raise RuntimeError(
            f"{path.name} の列「{f['name']}」の columnType「{ct}」が "
            f"Budget Standard Taxonomy にも自作の宣言にも無い"
        )
    schema = {"fields": fields, "primaryKey": primary_key}
    if extra:
        schema["extraFields"] = extra
    return schema


def resource(path: pathlib.Path, name: str, title: str, description: str, primary_key: list[str],
             sources: list[dict] | None = None, constants: dict[str, object] | None = None) -> dict:
    body = path.read_bytes()
    r = {
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
        "schema": schema_for(path, body, primary_key, constants),
    }
    if sources:
        # リソース単位の出所。パッケージ単位の `sources` が「どの資料か」を言うのに対し、
        # ここは**この1ファイルがどの URL から来たか**を言う。
        r["sources"] = sources
    return r


def latest_fetch() -> str:
    """収録した原典のうち最も新しい取得時刻。パッケージの版がいつ時点かを表す"""
    stamps = [json.loads(p.read_text())["fetched_at"] for p in RAW.glob("**/provenance.json")]
    if not stamps:
        raise RuntimeError("証跡が1つも無い。先に ingestion を回すこと")
    return max(stamps)


def described(body: str, credit: str, modifications: list[str], notes: list[str]) -> str:
    """`description` を組み立てる。**CC BY の義務をここへ集める。**

    ⚠️ 帰属（§3(a)(1)(A)）と改変の明示（§3(a)(1)(B)）に FDP の標準プロパティは無い。
    以前は独自の `attribution` / `modified` / `modifications` に置いていたが、
    独自プロパティは**標準しか読まない実装からは存在しないのと同じ**なので、
    義務の伝達をそこに預けるのは弱かった（data/LICENSE がその弱点を明記していた）。
    `description` は Markdown が使える標準プロパティで、必ず人の目に触れる。

    機械可読なほうは標準の置き場に残してある —
    出典の文字列は `sources[].title`、条件は `licenses`、加工者は `contributors`。
    ここはそれを「どう表示してほしいか」に翻訳した一文である。
    """
    parts = [
        body,
        "## 出典表示（CC BY 4.0 §3(a)(1)(A)）\n\n"
        f"次の一文をそのまま使うこと。\n\n> {credit}\n\n"
        "機械可読な同じ内容は `sources[].title`（原典）と `contributors`（加工者）にある。",
        "## 改変（CC BY 4.0 §3(a)(1)(B)）\n\n"
        "原典に対して次のことをしている。\n\n"
        + "\n".join(f"- {m}" for m in modifications)
        + "\n\n原典そのものは `data/budget/raw/` に Parquet で保全してあるので、改変の前後を突き合わせられる。",
        *notes,
    ]
    return "\n\n".join(parts)


def base(name: str, title: str, description: str) -> dict:
    created = latest_fetch()
    return {
        # ⚠️ **1.0.0 の profile JSON は存在しない**（AGENTS.md に実測を記録）。
        # ここに書けるのは下層の Tabular Data Package v1 だけである。
        "profile": "tabular-data-package",
        "name": name,
        "title": title,
        "description": description,
        "homepage": HOMEPAGE,
        "version": "0.1.0",
        # 生成した時刻ではなく**原典を取得した時刻**を入れる。
        # 実行した瞬間を入れると、中身が同じでも回すたびに差分が出る。
        # 意味としても「いつ時点の原典から作られたか」のほうが利用者に要る。
        "created": created,
        "countryCode": "JP",
        # 仕様の「_ColumnType_ definition package」。**パッケージ直下が仕様どおりの置き場**で、
        # リソース側の `schema.fields[].columnType`（単数）が個々の列をここへ結び付ける。
        # 両方あるのは重複ではなく、宣言と参照の関係である。
        "columnTypes": TYPES["columnTypes"],
        "fudoki": TYPES["fudoki"],
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

    # ⚠️ **phase を定数にしてよいのは1つしか無いときだけ。**
    # 補正予算を足すと行ごとに phase が違うので、定数にすると descriptor が嘘になる。
    # （`phase_id` は実在の列なので複数でも耐えるが、定数の `phase_label` が嘘になる）
    phases = {(s.phase_id, s.phase_label) for s in srcs}
    if len(phases) != 1:
        raise SystemExit(
            f"{code} に予算段階が {len(phases)} 種類ある（{sorted(p[0] for p in phases)}）。"
            f"descriptor は単一 phase を前提にしているので、複数を許す構造へ変えてから配る"
        )

    # ⚠️ **単位は団体差。** 直書きすると、円で公開する団体を足したとき黙って嘘になる。
    # 年度で単位が割れている団体も、1つの配布物には収められない。
    units = {(s.source_amount_unit, s.source_amount_multiplier) for s in srcs}
    if len(units) != 1:
        raise SystemExit(
            f"{code}: 原典の金額の単位が {sorted(units)} と揃っていない。"
            f"1つの配布物に複数の単位は収められないので、分けて配ること"
        )
    unit, multiplier = units.pop()

    constants = {
        "jurisdiction_code": code,
        "jurisdiction_label": srcs[0].jurisdiction_name,
        "phase_label": srcs[0].phase_label,
        "currency": "JPY",
        "source_amount_unit": unit,
    }
    pkg = base(
        f"fudoki-budget-{code}",
        f"{srcs[0].jurisdiction_name} 予算（事業単位）",
        described(
            "自治体が公開した予算データを Fiscal Data Package の形にしたもの。"
            "**fudoki の判断は含まない**（分類・名寄せ・推定を一切していない）。"
            "COFOG の割当は派生パッケージ derived/ にあり、budget_line_id で join する。"
            "原典そのものは data/budget/raw/ に Parquet で入っている。",
            srcs[0].attribution,
            CANONICAL_MODIFICATIONS,
            [
                PROVENANCE_NOTE,
                CANONICAL_SOURCES_NOTE,
                # ⚠️ **定数の一覧を散文で書き写さない。** 書き写すと、定数を1つ足したとき
                # descriptor は正しいまま説明文だけが黙ってずれる。宣言（`field_types.json` の
                # `title`）から組み立てれば、出所が1つのままになる。
                "## 全行で同じ値の列\n\n"
                + "、".join(field_spec(d / "expenditure.csv", n)["title"]
                             for n in [*constants, "direction"])
                + "は行ごとに変わらないので、CSV の列から外して `schema.extraFields` に"
                "定数として置いてある（仕様の Constant Fields）。"
                f"金額は原典の単位（{unit}）のままで、円へ直すには {multiplier} を掛ける。"
                "非正規化した形へ戻すときは、その列を全行に補う。",
                "FDP は全要素が任意なので、COFOG 列を持たないこのパッケージも適合した FDP である。",
            ],
        ),
    )
    pkg["fiscalPeriod"] = {"start": f"{years[0]}-04-01", "end": f"{years[-1] + 1}-03-31"}
    pkg["licenses"] = licenses_of(srcs)
    # **加工したのは誰か。** Data Package v1 の role の推奨語彙は
    # author / publisher / maintainer / wrangler / contributor の5つで、
    # 仕様は「author を使っても原典の作成者という意味にはならない。
    # 原典の出所は `sources` で示せ」と明記している（実測: specs.frictionlessdata.io/data-package/）。
    # ⚠️ したがって**自治体を contributors に入れない**。自治体はこのパッケージを作っていない。
    # 正本で fudoki がしたのは他人のデータの荷造りなので `wrangler`（派生は `author`）。
    pkg["contributors"] = [{"title": "fudoki", "path": HOMEPAGE, "role": "wrangler"}]
    pkg["sources"] = [{"title": s.attribution, "path": s.landing_page} for s in srcs]
    # 全行同じ値なのでリソースの列から外したもの。**リソースの `extraFields` に置く。**
    # ⚠️ 以前は独自の `constants` に置いていたが、仕様が Constant Fields として
    # まさにこれを規定していた（`extraFields` の項目に `constant` を持たせる）。
    # 独自プロパティのままだと、標準しか読まない実装からは団体コードも通貨も見えない。
    # ⚠️ **direction ごとに1件ではない。** 正本は団体ごと・全年度で1リソースなので、
    # 同じ direction の証跡が年度の数だけある。dict のキーを direction にすると
    # 最後の1件で上書きされ、**残りが黙って消える**（1年度しか無いうちは表面化しない）。
    prov: dict[str, list[dict]] = {}
    for path in sorted(RAW.glob(f"jurisdiction={code}/**/provenance.json")):
        entry = json.loads(path.read_text())
        prov.setdefault(entry["direction"], []).append(entry)

    def origin(direction: str) -> list[dict]:
        """この1ファイルを構成する原典。**年度の数だけある。**

        証跡の写しではなく入口を置く。SHA-256・取得時刻・HTTP status は
        `data/budget/raw/**/provenance.json` にあり、その在り処は description が示す。
        """
        entries = prov.get(direction)
        if not entries:
            raise RuntimeError(f"{code}/{direction} の証跡が無い。先に ingestion を回すこと")
        return [{"title": f"{e['fiscal_year']}年度／{e['dataset_title']}／{e['resource_name']}",
                 "path": e["request_url"]} for e in entries]

    pkg["resources"] = [
        resource(d / "expenditure.csv", "expenditure", "歳出", "原典1行が1行。判断を含まない",
                 ["budget_line_id"], origin("expenditure"), {**constants, "direction": "expenditure"}),
        resource(d / "revenue.csv", "revenue", "歳入", "原典1行が1行。判断を含まない",
                 ["budget_line_id"], origin("revenue"), {**constants, "direction": "revenue"}),
    ]
    (d / "datapackage.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n")
    print(f"ok  {code}  {len(pkg['resources'])} リソース  {sum(r['bytes'] for r in pkg['resources']):,} バイト")


def build_derived() -> None:
    """派生。**東京全体で1パッケージ。** ここから先は fudoki の判断。"""
    d = PACKAGES / "derived"
    srcs = list(load_sources().values())
    pkg = base(
        "fudoki-budget-cofog",
        "予算の COFOG 割当（派生）",
        described(
            "**fudoki の判断**。自治体が言っていないことを付け加えている。"
            "正本とは budget_line_id で join する。"
            "根拠は cofog_rules に規則として出してあり、cofog_rule_id で引ける。"
            "分類不能の割合の低さは品質の指標ではない（成立範囲を正直に調べるのが目的）。",
            "fudoki（COFOG の割当と規則表）。"
            "原典: " + "／".join(sorted({s.attribution for s in srcs})),
            DERIVED_MODIFICATIONS,
            [PROVENANCE_NOTE],
        ),
    )
    # **派生は fudoki 自身の著作物なので、ライセンスを選ぶのは fudoki である。**
    # ⚠️ ただし選べる範囲は原典に縛られる。CC BY は継承を求めないので今は CC BY 4.0 を選べるが、
    # 原典に CC BY-SA の団体が入った時点で派生も BY-SA にするほかなくなる。
    # だから「fudoki は CC BY 4.0 と決めた」ではなく「原典が許す範囲で CC BY 4.0 を選んでいる」
    # と読めるように、原典のライセンス一覧を併記する。
    pkg["licenses"] = licenses_of(srcs)
    # 正本と違い、ここは荷造りではなく fudoki が書いた中身なので `author`。
    pkg["contributors"] = [{"title": "fudoki", "path": HOMEPAGE, "role": "author"}]
    # COFOG の版と出典。**割当列を持つこのパッケージにだけ置く。**
    # ⚠️ 以前は正本にも同じものが載っていた（COFOG 列を1つも持たないのに）。
    pkg["fudoki"] = {**pkg["fudoki"], "cofog": TYPES["cofog"]}
    pkg["sources"] = [{"title": s.attribution, "path": s.landing_page} for s in srcs]
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
