"""取得元の定義を `sources.toml` から読む。

TOML を正にしているのは、Python（tomllib）と Bun の両方が依存なしで読めるため。
定義を2言語で二重持ちすると、片方だけ直して気づかない状態を作る。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
    redistribute: str
    redistribute_basis: str
    license_id: str
    attribution: str
    landing_page: str
    resources: tuple[Resource, ...]

    @property
    def may_publish_raw(self) -> bool:
        """原典をリポジトリへ置いてよいか。

        根拠は `redistribute_basis`（①予算はカタログのライセンス）。
        ③会議録の gate（`data/transcripts/gates.json`）とは根拠が違うので繋がない —
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
