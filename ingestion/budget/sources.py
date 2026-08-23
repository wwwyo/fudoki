"""取得元の定義を `sources.toml` から読む。

TOML を正にしているのは、Python（tomllib）と Bun の両方が依存なしで読めるため。
定義を2言語で二重持ちすると、片方だけ直して気づかない状態を作る。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_TOML = Path(__file__).resolve().parent / "sources.toml"


@dataclass(frozen=True)
class Catalog:
    """CKAN カタログ。団体の解決規則はカタログごとに違うのでここに閉じる"""

    endpoint: str
    org_prefix: str


@dataclass(frozen=True)
class Resource:
    direction: str
    resource_name: str
    # データセット名。**団体によって歳出と歳入が別データセットになる**
    # （三鷹市は1データセットに2リソース、狛江市は歳出と歳入で別）。
    # 省略したときは取得元の `dataset_title` を使う。
    dataset_title: str | None = None


@dataclass(frozen=True)
class Source:
    key: str
    catalog: Catalog
    jurisdiction_code: str
    jurisdiction_name: str
    fiscal_year: int
    fiscal_year_label: str
    phase_id: str
    phase_label: str
    # 取得元に1つしかデータセットが無いときの既定。リソース側の宣言が優先する。
    dataset_title: str | None
    encoding: str
    # 原典の金額の単位と、円へ直す倍率。**取得元ごとに違う**（encoding と同じ原典の性質）。
    # ⚠️ 以前は倍率が fdp/field_types.json の**全団体共通の**フィールド宣言に入っており、
    # 単位が円の団体を足すと「円に直すには 1000 を掛ける」がその団体の配布物にも付いた。
    # 金額の誤読を誘う種類の食い違いで、止める機構が無かった。
    source_amount_unit: str
    source_amount_multiplier: int
    redistribute: str
    redistribute_basis: str
    license_id: str
    attribution: str
    landing_page: str
    resources: tuple[Resource, ...]
    # 同名のデータセットが複数ある取得元で、どのリソース URL を採るかを絞る部分文字列。
    # ⚠️ **黙って先頭を採らない。** 狛江市は `/komae/R05/` と `/komae/` に
    # 同名のデータセットがあり、中身が違う（所属名称の改称、執行率の表記）。
    # 指定が無いまま複数当たれば取得は止まる（fetch.resolve_resource）。
    resource_url_contains: str | None = None

    # `data/budget/raw/` に何を置くか。**ここがこの宣言の正本**（文書は要約）。
    #
    #   verbatim   原文そのもの。復号の可逆性と原文の復元を検査できる。
    #              置けるのは redistribute=allow のときだけ（下の不変条件）
    #   extracted  原文から抽出した事実。**不可逆**なので復元は検査できない。
    #              再現性の保証は「証跡と抽出コードから取り直せること」に変わる
    #
    # ⚠️ dbt の原典突合の検査（staging_is_one_to_one / canonical_preserves_source /
    # package_preserves_source）は raw が原文であることを前提にしている。
    # extracted を通すときは、その3本を分岐させるか別の検査に差し替える必要がある。
    raw_form: str = "verbatim"

    def __post_init__(self) -> None:
        # ⚠️ **値も検証する。** `alow` のような綴り違いが通ると、
        # 再配布の判断を見ない経路（extracted）ではそのまま権利表示まで流れる。
        if self.redistribute not in ("allow", "review", "deny"):
            raise ValueError(f"{self.key}: redistribute は allow / review / deny（{self.redistribute}）")
        if not self.license_id:
            raise ValueError(f"{self.key}: license_id が空。不明なら NOASSERTION と書くこと")
        if not self.redistribute_basis:
            raise ValueError(f"{self.key}: redistribute_basis が空。判断の根拠を書くこと")
        if self.source_amount_multiplier < 1:
            raise ValueError(f"{self.key}: source_amount_multiplier は1以上（{self.source_amount_multiplier}）")
        if self.raw_form not in ("verbatim", "extracted"):
            raise ValueError(f"{self.key}: raw_form は verbatim か extracted（{self.raw_form}）")
        # ⚠️ **原文を置けるのは再配布可のときだけ。**
        # 抽出した事実（事業名・金額・コード）は著作物ではないので配れるが、
        # 原文そのものは別で、再配布可と判定できていなければ置けない。
        # ⚠️ **ライセンスが未確定の原文は置けない。**
        # 置くと、配布物にライセンスを貼る段で fudoki が勝手に条件を決めることになる。
        # 抽出した事実なら原典のライセンスが付いてこないので問題にならないが、原文は別。
        if self.raw_form == "verbatim" and self.license_id == "NOASSERTION":
            raise ValueError(
                f"{self.key}: license_id=NOASSERTION なのに raw_form=verbatim。"
                f"ライセンスが未確定の原文はリポジトリへ置けない（抽出した事実なら置ける）"
            )
        if self.raw_form == "verbatim" and self.redistribute != "allow":
            raise ValueError(
                f"{self.key}: redistribute={self.redistribute} なのに raw_form=verbatim。"
                f"原文をリポジトリへ置けるのは再配布可と判定した取得元だけ"
            )

    def dataset_title_for(self, resource: Resource) -> str:
        """そのリソースを載せているデータセット名。リソース側の宣言が優先する"""
        title = resource.dataset_title or self.dataset_title
        if title is None:
            raise ValueError(
                f"{self.key}: {resource.direction} のデータセット名が取得元にもリソースにも無い"
            )
        return title
    @property
    def may_publish_verbatim(self) -> bool:
        """**原文そのもの**をリポジトリへ置いてよいか。

        ⚠️ **「配布物を作ってよいか」ではない。** 抽出した事実は著作物ではないので、
        ここが False でも配布物は作れる（著作権法2条1項1号は著作物を
        「思想又は感情を創作的に表現したもの」と定義しており、事業名と金額はそれにあたらない）。
        止まるのは原文の複製だけである。

        根拠は `redistribute_basis`（①予算はカタログのライセンス）。
        ③会議録の gate（`ingestion/transcripts/gates.json`）とは根拠が違うので繋がない —
        三鷹市は会議録が review だが予算は CC BY で、繋ぐと予算が止まる。
        「公開されている」ことは「再配布してよい」ことを意味しない。
        """
        return self.redistribute == "allow"


def load_sources(path: Path = SOURCES_TOML) -> dict[str, Source]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    catalogs = {name: Catalog(**spec) for name, spec in raw.pop("catalog", {}).items()}
    # 事業名・歳入科目名の取得元は別の形（PDF とページ範囲）なので Source として読まない。
    # 正本は同じ TOML に置く — 取得元の宣言が2ファイルに割れるほうが見落とす。
    raw.pop("project_names", None)
    raw.pop("revenue_accounts", None)

    sources: dict[str, Source] = {}
    for key, spec in raw.items():
        spec = dict(spec)
        catalog_name = spec.pop("catalog")
        if catalog_name not in catalogs:
            raise ValueError(f"{key}: カタログ「{catalog_name}」が未定義")
        spec.setdefault("dataset_title", None)
        resources = tuple(Resource(**r) for r in spec.pop("resources"))
        if not resources:
            raise ValueError(f"{key}: リソースが1つも無い")
        sources[key] = Source(key=key, catalog=catalogs[catalog_name], resources=resources, **spec)
    return sources


def resolve(key: str) -> Source:
    sources = load_sources()
    if key not in sources:
        available = ", ".join(sorted(sources)) or "(無し)"
        raise KeyError(f"取得元「{key}」が未定義。定義済み: {available}")
    return sources[key]


def load_project_names(path: Path = SOURCES_TOML) -> dict[str, dict]:
    """事業名の取得元（PDF）。`sources.toml` の `[project_names]` 節。

    ⚠️ **`Source` には乗らない。** PDF とページ範囲と列の x 範囲という別の形なので、
    CKAN の取得元と同じデータクラスにすると片方に無い項目が任意だらけになる。
    ただし権利の語彙（`raw_form` / `redistribute` / `license_id`）は揃えてあり、
    証跡にも同じキーで記録している。

    ⚠️ **同じ toml を3箇所で開いていた**（抽出器・記述子の生成・この module）。
    取得元の宣言を読む入口は1つにする。
    """
    return tomllib.loads(path.read_text(encoding="utf-8")).get("project_names", {})


def load_revenue_accounts(path: Path = SOURCES_TOML) -> dict[str, dict]:
    """歳入の科目名称の取得元（決算資料の歳入事項別明細）。`[revenue_accounts]` 節"""
    return tomllib.loads(path.read_text(encoding="utf-8")).get("revenue_accounts", {})
