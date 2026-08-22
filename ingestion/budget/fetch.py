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
import http.client
import io
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

from ingestion.budget.sources import Catalog, Resource, Source, load_sources, resolve

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
# 層ごとに名前空間を切る。②調達は OCDS、③会議録は Popolo と、
# 標準も descriptor も別なので、同じ packages/ には収まらない。
LAYER = "budget"
RAW = ROOT / "data" / LAYER / "raw"

UA = "fudoki/0.1 (+https://github.com/wwwyo/fudoki)"
MAX_BYTES = 20 * 1024 * 1024


class Truncated(Exception):
    """応答が途中で切れた。**再試行してよい失敗。**

    ⚠️ 取得元の異常（MAX_BYTES 超過）とは別物なので例外を分ける。
    以前は両方 RuntimeError で、docstring は「Content-Length 突合で落ちたものを再試行する」と
    書いてあったのに実際には即死していた（説明と実装が食い違っていた）。
    """


@dataclass
class Fetched:
    url: str
    status: int
    body: bytes
    sha256: str
    fetched_at: str


def http_get(url: str, attempts: int = 12) -> Fetched:
    """取得する。**短く読めたら成功にしない。**

    ⚠️ 東京都カタログの検索 API は 5MB 級の応答を返すことがあり、
    実測で `IncompleteRead` が半分ほどの確率で出た（2026-08-22）。
    ここで諦めると取得が日によって落ちるので、切れた取得だけを繰り返す。
    切り捨てを成功として扱わないための仕組み（引数なしの read と Content-Length 突合）は
    そのままで、そこが落ちたものを再試行しているだけである。
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            return _http_get_once(url)
        except (Truncated, http.client.IncompleteRead, urllib.error.URLError, TimeoutError) as e:
            last = e
            print(f"retry {i + 1}/{attempts}  {type(e).__name__}  {url}")
            time.sleep(min(2 ** i, 8))
    raise RuntimeError(f"{attempts} 回試して取得できない: {url}") from last


def _http_get_once(url: str) -> Fetched:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as res:  # noqa: S310  (取得元は sources.toml の固定 https)
        # 引数なしの read() を使う。分割して読むと、途中で接続が切れても
        # 短いレスポンスとして黙って通ってしまう（IncompleteRead が上がらない）。
        body = res.read()
        declared = res.headers.get("Content-Length")
        if declared is not None and len(body) != int(declared):
            raise Truncated(f"Content-Length {declared} に対し {len(body)} バイトしか取れていない: {url}")
        if len(body) > MAX_BYTES:
            raise RuntimeError(f"{MAX_BYTES} バイトを超えた。取得元の異常: {url}")
        return Fetched(
            url=url,
            status=res.status,
            body=body,
            sha256=hashlib.sha256(body).hexdigest(),
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )


# CKAN の検索結果。**(カタログ, 団体) ごとに1回だけ引く。**
# ⚠️ データセット名ごとに引くと、狛江市は年度 × direction で12回になる。
# 応答は 1.4MB 級で IncompleteRead を頻発させる当のリクエストなので、
# 回数がそのまま失敗の確率と待ち時間になる（実測 2 → 14 回に増えていた）。
# 団体で絞れば1回で全データセットが返り、名前の一致は元から手元で見ている。
_SEARCH_CACHE: dict[str, list[dict]] = {}


def datasets_of(src: Source) -> list[dict]:
    """その団体のデータセット一覧。同じ団体を何度引いても取得は1回。"""
    org = src.catalog.org_prefix + src.jurisdiction_code
    key = f"{src.catalog.endpoint}\x1f{org}"
    if key not in _SEARCH_CACHE:
        # fq でカタログ側に絞らせる。q での全文検索と違い、団体が確定するので
        # 「同名データセットが別の団体にもある」場合の取り違えも起きない。
        query = urllib.parse.quote(f"organization:{org}")
        got = http_get(f"{src.catalog.endpoint}?fq={query}&rows=1000")
        result = json.loads(got.body).get("result", {})
        found, returned = result.get("count", 0), result.get("results", [])
        if found > len(returned):
            raise RuntimeError(
                f"{org} のデータセットが {found} 件あるのに {len(returned)} 件しか返っていない。"
                f"rows を増やすこと（先頭だけを見て「無い」と判定しないため）"
            )
        _SEARCH_CACHE[key] = returned
    return _SEARCH_CACHE[key]


def resolve_resource(src: Source, spec: Resource) -> str:
    """CKAN からリソース URL を引く。

    リソース URL は自治体側の CMS が振る内部番号で資料の差し替えで動くが、
    データセット名とリソース名は安定している。だから URL を直書きせず毎回解決する。

    ⚠️ **同名のデータセットが複数あるとき、黙って先頭を採らない。**
    狛江市は `/komae/R05/` と `/komae/` に同名のデータセットがあり、
    中身が違う（所属名称の改称、執行率が `-` と `****`）。
    先頭を採る実装だと、CKAN の並び順が変わった日に配布物の中身が入れ替わる。
    候補が複数のまま残ったら `resource_url_contains` の宣言を要求して止める。
    """
    dataset_title = src.dataset_title_for(spec)
    org = src.catalog.org_prefix + src.jurisdiction_code
    pkgs = [p for p in datasets_of(src) if p.get("title") == dataset_title]
    if not pkgs:
        raise RuntimeError(f"データセット「{dataset_title}」が {src.jurisdiction_name}（{org}）に見つからない")

    urls = sorted({r["url"] for p in pkgs for r in p.get("resources", [])
                   if r.get("name") == spec.resource_name})
    if not urls:
        names = sorted({r.get("name") for p in pkgs for r in p.get("resources", [])})
        raise RuntimeError(f"リソース「{spec.resource_name}」が無い。あるのは: {names}")

    if src.resource_url_contains is not None:
        urls = [u for u in urls if src.resource_url_contains in u]
        if not urls:
            raise RuntimeError(
                f"リソース「{spec.resource_name}」に "
                f"resource_url_contains=「{src.resource_url_contains}」を含む URL が無い"
            )
    if len(urls) > 1:
        if src.resource_url_contains is None:
            raise RuntimeError(
                f"データセット「{dataset_title}」のリソース「{spec.resource_name}」が {len(urls)} 件ある: {urls}。"
                f"どれを採るかを sources.toml の resource_url_contains で宣言すること"
            )
        raise RuntimeError(
            f"resource_url_contains=「{src.resource_url_contains}」で絞っても "
            f"リソース「{spec.resource_name}」が {len(urls)} 件残る: {urls}。"
            f"一意になる部分文字列へ変えること"
        )
    return urls[0]


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

        url = resolve_resource(src, spec)
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
            "dataset_title": src.dataset_title_for(spec),
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
    # 引数なしなら **`sources.toml` に登録された取得元すべて**。
    # ⚠️ 呼び出し側に取得元を並べさせない — 並べさせると、
    # 取得元を足したのに pipeline に足し忘れた状態が黙って通る。
    keys = sys.argv[1:] or sorted(load_sources())
    for key in keys:
        print(f"--- {key}")
        ingest(key)
