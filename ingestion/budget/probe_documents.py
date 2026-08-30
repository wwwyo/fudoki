"""**調査スクリプト**。本番の Extract ではない。

`observations/discovery/<団体コード>.json`（取得元の探索の観測）が挙げた資料を実際に開き、
**中身から**どこまで届いているかを測る。資料名では判定しない（パーサ設計の原則3）。

⚠️ **「予算に関する説明書」という名前は粒度を保証しない。** 実際、名前が有望な資料が
款項レベルの集計でしかないことがある（「予算概要」「予算要求状況一覧表」）。
逆に「決算参考書」のような素っ気ない名前が事項別明細を持つこともある。
だから開いて数える。

## 何を測るか

地方自治法施行令第147条の様式により、**歳入歳出予算事項別明細書**は款・項・目に加えて
**節**（給料・職員手当等・需用費…の27区分）と**説明**欄を持つ。したがって:

- 節の法定語が本文に複数現れる → その資料は目より下（節）まで降りている
- 説明欄がある → 事業名がそこに載っている見込み（**あくまで見込み。名称の有無は別に測る**）

款項どまりの集計表には節が現れない。これが名前に頼らない判別になる。

⚠️ **測るのは代表1本だけ。** 分冊されている資料は `splitInto` が本数を持つが、
ここで開くのは `fileUrl` の1本である。歳入の分冊しか代表になっていない団体では
歳出の粒度を測ったことにならない。`probedFile` に何を開いたかを残す。

⚠️ **テキストが取れない PDF がある**（文字がアウトライン化されている）。
その場合は `unknown` を返す。OCR はここではやらない — 較正が要る経路を
調査スクリプトに埋めると、誤読を測定値として扱うことになる。

⚠️ **ネットワークを叩くのでサンドボックスを外して回す**（AGENTS.md）。

    uv run python -m ingestion.budget.probe_documents            # 結果を表示
    uv run python -m ingestion.budget.probe_documents --write    # observations へ書き出す
    uv run python -m ingestion.budget.probe_documents 131229     # 団体を絞る
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.error

from ingestion.lib.http import http_get

HERE = pathlib.Path(__file__).resolve().parent
DISCOVERY = HERE / "observations" / "discovery"
OUT = HERE / "observations" / "budget-document-probe.json"

# 地方自治法施行規則 別表第二（歳出予算の節の区分）の語。
# ⚠️ **款・項・目の名称と重ならない語を選ぶ。** 「扶助費」「補助費」は性質別分類の語でもあるので、
# 単独では節の証拠にならない。ここに置くのは節にしか現れない語に限る。
SETSU_WORDS = (
    "職員手当等", "共済費", "報償費", "需用費", "役務費", "委託料",
    "使用料及び賃借料", "工事請負費", "負担金、補助及び交付金", "原材料費",
    "公課費", "償還金利子及び割引料", "補償、補填及び賠償金",
)
# 事項別明細書そのものの見出し
MEISAI_WORDS = ("事項別明細書", "事項別明細")
# 説明欄。事業名はここに載る
EXPLANATION_WORDS = ("説明",)
# ⚠️ **テキストが「取れる」ことと「読める」ことは別。**
# ToUnicode を持たない埋め込みフォントの PDF は、`pdftotext` が字数ぶんの文字を返すのに
# 中身が別の文字に化ける（板橋区の予算書は「本 年 度」が `ᮏࠉᖺࠉᗘ` になる）。
# 字数だけを見ていると「テキストあり・科目の語なし」＝款項どまり、と誤って判定する。
# 予算資料なら必ず現れる語が1つも無ければ、化けていると見なす。
ANCHOR_WORDS = ("予算", "決算", "歳出", "歳入", "科目", "金額", "合計", "円")

# 何ページ見るか。
# ⚠️ **連続したブロックで採らない。** 500ページ級の資料は会計・歳入歳出・款で
# 章が分かれており、先頭と中ほどの2ブロックだけだと「職員費しか無い章」に当たって
# 節の語が2語しか出ないことがある（千代田区・中野区で実測）。全体に散らして採る。
HEAD_PAGES = 4
SPREAD_SAMPLES = 12
# テキストが取れたとみなす1ページあたりの最低文字数。
# アウトライン化された PDF は 0〜数文字しか返さない（狛江市の決算資料で実測）
MIN_CHARS_PER_PAGE = 40


def _page_count(pdf: pathlib.Path) -> int | None:
    got = subprocess.run(  # noqa: S603
        ["pdfinfo", str(pdf)], capture_output=True, check=False
    ).stdout.decode(errors="replace")
    for line in got.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":")[1].strip())
    return None


def _text(pdf: pathlib.Path, first: int, last: int) -> str:
    got = subprocess.run(  # noqa: S603
        ["pdftotext", "-layout", "-f", str(first), "-l", str(last), str(pdf), "-"],
        capture_output=True, check=False,
    )
    return got.stdout.decode(errors="replace")


def probe_pdf(body: bytes) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(body)
        f.flush()
        path = pathlib.Path(f.name)
        pages = _page_count(path)
        if not pages:
            return {"reaches": "unknown", "basis": "pdfinfo がページ数を返さない"}

        head_last = min(HEAD_PAGES, pages)
        parts = [_text(path, 1, head_last)]
        spread = sorted({
            head_last + max(1, round((pages - head_last) * i / (SPREAD_SAMPLES + 1)))
            for i in range(1, SPREAD_SAMPLES + 1)
        } & set(range(head_last + 1, pages + 1)))
        parts.extend(_text(path, n, n) for n in spread)
        head, middle = "".join(parts), ""

    sampled = head_last + len(spread)
    # ⚠️ **空白を除いてから突き合わせる。** 罫線表の PDF は1文字ずつ字間が空いており、
    # `pdftotext` が「需 用 費」のように分けて吐く。素の文字列で探すと
    # 節の語が1つも当たらず、事項別明細書が「款項どまり」に見える（葛飾区で実測）。
    text = re.sub(r"\s+", "", head + middle)
    chars = len(text)
    if chars < MIN_CHARS_PER_PAGE * sampled:
        return {
            "pages": pages, "sampledPages": sampled, "charsPerPage": round(chars / sampled),
            "reaches": "ocr-required",
            "basis": "テキストが取れない（文字がアウトライン化されている）。OCR の経路で読む",
        }

    if not any(w in text for w in ANCHOR_WORDS):
        return {
            "pages": pages, "sampledPages": sampled, "charsPerPage": round(chars / sampled),
            "reaches": "ocr-required",
            "basis": "テキストは取れるが語が復元できない（ToUnicode の無い埋め込みフォント）。OCR の経路で読む",
        }

    setsu = sorted({w for w in SETSU_WORDS if w in text})
    meisai = sorted({w for w in MEISAI_WORDS if w in text})
    explanation = any(w in text for w in EXPLANATION_WORDS)
    levels = sorted({w for w in ("款", "項", "目", "節") if w in text})

    if len(setsu) >= 3:
        reaches, basis = "setsu", f"節の法定語が {len(setsu)} 語: {'、'.join(setsu[:6])}"
    elif meisai and "節" in levels:
        # 事項別明細書に節の欄がある時点で目より下である。節の名称が何語拾えたかは
        # サンプルの当たり方の問題でしかない（北区の決算書は 1 語しか拾えなかった）
        reaches, basis = "setsu", f"事項別明細書に節の欄がある（節の名称は {len(setsu)} 語)"
    elif meisai:
        reaches, basis = "moku", f"事項別明細の見出しはあるが節の欄が無い（節の名称 {len(setsu)} 語）"
    elif "目" in levels:
        reaches, basis = "moku", "目の語はあるが節の語が無い"
    elif levels:
        reaches, basis = "kou", f"科目の語は {'、'.join(levels)} まで"
    else:
        reaches, basis = "unknown", "科目の語が1つも無い"

    return {
        "pages": pages, "sampledPages": sampled, "charsPerPage": round(chars / sampled),
        "setsuWords": setsu, "meisaiWords": meisai, "hasExplanationColumn": explanation,
        "levelWords": levels, "reaches": reaches, "basis": basis,
    }


def probe(doc: dict) -> dict:
    base = {k: doc.get(k) for k in ("kind", "title", "fiscalYear", "format", "splitInto")}
    base["probedFile"] = doc.get("fileUrl")
    if not doc.get("fileUrl") or doc.get("httpStatus") != 200:
        return {**base, "reaches": "unprobed", "basis": "探索が実ファイルまで届いていない"}
    if (doc.get("format") or "").upper() != "PDF":
        return {**base, "reaches": "unprobed", "basis": "PDF 以外はここでは測らない（check_granularity が列で測る）"}
    try:
        got = http_get(doc["fileUrl"])
    except urllib.error.HTTPError as e:
        # ⚠️ **403 は「取れない」であって「無い」ではない。** 東村山市は CloudFront の
        # WAF がブラウザ以外の User-Agent を全部弾く（robots.txt 自体も 403 を返す）。
        # **UA を偽装して回避しない** — ③会議録で DiscussNetPremium を規模が最大でも
        # 対象から外したのと同じ判断で、拒否の宣言を迂回する経路は採らない。照会に回す。
        return {**base, "reaches": "blocked", "basis": f"HTTP {e.code}（取得を拒否されている。照会が要る）"}
    except Exception as e:  # noqa: BLE001  取得元の異常は観測として残す。止めない
        return {**base, "reaches": "unknown", "basis": f"{type(e).__name__}: {e}"}
    if got.status != 200:
        return {**base, "reaches": "blocked", "basis": f"HTTP {got.status}"}
    return {**base, "sha256": got.sha256, "bytes": len(got.body), **probe_pdf(got.body)}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv[1:]
    if not DISCOVERY.exists():
        raise SystemExit(f"{DISCOVERY} が無い。先に取得元の探索を回すこと")

    result: dict[str, dict] = {}
    for path in sorted(DISCOVERY.glob("*.json")):
        found = json.loads(path.read_text())
        code = found["code"]
        if args and code not in args:
            continue
        probes = [probe(d) for d in found.get("documents", [])]
        result[code] = {"name": found["name"], "documents": probes}
        best = max((p for p in probes), key=lambda p: _rank(p["reaches"]), default=None)
        mark = {"setsu": "✓", "moku": "◎", "ocr-required": "▲",
                "blocked": "✖"}.get(best["reaches"] if best else "", "△")
        print(f"  {mark} {code} {found['name']:8s} "
              f"{(best or {}).get('reaches', 'なし'):9s} {(best or {}).get('basis', '')[:70]}")

    if write:
        OUT.write_text(json.dumps({
            "note": "探索が挙げた資料を実際に開いて、中身から粒度を測った観測。資料名では判定しない（原則3）。"
                    "測ったのは代表1本だけで、分冊の他ファイルは見ていない。",
            "generatedBy": "ingestion/budget/probe_documents.py",
            "jurisdictions": result,
        }, ensure_ascii=False, indent=2) + "\n")
        print(f"\n{OUT} へ書き出した")


def _rank(reaches: str) -> int:
    # ⚠️ OCR が要る資料は**粒度が低いのではなく、まだ測れていない**。
    # 目どまりと確かめた資料より上に置かない（測っていないものを結果にしない）が、
    # 経路が塞がっている `blocked` や見ていない `unprobed` よりは前に進んでいる
    return {"setsu": 5, "moku": 4, "kou": 3, "ocr-required": 2, "blocked": 1,
            "unknown": 1, "unprobed": 0}.get(reaches, 0)


if __name__ == "__main__":
    main()
