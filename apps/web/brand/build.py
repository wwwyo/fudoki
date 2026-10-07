"""設定値と採用書体の輪郭から風土記のロゴ一式を生成する。

`bun run --cwd apps/web build:brand` で各 public ディレクトリと OG 画像を同期する。
字母は固定バージョンの Zen角ゴシック New（OFL-1.1）を使い、
SVG はパス化する。フォントの読み込みや端末の代替書体に依存させない。
"""

import shutil
import subprocess
import json
import sys
from functools import lru_cache
from pathlib import Path

from fonts import load_glyphs
from geometry import geometries

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = HERE.parent / "public"
CONFIG = json.loads((HERE / "config.json").read_text())
INK, INK_DARK, PAPER = (CONFIG[k] for k in ("ink", "inkDark", "paper"))
NAME, WEIGHT = "風土記", CONFIG["weight"]
RECTS = geometries()[CONFIG["markProportion"]]
MARK_RIGHT = RECTS[-1][0] + RECTS[-1][2]
H, TEXT_SIZE = CONFIG["canvasHeight"], CONFIG["textSize"]
TEXT_CENTER_Y = H / 2 + 0.5 + CONFIG["textOffsetY"]
MARK_SCALE = CONFIG["markScale"]
MARK_X, MARK_Y = CONFIG["markOffsetX"], CONFIG["markOffsetY"]
TEXT_X = MARK_X + MARK_RIGHT * MARK_SCALE + CONFIG["gap"]
# 全角の advance は「土」の左右に空きすぎるため、見える字面間で指定する。
PAIR_GAPS = CONFIG["pairGaps"]


@lru_cache
def glyphs() -> tuple[dict, ...]:
    """採用書体から必要な三文字の輪郭と字面を取り出す。"""
    found = load_glyphs(CONFIG["font"], WEIGHT)
    return tuple(found[ch] for ch in NAME)


def text_width(size: float) -> float:
    """輪郭の幅とペアごとの字間を共通のサイズへ換算する。"""
    return sum((g["bounds"][2] - g["bounds"][0]) * size / g["upm"] for g in glyphs()) + sum(PAIR_GAPS)


def wordmark(size: float, x: float, cy: float) -> str:
    """共通ベースラインで字面を揃え、ペアごとの見える空きを適用する。"""
    gl = glyphs()
    top = max(g["bounds"][3] / g["upm"] for g in gl)
    bottom = min(g["bounds"][1] / g["upm"] for g in gl)
    baseline = cy + (top + bottom) * size / 2
    parts = []
    for i, g in enumerate(gl):
        scale = size / g["upm"]
        parts.append(
            f'<path transform="translate({x - g["bounds"][0] * scale:.4f} {baseline:.4f}) '
            f'scale({scale:.5f} -{scale:.5f})" d="{g["d"]}"/>'
        )
        x += (g["bounds"][2] - g["bounds"][0]) * scale
        if i < len(PAIR_GAPS):
            x += PAIR_GAPS[i]
    return "".join(parts)


def rule_color(ink: str, dark: bool = False) -> str:
    """細い基準線だけ背景との明度差を増やし、色相は保つ。"""
    amount = CONFIG["ruleContrast"]
    rgb = [int(ink[i:i + 2], 16) for i in (1, 3, 5)]
    adjusted = [int((v + (255 - v) * amount if dark else v * (1 - amount)) + 0.5) for v in rgb]
    return "#" + "".join(f"{v:02x}" for v in adjusted)


def mark(scale: float = 1, x: float = 0, y: float = 0, ink: str = INK, dark: bool = False, themed: bool = False) -> str:
    """32 単位の短冊を任意の位置・倍率で配置する。"""
    strips = "".join(
        f'<rect x="{sx:.8f}" y="{sy:.8f}" width="{w:.8f}" height="{h:.8f}" rx="{radius:.8f}"/>'
        for sx, sy, w, h, radius in RECTS[:-1]
    )
    rule_ink = "var(--logo-rule-ink)" if themed else rule_color(ink, dark)
    # var() は fill= のような presentation attribute では解決されず、style の CSS プロパティ経由でだけ効く
    rule_fill = f'style="fill:{rule_ink}"' if themed else f'fill="{rule_ink}"'
    sx, sy, w, h, _ = RECTS[-1]
    radius = CONFIG["ruleRadius"]
    baseline = f'<rect x="{sx:.8f}" y="{sy:.8f}" width="{w:.8f}" height="{h:.8f}" rx="{radius:.8f}" {rule_fill}/>'
    return f'<g transform="translate({x} {y}) scale({scale})">{strips}{baseline}</g>'


