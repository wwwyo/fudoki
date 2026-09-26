"""原典 PDF のローカル閲覧レイヤを組む。

検証画面（`/pipeline/<団体コード>/`）が「原典 → 取り込み」の組を開いたとき、
原典の頁をその姿で出すための頁画像・語の文字層・行→頁内位置の対応を書き出す。

⚠️ **出力はローカル専用。** `apps/web/.local/pdf/` に書き、`public/` には書かない
（`.local/` は gitignore）。原典 PDF の写し（頁画像・OCR テキスト・行と頁の対応）は
再配布の判断が付いていないものを含むので、公開の配信物には載せない
（`docs/prd/pipeline-verification-view/prd.md`）。

原典の PDF は `request_url` から取り直す。証跡が書いているとおり repo の data/
には置いていないので、取得は `ingestion.lib.http` のキャッシュ（24h）を使う。

使い方: `bun run pdf:layer`（`bun run pipeline` の一部）
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import tempfile

import duckdb

from ingestion.budget.statement_layout import normalize
from ingestion.lib.http import http_get
from ingestion.lib.pdf import pages_of

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "budget" / "raw"
OUT = ROOT / "apps" / "web" / ".local" / "pdf"

# 頁画像の解像度。検証画面は原寸確認が主ではないので、文字が潰れない下限より少し上
DPI = 110

# 行→頁対応の作り方の版。照合ロジックを変えたら上げる（頁画像・語層は原典だけに
# 依存するので作り直さず、hits.json だけを再計算する）
HITS_VERSION = 4


def _source_id(prov: dict, prov_path: pathlib.Path) -> str | None:
    """証跡がぶら下がる系統上のソースノードの id。

    ⚠️ **正本の取り込みと抽出物で id の形が違う**（dbt の `sources` がそう名乗る）。
    判定は `extractor` のパスではなく置き場でやる — 両方とも extractor を持つので
    中身では区別が付かない。
    """
    parts = prov_path.relative_to(RAW).parts
    code = prov["jurisdiction_code"]
    if parts[0].startswith("jurisdiction="):
        direction = next(p.split("=", 1)[1] for p in parts if p.startswith("direction="))
        return f"source.fudoki.raw_{code}.{direction}"
    if parts[0] == "project-names":
        return f"source.fudoki.raw_{code}_project_names.data"
    if parts[0] == "revenue-accounts":
        return f"source.fudoki.raw_{code}_revenue_accounts.data"
    return None


Line = tuple[list[float], str, list[str]]   # (bbox, 連結テキスト, 語の列)


def _lines(words: list[tuple[float, float, float, float, str]], tolerance: float = 2.0) -> list[Line]:
    """語を視覚的な行へまとめる。`rows_of`（文字用）と同じ y 近接の束ね方を語に対して行う"""
    if not words:
        return []
    keys = sorted({(w[1] + w[3]) / 2 for w in words})
    groups = [[keys[0]]]
    for cy in keys[1:]:
        if cy - groups[-1][-1] > tolerance:
            groups.append([])
        groups[-1].append(cy)
    center_of = {cy: i for i, g in enumerate(groups) for cy in g}
    lines: list[list[tuple[float, float, float, float, str]]] = [[] for _ in groups]
    for w in words:
        lines[center_of[(w[1] + w[3]) / 2]].append(w)
    out = []
    for line in lines:
        ws = sorted(line, key=lambda w: w[0])
        box = [min(w[0] for w in ws), min(w[1] for w in ws),
               max(w[2] for w in ws), max(w[3] for w in ws)]
        out.append((box, normalize("".join(w[4] for w in ws)), [normalize(w[4]) for w in ws]))
    return out


def _statement_rows(parquet: pathlib.Path):
    """事項別明細書の抽出物。葉は内訳 → 節 → 事業 → 目の順で一番深い名前を持つ"""
    cols = "source_row, 款, 項, 目, 目名称, 事業名, 節名称, 内訳名称, 本年度予算額"
    for r in duckdb.query(f"select {cols} from read_parquet('{parquet}')").fetchall():
        (row, kan, kou, moku, moku_name, proj, setsu, detail, amount) = r
        names = [n for n in (detail, setsu, proj) if n]
        candidates = [normalize(n) for n in names] if names else [
            normalize(moku_name or ""), normalize(f"{kan}-{kou}-{moku}{moku_name or ''}")]
        yield row, [c for c in candidates if c], int(amount or 0)


def _project_name_rows(parquet: pathlib.Path):
    for row, name, amount in duckdb.query(
            f"select ordinal, project_name, amount_thousand_yen from read_parquet('{parquet}')").fetchall():
        yield row, [normalize(name)] if name else [], int(amount or 0)


# 名称の折り返しは ±2 行まで見る。折り返した名前は金額と同じ行に全部は載らないので、
# 「金額の行 ± 近接行の連結」に名称が収まるかを見る
WRAP = 2


def _hits(prov: dict, prov_path: pathlib.Path, pages_lines: dict[int, list[Line]]):
    """行 → 頁内位置。名称と金額（桁区切り付きの印字の形）を同じ箇所に持つ語の帯を探す。

    金額は語単位で照合する — `262` が `1,262` の部分文字列として当たる誤検出を避ける。
    名称は行に折り返されうるので、金額の行の前後 WRAP 行を連結した文字列で照合する。
    """
    kind = "statement" if "extract_statement" in (prov.get("extractor") or "") \
        else "project-names" if "extract_projects" in (prov.get("extractor") or "") else None
    if kind is None or not prov.get("pages"):   # revenue-accounts は OCR のみ — 語の層が無い
        return {}
    rows = _statement_rows(prov_path.parent / "data.parquet") if kind == "statement" \
        else _project_name_rows(prov_path.parent / "data.parquet")
    first, last = prov["pages"]
    out: dict[str, dict] = {}
    for rowkey, names, amount in rows:
        # 金額は語の中で `316,980千円` のように単位を伴うことがあり、また語の分割を
        # またぐことがある（`57,` `397`）。語単位と、隣接2語の連結の両方で見る。
        # 直前が数字・カンマのもの（`1,262` の `262`）は別の金額の一部なので弾く
        amount_re = re.compile(
            r"(?<![0-9,])" + re.escape(normalize(f"{amount:,}")) + r"(?:千円|円)?$")
        for name in names:
            found = None
            for pno in range(first, last + 1):
                lines = pages_lines.get(pno, [])
                for i, (_, text, words) in enumerate(lines):
                    hit_amount = any(amount_re.search(w) for w in words) or any(
                        amount_re.fullmatch(words[j] + words[j + 1])
                        for j in range(len(words) - 1))
                    if not hit_amount:
                        continue
                    if name in text:
                        found = (pno, i, i)
                        break
                    for a, b in ((max(0, i - WRAP), i), (i, min(len(lines) - 1, i + WRAP))):
                        if name in "".join(t for _, t, _ in lines[a:b + 1]):
                            found = (pno, a, b)
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                pno, a, b = found
                ls = pages_lines[pno][a:b + 1]
                box = [min(l[0][0] for l in ls), min(l[0][1] for l in ls),
                       max(l[0][2] for l in ls), max(l[0][3] for l in ls)]
                out[str(rowkey)] = {"page": pno, "box": [round(v, 2) for v in box]}
                break
    return out


def main() -> None:
    prov_paths = sorted(RAW.glob("**/provenance.json"))
    docs: dict[str, dict] = {}
    for path in prov_paths:
        prov = json.loads(path.read_text())
        if not prov.get("extractor") or not prov["request_url"].endswith(".pdf"):
            continue
        doc = docs.setdefault(prov["sha256"], {
            "code": prov["jurisdiction_code"], "title": prov.get("document_title") or prov.get("resource_name") or "",
            "url": prov["request_url"], "sha256": prov["sha256"],
            "years": set(), "pages": [], "provs": [],
        })
        doc["years"].add(prov["fiscal_year"])
        if prov.get("pages"):
            doc["pages"].append(tuple(prov["pages"]))
        doc["provs"].append((prov, path))

    index: dict[str, dict] = {}
    for sha, doc in sorted(docs.items()):
        doc_id = f"{doc['code']}-{sha[:12]}"
        doc_dir = OUT / doc_id
        render_done = (doc_dir / ".rendered").exists() \
            and (doc_dir / ".rendered").read_text().strip() == sha
        hits_done = (doc_dir / ".hits").exists() \
            and (doc_dir / ".hits").read_text().strip() == f"{sha} v{HITS_VERSION}"
        if render_done and hits_done:
            index[doc_id] = json.loads((doc_dir / "meta.json").read_text())
            continue

        first = min(p[0] for p in doc["pages"])
        last = max(p[1] for p in doc["pages"])
        doc_dir.mkdir(parents=True, exist_ok=True)

        if render_done:
            words_by_page = {}
            for f in doc_dir.glob("p*.json"):
                p = json.loads(f.read_text())
                words_by_page[int(f.stem[1:])] = (p["w"], p["h"], [tuple(w) for w in p["words"]])
        else:
            got = http_get(doc["url"])
            if got.sha256 != sha:
                print(f"warn  {doc_id}  sha256 が証跡と違う（再掲載された?）— この取得物で進める")
            for stale in [*doc_dir.glob("p*.png"), *doc_dir.glob("p*.json")]:
                stale.unlink(missing_ok=True)
            with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                f.write(got.body)
                pdf = pathlib.Path(f.name)
                try:
                    pages = pages_of(pdf, first, last)
                except subprocess.CalledProcessError:
                    pages = pages_of(pdf, first, last, redistill=True)
                words_by_page = {first + i: (w, h, ws) for i, (w, h, ws) in enumerate(pages)}
                for pno, (w, h, ws) in words_by_page.items():
                    (doc_dir / f"p{pno}.json").write_text(json.dumps(
                        {"w": round(w, 1), "h": round(h, 1),
                         "words": [[round(a, 2), round(b, 2), round(c, 2), round(d, 2), t]
                                   for a, b, c, d, t in ws]}, ensure_ascii=False))
                prefix = doc_dir / "img"
                subprocess.run(  # noqa: S603
                    ["pdftocairo", "-png", "-r", str(DPI), "-f", str(first), "-l", str(last),
                     str(pdf), str(prefix)], check=True)
                for img in doc_dir.glob("img-*.png"):
                    img.rename(doc_dir / f"p{int(img.stem.split('-')[-1])}.png")
            (doc_dir / ".rendered").write_text(sha + "\n")

        pages_lines = {pno: _lines(ws) for pno, (_, _, ws) in words_by_page.items()}
        hits: dict[str, dict] = {}
        sources: list[str] = []
        for prov, path in doc["provs"]:
            src = _source_id(prov, path)
            if src is None:
                continue
            sources.append(src)
            hits[src] = _hits(prov, path, pages_lines)
        (doc_dir / "hits.json").write_text(json.dumps(hits, ensure_ascii=False))
        (doc_dir / ".hits").write_text(f"{sha} v{HITS_VERSION}\n")

        meta = {
            "code": doc["code"], "title": doc["title"], "url": doc["url"], "sha256": sha,
            "years": sorted(doc["years"]), "first": first, "last": last,
            "textLayer": any(ws for _, _, ws in words_by_page.values()),
            # ⚠️ hits が0件のソースもここに入る（OCR の原典は対応が付かないが、
            # 「どの原典の頁か」は分かる — 語層が無いことと頁が無いことは別）
            "sources": sources,
        }
        (doc_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))
        index[doc_id] = meta
        n_hits = sum(len(h) for h in hits.values())
        print(f"ok    {doc_id}  p.{first}–{last}  語層 {'あり' if meta['textLayer'] else 'なし（OCR）'}  行対応 {n_hits} 件")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.json").write_text(json.dumps(
        {"generatedFrom": "data/budget/raw/**/provenance.json", "docs": index},
        ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
