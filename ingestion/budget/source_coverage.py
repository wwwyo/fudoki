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

from ingestion.budget.probe_documents import _rank
from ingestion.budget.sources import load_sources

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OBS = HERE / "observations"
JURISDICTIONS = ROOT / "ingestion" / "shared" / "jurisdictions.json"
OUT = OBS / "budget-source-coverage.json"

# 中身を測った結果のうち、事業単位に届く見込みがあるもの。
# 節（目より下）まで降りていれば、説明欄に事業名が載る様式である
REACHES_BELOW_MOKU = ("setsu",)


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def main() -> None:
    registry = json.loads(JURISDICTIONS.read_text())["jurisdictions"]
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
            docs = probe.get(code, {}).get("documents", [])
            best = max(docs, key=lambda d: _rank(d.get("reaches")), default=None)
            reaches = best.get("reaches") if best else None
            if reaches in REACHES_BELOW_MOKU:
                state, route = "確定", "site-pdf"
                basis = f"{best['title'][:22]} を開いて {best['basis'][:36]}"
            elif reaches == "ocr-required":
                state, route = "OCR 待ち", "site-pdf"
                basis = f"{best['title'][:22]}。{best['basis'][:34]}"
            elif reaches == "blocked":
                state, route = "照会が要る", "site-pdf"
                basis = f"{best['title'][:22]}。{best['basis'][:34]}"
            elif reaches == "moku":
                state, route = "目どまり", "site-pdf"
                basis = f"{best['title'][:22]}。テキスト経路では節に届かない（OCR で再確認）"
            else:
                state, route = "資料が無い", "-"
                basis = "事項別明細書にあたる資料が公開されていない"
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
