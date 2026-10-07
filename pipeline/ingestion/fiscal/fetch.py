"""原典を取得して `pipeline/.cache/` 配下の `raw/` へ Parquet で落とす。

解釈・整形・結合はしない。列はすべて VARCHAR のまま置く（型推論は判断なので staging の仕事）。

**「無加工」を主張ではなく検査にする。** 3つ通してから確定する。

1. 文字コードの復号が可逆か（原文バイトへ戻るか）
2. セル数がヘッダと揃っているか（揃っていないと列への射影で余りが落ちる）
3. 書き出した Parquet を読み戻して、原典の行と一致するか

どれか落ちたら書き出さない（気づかないまま加工された原典を配らないため）。

冪等。同じ SHA-256 の Parquet が既にあれば取得しない。
"""

from __future__ import annotations
from ingestion.inputs import record_input

import csv
import io
import json
import pathlib
import sys

from ingestion.fiscal.sources import Resource, Source, load_sources, resolve
from ingestion.lib.ckan import datasets_of_organization
from ingestion.lib.http import Fetched, http_get

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
# 層ごとに名前空間を切る。予算は FDP、調達は OCDS と、
# 標準も descriptor も別なので、同じ datapackages/ には収まらない。
LAYER = "budget"
from ingestion.paths import RAW

# CKAN の検索結果。**(カタログ, 団体) ごとに1回だけ引く。**
# ⚠️ データセット名ごとに引くと、狛江市は年度 × direction で12回になる。
# 応答は 1.4MB 級で IncompleteRead を頻発させる当のリクエストなので、
# 回数がそのまま失敗の確率と待ち時間になる（実測 2 → 14 回に増えていた）。
# 団体で絞れば1回で全データセットが返り、名前の一致は元から手元で見ている。
_SEARCH_CACHE: dict[str, list[dict]] = {}


def datasets_of(src: Source) -> list[dict]:
    """その団体のデータセット一覧。同じ団体を何度引いても取得は1回。

    列挙は ingestion.lib.ckan が受け持ち、ここではプロセス内でキャッシュする。
    """
    if src.catalog is None:
        raise RuntimeError(f"{src.key}: カタログの宣言が無い（全リソースが直 URL のはず）")
    org = src.catalog.org_prefix + src.jurisdiction_code
    key = f"{src.catalog.endpoint}\x1f{org}"
    if key not in _SEARCH_CACHE:
        _SEARCH_CACHE[key] = datasets_of_organization(src.catalog.endpoint, org)
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
    assert src.catalog is not None  # 直 URL のリソースはここへ来ない（呼ぶ側が分岐している）
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


def parse_records(text: str) -> tuple[str, list[str], str]:
    """Keep lexical CSV records so quoting and embedded newlines remain reversible."""
    lines = io.StringIO(text, newline="").readlines()
    reader = csv.reader(io.StringIO(text, newline=""))
    records = []
    cells = []
    previous = 0
    for row in reader:
        records.append("".join(lines[previous:reader.line_num]))
        cells.append(row)
        previous = reader.line_num
    trailing = []
    while cells and not any(c.strip() for c in cells[-1]):
        cells.pop()
        trailing.insert(0, records.pop())
    if not records:
        raise RuntimeError("行が無い")
    return records[0], records[1:], "".join(trailing)


def _source_json(src: Source, spec: Resource, direction: str, got: Fetched,
                     header: list[str], rows: int, fetched_at: str | None = None,
                     csv_layout: dict | None = None) -> str:
    """入力一覧へ渡す出典・意味の宣言と取り込み結果。"""
    return json.dumps({
            "source_key": src.key,
            "jurisdiction_code": src.jurisdiction_code,
            "fiscal_year": src.fiscal_year,
            "direction": direction,
            "document_kind": src.document_kind,
            # ⚠️ **直 URL では None。** カタログを引いていないので載せているデータセットが無い。
            # 以前はここに取得元の既定（カタログのデータセット名）が入っており、
            # **市サイトから取ったものの証跡が、引いてもいないカタログを指していた。**
            # 資料の在り処は landing_page（配布物のパッケージ単位の `sources`）が持つ。
            "dataset_title": src.dataset_title_for(spec),
            "resource_name": spec.resource_name,
            # ⚠️ **していない照合を書かない。** ここは長く「年度の照合は原典の年度列と
            # partition の突き合わせで行う」と書いていたが、**原典に年度の列が無い
            # (団体, 年度, direction) が実在する**（多摩市の令和7年度の歳出）。
            # その組では誰も年度を照合しておらず、証跡だけが照合したと言っている状態になる。
            # 取得側が言えるのは「どう年度を決めたか」までなので、そこで止める。
            "fiscal_year_basis": (
                f"sources.toml が宣言した公式ページの URL。"
                f"リソース名「{spec.resource_name}」は取得元ページのリンクテキストを人が写したもので、"
                f"取得時には照合していない（宣言どうしの自己参照になるため）。"
                f"根拠は resource_url_basis にある"
                if spec.url is not None else
                f"CKAN のリソース名「{spec.resource_name}」の「{src.fiscal_year_label}」から解決"
            ),
            # カタログを介さず直接取りに行ったか。**リソース URL の安定性の保証が違う**
            # （カタログ経由は名前から毎回解決するので資料の差し替えに追随する）。
            "resource_url_declared": spec.url is not None,
            "resource_url_basis": spec.url_basis,
            "request_url": got.url,
            "status": got.status,
            "bytes": len(got.body),
            "sha256": got.sha256,
            "fetched_at": fetched_at or got.fetched_at,
            "encoding": src.encoding,
            "header": header,
            "rows": rows,
            # `raw/` の保証は団体で違う。verbatim なら原文を復元できることを検査済み、
            # extracted なら抽出結果なので復元は成立しない。下流の検査がこれで分岐する。
            "raw_form": src.raw_form,
            "roundtrip_verified": True,
            **({"csv_layout": csv_layout} if csv_layout is not None else {}),
            "license_id": src.license_id,
            "attribution": src.attribution,
        }, ensure_ascii=False, indent=2) + "\n"


