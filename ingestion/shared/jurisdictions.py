"""団体の同一性。**層に依存しない。** `jurisdictions.ts` の Python 版対。

①予算・②調達・③会議録はすべて全国地方公共団体コードで束ねるので、名称と識別子は
どの層からも参照される。②③は TS からこの JSON を読んでいるが、①予算は Python
（`ingestion/budget/*`）なので、同じ事実を Python 側で再宣言せずここから引く。

⚠️ 以前は `ingestion/budget/sources.toml` が `jurisdiction_name` を団体×年度ごとに
反復宣言しており（狛江市だけで6回）、`jurisdictions.json` と突き合わせる経路が無かった。
sources.toml に誤記があっても検知されず、配布物の `jurisdiction_label` へそのまま出ていた。
"""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent / "jurisdictions.json"


def load_jurisdictions(path: Path = REGISTRY_PATH) -> dict[str, dict]:
    """全国地方公共団体コードをキーにした団体情報（name / ocdId / tokyoCatalogDatasets）"""
    return json.loads(path.read_text(encoding="utf-8"))["jurisdictions"]


def jurisdiction_name(code: str, path: Path = REGISTRY_PATH) -> str:
    """団体コードから名称を引く。**登録が無ければ例外**（黙って欠けさせない）"""
    registry = load_jurisdictions(path)
    if code not in registry:
        raise KeyError(
            f"団体コード「{code}」が ingestion/shared/jurisdictions.json に無い。"
            f"団体の名称と識別子はそこで一元管理している（AGENTS.md 参照）"
        )
    return registry[code]["name"]
