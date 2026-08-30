"""取得元の定義を `sources.toml` から読む。

TOML を正にしているのは、Python（tomllib）と Bun の両方が依存なしで読めるため。
定義を2言語で二重持ちすると、片方だけ直して気づかない状態を作る。
"""

from __future__ import annotations

import tomllib
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from ingestion.shared.jurisdictions import jurisdiction_name as _jurisdiction_name

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

    # ⚠️ **カタログを介さず直接取りに行く URL。既定では使わない。**
    #
    # 通常はデータセット名とリソース名から CKAN で解決する。リソース URL は自治体の CMS が
    # 振る内部番号で資料の差し替えのたびに動くのに対し、名前のほうは安定しているためである。
    # ここに URL を書くと、その安定性を捨てて自治体の URL 設計に賭けることになる。
    #
    # それでも要るのは、**原典は公開されているのにカタログへ登録されていない**場合。
    # 多摩市は市サイトに令和7年度まで同じ書式の CSV を置いているが、カタログの登録は
    # 令和4年度で止まっており、名前から解決する経路では届かない。
    #
    # ⚠️ **年度の照合が取得時にできなくなる。** カタログ経由なら「リソース名に年度表記が
    # 含まれること」を取得の前に見ているが、直 URL では resource_name が fudoki の書いた
    # 文字列なので自己参照になり検査にならない。年度が合っているかは原典の年度列と
    # partition の突き合わせ（dbt の source_year_matches_partition）に移る。
    # **その検査が無い団体でこれを使うと、年度の裏づけがどこにも無くなる。**
    url: str | None = None
    # なぜカタログを外れるのか。**URL を書くなら理由も書く**（書かないと停止する）。
    # 理由が無いと、後から読んだ者に「カタログにあるのに横着した」のと区別が付かない。
    url_basis: str | None = None

    def __post_init__(self) -> None:
        if self.url is not None and not self.url_basis:
            raise ValueError(
                f"{self.resource_name}: url を宣言するなら url_basis も書くこと"
                f"（カタログから解決できない理由が要る）"
            )
        # ⚠️ **読まれない宣言を残さない。** url を書いた時点でカタログは一度も引かれないので、
        # データセット名は解決にも証跡にも使われない。残すと「カタログのこのデータセットから
        # 取った」と読めてしまい、実際には市サイトから取っている、という嘘になる。
        if self.url is not None and self.dataset_title is not None:
            raise ValueError(
                f"{self.resource_name}: url を宣言したリソースに dataset_title は書かない"
                f"（カタログを引かないので、どこからも読まれない宣言になる）"
            )
        if self.url is not None:
            # ⚠️ **前方一致で見ない。** `https://` だけの文字列も、改行を挟んだ値も、
            # 認証情報を埋めた URL も通ってしまう。取得の宛先は証跡に残り配布物の
            # `sources` にも出るので、形が壊れたものを黙って通さない。
            parsed = urllib.parse.urlparse(self.url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(f"{self.resource_name}: url は https の絶対 URL のみ（{self.url}）")
            if parsed.username or parsed.password:
                raise ValueError(f"{self.resource_name}: url に認証情報を書かない（{self.url}）")
            if any(c in self.url for c in " \t\r\n"):
                raise ValueError(f"{self.resource_name}: url に空白や改行が入っている（{self.url!r}）")


@dataclass(frozen=True)
class Source:
    key: str
    # ⚠️ **カタログを引かない取得元がある。** 全リソースが `url` を宣言していれば
    # CKAN は一度も叩かれないので、カタログの宣言は読まれない。
    # 読まれない宣言を残すと「カタログから取った」と読めてしまうので、`load_sources` が
    # 「全リソースが直 URL なら catalog を書いてはいけない」を強制する。
    catalog: Catalog | None
    jurisdiction_code: str
    # ⚠️ **sources.toml には書かない。** `jurisdiction_code` から
    # `ingestion/shared/jurisdictions.json` を引いて load_sources が埋める。
    # 団体の名称と識別子はそこが正本（①②③で同じキーを使う）。
    jurisdiction_name: str
    fiscal_year: int
    # ⚠️ **カタログ経由のときだけ読まれる。** 年度表記がリソース名に含まれることを
    # 取得の前に確かめるためのもので、直 URL では照合が自己参照になるので使わない。
    # 全リソースが直 URL のブロックでは `load_sources` が「書いてはいけない」を強制する
    # （読まれない宣言は、読まれていることと区別が付かない）。
    fiscal_year_label: str | None
    phase_id: str
    phase_label: str
    # 取得元に1つしかデータセットが無いときの既定。リソース側の宣言が優先する。
    dataset_title: str | None
    encoding: str
    # ⚠️ **金額の単位は持たない。** (団体, 年度) の粒度では direction や段階で
    # 単位が割れる団体を表せず、`budget_amounts` との突き合わせも粗くなる。
    # 単位の正本は `dbt/dbt_project.yml` の `budget_amounts`
    # （検査は dbt/macros/check_budget_amount_units.sql）。
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

    def dataset_title_for(self, resource: Resource) -> str | None:
        """そのリソースを載せているデータセット名。リソース側の宣言が優先する。

        ⚠️ **直 URL のリソースには存在しない（None を返す）。** カタログを引かないので
        載せているデータセットが無く、資料の在り処は `landing_page` が持つ。
        以前はここが取得元の既定（カタログのデータセット名）を返しており、
        **市サイトから取ったものの証跡に、引いてもいないカタログのデータセット名が
        載っていた**（配布物の `sources[].title` にもそのまま出ていた）。
        """
        if resource.url is not None:
            return None
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
        catalog_name = spec.pop("catalog", None)
        spec.setdefault("dataset_title", None)
        resources = tuple(Resource(**r) for r in spec.pop("resources"))
        if not resources:
            raise ValueError(f"{key}: リソースが1つも無い")
        # ⚠️ **カタログの宣言は、カタログを引くときだけ書く。**
        # 全リソースが直 URL なら CKAN は一度も叩かれないので、`catalog` も
        # `dataset_title` もどこからも読まれない。残すと後から読んだ者が
        # 「カタログから取った」と誤読し、証跡もそう読める文字列を持ってしまう。
        spec.setdefault("fiscal_year_label", None)
        via_catalog = [r for r in resources if r.url is None]
        # カタログを引くなら要る宣言／引かないなら書いてはいけない宣言。**同じ集合の裏表**。
        # ⚠️ **CKAN 解決でしか読まれない宣言をここに漏らさない。**
        # `resource_url_contains` は同名データセットが複数当たったときの絞り込みで、
        # 直 URL では一度も参照されない。漏らすと「全直 URL ならカタログ専用の宣言を
        # 残さない」という不変条件に穴が開く。
        catalog_only = {"catalog": catalog_name,
                        "dataset_title": spec["dataset_title"],
                        "fiscal_year_label": spec["fiscal_year_label"],
                        "resource_url_contains": spec.get("resource_url_contains")}
        if via_catalog:
            for name in ("catalog", "fiscal_year_label"):
                if catalog_only[name] is None:
                    raise ValueError(
                        f"{key}: カタログから解決するリソースがあるのに {name} の宣言が無い"
                    )
        else:
            dead = sorted(n for n, v in catalog_only.items() if v is not None)
            if dead:
                raise ValueError(
                    f"{key}: 全リソースが url を宣言しているのに {dead} が残っている。"
                    f"カタログを一度も引かないので、どこからも読まれない宣言になる"
                )
        if catalog_name is not None and catalog_name not in catalogs:
            raise ValueError(f"{key}: カタログ「{catalog_name}」が未定義")
        # ⚠️ **TOML に書かれていたら止める。** 既定値で上書きすると、
        # 誤記を黙って直したのか宣言が効いていないのかを読み手が区別できない。
        if "jurisdiction_name" in spec:
            raise ValueError(
                f"{key}: jurisdiction_name は sources.toml に書かない。"
                f"団体の名称は ingestion/shared/jurisdictions.json が正本で、"
                f"jurisdiction_code から引く"
            )
        sources[key] = Source(
            key=key,
            catalog=catalogs[catalog_name] if catalog_name is not None else None,
            resources=resources,
            jurisdiction_name=_jurisdiction_name(spec["jurisdiction_code"]),
            **spec,
        )
    return sources


def load_catalogs(path: Path = SOURCES_TOML) -> dict[str, Catalog]:
    """カタログの宣言だけを引く。**取得元を1つも読まずに宛先を知りたいときのため。**

    ⚠️ 粒度の調査（`check_granularity.py`）が CKAN の宛先と団体コードの解決規則を
    自前のリテラルで持っていた。同じ事実が2箇所にあると、カタログを足したり
    宛先が変わったりしたときに調査だけが古いカタログを見続ける。
    """
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return {name: Catalog(**spec) for name, spec in raw.get("catalog", {}).items()}


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
    return _pdf_sources("project_names", path)


def load_revenue_accounts(path: Path = SOURCES_TOML) -> dict[str, dict]:
    """歳入の科目名称の取得元（決算資料の歳入事項別明細）。`[revenue_accounts]` 節"""
    return _pdf_sources("revenue_accounts", path)


def _pdf_sources(section: str, path: Path) -> dict[str, dict]:
    """PDF 系の取得元。**キーの団体コードを registry と突き合わせる。**

    ⚠️ **CKAN 側（load_sources）だけを registry に通しても足りない。** こちらは
    `"132195:2023"` のキー自体が partition の団体コードになるので、誤記のまま
    `data/budget/raw/**/jurisdiction=132159/` のような未知の団体の区画へ書けてしまう。
    名称を引く経路が無い分、CKAN 側より検知が遅れる。
    """
    section_raw = tomllib.loads(path.read_text(encoding="utf-8")).get(section, {})
    for key in section_raw:
        code = key.split(":")[0]
        _jurisdiction_name(code)      # 未登録なら KeyError
    return section_raw
