"""**調査スクリプト**。3つの観測を突き合わせて「団体ごとに取得元が決まったか」を出す。

読むもの:

| 観測 | 何を持つか |
|---|---|
| `observations/budget-granularity.json` | 東京都カタログの資料を**列構成**で測った結果 |
| `observations/discovery/<コード>.json`  | 団体サイトを辿って見つけた資料の URL と権利まわり |
| `observations/budget-document-probe.json` | その資料を**開いて中身**で測った結果 |
| `sources.toml`                          | すでに取得元として確定し、収録済みの団体 |

⚠️ **「取得元が決まった」と言えるのは、実物を開いて目より下に届いていることを見たときだけ。**
資料名が「予算に関する説明書」であることは根拠にならない（原則3）。
URL が 200 を返すことも根拠にならない（それは在ることしか言っていない）。

⚠️ **再配布の可否と、取得できるかは別の判断である。** サイトが無断複製を禁じていても
そこから**抽出した事実**は配れる（原文は置かない = `raw_form = "extracted"`）。
だから `deny` は取得元の失格理由にならない。混同すると団体が丸ごと空になる。

    uv run python -m ingestion.budget.source_coverage
    uv run python -m ingestion.budget.source_coverage --write
"""

from __future__ import annotations

import json
import pathlib
import sys

from ingestion.budget.probe_documents import best_probe
from ingestion.budget.sources import load_sources
from ingestion.shared.jurisdictions import load_jurisdictions

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OBS = HERE / "observations"
OUT = OBS / "budget-source-coverage.json"

# `reaches` を団体の状態へ翻訳する対応表。**ここに閾値や推定を持ち込まない** —
# 判断は probe_documents 側で済んでおり、この表は 1 対 1 の言い換えである。
#
# ⚠️ **「測れていない」を「資料が無い」に潰さない。** `unknown` は資料を開いた上で
# 判定が付かなかった状態、`unprobed` はそもそも開いていない状態で、どちらも
# 「その団体に資料が存在しない」とは別のことを言っている。潰すと、測っていないものが
# 結果として出る（AGENTS.md「測っていないものを結果として出さない」）。
STATE_OF_REACHES: dict[str | None, tuple[str, str]] = {
    "setsu": ("確定", "site-pdf"),
    "moku": ("目どまり", "site-pdf"),
    "kou": ("目どまり", "site-pdf"),
    "ocr-required": ("OCR 待ち", "site-pdf"),
    "blocked": ("照会が要る", "site-pdf"),
    "unknown": ("測れていない", "site-pdf"),
    "unprobed": ("測れていない", "site-pdf"),
    # 探索は回ったが、資料が1本も挙がらなかった団体
    None: ("資料が無い", "-"),
}


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def main() -> None:
    registry = load_jurisdictions()
    registered = {s.jurisdiction_code for s in load_sources().values()}
    discovery = {p.stem: json.loads(p.read_text()) for p in sorted((OBS / "discovery").glob("*.json"))}
    probe = _load(OBS / "budget-document-probe.json").get("jurisdictions", {})

    resolved: dict[str, dict] = {}
    tally: dict[str, list[str]] = {}
    for code, meta in registry.items():
        name = meta["name"]
        if code in registered:
            state, route, basis = "収録済み", "catalog", "sources.toml に登録済み"
        elif code not in discovery:
            state, route, basis = "未調査", "-", "取得元の探索がまだ回っていない"
        else:
            best = best_probe(probe.get(code, {}).get("documents", []))
            reaches = best.get("reaches") if best else None
            state, route = STATE_OF_REACHES[reaches]
            basis = (
                f"{best['title'][:22]}。{best['basis'][:40]}" if best
                else "探索は回ったが、事項別明細書にあたる資料が1本も挙がらなかった"
            )
        stance = (discovery.get(code, {}).get("copyright") or {}).get("stance", "-")
        resolved[code] = {"name": name, "state": state, "route": route,
                          "redistribute": stance, "basis": basis}
        tally.setdefault(state, []).append(code)
        print(f"  {code} {name:8s} {state:6s} {route:10s} 再配布 {stance:7s} {basis}")

    print()
    for state, codes in sorted(tally.items(), key=lambda kv: -len(kv[1])):
        print(f"  {state}: {len(codes)} 団体")
    print(f"  母集団: {len(registry)} 団体")

    if "--write" in sys.argv[1:]:
        OUT.write_text(json.dumps({
            "note": "団体ごとに取得元が決まったかの突き合わせ。カタログの列判定・サイト探索・"
                    "中身の粒度の3つの観測から導く。**この表に新しい事実は無い** — "
                    "根拠は3つの観測の側にあり、ここはそれを1行に畳んだものである。",
            "generatedBy": "ingestion/budget/source_coverage.py",
            "population": len(registry),
            "tally": {k: len(v) for k, v in tally.items()},
            "jurisdictions": resolved,
        }, ensure_ascii=False, indent=2) + "\n")
        print(f"\n{OUT} へ書き出した")


if __name__ == "__main__":
    main()
