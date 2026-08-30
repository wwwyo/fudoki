"""東京都62団体の境界データを組む。`bun run fetch:boundaries`

ホームページの地図（自治体クリック→その団体のパイプラインへ）に使う表示用データ。
正本ではなく表示用の派生物なので `apps/web/public/tokyo.geojson` に置く
（`apps/web/brand/build.py` と同じ「生成物と consumer の近くに置く」置き場）。

取得元は国土数値情報 行政区域データ（N03、国土交通省、CC BY 4.0）。

⚠️ **公式サイトの「最新データ」ページの相対リンクが正準 URL である。**
年度ごとの datalist ページ（`KsjTmplt-N03-<year>.html`）自体は
`../data/N03-<date>_13_GML.zip` のような単純な URL を推測させるが、
実際の配置は `../data/N03/N03-<year>/N03-<date>_13_GML.zip`
（年フォルダが1段挟まる）。実測で確認してから固定する。

⚠️ **2026年版（2026-01-01時点）を採用した。** 2025年版・2026年版とも配布されているが、
2026年版は 2026-04 公開で既に5か月経過しており（2026-08-30 実測）、
「最新だが未成熟」ではない。最新の境界を使う理由でこちらを選ぶ。
"""

from __future__ import annotations

import io
import json
import pathlib
import zipfile

from ingestion.lib.http import http_get

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
OUT = ROOT / "apps" / "web" / "public" / "tokyo.geojson"
JURISDICTIONS = ROOT / "ingestion" / "shared" / "jurisdictions.json"

URL = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/N03-20260101_13_GML.zip"
SHA256 = "94f10b26256566db970dd74b09d614f059c1e8a432f9244ac9c4add76c32ff16"
ENTRY = "N03-20260101_13.geojson"

# 東京都のうち島嶼部（本土から離れた9町村）。
# ⚠️ **緯度経度のハードコードでは判定しない。** 島であることは地理的な事実だが、
# 「どこまでが本土か」を座標で線引きするのは fudoki の判断になってしまう。
# 代わりに、東京都総務局が実際に敷いている行政区分（支庁）をそのまま使う——
# 大島支庁・三宅支庁・八丈支庁・小笠原支庁の管轄下にある9町村が、都が「島嶼部」として
# 扱っている対象と一致する（多摩地域の山間部にある瑞穂町・日の出町・檜原村・奥多摩町は
# 本土側の西多摩郡であって支庁の管轄ではないため、ここには含めない）。
ISLAND_CODES = frozenset({
    "133612",  # 大島町   （大島支庁）
    "133621",  # 利島村   （大島支庁）
    "133639",  # 新島村   （大島支庁）
    "133647",  # 神津島村 （大島支庁）
    "133817",  # 三宅村   （三宅支庁）
    "133825",  # 御蔵島村 （三宅支庁）
    "134015",  # 八丈町   （八丈支庁）
    "134023",  # 青ヶ島村 （八丈支庁）
    "134210",  # 小笠原村 （小笠原支庁）
})

# 簡略化の許容幅（度）。東京の緯度（約35.7°N）では
# 経度方向 約0.001°≈90m、緯度方向 約0.001°≈111m に相当するので、
# 0.0005° はおよそ 50m。**この数字は実際に出力サイズを見て決めた**
# （0 → 8.9MB、0.0002° → 917KB、0.0005° → 778KB、0.001° → 720KB、
# 0.01° まで上げても 660KB 止まりで頭打ち——大部分の点数は
# 主要な海岸線の複雑さではなく、小笠原諸島の無数の小島に張り付いているため）。
# 「数百 KB」の目標に対して形状の崩れを抑えたいので、頭打ちの手前で最も緩い
# 0.0005° を採る。
SIMPLIFY_TOLERANCE_DEG = 0.0005

# 座標の丸め桁。4桁 ≈ 11m（AGENTS.md の指定通り）。
COORD_DECIMALS = 4


