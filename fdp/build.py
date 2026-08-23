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

⚠️ **`profile` は `tabular-data-package` が正しい値であって、妥協ではない。**
FDP の profile は Tabular Data Package を `allOf` で継承しており、継承元の `profile` は
enum で `tabular-data-package` に固定されている。FDP の URL を入れると継承元の制約に
違反する。**「これは FDP である」を宣言する口は、仕様の設計上どこにも無い**
（`columnTypes` を持っていることが事実上の印になるだけ）。
だから `fudoki.specification` は代替が見つかるまでの間に合わせではなく、
構造的に標準へ寄せられないものである。

⚠️ 別件として、**1.0.0 に対応する profile JSON も存在しない**（2026-08-23 実測）。
仕様本文が Profile として挙げる fiscal.datapackage.org/profiles/fiscal-data-package.json は
0.3 世代のままで、1.0.0 が廃止した `model`（measures / dimensions）を required に持つ。
1.0.0 への適合を機械に検査させる経路が無いということで、AGENTS.md に記録してある
（配布物には載せない — 利用者の行動が変わらないため）。
"""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib

import yaml

from ingestion.budget.sources import load_project_names, load_revenue_accounts, load_sources

ROOT = pathlib.Path(__file__).resolve().parent.parent
# 変換の宣言。**金額の段階と単位はここが正本**（dbt のモデルが同じ宣言から組まれる）。
# ⚠️ 写すと、モデルの倍率を直したのに descriptor だけ古い前提のまま出る。
DBT_VARS = yaml.safe_load((ROOT / "dbt" / "dbt_project.yml").read_text())["vars"]
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
# 判断のリソースごとの改変。**そのリソースが実際にある団体にだけ付ける。**
# ⚠️ やっていない改変を書かない。事業名は狛江市にしか無い。
JUDGMENT_MODIFICATIONS = {
    "cofog": "原典の各行に COFOG の分類と連結の判断を付け加えた（自治体が言っていないこと）",
    "account_names": "科目に法定マスタ（地方自治法施行規則 別記の区分）への対応を付け加えた"
                     "（コードのずれと表記差の吸収は fudoki の判断）",
    "project_names": "原典に無い事業名を決算資料 PDF の事項別明細から起こし、"
                     "同じ目の中で金額が一致する大事業へ対応づけた"
                     "（自治体がこの対応を宣言しているわけではない）",
}

# 判断のリソース。**原典と突き合わせる相手がいない**ので、正本と同じ検査は掛からない。
# どう決めたかは dbt の core モデルにあり、規則そのものも cofog_rules で配る。
JUDGMENT_RESOURCES = [
    ("cofog", "COFOG の割当（fudoki の判断）",
     "自治体が言っていないことを付け加えている。正本とは budget_line_id で join する。"
     "根拠は cofog_rules に規則として出してあり、cofog_rule_id で引ける。"
     "分類不能の割合の低さは品質の指標ではない（成立範囲を正直に調べるのが目的）",
     ["budget_line_id"]),
    ("cofog_rules", "COFOG の割り当て規則（fudoki の判断）",
     "判断の中身そのもの。結果だけを配ると、利用者は検算できても判断を検討できない。"
     "その団体に効く規則だけを収めている（applies_to が空の規則はどの団体にも効く）",
     ["rule_id"]),
    ("account_names", "科目の名称と法定マスタへの対応（fudoki の判断を含む）",
     "款・項・目の名称のカタログと、地方自治法施行規則 別記の区分への対応。"
     "**款のコードは団体ごとに法定とずれる**（災害復旧費を持たない市では以降が詰まる）ので、"
     "団体をまたぐ比較は master_kan_code / master_kou_code で行う。"
     "名称の出所（原典か、決算書 PDF から fudoki が解決したか）は name_source が言う",
     ["fiscal_year", "direction", "fund_code", "kan_code", "kou_code", "moku_code"]),
    ("project_names", "事業名の対応づけ（fudoki の判断）",
     "原典の CSV に事業の名称が無い団体で、決算資料 PDF から起こした名称を"
     "金額で大事業へ対応づけたもの。対応づけの確からしさ（match_method / match_basis / "
     "candidate_count）を併記してある",
     ["fiscal_year", "fund_code", "kan_code", "kou_code", "moku_code", "daijigyo_code"]),
]


def amounts_of(code: str, direction: str) -> list[dict]:
    """そのリソースが持つ金額の宣言（段階・単位・倍率）。

    **正本は `dbt/dbt_project.yml` の `budget_amounts`。** ここへ写すと、
    モデルの倍率や段階を直したのに descriptor が古い前提のまま出る。
    宣言どおりに書けているかは `verify_against_csv` が配布物そのものを見て確かめる。
    """
    return DBT_VARS["budget_amounts"][code][direction]


def verify_against_csv(path: pathlib.Path, amounts: list[dict]) -> None:
    """宣言と配布物が食い違っていないか。**descriptor だけ正しい状態を作らない。**"""
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
        for row in rows:
            unit = row.get("source_amount_unit", amounts[0]["unit"])
            seen.add((row["phase_id"], unit))
            src, val = int(row["source_amount"]), int(row["value"])
            expected = next((a["multiplier"] for a in amounts if a["phase"] == row["phase_id"]), None)
            if expected is None:
                raise RuntimeError(f"{path.name}: 宣言に無い予算段階「{row['phase_id']}」が配布物にある")
            if val != src * expected:
                raise RuntimeError(f"{path.name}: value {val} が source_amount {src} × {expected} と違う")
    declared = {(a["phase"], a["unit"]) for a in amounts}
    if seen != declared:
        raise RuntimeError(
            f"{path.name}: 配布物の (段階, 単位) {sorted(seen)} が宣言 {sorted(declared)} と違う"
        )
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


def base(name: str, title: str, description: str, created: str) -> dict:
    # ⚠️ **`created` を呼ぶ側から渡す。** 団体ごとのパッケージはその団体の証跡だけを見る。
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
    # ⚠️ **抽出した事実は配れるが、原典突合の検査には掛けられない。**
    # dbt の原典突合（staging_is_one_to_one / canonical_preserves_source /
    # package_preserves_source）は raw が原文であることを前提にしており、
    # extracted に当てると誤って落ちるか、誤って通る。
    # ⚠️ 以前ここは extracted の取得元があるだけで全部止めていたが、それでは
    # **PDF から起こすほかない大半の団体の配布物が丸ごと空になる**（data/LICENSE）。
    # 止めるべきなのは「原文前提の検査に extracted を掛けること」だけなので、
    # 全面停止ではなくその不変条件を検査する。
    covered = set(DBT_VARS["budget_levels"].get(code, {}))
    wrong = sorted({s.key for s in srcs if s.raw_form == "extracted" and {res.direction for res in s.resources} & covered})
    if wrong:
        raise SystemExit(
            f"{code}: raw_form=extracted の取得元が原典突合の対象になっている（{wrong}）。"
            f"検査が原文前提のままなので、分岐させるまで配布物を作らない"
        )
    years = sorted(s.fiscal_year for s in srcs)

    # 原典の文書そのものの種類（当初予算 / 決算）。**行が持つ予算段階とは別の軸。**
    # 「予算（事業単位）」と決め打ちすると、決算書から作った狛江市のパッケージが嘘になる。
    document = sorted({s.phase_label for s in srcs})

    # ⚠️ **金額の段階と単位は取得元ではなく変換の宣言から引く。**
    # 決算書は原典1行が複数段階の金額を持ち（狛江市は予算額 / 予算計 / 執行累計）、
    # 段階ごとに単位も違う（歳入の予算現額だけ千円）。
    # `Source` は (団体, 年度) の粒度なので、この割れ方を表せない。
    amounts = {name: amounts_of(code, name) for name in ("expenditure", "revenue")}
    flat = [a for v in amounts.values() for a in v]
    # ⚠️ **2つの宣言が食い違っていないことを見る。** 取得元の宣言（原典の主たる単位）が
    # 変換の宣言に1つも現れないなら、どちらかが古い。
    declared_units = {(a["unit"], a["multiplier"]) for a in flat}
    for s in srcs:
        if (s.source_amount_unit, s.source_amount_multiplier) not in declared_units:
            raise SystemExit(
                f"{code}: sources.toml の単位 {(s.source_amount_unit, s.source_amount_multiplier)} が "
                f"dbt の budget_amounts の宣言 {sorted(declared_units)} に無い"
            )

    # ⚠️ **どの判断が入るかは description より先に決める。** 改変の明示（CC BY §3(a)(1)(B)）は
    # description に載るので、リソースを足しながら後から追記すると説明文に反映されない。
    present = [j for j in JUDGMENT_RESOURCES if (d / f"{j[0]}.csv").exists()]
    modifications = CANONICAL_MODIFICATIONS + [
        JUDGMENT_MODIFICATIONS[n] for n, *_ in present if n in JUDGMENT_MODIFICATIONS
    ]
    # 事業名の取得元（PDF）。原典の CSV とは別の資料で、再配布の可否も別に判定している。
    pdf_specs = {**load_project_names(),
                 **{f"revenue/{k}": v for k, v in load_revenue_accounts().items()}}
    pdfs = [spec for key, spec in sorted(pdf_specs.items())
            if key.split("/")[-1].split(":")[0] == code]
    # 同じ PDF（歳出と歳入で同一文書）を2回出典に載せない
    seen_urls: set[str] = set()
    pdfs = [s for s in pdfs if not (s["url"] in seen_urls or seen_urls.add(s["url"]))]

    constants = {
        "jurisdiction_code": code,
        "jurisdiction_label": srcs[0].jurisdiction_name,
        "currency": "JPY",
    }
    # ⚠️ **定数にしてよいのは、実際に1種類しか無いときだけ。**
    # 複数あるものを定数にすると、CSV の列は正しいまま descriptor だけが嘘になる。
    phase_labels = {(a["phase"], a["phase_label"]) for a in flat}
    if len(phase_labels) == 1:
        constants["phase_label"] = next(iter(phase_labels))[1]
    if len(declared_units) == 1:
        constants["source_amount_unit"] = next(iter(declared_units))[0]
    pkg = base(
        f"fudoki-budget-{code}",
        f"{srcs[0].jurisdiction_name} {'・'.join(document)}（事業単位）",
        described(
            f"自治体が公開した{'・'.join(document)}データを Fiscal Data Package の形にしたもの。"
            "歳出・歳入のリソースは**原典を正規化しただけで、fudoki の判断を含まない**"
            "（分類・名寄せ・推定を一切していない）。"
            "COFOG の割当と事業名の対応づけは fudoki の判断で、"
            "同じパッケージの別リソースにしてある（budget_line_id などのキーで join する）。"
            "原典そのものは data/budget/raw/ に Parquet で入っている。",
            srcs[0].attribution,
            modifications,
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
                "非正規化した形へ戻すときは、その列を全行に補う。",
                "## 金額の段階と単位\n\n"
                + "\n".join(
                    f"- {name}: "
                    + "、".join(f"{a['phase_label']}（{a['phase']}）は原典の {a['unit']} で、"
                                f"円へ直すには {a['multiplier']} を掛ける"
                                for a in amounts[name])
                    for name in amounts)
                + "\n\n段階が複数ある場合は原典1行を段階ごとの行へ展開してあるので、"
                "主キーは budget_line_id と phase_id の組になる。",
                *([
                    "## 事業名の出所\n\n"
                    "原典の CSV に事業の名称が無いため、市が公開している決算資料 PDF から起こした。"
                    "⚠️ **その PDF は再配布の可否が未確定である**（`licenses` には入れていない）。"
                    "配っているのは抽出した事実（事業名・コード・金額）であって原文の複製ではないが、"
                    "列の出所を辿れるよう `sources` に出典として並べてある。\n\n"
                    + "\n".join(f"- {s['document_title']}" for s in pdfs)
                ] if pdfs else []),
            ],
        ),
        latest_fetch(f"jurisdiction={code}/**/provenance.json"),
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
    pkg["sources"] = ([{"title": s.attribution, "path": s.landing_page} for s in srcs]
                      + [{"title": s["document_title"], "path": s["url"]} for s in pdfs])
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

    pkg["resources"] = []
    for name, title in (("expenditure", "歳出"), ("revenue", "歳入")):
        path = d / f"{name}.csv"
        multi = len(amounts[name]) > 1
        # ⚠️ **主キーは段階の数で変わる。** 決算書は原典1行を段階ごとの行へ展開するので、
        # budget_line_id だけでは一意でない（Table Schema の primaryKey が嘘になる）。
        const = {**constants, "direction": name}
        # ⚠️ **段階が複数あるリソースは、段階と単位を行の列で持っている。**
        # 定数として二重に宣言できない（`schema_for` が実在の列との重複で止める）。
        # 定数にできるのは、段階が1つでその値が全行で同じときだけ。
        if not multi:
            const["phase_label"] = amounts[name][0]["phase_label"]
            const["source_amount_unit"] = amounts[name][0]["unit"]
        verify_against_csv(path, amounts[name])
        pkg["resources"].append(resource(
            path, name, title,
            ("原典1行が1行。判断を含まない" if not multi
             else "原典1行を予算段階ごとの行へ展開している。判断を含まない"),
            ["budget_line_id", "phase_id"] if multi else ["budget_line_id"],
            origin(name), const))

    # ⚠️ **判断のリソースも同じパッケージに入れる。** 以前は `derived/` へ団体をまたいで
    # 置いていたが、畳むと**団体ごとに違うライセンスと出典が1つの表示に潰れる**。
    # 横断は失われない — 各団体の cofog.csv は同じスキーマなので
    # `read_csv('data/budget/datapackages/*/cofog.csv')` で1行で束ねられる。
    for name, title, description, key in present:
        path = d / f"{name}.csv"
        pkg["resources"].append(resource(path, name, title, description, key))
    if (d / "cofog.csv").exists():
        # COFOG の版と出典。**割当列を持つパッケージにだけ置く。**
        pkg["cofog"] = TYPES["cofog"]
    (d / "datapackage.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n")
    print(f"ok  {code}  {len(pkg['resources'])} リソース  {sum(r['bytes'] for r in pkg['resources']):,} バイト")


if __name__ == "__main__":
    # **団体の一覧を手で持たない。** 取得元（sources.toml）と変換の宣言（dbt_project.yml）が
    # それぞれ正本なので、生成対象はその一致として決まる。
    # ⚠️ 以前は3つ目の手書きリスト（IMPLEMENTED）があり、団体を足すたびに3箇所へ登録していた。
    # しかも突き合わせは sources.toml とだけで、**dbt の宣言との食い違いは誰も見ていなかった**。
    registered = {s.jurisdiction_code for s in load_sources().values()}
    declared = set(DBT_VARS["budget_levels"])
    if registered != declared:
        raise SystemExit(
            f"sources.toml の団体 {sorted(registered)} と dbt の宣言 {sorted(declared)} が一致しない。"
            f"配布物を欠けたまま書き出さないため停止する"
        )
    for code in sorted(registered):
        build_jurisdiction(code)