def svg(width: float, height: float, content: str, ink: str, themed: bool = False) -> str:
    """透過背景の SVG に同じ色相の塗りとアクセシブルな名前を付ける。"""
    theme = (
        f'<style>svg {{ color: {INK}; --logo-rule-ink: {rule_color(INK)}; }} '
        f'@media (prefers-color-scheme: dark) {{ svg {{ color: {INK_DARK}; --logo-rule-ink: {rule_color(INK_DARK, True)}; }} }}</style>'
        if themed else ""
    )
    fill = 'fill="currentColor"' if themed else f'fill="{ink}"'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.4f} {height:g}" '
        f'role="img" aria-label="{NAME}">\n  <title>{NAME}</title>{theme}\n'
        f'  <g {fill}>{content}</g>\n</svg>\n'
    )


PUBLIC.mkdir(parents=True, exist_ok=True)
for suffix, ink in (("", INK), ("-dark", INK_DARK)):
    (PUBLIC / f"mark{suffix}.svg").write_text(svg(32, 32, mark(ink=ink, dark=bool(suffix)), ink))
    (PUBLIC / f"wordmark{suffix}.svg").write_text(
        svg(text_width(TEXT_SIZE) + 4, H, wordmark(TEXT_SIZE, 2, TEXT_CENTER_Y), ink)
    )
    tx = TEXT_X
    (PUBLIC / f"logo{suffix}.svg").write_text(
        svg(tx + text_width(TEXT_SIZE) + 2, H, mark(MARK_SCALE, MARK_X, MARK_Y, ink, bool(suffix)) + wordmark(TEXT_SIZE, tx, TEXT_CENTER_Y), ink)
    )
(PUBLIC / "favicon.svg").write_text(svg(32, 32, mark(themed=True), INK, themed=True))

for target in (ROOT / "pipeline/verify/view/public", ROOT / "apps/docs/public"):
    for name in ("mark.svg", "mark-dark.svg", "wordmark.svg", "wordmark-dark.svg", "logo.svg", "logo-dark.svg", "favicon.svg"):
        shutil.copyfile(PUBLIC / name, target / name)

# OS の設定を追うファビコンと、画面の .dark で選ぶ SVG は分ける。
# 画像内部の prefers-color-scheme は画面側のクラスを参照できない。
OW, OH = 1200, 630
og_height = 112
og_width = TEXT_X + text_width(TEXT_SIZE) + 2
scale = og_height / H
og = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{OW}" height="{OH}" viewBox="0 0 {OW} {OH}">\n'
    f'<rect width="{OW}" height="{OH}" fill="{PAPER}"/>\n'
    f'<g fill="{INK}" transform="translate({(OW - og_width * scale) / 2:.4f} {(OH - og_height) / 2:g}) scale({scale:g})">'
    f'{mark(MARK_SCALE, MARK_X, MARK_Y)}{wordmark(TEXT_SIZE, TEXT_X, TEXT_CENTER_Y)}</g>\n</svg>\n'
)
(HERE / "og.svg").write_text(og)
# 生成済み PNG を使う利用者や CI に、画像変換ツールを背負わせない。
subprocess.run([
    "mise", "x", "imagemagick@7.1.2_27", "--", "magick", "-density", "192",
    str(HERE / "og.svg"), "-resize", f"{OW}x{OH}", "-strip", f"PNG24:{PUBLIC / 'og.png'}",
], check=True)
subprocess.run([sys.executable, str(HERE / "build-editor.py")], check=True)
print("mark / wordmark / logo / favicon を各 public に同期、og.png を生成")
