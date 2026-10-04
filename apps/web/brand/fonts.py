"""採用書体の固定バージョンからロゴ用の輪郭を取得する。"""

import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NAME = "風土記"


def font_paths(key: str) -> list[Path]:
    """固定ハッシュを検証して書体を用意する。"""
    if key == "noto":
        directory = ROOT / "pipeline/verify/view/node_modules/@fontsource-variable/noto-sans-jp/files"
        return sorted(directory.glob("*-wght-normal.woff2"))
    source = next(s for s in json.loads((HERE / "type-fonts.json").read_text()) if s["id"] == key)
    cache = ROOT / ".cache/logo-fonts"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{key}.ttf"
    if not path.exists():
        with urllib.request.urlopen(source["url"], timeout=45) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError(f"フォントのハッシュが一致しません: {key}")
        with tempfile.TemporaryDirectory(dir=cache, prefix=f".{key}-") as directory:
            temporary = Path(directory) / path.name
            temporary.write_bytes(data)
            temporary.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError(f"フォントのハッシュが一致しません: {key}")
    return [path]


def load_glyphs(key: str, weight: int) -> dict[str, dict]:
    """各文字の輪郭・字面・emサイズを指定ウェイトで取り出す。"""
    found = {}
    for path in font_paths(key):
        with TTFont(path) as font:
            cmap = font.getBestCmap()
            if "fvar" not in font and font["OS/2"].usWeightClass != weight:
                raise ValueError(f"静的フォントに指定ウェイトがありません: {key} / {weight}")
            gs = font.getGlyphSet(location={"wght": weight} if "fvar" in font else None)
            for ch in NAME:
                if ch in found or ord(ch) not in cmap:
                    continue
                pen, bounds = SVGPathPen(gs), BoundsPen(gs)
                gs[cmap[ord(ch)]].draw(pen)
                gs[cmap[ord(ch)]].draw(bounds)
                found[ch] = {"d": pen.getCommands(), "bounds": bounds.bounds, "upm": font["head"].unitsPerEm}
        if len(found) == len(NAME):
            break
    if len(found) != len(NAME):
        raise ValueError(f"字形が見つかりません: {set(NAME) - found.keys()}")
    return found