def ingest(key: str) -> None:
    src = resolve(key)

    # ⚠️ **この取得器は原文をそのまま置くものだけを扱う。**
    # 「原文を置けるのは再配布可のときだけ」という不変条件は `Source` が持っているので、
    # ここでは扱える形かどうかだけを見る（同じ規則を2箇所に置かない）。
    # 抽出する取得器は別に要る（raw_form=extracted。原文を復元できないので復元検査が成立しない）。
    if src.raw_form != "verbatim":
        raise RuntimeError(
            f"{key} は raw_form={src.raw_form}。この取得器は原文をそのまま置くものなので扱えない"
        )

    for spec in src.resources:
        direction = spec.direction
        # 年度の唯一の出所はリソース名。照合できなければ収録しない。
        # ⚠️ **直 URL の宣言があるときは、この照合が成立しない** — resource_name が
        # カタログの持つ名前ではなく fudoki の書いた文字列になるので、自己参照になる。
        # ⚠️ **移る先があるとは限らない。** 原典に年度の列があれば dbt の
        # source_year_matches_partition が partition と突き合わせるが、
        # **その列が無い (団体, 年度, direction) が実在する**（多摩市の令和7年度の歳出）。
        # そのとき年度を言っているのは、人が取得元ページで読んだ見出しとリンクテキストだけで、
        # それは `url_basis` に文章として残っている（機械は見ていない）。
        if spec.url is None:
            # 直 URL のときは宣言そのものが無い（load_sources が禁じている）
            assert src.fiscal_year_label is not None
        if spec.url is None and src.fiscal_year_label not in spec.resource_name:
            raise RuntimeError(f"リソース名「{spec.resource_name}」に年度表記「{src.fiscal_year_label}」が無い")

        url = spec.url or resolve_resource(src, spec)
        got = http_get(url)
        if got.status != 200:
            raise RuntimeError(f"HTTP {got.status}: {url}")

        out_dir = (RAW / f"jurisdiction={src.jurisdiction_code}" / f"year={src.fiscal_year}"
                   / f"document_kind={src.document_kind}" / f"edition={got.sha256}" / f"direction={direction}")
        out = out_dir / "data.parquet"
        text = got.body.decode(src.encoding)
        # 復号が可逆か検査する。文字コードを取り違えると黙って別の字に化けるので、
        # 「読めた」ことを成功と見なさない。
        if text.encode(src.encoding) != got.body:
            raise RuntimeError(f"{direction}: {src.encoding} での復号が可逆でない。文字コードの指定が誤っている")
        text = text.lstrip("\ufeff")

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

        # Keep original record syntax as well as decoded cells; quoting is not inferred.
        header_record, records, trailing_records = parse_records(text)
        if header_record + "".join(records) + trailing_records != text:
            raise RuntimeError(f"{direction}: CSV レコードから原文を復元できない")
        if len(records) != len(rows) or any(
            list(csv.reader(io.StringIO(record, newline=""))) != [row]
            for record, row in zip(records, rows, strict=True)
        ):
            raise RuntimeError(f"{direction}: 原文レコードとセルが一致しない")
        csv_layout = {"header_record": header_record, "trailing_records": trailing_records,
                      "record_column": "source_record"}
        if "source_record" in header or "source_row" in header:
            raise RuntimeError(f"{direction}: 原典の列名が証跡列と衝突する")

        import duckdb  # noqa: PLC0415  (取得だけしたいときに import させない)

        out_dir.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect()
        con.execute("CREATE TABLE t (source_row BIGINT, cells VARCHAR[], source_record VARCHAR)")
        con.executemany("INSERT INTO t VALUES (?, ?, ?)", [(i + 2, r, records[i]) for i, r in enumerate(rows)])
        # 列名は原典のヘッダそのまま。全列 VARCHAR（型推論は判断なので staging へ）。
        cols = ", ".join(f'cells[{i + 1}] AS "{h}"' for i, h in enumerate(header))
        con.execute(f"COPY (SELECT source_row, {cols}, source_record FROM t ORDER BY source_row) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")

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
        back_records = [r[0] for r in con.execute(
            f"SELECT source_record FROM read_parquet('{out}') ORDER BY source_row"
        ).fetchall()]
        if back_records != records or header_record + "".join(back_records) + trailing_records != text:
            raise RuntimeError(f"{direction}: Parquet の原文レコードが一致しない")
        con.close()

        record_input(out_dir, json.loads(_source_json(src, spec, direction, got, header, len(rows), csv_layout=csv_layout)))
        print(f"ok    {direction}  {len(rows)} 行  {len(got.body)} バイト  sha256={got.sha256[:16]}…  復元一致")


if __name__ == "__main__":
    # 引数なしなら **`sources.toml` に登録された取得元すべて**。
    # ⚠️ 呼び出し側に取得元を並べさせない — 並べさせると、
    # 取得元を足したのに pipeline に足し忘れた状態が黙って通る。
    keys = sys.argv[1:] or sorted(load_sources())
    for key in keys:
        print(f"--- {key}")
        ingest(key)
