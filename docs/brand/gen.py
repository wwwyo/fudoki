"""ブランドカラー探索ボードのアートボードを書き出す。"""
import io, json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 画面側の意味色（DESIGN.md より）。ブランド色と衝突しないかを見るために並べる
SEMANTIC = [
    ("#577ea5", "判断なし"), ("#a16c48", "判断あり"), ("#aa5910", "境界"),
    ("#3d865a", "割当済み"), ("#a97416", "分類不能"), ("#79818d", "対象外"),
]

DIRECTIONS = [
    dict(file="Main", label="藍", sub="現状", ink="#1f3a5f", paper="#f7f4ec", accent="#8a5a3c",
         why="いま使っている色。寒色で静かで、検査画面の無彩色基調から浮かない。",
         cost="画面の「判断なし」#577ea5 と同系。ブランド色と意味色が混ざり、藍が何かを意味していると読まれる。"),
    dict(file="Sumi", label="墨と朱", sub="すみとしゅ", ink="#23201d", paper="#f5f1e8", accent="#b7411e",
         why="記録は墨で書かれた。ほぼ無彩色なので「彩度ゼロが既定、色が付くものには意味がある」という画面の規範と衝突しない。朱は官印の色で、1点だけ効かせる。",
         cost="地味。ブランドとして記憶に残りにくく、他の行政系サイトと見分けが付きにくい。"),
    dict(file="Aoni", label="青丹", sub="あをに", ink="#2f5d43", paper="#f4f1e6", accent="#c1553a",
         why="「あをによし」は奈良の都にかかる枕詞で、青（岩緑青）と丹（赤土）という顔料そのものを指す。713年の官命という出自に最も近い。",
         cost="緑は「割当済み」#3d865a と近い。COFOG が付いた状態の色と混ざる。"),
    dict(file="Bengara", label="弁柄", sub="べんがら", ink="#6b2d1e", paper="#f6f0e4", accent="#2b3a55",
         why="鉄丹。神社の柱と町家の格子に塗られてきた顔料で、土地に塗られたものという意味で「風土」に直結する。",
         cost="赤茶は destructive（検査の失敗）と距離が近く、画面上で警告色として読まれる余地がある。"),
    dict(file="Kachi", label="勝色", sub="かちいろ", ink="#1c2a44", paper="#f2efe6", accent="#c08a2e",
         why="藍を最も濃く染めた段階の名。現状の藍を捨てずに古風へ寄せる保守案で、ロゴ以外の資産を作り直さずに済む。",
         cost="現状と同じ衝突をそのまま引き継ぐ。寒色が意味色の寒色と同系である問題は解けていない。"),
]

BARS = [(2, 14, 14), (8, 6, 22), (14, 18, 10), (20, 2, 26), (26, 11, 17)]


def mark(size: int) -> str:
    bars = "".join(
        f'<rect x="{x}" y="{y}" width="4" height="{h}" rx="2"></rect>' for x, y, h in BARS
    )
    bars += '<rect x="2" y="29" width="28" height="2" rx="1"></rect>'
    return (
        f'<svg viewBox="0 0 32 32" width="{size}" height="{size}" '
        f'style="flex: none; fill: {{{{ink}}}}"><g>{bars}</g></svg>'
    )


def swatch(color: str, name: str, note: str) -> str:
    return (
        '<div style="display: flex; flex-direction: column; gap: 6px">'
        f'<div style="width: 96px; height: 56px; border-radius: 4px; background: {color}"></div>'
        f'<div style="font-size: 12px; font-weight: 500; color: {{{{ink}}}}">{name}</div>'
        f'<div style="font-size: 11px; color: #8a857c; font-family: Geist, system-ui, sans-serif">{note}</div>'
        "</div>"
    )


def semantic_row() -> str:
    items = "".join(
        '<div style="display: flex; align-items: center; gap: 5px">'
        f'<i style="width: 10px; height: 10px; border-radius: 2px; background: {c}"></i>'
        f'<span style="font-size: 11px; color: #57534e">{n}</span>'
        "</div>"
        for c, n in SEMANTIC
    )
    return f'<div style="display: flex; flex-wrap: wrap; gap: 14px">{items}</div>'


