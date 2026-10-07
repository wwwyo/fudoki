"""CKAN の団体別データセット列挙。件数に達するまでページングする。"""

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
