"""原典を取得して data/budget/raw/ へ Parquet で落とす。

解釈・整形・結合はしない。列はすべて VARCHAR のまま置く（型推論は判断なので staging の仕事）。

**「無加工」を主張ではなく検査にする。** 3つ通してから確定する。

1. 文字コードの復号が可逆か（原文バイトへ戻るか）
2. セル数がヘッダと揃っているか（揃っていないと列への射影で余りが落ちる）
3. 書き出した Parquet を読み戻して、原典の行と一致するか

どれか落ちたら書き出さない（気づかないまま加工された原典を配らないため）。

冪等。同じ SHA-256 の Parquet が既にあれば取得しない。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import pathlib
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

from ingestion.budget.sources import Catalog, Source, resolve

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
# 層ごとに名前空間を切る。②調達は OCDS、③会議録は Popolo と、
# 標準も descriptor も別なので、同じ packages/ には収まらない。
LAYER = "budget"
RAW = ROOT / "data" / LAYER / "raw"

UA = "fudoki/0.1 (+https://github.com/wwwyo/fudoki)"
MAX_BYTES = 20 * 1024 * 1024


@dataclass
class Fetched:
    url: str
    status: int
    body: bytes
    sha256: str
    fetched_at: str


def http_get(url: str) -> Fetched:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as res:  # noqa: S310  (取得元は sources.toml の固定 https)
        # 引数なしの read() を使う。分割して読むと、途中で接続が切れても
        # 短いレスポンスとして黙って通ってしまう（IncompleteRead が上がらない）。
        body = res.read()
        declared = res.headers.get("Content-Length")
        if declared is not None and len(body) != int(declared):
            raise RuntimeError(f"Content-Length {declared} に対し {len(body)} バイトしか取れていない: {url}")
        if len(body) > MAX_BYTES:
            raise RuntimeError(f"{MAX_BYTES} バイトを超えた。取得元の異常: {url}")
        return Fetched(
            url=url,
            status=res.status,
            body=body,
            sha256=hashlib.sha256(body).hexdigest(),
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )


def resolve_resource(src: Source, resource_name: str) -> str:
    """CKAN からリソース URL を引く。

    リソース URL は自治体側の CMS が振る内部番号で資料の差し替えで動くが、
    データセット名とリソース名は安定している。だから URL を直書きせず毎回解決する。
    """
    catalog: Catalog = src.catalog
    q = urllib.parse.quote(src.dataset_title)
    got = http_get(f"{catalog.endpoint}?q={q}&rows=300")
    results = json.loads(got.body).get("result", {}).get("results", [])
    org = catalog.org_prefix + src.jurisdiction_code
    pkg = next(
        (p for p in results
         if (p.get("organization") or {}).get("name") == org and p.get("title") == src.dataset_title),
        None,
    )
    if pkg is None:
        raise RuntimeError(f"データセット「{src.dataset_title}」が {src.jurisdiction_name}（{org}）に見つからない")
    res = next((r for r in pkg.get("resources", []) if r.get("name") == resource_name), None)
    if res is None:
        names = [r.get("name") for r in pkg.get("resources", [])]
        raise RuntimeError(f"リソース「{resource_name}」が無い。あるのは: {names}")
    return res["url"]


def parse_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """CSV を行と列に割る。**セルを trim しない**（空白の除去も加工なので staging の仕事）。"""
    rows = list(csv.reader(io.StringIO(text, newline="")))
    while rows and not any(c.strip() for c in rows[-1]):
        rows.pop()
    if not rows:
        raise RuntimeError("行が無い")
    return rows[0], rows[1:]


def reconstruct(header: list[str], rows: list[list[str]], newline: str, trailing: str) -> str:
    """復元。原典が引用符を使っていない前提で、使っていたらここで一致しなくなり検知できる。"""
    return newline.join(",".join(r) for r in [header, *rows]) + trailing


def ingest(key: str) -> None:
    src = resolve(key)

    if not src.may_publish_raw:
        raise RuntimeError(
            f"{key} は redistribute={src.redistribute}。再配布可と判定した取得元しか raw を書き出さない"
        )

    for spec in src.resources:
        direction = spec.direction
        # ⚠️ **phase を含める。** 当初予算と補正予算は同じ (団体, 年度, direction) を持つ。
        # 含めないと後から補正を足したとき、黙って上書きされる。
        out_dir = (RAW / f"jurisdiction={src.jurisdiction_code}" / f"year={src.fiscal_year}"
                   / f"phase={src.phase_id}" / f"direction={direction}")
        out = out_dir / "data.parquet"
        # 証跡は取得物の隣に置く。**この2つは不可分**で、別の木に分けると
        # どの Parquet がどの取得に対応するかがパスの規約でしか繋がらなくなる。
        prov_path = out_dir / "provenance.json"

        # 年度の唯一の出所はリソース名。照合できなければ収録しない。
        if src.fiscal_year_label not in spec.resource_name:
            raise RuntimeError(f"リソース名「{spec.resource_name}」に年度表記「{src.fiscal_year_label}」が無い")

        url = resolve_resource(src, spec.resource_name)
        got = http_get(url)
        if got.status != 200:
            raise RuntimeError(f"HTTP {got.status}: {url}")

        if prov_path.exists() and json.loads(prov_path.read_text()).get("sha256") == got.sha256 and out.exists():
            print(f"skip  {direction}  同じ SHA-256 の Parquet が既にある")
            continue

        text = got.body.decode(src.encoding)
        # 復号が可逆か検査する。文字コードを取り違えると黙って別の字に化けるので、
        # 「読めた」ことを成功と見なさない。
        if text.encode(src.encoding) != got.body:
            raise RuntimeError(f"{direction}: {src.encoding} での復号が可逆でない。文字コードの指定が誤っている")
        text = text.lstrip("\ufeff")

        newline = "\r\n" if "\r\n" in text else "\n"
        header, rows = parse_rows(text)

        # ⚠️ **セル数がヘッダと揃っているか先に見る。**
        # 揃っていない行を列へ射影すると余りが黙って落ちる。
        # 復元の検査は parse 済みの行を使うので、この落ち方は検出できない。
        odd = [(i + 2, len(r)) for i, r in enumerate(rows) if len(r) != len(header)]
        if odd:
            raise RuntimeError(
                f"{direction}: セル数がヘッダ（{len(header)}列）と違う行がある: "
                f"{odd[:5]}{' ほか' if len(odd) > 5 else ''}"
            )

        # 無加工の検査。復元して原文と一致しなければ書き出さない。
        trailing = text[len(text.rstrip("\r\n")):]
        rebuilt = reconstruct(header, rows, newline, trailing)
        if rebuilt != text:
            raise RuntimeError(
                f"{direction}: Parquet から原文を復元できない（引用符や改行を含む可能性）。"
                f"原文 {len(text)} 文字 / 復元 {len(rebuilt)} 文字"
            )

        import duckdb  # noqa: PLC0415  (取得だけしたいときに import させない)

        out_dir.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect()
        con.execute("CREATE TABLE t (source_row BIGINT, cells VARCHAR[])")
        con.executemany("INSERT INTO t VALUES (?, ?)", [(i + 2, r) for i, r in enumerate(rows)])
        # 列名は原典のヘッダそのまま。全列 VARCHAR（型推論は判断なので staging へ）。
        cols = ", ".join(f'cells[{i + 1}] AS "{h}"' for i, h in enumerate(header))
        con.execute(f"COPY (SELECT source_row, {cols} FROM t ORDER BY source_row) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")

        # **書いた Parquet を読み戻して確かめる。**
        # ここまでの検査は parse 済みの行しか見ておらず、書き出しで
        # 空文字が NULL になるような取りこぼしを検出できない。
        back = con.execute(
            f"SELECT {', '.join(f'\"{h}\"' for h in header)} FROM read_parquet('{out}') ORDER BY source_row"
        ).fetchall()
        if [list(r) for r in back] != rows:
            diff = next(
                (i + 2 for i, (a, b) in enumerate(zip(back, rows, strict=True)) if list(a) != b),
                None,
            )
            raise RuntimeError(
                f"{direction}: 書き出した Parquet が原典の行と一致しない"
                f"（最初の相違は {diff} 行目）"
            )
        con.close()

        prov_path.write_text(json.dumps({
            "jurisdiction_code": src.jurisdiction_code,
            "fiscal_year": src.fiscal_year,
            "direction": direction,
            "dataset_title": src.dataset_title,
            "resource_name": spec.resource_name,
            "fiscal_year_basis": f"CKAN のリソース名「{spec.resource_name}」の「{src.fiscal_year_label}」から解決",
            "request_url": got.url,
            "status": got.status,
            "bytes": len(got.body),
            "sha256": got.sha256,
            "fetched_at": got.fetched_at,
            "encoding": src.encoding,
            "header": header,
            "rows": len(rows),
            "roundtrip_verified": True,
            "license_id": src.license_id,
            "attribution": src.attribution,
        }, ensure_ascii=False, indent=2) + "\n")
        print(f"ok    {direction}  {len(rows)} 行  {len(got.body)} バイト  sha256={got.sha256[:16]}…  復元一致")


if __name__ == "__main__":
    ingest(sys.argv[1] if len(sys.argv) > 1 else "132047:2024")
