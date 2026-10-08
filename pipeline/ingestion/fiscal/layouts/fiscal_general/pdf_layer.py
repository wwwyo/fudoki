"""原典 PDF のローカル閲覧レイヤを組む。

検証画面（`/pipeline/<団体コード>/`）が「原典 → 取り込み」の組を開いたとき、
原典の頁をその姿で出すための頁画像・語の文字層・行→頁内位置の対応を書き出す。

出力は pipeline/.cache/pdf/ に置く。固定した原典のハッシュと生成処理・依存・設定で
キャッシュを区切り、原典 URL から最新の資料を再取得しない。

使い方: `bun run --cwd pipeline pdf:layer`（`bun run pipeline` の一部）
"""

from __future__ import annotations

import hashlib
import json
import struct
import pathlib
import re
import subprocess
import tempfile
import argparse

import duckdb

from ingestion.fiscal.layouts.fiscal_general.statement_layout import normalize
from ingestion.inputs import origin_path
from ingestion.lib.pdf import pages_of

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent.parent
from ingestion.paths import RAW
OUT = ROOT / ".cache" / "pdf"

# 頁画像の解像度。検証画面は原寸確認が主ではないので、文字が潰れない下限より少し上
DPI = 110

# 行→頁対応の作り方の版。照合ロジックを変えたら上げる（頁画像・語層は原典だけに
# 依存するので作り直さず、hits.json だけを再計算する）
HITS_VERSION = 6
GENERATOR_KEY = hashlib.sha256(
    pathlib.Path(__file__).read_bytes() + (ROOT.parent / 'uv.lock').read_bytes()
    + f'{DPI}:{HITS_VERSION}'.encode()
).hexdigest()[:16]


def _source_id(prov: dict, prov_path: pathlib.Path) -> str | None:
    """証跡がぶら下がる系統上のソースノードの id。

    ⚠️ **正本の取り込みと抽出物で id の形が違う**（dbt の `sources` がそう名乗る）。
    判定は `extractor` のパスではなく置き場でやる — 両方とも extractor を持つので
    中身では区別が付かない。
    """
    parts = prov_path.relative_to(RAW).parts
    code = prov["jurisdiction_code"]
    if parts[0] == 'statement-moku-setsu':
        return f"source.fudoki.raw_{code}_moku_setsu.data"
    if parts[0].startswith("jurisdiction="):
        if prov.get('table_id') and 'extract_statement' not in (prov.get('extractor') or ''):
            return f"source.fudoki.raw_{code}_history.data"
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
    for r in duckdb.query(
            f"select {cols} from read_parquet('{parquet}') order by source_row").fetchall():
        (row, kan, kou, moku, moku_name, proj, setsu, detail, amount) = r
        names = [n for n in (detail, setsu, proj) if n]
        candidates = [normalize(n) for n in names] if names else [
            normalize(moku_name or ""), normalize(f"{kan}-{kou}-{moku}{moku_name or ''}")]
        yield row, [c for c in candidates if c], int(amount or 0)


def _project_name_rows(parquet: pathlib.Path):
    for row, name, amount in duckdb.query(
            f"select ordinal, project_name, amount_thousand_yen from read_parquet('{parquet}')"
            " order by ordinal").fetchall():
        yield row, [normalize(name)] if name else [], int(amount or 0)


# 名称の折り返しは ±2 行まで見る。折り返した名前は金額と同じ行に全部は載らないので、
# 「金額の行 ± 近接行の連結」に名称が収まるかを見る
WRAP = 2