def artboard(d: dict) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Shippori+Mincho+B1:wght@700&amp;family=Noto+Sans+JP:wght@400;500;600&amp;family=Geist:wght@400;500;600&amp;display=swap">
  <style>
    body {{ margin: 0; font-family: 'Noto Sans JP', system-ui, sans-serif; }}
    a {{ color: {d['accent']}; }}
    a:hover {{ color: {d['ink']}; }}
  </style>
</helmet>
<div style="width: 720px; height: 600px; box-sizing: border-box; padding: 40px; background: {{{{paper}}}}; display: flex; flex-direction: column; gap: 26px">

  <div style="display: flex; align-items: baseline; gap: 10px">
    <span style="font-family: 'Shippori Mincho B1', serif; font-weight: 700; font-size: 22px; color: {{{{ink}}}}">{d['label']}</span>
    <span style="font-size: 12px; color: #8a857c">{d['sub']}</span>
    <span style="margin-left: auto; font-family: Geist, ui-monospace, monospace; font-size: 12px; color: #8a857c">{{{{ink}}}}</span>
  </div>

  <div style="display: flex; align-items: center; gap: 22px">
    {mark(76)}
    <span style="font-family: 'Shippori Mincho B1', serif; font-weight: 700; font-size: 68px; line-height: 1; letter-spacing: 0.04em; color: {{{{ink}}}}; transform: translateY(4px)">風土記</span>
  </div>

  <div style="display: flex; gap: 16px">
    {swatch('{{ink}}', '主色', 'ロゴ・見出し')}
    {swatch('{{paper}}', '地色', 'og・ロゴの背景')}
    {swatch('{{accent}}', '差し色', 'リンク・強調')}
  </div>

  <div style="border-top: 1px solid #ddd6c9; padding-top: 18px; display: flex; flex-direction: column; gap: 12px">
    <div style="font-size: 11px; font-weight: 500; color: #8a857c">画面の意味色と並べたとき</div>
    {semantic_row()}
  </div>

  <div style="display: flex; flex-direction: column; gap: 7px; margin-top: auto">
    <div style="font-size: 13px; line-height: 1.7; color: {{{{ink}}}}">{d['why']}</div>
    <div style="font-size: 12px; line-height: 1.7; color: #8a6a5a">引き換えに: {d['cost']}</div>
  </div>

</div>
</x-dc>
<script data-dc-script data-props='{{"ink": {{"editor": "color", "default": "{d['ink']}"}}, "paper": {{"editor": "color", "default": "{d['paper']}"}}, "accent": {{"editor": "color", "default": "{d['accent']}"}}, "$preview": {{"width": 720, "height": 600}}}}'>
class Component extends DCLogic {{
  renderVals() {{
    return {{
      ink: this.props.ink ?? '{d['ink']}',
      paper: this.props.paper ?? '{d['paper']}',
      accent: this.props.accent ?? '{d['accent']}',
    }};
  }}
}}
</script>
</body>
</html>
"""


for d in DIRECTIONS:
    (HERE / f"{d['file']}.dc.html").write_text(artboard(d), encoding="utf-8")

W, H, GAP = 720, 600, 80
pos = [(0, 0), (W + GAP, 0), (2 * (W + GAP), 0), (0, H + GAP), (W + GAP, H + GAP)]
canvas = {
    "artboards": [
        {"file": f"{d['file']}.dc.html", "x": x, "y": y, "w": W, "h": H, "title": d["label"]}
        for d, (x, y) in zip(DIRECTIONS, pos)
    ],
    "annotations": [
        {
            "id": "brief",
            "x": 0,
            "y": -220,
            "w": 720,
            "text": "ロゴの藍 #1f3a5f を置き換える候補。\n"
            "古風な日本の顔料から採り、それぞれ「なぜ」と「引き換えに何を失うか」を添えた。\n\n"
            "見るべきは下段の帯。画面の意味色（判断の有無・COFOG の状態）と\n"
            "ブランド色が同系だと、色が意味を持つという規範が崩れる。",
        },
        {
            "id": "note-semantic",
            "x": 2 * (W + GAP),
            "y": H + GAP,
            "w": 560,
            "text": "画面側の意味色は動かさない前提。\n"
            "「判断の有無を寒色/暖色で対にする」は情報設計なので、\n"
            "ブランドの都合で動かすと画面の読み方が変わる。",
        },
    ],
    "launch": {"view": "canvas"},
}
(HERE / "canvas.json").write_text(json.dumps(canvas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("artboards:", ", ".join(d["file"] for d in DIRECTIONS))
