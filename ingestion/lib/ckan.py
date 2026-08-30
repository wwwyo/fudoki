"""CKAN のデータセット列挙。**層に依存しない。**

⚠️ **「団体の全データセット」を引く経路を2つ持たない。**
本番の取得器（`ingestion/budget/fetch.py`）と粒度の調査（`ingestion/budget/check_granularity.py`）が
それぞれ同じクエリを組んでいた。**同じ判断（`q` の全文検索ではなく `fq=organization:` で
団体を確定させる）を2箇所に置くと、片方だけ直したときに気づけない。**
実際、調査側だけがページングを実装し、取得側は `rows=1000` の一発で
「返りが足りなければ rows を増やせ」と例外にしていた。
"""

from __future__ import annotations

import json
import urllib.parse

from ingestion.lib.http import http_get

# 1回のリクエストで取る件数。CKAN 側に上限があるのでページングする
PAGE = 300


def datasets_of_organization(endpoint: str, org: str) -> list[dict]:
    """その団体の**全**データセット。

    ⚠️ **`result.count` まで辿る。** 打ち切ると「無い」の根拠に使えない。
    fq でカタログ側に絞らせるのは、`q` の全文検索と違って団体が確定するためで、
    同名のデータセットが別の団体にもある場合の取り違えも起きない。
    """
    rows: list[dict] = []
    start = 0
    while True:
        query = urllib.parse.quote(f"organization:{org}")
        got = http_get(f"{endpoint}?fq={query}&rows={PAGE}&start={start}")
        result = json.loads(got.body).get("result", {})
        found, returned = result.get("count", 0), result.get("results", [])
        rows.extend(returned)
        if not returned or len(rows) >= found:
            return rows
        start += PAGE