def _hits(prov: dict, prov_path: pathlib.Path, pages_lines: dict[int, list[Line]]):
    """行 → 頁内位置。名称と金額（桁区切り付きの印字の形）を同じ箇所に持つ語の帯を探す。

    金額は語単位で照合する — `262` が `1,262` の部分文字列として当たる誤検出を避ける。
    名称は行に折り返されうるので、金額の行の前後 WRAP 行を連結した文字列で照合する。
    """
    if prov.get('table_id'):
        page_column, box_column = ('source_page', 'source_bbox') \
            if 'extract_statement' in (prov.get('extractor') or '') else ('page_number', 'bbox_json')
        rows = duckdb.query(f"select source_row, {page_column}, {box_column} from read_parquet('{prov_path.parent / 'data.parquet'}')").fetchall()
        out = {}
        for row, page, box in rows:
            bounds = json.loads(box) if box else None
            if page is not None and isinstance(bounds, list) and len(bounds) == 4:
                out[f"{prov['sha256']}|{prov['table_id']}|{row}"] = {"page": page, "box": bounds}
        return out
    kind = "statement" if "extract_statement" in (prov.get("extractor") or "") \
        else "project-names" if "extract_projects" in (prov.get("extractor") or "") else None
    if kind is None or not prov.get("pages"):   # revenue-accounts は OCR のみ — 語の層が無い
        return {}
    rows = _statement_rows(prov_path.parent / "data.parquet") if kind == "statement" \
        else _project_name_rows(prov_path.parent / "data.parquet")
    first, last = prov["pages"]
    out: dict[str, dict] = {}
    # 抽出の順序 = 文書中の並び順（rowkey が文書順に振られている）。同名・同額の
    # 別行（実在する）が全員同じ印字箇所を指さないよう、探索は前の行の一致位置の
    # 後からだけ進める — 「最初の一致」に畳むと重複行すべてが誤対応になる
    cur_p, cur_i = first, 0
    for rowkey, names, amount in rows:
        # 金額は語の中で `316,980千円` のように単位を伴うことがあり、また語の分割を
        # またぐことがある（`57,` `397`）。語単位と、隣接2語の連結の両方で見る。
        # 直前が数字・カンマのもの（`1,262` の `262`）は別の金額の一部なので弾く
        amount_re = re.compile(
            r"(?<![0-9,])" + re.escape(normalize(f"{amount:,}")) + r"(?:千円|円)?$")
        found = None
        for name in names:
            for pno in range(cur_p, last + 1):
                lines = pages_lines.get(pno, [])
                for i in range(cur_i if pno == cur_p else 0, len(lines)):
                    _, text, words = lines[i]
                    hit_amount = any(amount_re.search(w) for w in words) or any(
                        amount_re.fullmatch(words[j] + words[j + 1])
                        for j in range(len(words) - 1))
                    if not hit_amount:
                        continue
                    if name in text:
                        found = (pno, i, i, i)
                    else:
                        for a, b in ((max(0, i - WRAP), i), (i, min(len(lines) - 1, i + WRAP))):
                            if name in "".join(t for _, t, _ in lines[a:b + 1]):
                                found = (pno, i, a, b)
                                break
                    if found:
                        break
                if found:
                    break
            if found:
                break
        if found:
            pno, i, a, b = found
            # 次の行はこの行の金額行より後にある — 同じ行へ二度割り当てない
            cur_p, cur_i = pno, i + 1
            ls = pages_lines[pno][a:b + 1]
            box = [min(l[0][0] for l in ls), min(l[0][1] for l in ls),
                   max(l[0][2] for l in ls), max(l[0][3] for l in ls)]
            out[str(rowkey)] = {"page": pno, "box": [round(v, 2) for v in box]}
    return out


