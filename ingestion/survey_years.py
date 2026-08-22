"""三鷹市の他年度が令和6年度と互換かを測る。

**取り込めるかどうかを名前ではなく実物で判定する。** 列構成・金額の型・引用符の有無・会計の範囲。
結果は `data/observations/` に残す（要約ではなく観測が SSOT）。

ネットワークを叩くので CI では回さない。
"""

from __future__ import annotations

import csv
import io
import json
import pathlib
import re
import sys

from ingestion.fetch import ROOT, http_get, resolve_resource
from ingestion.sources import Resource, Source, resolve

# 令和6年度の列構成。ここと違えば取り込みの前提が崩れている。
BASELINE = {
    "expenditure": ["01会計", "02款", "03項", "04目", "05事項", "06節", "07細々節", "08予算額"],
    "revenue": ["01会計", "02款", "03項", "04目", "05節", "06細節", "07細々節", "08予算額"],
}
# ⚠️ **和暦の表記が元号で揺れている。** 令和は全角数字（令和６年度）、平成は半角（平成30年度）。
# カタログのリソース名がそうなっているので、こちらで正規化せず実物に合わせる。
# 年度の唯一の出所がリソース名なので、ここを間違えると年度を取り違える。
YEARS = [
    (2016, "平成28年度"), (2017, "平成29年度"), (2018, "平成30年度"), (2019, "令和元年度"),
    (2020, "令和２年度"), (2021, "令和３年度"), (2022, "令和４年度"), (2023, "令和５年度"), (2024, "令和６年度"),
]


def survey_one(src: Source, year: int, label: str, direction: str) -> dict:
    base = {"year": year, "label": label, "direction": direction}
    name = next(
        (r["name"] for r in _resources(src) if label in r["name"] and _dir_of(r["name"]) == direction),
        None,
    )
    if name is None:
        return {**base, "compatible": None, "basis": f"{label} の {direction} リソースがカタログに無い"}

    url = resolve_resource(src, name)
    got = http_get(url)
    base |= {"resourceName": name, "url": url, "status": got.status, "bytes": len(got.body),
             "sha256": got.sha256, "fetchedAt": got.fetched_at}
    if got.status != 200:
        return {**base, "compatible": None, "basis": f"取得できない: HTTP {got.status}"}

    text = got.body.decode(src.encoding).lstrip("﻿")
    # ⚠️ **引用符は生の行で数える。** csv.reader は引用符を消費するので、
    # パース後に探しても必ず 0 件になる。実際それで「18/18 互換」と誤判定した。
    raw_lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    quoted = sum(1 for ln in raw_lines[1:] if '"' in ln)

    rows = [r for r in csv.reader(io.StringIO(text, newline="")) if any(c.strip() for c in r)]
    header, body = rows[0], rows[1:]
    funds = sorted({r[0] for r in body if r})
    amounts = [r[7] for r in body if len(r) > 7]
    all_int = all(re.fullmatch(r"-?\d+", a or "") for a in amounts)

    reasons = []
    if header != BASELINE[direction]:
        reasons.append(f"列構成が令和6年度と違う: {header}")
    if not all_int:
        reasons.append("金額列に整数でない値がある")
    if quoted:
        reasons.append(
            f"{quoted} 行に引用符付きのセルがある。"
            f"現在の取り込みは引用符を含む原典を復元できず落ちるので、収録には引用符を解釈するパーサが要る"
        )
    return {
        **base, "rows": len(body), "columns": header, "funds": funds,
        "amountAllIntegers": all_int, "quotedRows": quoted,
        "totalRaw": sum(int(a) for a in amounts) if all_int else None,
        "compatible": not reasons,
        "basis": ("列構成が令和6年度と一致。金額列は全て整数。引用符なし。"
                  f"会計 {len(funds)} 件") if not reasons else " / ".join(reasons),
    }


_cache: dict[str, list[dict]] = {}


def _resources(src: Source) -> list[dict]:
    """カタログのリソース一覧。1回引いて使い回す"""
    if src.key not in _cache:
        import urllib.parse
        q = urllib.parse.quote(src.dataset_title)
        got = http_get(f"{src.catalog.endpoint}?q={q}&rows=300")
        org = src.catalog.org_prefix + src.jurisdiction_code
        pkg = next(p for p in json.loads(got.body)["result"]["results"]
                   if (p.get("organization") or {}).get("name") == org and p["title"] == src.dataset_title)
        _cache[src.key] = pkg["resources"]
    return _cache[src.key]


def _dir_of(name: str) -> str | None:
    return "expenditure" if "歳出" in name else "revenue" if "歳入" in name else None


if __name__ == "__main__":
    src = resolve(sys.argv[1] if len(sys.argv) > 1 else "132047:2024")
    obs = [survey_one(src, y, label, d) for y, label in YEARS for d in ("expenditure", "revenue")]
    out = ROOT / "data" / "observations" / "mitaka-budget-years.json"
    out.write_text(json.dumps({
        "note": "取り込めるかを名前ではなく実物で判定する。列構成・金額の型・引用符・会計の範囲。",
        "generatedBy": "uv run python -m ingestion.survey_years",
        "baseline": BASELINE,
        "caveat": "互換と判定しても、実際に取り込むまで通ることの保証にはならない。",
        "observations": obs,
    }, ensure_ascii=False, indent=2) + "\n")
    ok = sum(1 for o in obs if o["compatible"])
    print(f"互換 {ok}/{len(obs)}  → {out.relative_to(ROOT)}")
    for o in obs:
        if not o["compatible"]:
            print(f"  {'?' if o['compatible'] is None else '✗'} {o['label']} {o['direction']}: {o['basis'][:70]}")
