"""風土記のロゴ一式を組む。`bun run build:brand`

commit した生成物には生成手段を残す、という repo の決めごとに従ってここに置く。
生成物は3つ。

| 出力 | 用途 |
|---|---|
| `apps/web/public/favicon.svg` | マーク単体（タブ・16〜32px） |
| `apps/web/public/logo.svg` | マーク + 「風土記」の横組み |
| `apps/web/public/og.png` | 1200x630。OGP のカード |

**文字は `<text>` ではなく outline を path に焼く。** 閲覧側にフォントが無ければ
別の字形で出る、という状態はロゴとして成立しない。焼いた時点で SVG は
フォントに依存しなくなるので、`logo.svg` 単体で配布できる。

字母は **Shippori Mincho B1 Bold（SIL OFL 1.1）**。活版印刷の再現を狙って設計された
明朝で、「同じ様式で刷られた記録」という主題がマークの短冊（木簡）と直結する。
本文の Noto Sans JP とは別物でよい — 本文で長所になる無個性は、表示用の文字では短所になる。

字母は `apps/web` の devDependency（`@fontsource/shippori-mincho-b1`）から読む。
⚠️ outline の再配布が許されるライセンスであることが選定の前提。
システムフォント（ヒラギノ・游明朝・Toppan）は Apple デバイス上での使用に限られるので、
公開リポジトリに焼き込めない。

⚠️ **このスクリプトは手元のフォントと ImageMagick に依存する。**
生成物は commit してあるので、動かせなくてもロゴは使える（意匠を変えるときだけ要る）。

    FONT=/path/to/SourceHanSansJP-Bold.otf bun run build:brand
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent / "public"

# .woff2 ではなく .woff を読む。woff は zlib なので fontTools が単体で開ける
# （woff2 は brotli が要る）。字形は同じ。
_DEFAULT_FONT = (
    HERE.parent
    / "node_modules/@fontsource/shippori-mincho-b1/files"
    / "shippori-mincho-b1-japanese-700-normal.woff"
)
FONT = Path(os.environ.get("FONT", _DEFAULT_FONT))

# 青丹（あをに）。「あをによし」は奈良の都にかかる枕詞で、青（岩緑青）と丹（赤土）という
# 顔料の対そのものを指す。713年の官命という出自に最も近いので、単色ではなく**対**で持つ。
# 対はマークの基準線に出る — 短冊が並ぶ「地面」だけが丹になる。
INK, RULE, PAPER = "#2f5d43", "#c1553a", "#f4f1e6"
INK_DARK, RULE_DARK = "#8fbfa2", "#e08267"
# 「風土記」の文字は**本文色**で組む。マークが色を持ち、文字は持たない。
# 両方に色を付けると、どちらがブランドの主張なのかが割れる。
# 値は画面の `--foreground`（`oklch(0.145 0 0)` / `oklch(0.985 0 0)`）と同じ。
TEXT, TEXT_DARK = "#0a0a0a", "#fafafa"

# マークの意匠。同じ基準線に並ぶ、長さの違う短冊（木簡 / 棒グラフ）。32 単位系。
BARS = [(2, 14, 14), (8, 6, 22), (14, 18, 10), (20, 2, 26), (26, 11, 17)]
BASELINE = (2, 29, 28, 2)

if not FONT.exists():
    sys.exit(f"フォントが無い: {FONT}\nFONT=... で場所を渡してください")

font = TTFont(FONT)
gs = font.getGlyphSet()
cmap = font.getBestCmap()
UPM = font["head"].unitsPerEm


def _glyphs(text: str) -> list[dict]:
    out = []
    for ch in text:
        gn = cmap[ord(ch)]
        pen, bp = SVGPathPen(gs), BoundsPen(gs)
        gs[gn].draw(pen)
        gs[gn].draw(bp)
        out.append({"d": pen.getCommands(), "w": gs[gn].width, "b": bp.bounds})
    return out


def measure(text: str, size: float, tracking: float = 0.0) -> float:
    """組んだときの幅。中央寄せの座標を出すのに要る。"""
    gl = _glyphs(text)
    return sum(g["w"] * size / UPM + tracking * size for g in gl) - tracking * size


def draw(text: str, size: float, x: float, cy: float, tracking: float = 0.0) -> str:
    """text を outline で描く。cy は**視覚的な中心**（em box ではなく実際の字面の中心）。"""
    gl = _glyphs(text)
    s = size / UPM
    tops = [g["b"][3] for g in gl if g["b"]]
    bottoms = [g["b"][1] for g in gl if g["b"]]
    baseline = cy + (min(bottoms) + max(tops)) / 2 * s
    parts, cur = [], x
    for g in gl:
        if g["d"]:
            parts.append(
                f'<path transform="translate({cur:.2f} {baseline:.2f}) '
                f'scale({s:.5f} -{s:.5f})" d="{g["d"]}"/>'
            )
        cur += g["w"] * s + tracking * size
    return "".join(parts)


def mark(
    scale: float, dx: float = 0, dy: float = 0,
    themed: bool = False, ink: str = INK, rule: str = RULE,
) -> str:
    """短冊のマーク。基準線だけ丹になる。

    themed=True は `.ink` / `.rule` クラスで CSS に委ねる（ファビコン専用）。
    False は渡された色を直接置く。
    """
    bar_a = ' class="ink"' if themed else f' fill="{ink}"'
    rule_a = ' class="rule"' if themed else f' fill="{rule}"'
    bars = "".join(
        f'<rect{bar_a} x="{x}" y="{y}" width="4" height="{h}" rx="2"/>' for x, y, h in BARS
    )
    bx, by, bw, bh = BASELINE
    bars += f'<rect{rule_a} x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="1"/>'
    return f'<g transform="translate({dx} {dy}) scale({scale})">{bars}</g>'


THEME = f"""
  <style>
    .ink {{ fill: {INK}; }}
    .rule {{ fill: {RULE}; }}
    @media (prefers-color-scheme: dark) {{
      .ink {{ fill: {INK_DARK}; }}
      .rule {{ fill: {RULE_DARK}; }}
    }}
  </style>"""

# ---- favicon.svg：マーク単体 ----
(PUBLIC / "favicon.svg").write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" role="img" aria-label="風土記">{THEME}\n'
    f'  {mark(1, 0, 0, themed=True)}\n</svg>\n'
)

# ---- mark.svg / mark-dark.svg：マーク単体 ----
# ファビコンと同じ意匠だが、**テーマの追い方が違うので別ファイルにする**。
# ファビコンはブラウザのタブが OS 設定に従うのでメディアクエリでよく、
# こちらは画面のテーマ（クラス）に合わせるので 2 枚に分けてクラスで出し分ける。
for name, ink, rule in [("mark.svg", INK, RULE), ("mark-dark.svg", INK_DARK, RULE_DARK)]:
    (PUBLIC / name).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" role="img" aria-label="風土記">\n'
        f"  {mark(1, 0, 0, ink=ink, rule=rule)}\n</svg>\n"
    )

# ---- logo.svg / logo-dark.svg：マーク + 「風土記」の横組み ----
# ⚠️ 字面の中心（draw が計算する ink bbox の中心）に合わせると、重心が上に見える。
# マークは下端の基準線が「地面」として読まれるぶん視覚的な重さが下にあるのに対し、
# 明朝の「風土記」は横画が上半分に密集していて、幾何的な中心より上に重さが寄るため。
# 光学的に下へ寄せる。TEXT_DY はこの補正で、字面の高さに対する比で持つ。
#
# ⚠️ **ロゴはテーマを媒体に委ねず、2枚に分ける。**
# 画面のテーマはクラス（`.dark`）で切り替わるが、`<img>` の中の
# `prefers-color-scheme` は OS 設定しか見ない。1枚にすると、OS がライトのまま
# 画面をダークにしたときにロゴだけ取り残される。ファビコンは逆に
# ブラウザのタブが OS 設定に従うので、あちらはメディアクエリのままでよい。
H, GAP, TEXT_SIZE, TEXT_DY = 40, 9, 30, 0.055
tx = 32 * (H / 32) + GAP
W = tx + measure("風土記", TEXT_SIZE, 0.03)
for name, ink, rule, text in [
    ("logo.svg", INK, RULE, TEXT),
    ("logo-dark.svg", INK_DARK, RULE_DARK, TEXT_DARK),
]:
    (PUBLIC / name).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H}" role="img" aria-label="風土記">\n'
        f"  <title>風土記</title>\n"
        f"  {mark(H / 32, 0, 0, ink=ink, rule=rule)}\n"
        f'  <g fill="{text}">{draw("風土記", TEXT_SIZE, tx, H / 2 + TEXT_SIZE * TEXT_DY, 0.03)}</g>\n</svg>\n'
    )

# ---- og.png：1200x630。SVG を経由して焼く ----
OW, OH = 1200, 630
OG_MARK, OG_TEXT, OG_GAP = 96, 88, 26
block = OG_MARK + OG_GAP + measure("風土記", OG_TEXT, 0.04)
ox, cy = (OW - block) / 2, OH / 2
og = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{OW}" height="{OH}" viewBox="0 0 {OW} {OH}">\n'
    f'  <rect width="{OW}" height="{OH}" fill="{PAPER}"/>\n'
    f'  {mark(OG_MARK / 32, ox, cy - OG_MARK / 2)}\n'
    f'  <g fill="{TEXT}">{draw("風土記", OG_TEXT, ox + OG_MARK + OG_GAP, cy + OG_TEXT * TEXT_DY, 0.04)}</g>\n'
    "</svg>\n"
)
(HERE / "og.svg").write_text(og)

# ImageMagick は mise.toml に入れていない。ロゴを描き直すときにしか要らないものを
# 全員の `mise install` と CI に背負わせない（生成物は commit してある）。
IMAGEMAGICK = "imagemagick@7.1.2_27"
args = ["-density", "384", str(HERE / "og.svg"), "-resize", f"{OW}x{OH}",
        "-strip", f"PNG24:{PUBLIC / 'og.png'}"]
if shutil.which("mise"):
    cmd = ["mise", "x", IMAGEMAGICK, "--", "magick", *args]
elif shutil.which("magick"):
    cmd = ["magick", *args]
else:
    sys.exit(f"og.svg までは書いた。PNG にするには {IMAGEMAGICK} が要る")
subprocess.run(cmd, check=True)
print(f"favicon.svg / logo.svg ({W:.0f}x{H}) / og.png ({OW}x{OH})")
