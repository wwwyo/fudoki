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
    dataset_title: str
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

    sources: dict[str, Source] = {}
    for key, spec in raw.items():
        spec = dict(spec)
        catalog_name = spec.pop("catalog")
        if catalog_name not in catalogs:
            raise ValueError(f"{key}: カタログ「{catalog_name}」が未定義")
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
