"""HTTP の取得とキャッシュ。**層に依存しない。**

⚠️ **以前これは `ingestion/budget/fetch.py`（CSV の取得器）にあった。**
PDF から事業名を起こす取得器がそこから import しており、
**抽出器が CSV 取得器に依存する**という逆向きの依存になっていた。
②調達・③会議録の取得器を足せば同じ形で増える。共通処理は層の外に置く。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

import certifi

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

UA = "fudoki/0.1 (+https://github.com/wwwyo/fudoki)"
# 取得したものを置く。**commit しない**（.gitignore）。
# ⚠️ **取得元は自治体のサーバである。** 同じ資料を何度も取りに行かない。
# 開発中は抽出を作り込むために何度も回すので、キャッシュが無いと
# 1回の試行で PDF 4本（14MB）を落とすことになる。
CACHE = ROOT / "ingestion" / ".http-cache"
# 取り直す間隔。原典が差し替わったかを見るのは取得の目的なので、無期限にはしない。
CACHE_TTL_SECONDS = 24 * 60 * 60
# 取得の上限。**取得元の異常を止めるための柵**であって、資料の大きさの想定ではない。
# ⚠️ **20MB では本物の資料を弾いていた。** 3団体の CSV に合わせた値だったので、
# 予算書・決算書の PDF を取り始めた途端に落ち始めた（2026-08-30 実測で、
# 東村山市の決算書 37.7MB を筆頭に 173 本中 9 本が超えていた）。
# しかも `RuntimeError` は「取得元の異常」と名乗るので、**自分の閾値が原因なのに
# 相手のせいに見える**。北区・荒川区・調布市はこれで事項別明細書が落ち、
# 浅い資料だけが残って「目どまり」と誤って判定されていた。
MAX_BYTES = 128 * 1024 * 1024


@dataclass
class Fetched:
    url: str
    status: int
    body: bytes
    sha256: str
    fetched_at: str


def http_get(url: str, *, refresh: bool = False) -> Fetched:
    """取得する。**キャッシュがあればそれを返す。**

    ⚠️ **取得元は自治体のサーバである。** 同じ資料を何度も取りに行かない。
    取得したものは `.http-cache/`（commit しない）へ置き、既定で24時間は再利用する。

    ⚠️ **再試行はしない。** 以前ここに12回の指数バックオフを入れていたが、
    **実在しない問題への対策だった。** `IncompleteRead` を頻発させていたのは取得元ではなく、
    開発環境（Claude Code のサンドボックス）が通す HTTP プロキシで、
    切れる位置が毎回一致することから切り分けた。同じ URL を
    サンドボックス外の urllib と curl で取ると 5回とも成功する。
    再試行を残すと、**本物の切断を12回黙って握りつぶして失敗を遅らせるだけ**になり、
    「切り捨てを成功として扱わない」という取り込みの柱と逆を向く。
    ネットワークを叩くスクリプトはサンドボックスを外して回すこと（AGENTS.md）。
    """
    cached = _from_cache(url) if not refresh else None
    if cached is not None:
        return cached
    got = _http_get_once(url)
    _to_cache(got)
    return got


def _cache_path(url: str) -> pathlib.Path:
    return CACHE / f"{hashlib.sha256(url.encode()).hexdigest()[:32]}.json"


def _from_cache(url: str) -> Fetched | None:
    """キャッシュから返す。**取得時刻はキャッシュした時刻のまま**返す。

    ⚠️ 今の時刻を入れると、取り直していないのに証跡の `fetched_at` が動き、
    「いつ時点の原典から作られたか」が嘘になる。
    """
    path = _cache_path(url)
    if not path.exists():
        return None
    meta = json.loads(path.read_text())
    age = datetime.now(UTC) - datetime.fromisoformat(meta["fetched_at"])
    if age.total_seconds() > CACHE_TTL_SECONDS:
        return None
    body = (CACHE / meta["body"]).read_bytes()
    if hashlib.sha256(body).hexdigest() != meta["sha256"]:
        return None      # 壊れていたら取り直す
    print(f"cache {url}")
    return Fetched(url=meta["url"], status=meta["status"], body=body,
                   sha256=meta["sha256"], fetched_at=meta["fetched_at"])


def _to_cache(got: Fetched) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    body_name = f"{got.sha256[:32]}.body"
    (CACHE / body_name).write_bytes(got.body)
    _cache_path(got.url).write_text(json.dumps({
        "url": got.url, "status": got.status, "sha256": got.sha256,
        "fetched_at": got.fetched_at, "body": body_name,
    }, ensure_ascii=False))


def _tls_context() -> ssl.SSLContext:
    """CA を certifi に固定する。

    ⚠️ **OS の信頼ストアに任せると、団体によって黙って落ちる。**
    Python は macOS では `/private/etc/ssl/cert.pem` を見るが、これは Homebrew の
    OpenSSL が置いたもので、GlobalSign GCC R46 系の root を持たないことがある。
    実測（2026-08-30）で目黒区・小金井市が `CERTIFICATE_VERIFY_FAILED` になり、
    同じ URL を curl と openssl は検証できた。**取得元の異常ではなく実行環境の差**なので、
    どの環境でも同じ判定になるよう束を明示する。検証は外さない（外すと相手の
    なりすましを取り込む経路になる）。
    """
    return ssl.create_default_context(cafile=certifi.where())


def _http_get_once(url: str) -> Fetched:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40, context=_tls_context()) as res:  # noqa: S310  (取得元は sources.toml の固定 https)
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