def _perpendicular_distance(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    (x, y), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5
    t = ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)
    px, py = ax + t * dx, ay + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def _rdp(points: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    """Douglas-Peucker（開いた折れ線）。

    再帰ではなくスタックで書く。海岸線の折れ線は数千点になることがあり、
    再帰版だと最悪ケース（点がほぼ一直線に並ばない複雑な形状）で
    Python の再帰上限（既定1000）に当たる。
    """
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i0, i1 = stack.pop()
        a, b = points[i0], points[i1]
        dmax, idx = -1.0, -1
        for i in range(i0 + 1, i1):
            d = _perpendicular_distance(points[i], a, b)
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps:
            keep[idx] = True
            stack.append((i0, idx))
            stack.append((idx, i1))
    return [p for p, k in zip(points, keep) if k]


def _bbox_ring(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """縮退したリングの最終フォールバック。外接矩形の4隅を返す。

    小さな無人島（小笠原諸島に多数ある）は許容幅を超えるほど単純化すると
    3点未満に潰れることがある。**潰れた場合に元のリングへ戻すと、
    許容幅を上げたのに合計点数が増えるという逆転が起きる**
    （実測で踏んだ——単純化に失敗したリングの数が許容幅とともに増え、
    その分が毎回フル解像度のまま合計へ戻ってきていた）。
    外接矩形なら常に4点固定で、フォールバックが許容幅に依存しない。
    """
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    a, b, c, d = (min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))
    return [a, b, c, d, a]


def _simplify_ring(ring: list[list[float]], eps: float) -> list[list[float]]:
    """閉じたリング（先頭=末尾）を単純化する。

    ⚠️ **閉じたリングにそのまま開いた版の RDP はかけられない。**
    先頭と末尾を固定端点にすると、その2点だけを基準にした単純化になり、
    リングの反対側の輪郭が線分1本に潰れる。代わりにリングを2分し
    （0→中点、中点→0）、それぞれを独立した開いた折れ線として単純化してから
    繋ぎ直す。中点の選び方（インデックスの半分）は最遠点ではなく簡便法だが、
    表示用途の許容誤差としては十分——市境が中点の左右で著しく偏った形の
    自治体は無い。
    """
    pts = [tuple(p) for p in ring[:-1]]
    n = len(pts)
    if n <= 4:
        return ring
    mid = n // 2
    chain_a = pts[0:mid + 1]
    chain_b = pts[mid:] + [pts[0]]
    sa = _rdp(chain_a, eps)
    sb = _rdp(chain_b, eps)
    merged = sa[:-1] + sb[:-1] + [sa[0]]
    if len(merged) < 4:
        merged = _bbox_ring(pts)
    return [[round(x, COORD_DECIMALS), round(y, COORD_DECIMALS)] for x, y in merged]


def _extract_geojson(zip_bytes: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        with zf.open(ENTRY) as f:
            return json.load(f)


def main() -> None:
    jurisdictions = json.loads(JURISDICTIONS.read_text())["jurisdictions"]
    # N03_007 は全国地方公共団体コード**から検査数字（末尾1桁）を除いた5桁**
    # （JIS X 0402 の行政区域コード）。fudoki の正本キーは6桁なので、
    # 5桁プレフィクスで対応を取る。62件が5桁の時点で重複しないことは
    # 「地方公共団体コードは同じ団体を指す限り先頭5桁が一意」という設計に
    # 支えられている（実測でも 62 個の5桁プレフィクスが62個とも別だった）。
    code5_to_code6 = {code6[:5]: code6 for code6 in jurisdictions}
    if len(code5_to_code6) != len(jurisdictions):
        raise RuntimeError("5桁プレフィクスが重複する団体コードがある")

    got = http_get(URL)
    if got.sha256 != SHA256:
        raise RuntimeError(
            f"原文の SHA-256 が変わっている（{got.sha256}）。"
            "国土数値情報 N03 が更新された可能性がある。中身を確認したうえで "
            "URL と SHA256 を更新すること"
        )
    src = _extract_geojson(got.body)

    # 団体コードごとに Polygon をまとめる（飛び地・複数の島を1つの MultiPolygon へ）。
    grouped: dict[str, list] = {}
    for feature in src["features"]:
        code5 = feature["properties"]["N03_007"]
        code6 = code5_to_code6.get(code5)
        if code6 is None:
            continue  # 例: "13000"＝所属未定地（母集団62団体に無い）
        geom = feature["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        grouped.setdefault(code6, []).extend(polys)

    missing = set(jurisdictions) - set(grouped)
    if missing:
        raise RuntimeError(
            f"62団体のうち {len(missing)} 団体が N03 に見つからない: {sorted(missing)}。"
            "母集団が欠けたまま出力しない"
        )

    features = []
    for code6 in sorted(jurisdictions):
        simplified_polys = [
            [_simplify_ring(ring, SIMPLIFY_TOLERANCE_DEG) for ring in poly]
            for poly in grouped[code6]
        ]
        features.append({
            "type": "Feature",
            "properties": {
                "code": code6,
                "name": jurisdictions[code6]["name"],
                "island": code6 in ISLAND_CODES,
            },
            "geometry": {"type": "MultiPolygon", "coordinates": simplified_polys},
        })

    fc = {"type": "FeatureCollection", "features": features}
    encoded = json.dumps(fc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    OUT.write_bytes(encoded)
    print(f"ok  {len(features)} 団体  {len(encoded) / 1024:.1f} KB  -> {OUT}")


if __name__ == "__main__":
    main()
