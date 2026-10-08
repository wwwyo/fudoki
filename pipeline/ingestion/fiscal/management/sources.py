"""原典台帳 `sources.json` の取り込み宣言を、取得器の型へ変換する。

明示的な旧TOML入力は固定時の宣言を読み直す用途に限る。通常取得は台帳を使う。
"""

from __future__ import annotations

from importlib import import_module as _ingestion_module

import tomllib
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from ingestion.shared.jurisdictions import jurisdiction_name as _jurisdiction_name
from ingestion.fiscal.management.source_registry import PDF_SECTIONS, load_registry, project_sources

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SOURCES_JSON = Path(__file__).resolve().parent / "sources.json"


def _declarations(path: Path) -> dict:
    if path.suffix == ".toml":
        return tomllib.loads(path.read_text(encoding="utf-8"))
    return project_sources(load_registry(path))


@dataclass(frozen=True)
class Catalog:
    """CKAN カタログ。団体の解決規則はカタログごとに違うのでここに閉じる"""

    endpoint: str
    org_prefix: str


@dataclass(frozen=True)
class Resource:
    direction: str | None
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
    # 同一PDF中の会計・独立内訳を区別する。既存の無指定入力のIDは維持する。
    table_id: str | None = None

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
    # ⚠️ **原典別の取り込み宣言には書かない。** `jurisdiction_code` から
    # `packages/jurisdictions/jurisdictions.json` を引いて load_sources が埋める。
    # 団体の名称と識別子はそこが正本（財政データ・調達で同じキーを使う）。
    jurisdiction_name: str
    fiscal_year: int
    # ⚠️ **カタログ経由のときだけ読まれる。** 年度表記がリソース名に含まれることを
    # 取得の前に確かめるためのもので、直 URL では照合が自己参照になるので使わない。
    # 全リソースが直 URL のブロックでは `load_sources` が「書いてはいけない」を強制する
    # （読まれない宣言は、読まれていることと区別が付かない）。
    fiscal_year_label: str | None
    document_kind: str
    document_label: str
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

    # `pipeline/.cache/` 配下の `raw/` に何を置くか。**ここがこの宣言の正本**（文書は要約）。
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
        「公開されている」ことは「再配布してよい」ことを意味しない。
        """
        return self.redistribute == "allow"


def load_sources(path: Path = SOURCES_JSON) -> dict[str, Source]:
    raw = _declarations(path)
    catalogs = {name: Catalog(**spec) for name, spec in raw.pop("catalog", {}).items()}
    # 事業名・歳入科目名の取得元は別の形（PDF とページ範囲）なので Source として読まない。
    # 正本は同じ原典台帳に置く — 取得元の宣言が2ファイルに割れるほうが見落とす。
    for section in PDF_SECTIONS:
        raw.pop(section, None)

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
        # ⚠️ **取り込み宣言に書かれていたら止める。** 既定値で上書きすると、
        # 誤記を黙って直したのか宣言が効いていないのかを読み手が区別できない。
        if "jurisdiction_name" in spec:
            raise ValueError(
                f"{key}: jurisdiction_name は原典別の取り込み宣言に書かない。"
                f"団体の名称は packages/jurisdictions/jurisdictions.json が正本で、"
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


def statement_sources(path: Path = SOURCES_JSON) -> dict[str, Source]:
    """事項別明細書の取得元を `Source` の語彙へ畳む。**配布物の側が使う。**

    ⚠️ **`load_sources()` には混ぜない。** そちらは CSV の取得器（`fetch.py`）が回す集合で、
    混ぜると原文をそのまま置く取得器が PDF を掴んで落ちる（`raw_form != verbatim` で停止する）。
    取得の経路は分かれているが、**配布物から見た「取得元」は同じ概念**（誰の資料を、どの許諾で、
    どの入口から取ったか）なので、descriptor を組む側には同じ形で渡す。

    ⚠️ **CKAN 固有の項目は持たない。** カタログも `fiscal_year_label` も
    `dataset_title` も無い（カタログを一度も引かないので、書けば読まれない宣言になる）。
    """
    out: dict[str, Source] = {}
    for key, spec in load_statements(path).items():
        code, year, *_ = key.split(":")
        out[f"statement:{key}"] = Source(
            key=f"statement:{key}",
            catalog=None,
            jurisdiction_code=code,
            jurisdiction_name=_jurisdiction_name(code),
            fiscal_year=int(year),
            fiscal_year_label=None,
            document_kind=spec["document_kind"],
            document_label=spec["document_label"],
            dataset_title=None,
            # PDF はテキストの文字コードを持たない。CSV の取得器だけが読む項目なので空にする
            encoding="",
            redistribute=spec["redistribute"],
            redistribute_basis=spec["redistribute_basis"],
            license_id=spec["license_id"],
            attribution=spec["attribution"],
            landing_page=spec["landing_page"],
            raw_form=spec["raw_form"],
            resources=tuple(
                Resource(direction=direction, resource_name=spec["document_title"],
                         url=spec["url"], url_basis=spec["url_basis"], table_id=spec.get('table_id'))
                for direction in sorted(spec["pages"])
            ) + ((Resource(direction='expenditure', resource_name=spec['document_title'] + '（目×節の独立内訳）',
                           url=spec['url'], url_basis=spec['url_basis'],
                           table_id=spec['observed_moku_setsu_table_id']),)
                 if spec.get('observed_moku_setsu_table_id') else ()),
        )
    return out


def all_sources(path: Path = SOURCES_JSON) -> dict[str, Source]:
    """収録済みの取得元すべて。**配布物と検査の母集団はこちら。**

    ⚠️ 取得器ごとの集合（`load_sources` / `statement_sources`）を母集団にすると、
    経路を増やすたびに「その経路だけ誰も見ていない」団体が生まれる。
    """
    from ingestion.fiscal.layouts.fiscal_general.initial_detail_provider import initial_detail_sources
    initial = initial_detail_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    council_approved_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.council_approved_provider').council_approved_sources
    council = council_approved_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    native_council_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.native_council_provider').native_council_sources
    native = native_council_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    native_settlement_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_native_settlement.registration').native_settlement_sources
    native_settlement = native_settlement_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    initial445_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_initial445_registry').initial445_sources
    initial445 = initial445_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    held5_council_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.held5_council_provider').held5_council_sources
    held5 = held5_council_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    settlement2024_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_settlement2024_registry').settlement2024_sources
    settlement2024 = settlement2024_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    native_budget_sources = _ingestion_module('ingestion.fiscal.jurisdictions.131016.layouts.chiyoda2025_native.registration').native_budget_sources
    chiyoda2025 = native_budget_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    native_settlement_sources = _ingestion_module('ingestion.fiscal.jurisdictions.131016.layouts.chiyoda2021_settlement_native.registration').native_settlement_sources
    chiyoda2021settle = native_settlement_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    settlement2020_2023_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_settlement2020_2023_registry').settlement2020_2023_sources
    settlement2020_2023 = settlement2020_2023_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    pre2020_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_pre2020.registration').pre2020_sources
    pre2020 = pre2020_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    komae_recovered_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.komae_recovered_provider').komae_recovered_sources
    komae_recovered = komae_recovered_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    settlement2019_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_settlement2019_registry').settlement2019_sources
    settlement2019 = settlement2019_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    supplementary_fy2025_01_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132071.layouts.akishima_supplementary_fy2025_01_registry').supplementary_fy2025_01_sources
    supplementary_fy2025_01 = supplementary_fy2025_01_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    mitaka_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_initial2026').get_sources
    mitaka = mitaka_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    ordinary_history_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.registration').ordinary_history_sources
    ordinary=ordinary_history_sources() if path.resolve()==SOURCES_JSON.resolve() else {}
    komae_supplementary_2020_1_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132195.layouts.komae_supplementary_2020_1_provider').komae_supplementary_2020_1_sources
    supplementary1 = komae_supplementary_2020_1_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    existing = {**settlement2019, **supplementary_fy2025_01, **komae_recovered,**chiyoda2025, **chiyoda2021settle, **pre2020, **settlement2020_2023, **settlement2024, **held5, **initial445, **native_settlement, **native, **council, **initial, **load_sources(path), **statement_sources(path), **budget_history_sources(path),
            **supplementary_detail_sources(path), **settlement_pdf_sources(path)}
    if set(existing) & set(mitaka):
        raise ValueError('mitaka source key overlaps an existing/joint provider')
    existing.update(mitaka)
    if set(existing) & set(ordinary):
        raise ValueError('tama source key overlaps an existing/joint provider')
    existing.update(ordinary)
    if set(existing) & set(supplementary1):
        raise ValueError('komae source key overlaps an existing/joint provider')
    existing.update(supplementary1)
    registered_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_budget_detail').registered_sources
    native_initial = registered_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    if set(existing) & set(native_initial):
        raise ValueError('native initial source key overlaps an existing provider')
    existing.update(native_initial)
    chiyoda_supplementary_sources = _ingestion_module('ingestion.fiscal.jurisdictions.131016.layouts.chiyoda_budget_changes').registered_sources
    chiyoda_supplementary = chiyoda_supplementary_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    if set(existing) & set(chiyoda_supplementary):
        raise ValueError('Chiyoda supplementary source key overlaps an existing provider')
    existing.update(chiyoda_supplementary)
    tama_supplementary_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_supplementary_registry').registered_sources
    tama_supplementary = tama_supplementary_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    if set(existing) & set(tama_supplementary):
        raise ValueError('Tama supplementary source key overlaps an existing provider')
    existing.update(tama_supplementary)
    mitaka_supplementary_sources = _ingestion_module('ingestion.fiscal.jurisdictions.132047.layouts.mitaka_supplementary_registry').registered_sources
    mitaka_supplementary = mitaka_supplementary_sources() if path.resolve() == SOURCES_JSON.resolve() else {}
    if set(existing) & set(mitaka_supplementary):
        raise ValueError('Mitaka supplementary source key overlaps an existing provider')
    existing.update(mitaka_supplementary)
    return existing


def load_settlement_pdf(path: Path = SOURCES_JSON) -> dict[str, dict]:
    """Fixed settlement originals with independently observed table partitions."""
    section = _pdf_sources('settlement_pdf', path)
    for key, spec in section.items():
        if spec['raw_form'] != 'extracted' or spec['document_kind'] != 'settlement':
            raise ValueError(f'{key}: settlement PDF declarations must be extracted settlement observations')
        if spec['layout'] not in ('tama-settlement-book', 'tama-settlement-funding'):
            raise ValueError(f'{key}: unsupported settlement PDF layout')
        if (spec['source_amount_unit'], spec['unit_multiplier']) not in (('円', 1), ('千円', 1000)):
            raise ValueError(f'{key}: unsupported observed money unit')
        ids = [t['table_id'] for t in spec['tables']]
        if not ids or len(ids) != len(set(ids)) or not spec['year_basis'] or not spec['fund_basis']:
            raise ValueError(f'{key}: table identity or primary-source year/account evidence missing')
    return section


def settlement_pdf_sources(path: Path = SOURCES_JSON) -> dict[str, Source]:
    out = {}
    for key, spec in load_settlement_pdf(path).items():
        code, year, *_ = key.split(':')
        identifier = f'settlement-pdf:{key}'
        out[identifier] = Source(
            key=identifier, catalog=None, jurisdiction_code=code,
            jurisdiction_name=_jurisdiction_name(code), fiscal_year=int(year),
            fiscal_year_label=None, document_kind='settlement', document_label=spec['document_label'],
            dataset_title=None, encoding='', redistribute=spec['redistribute'],
            redistribute_basis=spec['redistribute_basis'], license_id=spec['license_id'],
            attribution=spec['attribution'], landing_page=spec['landing_page'], raw_form='extracted',
            resources=tuple(Resource(direction='expenditure', resource_name=spec['document_title'] + ' ' + t['table_id'],
                url=spec['url'], url_basis=spec['url_basis'], table_id=t['table_id']) for t in spec['tables']))
    return out


def load_supplementary_detail(path: Path = SOURCES_JSON) -> dict[str, dict]:
    """Adopted printed project×setsu changes, separate from the frozen moku pilot."""
    return _pdf_sources('supplementary_detail', path)


def supplementary_detail_sources(path: Path = SOURCES_JSON) -> dict[str, Source]:
    out = {}
    for key, spec in load_supplementary_detail(path).items():
        code, year, *_ = key.split(':')
        identifier = f'supplementary-detail:{key}'
        out[identifier] = Source(
            key=identifier, catalog=None, jurisdiction_code=code,
            jurisdiction_name=_jurisdiction_name(code), fiscal_year=int(year),
            fiscal_year_label=None, document_kind='supplementary', document_label=spec['document_title'],
            dataset_title=None, encoding='', redistribute=spec['redistribute'],
            redistribute_basis=spec['redistribute_basis'], license_id=spec['license_id'],
            attribution=spec['attribution'], landing_page=spec['landing_page'], raw_form='extracted',
            resources=(Resource(direction='expenditure', resource_name=spec['document_title'],
                url=spec['url'], url_basis=spec['url_basis'], table_id=spec['table_id']),))
    return out


def load_budget_history(path: Path = SOURCES_JSON) -> dict[str, dict]:
    """当初・補正のPDF資料宣言を読む。"""
    return _pdf_sources("budget_history", path)


def budget_history_sources(path: Path = SOURCES_JSON) -> dict[str, Source]:
    """履歴資料を説明用の取得元へ変換する。CSV取得器へは渡さない。"""
    out = {}
    for key, spec in load_budget_history(path).items():
        code, year = key.split(":")
        for document in spec['documents']:
            number = document['amendment_number']
            label = '当初予算書' if number == 0 else f'補正予算書 第{number}号'
            identifier = f'budget-history:{key}:{number}'
            out[identifier] = Source(
                key=identifier, catalog=None, jurisdiction_code=code,
                jurisdiction_name=_jurisdiction_name(code), fiscal_year=int(year),
                fiscal_year_label=None, document_kind='budget' if number == 0 else 'supplementary',
                document_label='当初予算書' if number == 0 else '補正予算書',
                dataset_title=None, encoding='', redistribute=spec['redistribute'],
                redistribute_basis=spec['redistribute_basis'], license_id=spec['license_id'],
                attribution=spec['attribution'], landing_page=spec['landing_page'], raw_form='extracted',
                resources=(Resource(direction='expenditure', resource_name=label,
                                    url=document['url'], url_basis='年度の予算ページにある正式予算書'),))
    return out


def load_catalogs(path: Path = SOURCES_JSON) -> dict[str, Catalog]:
    """カタログの宣言だけを引く。**取得元を1つも読まずに宛先を知りたいときのため。**

    ⚠️ 粒度の調査（`check_granularity.py`）が CKAN の宛先と団体コードの解決規則を
    自前のリテラルで持っていた。同じ事実が2箇所にあると、カタログを足したり
    宛先が変わったりしたときに調査だけが古いカタログを見続ける。
    """
    raw = _declarations(path)
    return {name: Catalog(**spec) for name, spec in raw.get("catalog", {}).items()}


def resolve(key: str) -> Source:
    sources = load_sources()
    if key not in sources:
        available = ", ".join(sorted(sources)) or "(無し)"
        raise KeyError(f"取得元「{key}」が未定義。定義済み: {available}")
    return sources[key]


def load_project_names(path: Path = SOURCES_JSON) -> dict[str, dict]:
    """事業名の取得元（PDF）。`sources.json` の `project_names` 取り込み宣言。

    ⚠️ **`Source` には乗らない。** PDF とページ範囲と列の x 範囲という別の形なので、
    CKAN の取得元と同じデータクラスにすると片方に無い項目が任意だらけになる。
    ただし権利の語彙（`raw_form` / `redistribute` / `license_id`）は揃えてあり、
    証跡にも同じキーで記録している。

    ⚠️ **旧TOMLを3箇所で開いていた**（抽出器・記述子の生成・この module）。
    取得元の宣言を読む入口は1つにする。
    """
    return _pdf_sources("project_names", path)


def load_revenue_accounts(path: Path = SOURCES_JSON) -> dict[str, dict]:
    """歳入の科目名称の取得元（決算資料の歳入事項別明細）。`[revenue_accounts]` 節"""
    return _pdf_sources("revenue_accounts", path)


def load_statements(path: Path = SOURCES_JSON) -> dict[str, dict]:
    """事項別明細書（PDF）を原典とする取得元。`sources.json` の `statement` 取り込み宣言。

    ⚠️ **`Source` には乗らない。** CKAN の取得元は (団体, 年度) に対して
    direction ごとの**別ファイル**を持つが、事項別明細書は1本の PDF の中で
    歳入と歳出が**頁範囲で分かれる**。同じデータクラスに載せると、どちらの団体でも
    半分が任意の項目になる。権利の語彙（`raw_form` / `redistribute` / `license_id`）は揃えてある。

    ⚠️ **`raw_form` は `extracted` しか許さない。** ここが落とすのは抽出した表であって
    原文の複製ではない。再配布可の団体（昭島市は PDL1.0）でも同じで、
    `verbatim` と名乗ると下流の復元一致の検査が成立すると読めてしまう。
    """
    section = _pdf_sources("statement", path)
    for key, spec in section.items():
        if spec.get("raw_form") != "extracted":
            raise ValueError(f"statement.{key}: raw_form は extracted のみ（抽出した表しか落とさない）")
        if not spec.get("url_basis"):
            raise ValueError(f"statement.{key}: url_basis が空。カタログを引かない理由を書くこと")
        if not spec.get("fund_basis"):
            # ⚠️ **会計は資料の中にしか無い。** CSV の団体は原典に `会計名称` の列があるが、
            # 事項別明細書は資料そのものが1会計ぶんで、会計名は表紙にしか出てこない。
            # 宣言で埋める以上、どこを読んで決めたかを書かないと捏造と区別が付かない。
            raise ValueError(f"statement.{key}: fund_basis が空。会計名の出所を書くこと")
        if spec.get("heading_style") not in ("dai", "paren"):
            # ⚠️ **既定値を持たせない。** 記法は実物を見ないと分からず、
            # 誤ると款・項が1つも立たないまま「目が0件」として静かに終わる。
            raise ValueError(
                f"statement.{key}: heading_style は dai（第１款）か paren（（款） 1）"
                f"（{spec.get('heading_style')}）")
        missing = {"expenditure", "revenue"} - set(spec.get("pages", {}))
        if missing:
            raise ValueError(f"statement.{key}: pages に {sorted(missing)} が無い")
        for direction, (a, b) in spec["pages"].items():
            # 見開きは (左, 右) の対で1論理行になるので、頁数が偶数でなければ対が崩れている
            if (b - a + 1) % 2:
                raise ValueError(
                    f"statement.{key}: {direction} の頁範囲 {a}〜{b} が奇数頁ぶん。"
                    f"見開きの対が崩れている")
    return section


def _pdf_sources(section: str, path: Path) -> dict[str, dict]:
    """PDF 系の取得元。**キーの団体コードを registry と突き合わせる。**

    ⚠️ **CKAN 側（load_sources）だけを registry に通しても足りない。** こちらは
    `"132195:2023"` のキー自体が partition の団体コードになるので、誤記のまま
    `raw/**/jurisdiction=132159/` のような未知の団体の区画へ書けてしまう。
    名称を引く経路が無い分、CKAN 側より検知が遅れる。
    """
    section_raw = _declarations(path).get(section, {})
    for key in section_raw:
        code = key.split(":")[0]
        _jurisdiction_name(code)      # 未登録なら KeyError
    return section_raw