def page_dimensions(width: float, height: float, png: pathlib.Path) -> tuple[float, float]:
    """描画画像と同じ向きの頁寸法を返す。回転PDFの文字座標は表示方向に従う。"""
    with png.open('rb') as stream:
        header = stream.read(24)
    if header[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Page render is not PNG')
    pixels_w, pixels_h = struct.unpack('>II', header[16:24])
    if (width > height) != (pixels_w > pixels_h):
        width, height = height, width
    if abs(width / height - pixels_w / pixels_h) > 0.01:
        raise ValueError('Page render and text dimensions disagree')
    return width, height


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jurisdiction', help='Render only this six-digit jurisdiction; preserve current generator cache entries for others')
    parser.add_argument('--origin-sha', help='Render only this fixed original SHA-256; preserve other current generator cache entries')
    args = parser.parse_args()
    selected = args.jurisdiction
    selected_sha = args.origin_sha
    if selected and not re.fullmatch(r'\d{6}', selected):
        parser.error('--jurisdiction requires six digits')
    if selected_sha and not re.fullmatch(r'[0-9a-f]{64}', selected_sha):
        parser.error('--origin-sha requires a lowercase SHA-256')
    from ingestion.inputs import describe_inputs
    from ingestion.paths import INPUT_LOCK
    input_descriptions = describe_inputs(INPUT_LOCK, RAW)
    docs: dict[str, dict] = {}
    for item in input_descriptions:
        path = RAW / item['path'] / 'data.parquet'
        prov = item['source']
        if selected and prov['jurisdiction_code'] != selected:
            continue
        if selected_sha and prov['sha256'] != selected_sha:
            continue
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

    def _parquet_fp(path: pathlib.Path) -> str | None:
        # 抽出 parquet が作り直されると行↔頁の対応は変わる — 証跡が同じでも
        # hits を再計算する必要があるので、読む parquet の内容を鍵に混ぜる
        f = path.parent / "data.parquet"
        return hashlib.sha256(f.read_bytes()).hexdigest()[:16] if f.exists() else None

    def _rendered(d: pathlib.Path, sha: str, first: int, last: int) -> bool:
        m = d / ".rendered"
        if not m.exists():
            return False
        marker = m.read_text().strip()
        if marker == f"{sha} {first}-{last}":
            return True
        if marker == sha:
            # 範囲を記録しない旧形式。要求範囲の画像と語層が揃っていれば
            # 新形式へ書き換えて済ませ、欠けていれば再レンダリングへ落とす
            if all((d / f"p{p}.png").exists() and (d / f"p{p}.json").exists()
                   for p in range(first, last + 1)):
                m.write_text(f"{sha} {first}-{last}\n")
                return True
        return False

    index: dict[str, dict] = {}
    index_path = OUT / 'index.json'
    if selected_sha and not docs:
        parser.error('--origin-sha did not match a fixed PDF input in the selected jurisdiction')
    if (selected or selected_sha) and index_path.exists():
        previous = json.loads(index_path.read_text()).get('docs', {})
        index = {key: value for key, value in previous.items()
                 if f'-{GENERATOR_KEY}-' in key
                 and (value['sha256'] != selected_sha if selected_sha else value['code'] != selected)}
    for sha, doc in sorted(docs.items()):
        doc_id = f"{doc['code']}-{GENERATOR_KEY}-{sha[:12]}"
        doc_dir = OUT / doc_id
        if not doc["pages"]:
            # 頁範囲を記録していない証跡では頁画像も対応も作れない（現行の証跡は全件記録）
            print(f"warn  {doc_id}  証跡に頁範囲が無い — スキップ")
            continue
        first = min(p[0] for p in doc["pages"])
        last = max(p[1] for p in doc["pages"])

        # hits/meta は証跡の中身（URL・頁範囲・年度・ソース紐付け）と抽出結果にも
        # 依存する。sha と照合版だけで判定すると、同じ PDF を指す証跡や抽出した
        # 行が更新されても古い meta と対応を使い続ける — 証跡・parquet 由来の
        # 部分もキャッシュキーに入れる
        meta_key = json.dumps(sorted(
            json.dumps([_source_id(p, pp), p["request_url"], p.get("pages"),
                        p["fiscal_year"], _parquet_fp(pp)], ensure_ascii=False)
            for p, pp in doc["provs"]), ensure_ascii=False)
        stamp = f"{sha} v{HITS_VERSION} {hashlib.sha256(meta_key.encode()).hexdigest()[:16]}"
        # 頁範囲が広がったとき render_done のままだと、新しい頁には画像も語層も
        # 無いまま meta だけ書くことになる — レンダリング済みの判定も範囲込みにする
        render_done = _rendered(doc_dir, sha, first, last)
        hits_done = (doc_dir / ".hits").exists() \
            and (doc_dir / ".hits").read_text().strip() == stamp
        if render_done and hits_done:
            index[doc_id] = json.loads((doc_dir / "meta.json").read_text())
            continue

        doc_dir.mkdir(parents=True, exist_ok=True)

        if render_done:
            words_by_page = {}
            for f in doc_dir.glob("p*.json"):
                p = json.loads(f.read_text())
                words_by_page[int(f.stem[1:])] = (p["w"], p["h"], [tuple(w) for w in p["words"]])
        else:
            origin = origin_path(sha)
            for stale in [*doc_dir.glob("p*.png"), *doc_dir.glob("p*.json")]:
                stale.unlink(missing_ok=True)
            with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                f.write(origin.read_bytes())
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
            (doc_dir / ".rendered").write_text(f"{sha} {first}-{last}\n")

        # Popplerの文字層は回転前のMediaBox寸法を返す場合があり、PNGは表示方向になる。
        for pno, (w, h, ws) in list(words_by_page.items()):
            w, h = page_dimensions(w, h, doc_dir / f"p{pno}.png")
            words_by_page[pno] = (w, h, ws)
            (doc_dir / f"p{pno}.json").write_text(json.dumps(
                {"w": round(w, 1), "h": round(h, 1), "words": ws}, ensure_ascii=False))
        pages_lines = {pno: _lines(ws) for pno, (_, _, ws) in words_by_page.items()}
        hits: dict[str, dict] = {}
        sources: list[str] = []
        for prov, path in doc["provs"]:
            src = _source_id(prov, path)
            if src is None:
                continue
            sources.append(src)
            hits.setdefault(src, {}).update(_hits(prov, path, pages_lines))
        (doc_dir / "hits.json").write_text(json.dumps(hits, ensure_ascii=False))
        (doc_dir / ".hits").write_text(stamp + "\n")

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
        {"generatedFrom": "fixed input source declarations", "docs": index},
        ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
