"""dbt の出力を Fiscal Data Package として配れる形にする。

（CSV は pipeline/.build/builds/<構築ID>/fiscal/ にある）

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

from ingestion.paths import PACKAGES, RAW, INPUT_LOCK
from ingestion.inputs import describe_inputs
from ingestion.fiscal.sources import all_sources, load_project_names, load_revenue_accounts

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
# 原典が名乗るライセンスのうち、CC BY 4.0 として配ってよいもの。
# ⚠️ **「オープンだから同じだろう」で足さない。** 継承条件が違えば下流の義務が変わる。
# 足すときは、その規約の原文が CC BY での利用を許諾していることを確かめて根拠を書く。
CC_BY_COMPATIBLE = {
    "CC-BY-4.0",
    # 公共データ利用規約（第1.0版）。デジタル庁の原文（2026-08-30 実測）に
    # 「本利用ルールは、クリエイティブ・コモンズ・ライセンスの表示4.0 国際ライセンスに
    # 規定される著作権利用許諾条件（以下「CC BY」といいます。）と互換性があります。…
    # 利用者がCC BYに従って利用することを許諾します。」とある。
    # https://www.digital.go.jp/resources/open_data/public_data_license_v1.0
    "PDL-1.0",
}


def licenses_of(srcs: list) -> list[dict]:
    """配布物に貼るライセンス。**取得元の宣言から決める。定数を貼らない。**

    ⚠️ 以前はここが定数の直書きだった。別の関数が値域を守っていたので今のところ
    結果は同じだったが、**「勝手にライセンスを付ける」そのもの**である。
    宣言が変わっても配布物が変わらない状態を残してはいけない。

      原典が CC BY を付けている        → それを素通しする
      原典が CC BY 互換を明示している   → それも素通しする（`CC_BY_COMPATIBLE`）
      原典の利用許諾が未判断（NOASSERTION）**だけ** → **`licenses` を書かない**

    ⚠️ **判断が付いた原典と未判断の原典が混ざる団体では、付いているほうを出す。**
    `licenses` が伝えるのは**下流が負う義務**である。CC BY の原典が1つでも入っていれば、
    下流には帰属・ライセンス表示・改変の明示の義務が実際に生じるので、
    書かないと**義務を伝え損ねる**（未判断だから伏せる、では下流が帰属を落とす）。
    逆に、どの原典も未判断のパッケージには伝えるべき義務がまだ無いので、書かない。
    どのリソースがどの原典から来たかは `sources` と `description` が言う。

    ⚠️ **最後の場合に fudoki のライセンスを貼らない。** 抽出した事実には原典のライセンスが
    付いてこないので、選択と構成にあたる部分を fudoki が CC BY 4.0 で配ることは**できる**。
    だがそれは「配ってよい条件を fudoki が決めた」という主張であって、
    **原典の許諾をまだ判断していない段階でそれを出すと、判断が済んだように読める**。
    `licenses` は Data Package の仕様でも任意なので、決まっていない状態は
    **書かないことで表す**（未定を表す値が仕様に無いため）。決まったら足す。
    """
    known = sorted({s.license_id for s in srcs} - {"NOASSERTION"})
    if any(lic not in CC_BY_COMPATIBLE for lic in known):
        raise SystemExit(
            f"原典のライセンスに {known} が含まれる。CC BY 4.0 以外は継承条件が違いうるので、"
            f"配布物のライセンスを決め直してから配ること"
        )
    return [LICENSE_CC_BY_4] if known else []


# CC BY 4.0 §3(a)(1)(B) が求める「改変した旨」の表示。**descriptor の `description` に書く。**
# ⚠️ 以前は独自の `modified` / `modifications` を足していたが、`modified` は
# **fudoki の配布物がすべて加工物なので常に true** で、情報量が無かった。
# 中身のあるリストのほうは標準の `description`（Markdown 可）に書けば
# 標準しか読まない実装からも読める。義務の伝達を独自フィールドに預けない。
# ⚠️ **やっていない改変を書かない。** 一度、原典1行が複数の予算段階を持つ団体のための
# 「段階ごとの行へ展開した」を全団体共通のリストへ入れており、1行1金額の三鷹市にも付いていた。
# 改変の明示は CC BY が求めているものなので、嘘を書くと表示そのものの信用が落ちる。
# 団体で改変が変わるなら、そのときリストを団体ごとに分けること。
JUDGMENT_RESOURCES = [
    ("tama_settlement_pdf_datasets", "多摩決算PDFの独立観測表", "採用した43独立観測表の識別子・原典・粒度・単位・行数。統制値と原典語は非加算であり財政明細ではない。", ["dataset_id"]),
    ("tama_settlement_pdf_account_names", "多摩決算書の印字科目名", "目×法定節表の印字科目名。原典区画・年度ごとの名称であり法定科目への分類は未確認。財源事業への名前による関係付けはしない。", ["dataset_id", "fund_label", "kan_code", "kou_code", "moku_code"]),
    ("account_names", "科目の名称と法定マスタへの対応（fudoki の判断を含む）",
     "款・項・目の名称のカタログと、法定マスタへの対応。"
     "**対応先は会計で違う**: 一般会計は地方自治法施行規則 別記の区分、"
     "法定の特別会計（国民健康保険・介護保険・後期高齢者医療）は"
     "地方財政状況調査の会計別表の勘定科目。それ以外の特別会計は調査票が無いので"
     "master_* が空のまま。"
     "**款のコードは団体ごとに法定とずれる**（災害復旧費を持たない市では以降が詰まる）ので、"
     "団体をまたぐ比較は canonical_fund と master_kan_code / master_kou_code で行う。"
     "名称の出所（原典 CSV か、事項別明細書 PDF からの抽出か、決算書 PDF から fudoki が解決したか）は name_source が言う",
     ["dataset_id", "fund_code", "fund_label", "kan_code", "kou_code", "moku_code"]),
    ("funds", "会計の名寄せと帳簿上の区分（fudoki の判断）",
     "同じ制度を担う会計の呼び名は団体で違う（「国民健康保険事業特別会計」"
     "「国民健康保険特別会計」）ので、比較は fund_label ではなく canonical_fund で行う。"
     "account_class は帳簿上の区分、sector は普通会計/公営事業会計の枠組み。"
     "**同名の款が会計によって別の科目になる**ことと、**会計間の繰出入を全会計で"
     "合算すると二重計上になる**ことが利用上の注意点（消去の判断は cofog.csv）",
     ["fund_label"]),
    ("interfund_transfers", "会計間移転の宣言（fudoki の判断）",
     "連結消去できると判断した会計間移転の宣言そのもの。"
     "ここにある行が歳出明細で consolidation=eliminated になっている。"
     "宣言が無い繰出入は相手方会計が確定できないため retained のまま",
     ["fiscal_year", "direction", "fund_label", "kan_code", "kou_code",
      "moku_code", "setsu_code", "amount_yen"]),
    ("project_names", "事業名の対応づけ（fudoki の判断）",
     "原典の CSV に事業の名称が無い団体で、決算資料 PDF から起こした名称を"
     "金額で大事業へ対応づけたもの。対応づけの確からしさ（match_method / match_basis / "
     "candidate_count）を併記してある",
     ["fiscal_year", "fund_code", "kan_code", "kou_code", "moku_code", "daijigyo_code"]),
]


TAMA_SETTLEMENT_PDF_RESOURCES = {
    'settlement_expenditure_pdf_legal_setsu': '多摩決算書の目×法定節。原典1行に1行、支出済額は円。下位事業と節の関係は未確認。原典の全観測・位置と反復印字統制値をsource_observation_jsonに保持する。',
    'settlement_expenditure_pdf_project_funding': '多摩令和4年度の細目×財源の独立内訳。支出済額は千円を原単位として保持し、amountは円換算。財源は法定節ではなく目×節との配分・関連づけは未確認。二つの内訳を足さない。',
    'settlement_expenditure_pdf_moku_controls': '非加算の印字目別統制値806行。15予備費目の支出済額0円・節なしを保持する。予算欄は原典観測であり段階を推定しない。明細と合算しない。',
    'settlement_expenditure_pdf_account_controls': '非加算の印字会計総額20行。目×法定節と同じ支出の統制値であり明細と合算しない。',
    'settlement_expenditure_pdf_project_controls': '非加算の印字事業総額404行。細目×財源と同じ支出の統制値であり明細と合算しない。',
}

KOMAE_INITIAL_REFERENCE_RESOURCES = {
    'initial_moku_reference': (["fiscal_line_id"], '旧当初2目の非加算参照。元の原典行・対象ID・千円印字値と円換算額・原典位置をsource_observation_jsonに保持する。authoritativeな全19版7409行のinitial_expenditure_budgetへ足し合わせない。'),
    'initial_target_equivalence': (["budget_item_id"], '非加算の初期対象対応証跡496件。538実補正行と初期行は同年度・同会計・印字経路/事業/担当課/節/sourceGrainのexact一致のみ。両namespaceと原文階層・原典位置を保持し、既存補正対象IDを変更しない。amount_initialは円で表す原典初期額の参照であり初期予算CSVへ重ねて加算しない。141対象/152補正行は対応未確認。'),
}

HOMEPAGE = "https://github.com/wwwyo/fudoki"
INPUT_NOTE = (
    "採用した原典・Parquetのハッシュと保存先、出典・意味の宣言は、"
    "Git管理する `pipeline/ingestion/fiscal/sources.lock.json` にある。"
    "検査結果は固定入力から再生成する検証レポートで確認する。"
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


def field_spec(path: pathlib.Path, name: str, scope: str | None = None) -> dict:
    """列の意味づけを引く。**同じ列名が direction で別の概念になることがある。**

    歳入明細の `setsu_code` は財源の分類だが、会計間の照合表では原典の科目の指定。
    共通の列型を与えると、照合条件を財源の分類として誤って配る。
    そこで `<direction>:<列名>` の宣言があればそちらを先に使う。
    """
    spec = TYPES["fields"].get(f"{scope}:{name}") if scope else None
    if spec is None:
        spec = TYPES["fields"].get(name)
    if spec is None:
        raise RuntimeError(
            f"{path.name} の列「{name}」に ColumnType の宣言が無い。"
            f"fdp/field_types.json に定義を足すこと"
        )
    return dict(spec)


def schema_for(path: pathlib.Path, body: bytes, primary_key: list[str],
               constants: dict[str, object] | None = None, scope: str | None = None) -> dict:
    """列に意味づけを与える。**宣言の無い列は配らない。**

    `constants` は全行同じ値なので CSV の列から外したもの。仕様の
    **Constant Fields**（`extraFields` の各項目に `constant` を持たせる）で表す。
    ⚠️ 独自の `constants` プロパティで持っていたときは、標準しか読まない実装から
    「団体コードも通貨も direction も分からない配布物」に見えていた。
    `extraFields` は定義上「非正規化した形には現れるが原典には無い列」なので、
    **CSV の列は1つも変わらない**（`fiscal_line_id` を含め公開済みの参照は無傷）。
    """
    fields = [field_spec(path, name, scope) for name in header_of(body)]
    extra = []
    for name, value in (constants or {}).items():
        spec = field_spec(path, name, scope)
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
             sources: list[dict] | None = None, constants: dict[str, object] | None = None,
             scope: str | None = None) -> dict:
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
        "schema": schema_for(path, body, primary_key, constants, scope),
    }
    if sources:
        # リソース単位の出所。パッケージ単位の `sources` が「どの資料か」を言うのに対し、
        # ここは**この1ファイルがどの URL から来たか**を言う。
        r["sources"] = sources
    return r



def described(body: str, credits: list[str], modifications: list[str], notes: list[str]) -> str:
    """`description` を組み立てる。**CC BY の義務をここへ集める。**

    ⚠️ 帰属（§3(a)(1)(A)）と改変の明示（§3(a)(1)(B)）に FDP の標準プロパティは無い。
    以前は独自の `attribution` / `modified` / `modifications` に置いていたが、
    独自プロパティは**標準しか読まない実装からは存在しないのと同じ**なので、
    義務の伝達をそこに預けるのは弱かった。
    `description` は Markdown が使える標準プロパティで、必ず人の目に触れる。

    機械可読なほうは標準の置き場に残してある —
    出典の文字列は `sources[].title`、条件は `licenses`、加工者は `contributors`。
    ここはそれを「どう表示してほしいか」に翻訳した一文である。
    """
    # ⚠️ **収録年度で取得元が違う団体がある。** 多摩市は令和3・4年度がカタログ、
    # 令和5〜7年度が市サイトで、原典の名乗りもそれぞれ違う。先頭の1件だけを
    # 「そのまま使うこと」と示すと、**利用者が3年度ぶん誤った帰属を書く**ことになる。
    # 1件しか無い団体の見え方は変えない（三鷹市・狛江市はここを通っても1行のまま）。
    if len(credits) == 1:
        credit_note = f"次の一文をそのまま使うこと。\n\n> {credits[0]}\n\n"
    else:
        credit_note = (
            "**収録した年度で原典の取得元が違うので、出典表示も1つではない。**\n"
            "使った年度に対応する次の一文をそのまま使うこと"
            "（全年度を使うなら全部を並べる）。\n\n"
            + "".join(f"> {c}\n>\n" for c in credits)
            + "\n"
        )
    parts = [
        body,
        "## 出典表示（CC BY 4.0 §3(a)(1)(A)）\n\n"
        + credit_note
        + "機械可読な同じ内容は `sources[].title`（原典）と `contributors`（加工者）にある"
        "（並びは収録年度の順）。",
        "## 改変（CC BY 4.0 §3(a)(1)(B)）\n\n"
        "原典に対して次のことをしている。\n\n"
        + "\n".join(f"- {m}" for m in modifications)
        + "\n\n原典 CSV/PDF のバイト列と、取り込み済み Parquet を別々に非公開 R2 へ保管する。固定した原典版と表の対応を入力一覧から辿れる。",
        *notes,
    ]
    return "\n\n".join(parts)


def base(name: str, title: str, description: str) -> dict:
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
        "countryCode": "JP",
        # 仕様の「_ColumnType_ definition package」。**パッケージ直下が仕様どおりの置き場**で、
        # リソース側の `schema.fields[].columnType`（単数）が個々の列をここへ結び付ける。
        # 両方あるのは重複ではなく、宣言と参照の関係である。
        "columnTypes": TYPES["columnTypes"],
        "fudoki": TYPES["fudoki"],
    }


def build_jurisdiction(code: str, inputs: list[dict] | None = None) -> None:
    """dbt が確定したリソースに列定義・原典・利用条件を付ける。"""
    directory = PACKAGES / code
    registered_sources = all_sources()
    sources = [source for source in registered_sources.values() if source.jurisdiction_code == code]
    pkg = base(f"fudoki-{code}", f"風土記 {code} の財政データ", "決算の実績と当初予算・変更履歴を別リソースとして提供する。")
    licenses = licenses_of(sources)
    if licenses:
        pkg["licenses"] = licenses
    pdfs = [entry for table in (load_project_names(), load_revenue_accounts()) for key, entry in table.items() if key.startswith(code + ":")]
    credits = list(dict.fromkeys(source.attribution for source in sources))
    pkg["sources"] = [{"title": source.attribution, "path": source.landing_page} for source in sources] + [{"title": entry["document_title"], "path": entry["url"]} for entry in pdfs]
    pkg["contributors"] = [{"title": "風土記", "path": HOMEPAGE, "role": "wrangler"}]
    pkg["description"] = described(pkg["description"], credits, ["列名・コード・名称を整理した", "金額を円へ正規化し、決算の実績と当初予算を別リソースに分けた", "分類・会計・科目・事業の対応を風土記の判断として付け加えた"], [INPUT_NOTE])
    pkg["resources"] = []
    provenance = inputs if inputs is not None else [item['source'] for item in describe_inputs(INPUT_LOCK) if item['source']['jurisdiction_code'] == code]
    for index, entry in enumerate(provenance):
        if entry.get("namespace") != "held5-council-approved-detail":
            continue
        source = registered_sources[entry["source_key"]]
        matches = [item for item in source.resources if item.table_id == entry["table_id"]
                   and item.url == entry["request_url"] and item.direction == "expenditure"]
        if (len(matches) != 1 or source.fiscal_year != entry["fiscal_year"]
                or source.jurisdiction_code != entry["jurisdiction_code"]
                or source.document_kind != "supplementary"):
            raise RuntimeError("保留補正の証跡と登録原典の範囲が一致しない")
        # The immutable provenance uses its own format; descriptor context comes
        # from the exact registered original, without rewriting that evidence.
        provenance[index] = {**entry, "direction": matches[0].direction,
                             "document_kind": source.document_kind,
                             "document_title": source.document_label}
    aux_keys = {name: key for name, _, _, key in JUDGMENT_RESOURCES}
    for path in sorted(directory.glob("*.csv")):
        name = path.stem
        direction = "revenue" if "revenue" in name else "expenditure" if "expenditure" in name else None
        constants = {"jurisdiction_code": code}
        with path.open("rb") as header_stream:
            header = header_of(header_stream.readline())
        if code == "132195" and name in KOMAE_INITIAL_REFERENCE_RESOURCES:
            key, description = KOMAE_INITIAL_REFERENCE_RESOURCES[name]
            direction = "expenditure"
            constants.update(direction=direction, document_kind="budget", currency="JPY")
        elif code == "132195" and name == "supplementary_moku_reference_observations":
            key = ["fiscal_line_id"]
            direction = "expenditure"
            constants.update(direction=direction, document_kind="supplementary", currency="JPY")
            description = ("旧補正102目の非加算参照。印字文字列・原単位の整数・原典行ID・頁・位置と採用判断を保持する。"
                           "amount_deltaのみ円換算。正準の事業×節の補正へ重ねて加算しない。"
                           "superseded_by_detailは同年度・会計・補正号の明細を採用した状態を表す。")
        elif code == "132195" and name == "held5_raw_detail":
            key = ["fiscal_line_id"]
            direction = "expenditure"
            constants.update(direction=direction, document_kind="supplementary", currency="JPY")
            description = ("承認済み補正5版241行の原典観測52列を保持する非加算参照。"
                           "amount_deltaとproject_printed_deltaは原典の千円単位で、円へ換算していない。"
                           "変更額の円換算値はexpenditure_budget_changes.csvにあり、この参照を加算しない。"
                           "提出日・議決日・効力発生日を区別し、未確認値はNULL。")
        elif name.endswith("_budget_items"):
            key = ["budget_item_id"]
            description = "年度内の予算対象。当初額の確認状態と、科目・事業経路・追加区分・名称を保持する。歳出は expenditure_setsu_id と粒度（line_granularity）を持つ。"
        elif name.endswith("_budget_changes"):
            key = ["change_id"]
            description = "各補正・繰越・予備費充用・流用の増減額。空の場合は変更がゼロと確定した意味ではない。"
        elif name.endswith("_settlement_links"):
            key = ["budget_item_id", "settlement_line_id"]
            description = "予算対象と決算明細の対応。対応未確認を区別し、金額を複製しない。"
        elif name == "initial_expenditure_budget":
            key = ["fiscal_line_id"]
            constants.update(direction=direction, document_kind="budget", currency="JPY")
            description = ("一明細・一金額。当初予算の基準額。対応を確かめた明細は事業と歳出の節の組合せへ集約し（line_granularity=expenditure_setsu）、"
                           "節より下の内訳と原典行の対応は details_json に保持する。節が確かめられない行は原典行の粒度（origin_line）。"
                           "expenditure_setsu_id は fiscal_expenditure_setsu_master（Git の定義）を指し、原典の節コードとは別物。"
                           "原典の報告値と単位は取り込み表とローカル検証記録に残す。予算履歴の復元・照合は未確認。")
            if code == "132195":
                description += " 狛江市FY2023〜2026の承認済み当初19会計版は全7409原典行で、7393法定節と16空白コードreserveを保持する。旧2目は非加算参照。496補正対象のexact初期対応は別証跡で、未確認141対象へゼロを作らない。"
        elif code == "132241" and name in TAMA_SETTLEMENT_PDF_RESOURCES:
            key = ["fiscal_line_id"]
            constants.update(direction="expenditure", document_kind="settlement", currency="JPY")
            description = TAMA_SETTLEMENT_PDF_RESOURCES[name]
        elif name.startswith("settlement_") or name.startswith("initial_"):
            key = ["fiscal_line_id"]
            constants.update(direction=direction, document_kind="settlement" if name.startswith("settlement_") else "budget", currency="JPY")
            description = "一明細・一金額。決算なら支出済額または収入済額、当初予算なら基準額。原典の報告値と単位は取り込み表とローカル検証記録に残す。予算履歴の復元・照合は未確認。"
        else:
            key = aux_keys[name]
            description = next(description for resource_name, _, description, _ in JUDGMENT_RESOURCES if resource_name == name)
            description = description.replace("cofog.csv", "歳出明細の分類列")
        if "cofog_code" in header:
            description += " COFOG の分類コード・状態・根拠は風土記の判断として同じ明細に含める。分類規則と規則 ID は Git と検証記録に保持する。"
        constants = {key: value for key, value in constants.items() if key not in header}
        seen = set()
        with path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                identity = tuple(row[column] for column in key)
                if identity in seen:
                    raise RuntimeError(f"{path.name}: duplicate primary key")
                seen.add(identity)
                if any(column in row and abs(int(row[column])) > 2**53-1 for column in ("amount", "amount_delta")):
                    raise RuntimeError(f"{path.name}: amount is not an exact integer")
        kind = "settlement" if name.startswith("settlement_") else "budget" if name.startswith("initial_") else None
        origins = [{"title": f"{entry['fiscal_year']}年度／{entry.get('resource_name') or entry.get('document_title')}", "path": entry["request_url"]} for entry in provenance if (direction is None or entry["direction"] == direction) and (kind is None or entry.get("document_kind", next(source.document_kind for source in sources if source.fiscal_year == entry["fiscal_year"])) == kind)]
        if code == "132195" and name in ("initial_expenditure_budget", "initial_target_equivalence"):
            origins = [{"title": entry["document_title"], "path": entry["request_url"]}
                       for entry in provenance if entry.get("observation_role") == "authoritative-initial-detail"]
        elif code == "132195" and name == "initial_moku_reference":
            origins = [{"title": f"{entry['fiscal_year']}年度 当初2目の非加算原典参照", "path": entry["request_url"]}
                       for entry in provenance if entry.get("table_id") == "expenditure-detail" and entry.get("document_kind") == "budget"]
        elif code == "132195" and name == "supplementary_moku_reference_observations":
            origins = [{"title": f"{entry['fiscal_year']}年度 補正目の非加算原典参照", "path": entry["request_url"]}
                       for entry in provenance if entry.get("table_id") == "expenditure-detail" and entry.get("document_kind") == "supplementary"]
        elif code == "132195" and name == "held5_raw_detail":
            origins = [{"title": entry["document_title"], "path": entry["request_url"]}
                       for entry in provenance if entry.get("namespace") == "held5-council-approved-detail"]
        if name == "project_names":
            origins.extend({"title": entry["document_title"], "path": entry["url"]} for entry in pdfs)
        if direction and any(entry.get("raw_form") == "extracted" for entry in provenance if entry["direction"] == direction):
            description += " 原典 PDF の抽出は不可逆であり、組版内の合計などによる検査は再生成する検証レポートで確認する。"
        field_scope = "held5-raw" if code == "132195" and name == "held5_raw_detail" else direction
        pkg["resources"].append(resource(path, name, name, description, key, origins, constants, field_scope))
    (directory / "datapackage.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n")
    print(f"ok {code} {len(pkg['resources'])} resources")


if __name__ == "__main__":
    registered = {source.jurisdiction_code for source in all_sources().values()}
    if registered != set(DBT_VARS["fiscal_levels"]):
        raise SystemExit("Ingestion jurisdictions differ from dbt declarations")
    inputs = describe_inputs(INPUT_LOCK)
    for code in sorted(registered):
        build_jurisdiction(code, [item['source'] for item in inputs if item['source']['jurisdiction_code'] == code])
