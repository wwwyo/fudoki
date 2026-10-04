from pathlib import Path
import json
from functools import lru_cache
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'docs/brand/logo-options'
FONTS=ROOT/'pipeline/verify/view/node_modules/@fontsource-variable/noto-sans-jp/files'
INK='#2f5d43'; DARK='#8fbfa2'
@lru_cache
def glyphs(weight):
    found={}
    for p in sorted(FONTS.glob('*-wght-normal.woff2')):
        with TTFont(p) as f:
            cm=f.getBestCmap(); needed=[ch for ch in '風土記' if ch not in found and ord(ch) in cm]
            if not needed:continue
            gs=f.getGlyphSet(location={'wght':weight})
            for ch in needed:
                g=gs[cm[ord(ch)]]
                bp=BoundsPen(gs);g.draw(bp)
                pen=SVGPathPen(gs);g.draw(pen)
                found[ch]=(pen.getCommands(),bp.bounds,f['head'].unitsPerEm)
        if len(found)==3:break
    return found

def type_paths(weight=700,gaps=(3,4),compress=1,size=32):
    chars=glyphs(weight)
    top=max(b[3]/u for _,b,u in chars.values());bottom=min(b[1]/u for _,b,u in chars.values())
    baseline=20.5+(top+bottom)*size/2
    x=2;parts=[]
    for i,ch in enumerate('風土記'):
        d,b,u=chars[ch];s=size/u
        parts.append(f'<path transform="translate({x-b[0]*s*compress:.4f} {baseline:.4f}) scale({s*compress:.6f} {-s:.6f})" d="{d}"/>')
        x+=(b[2]-b[0])*s*compress
        if i<2:x+=gaps[i]
    return ''.join(parts),x+2

# 角印: 風を白抜きするため、外形と文字を同じ evenodd path にする。
d,b,u=glyphs(650)['風'];s=20/(b[3]-b[1]);tx=16-(b[0]+b[2])/2*s;ty=16+(b[1]+b[3])/2*s
# 元の文字 path を transform した座標で出力する。
for p in FONTS.glob('*-wght-normal.woff2'):
    with TTFont(p) as f:
        cm=f.getBestCmap()
        if ord('風') not in cm:continue
        gs=f.getGlyphSet(location={'wght':650});pen=SVGPathPen(gs)
        gs[cm[ord('風')]].draw(TransformPen(pen,(s,0,0,-s,tx,ty)))
        seal_d=pen.getCommands();break
seal=f'<path fill-rule="evenodd" d="M2 2H30V30H2Z {seal_d}"/>'
binding='<g fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="miter"><path d="M4 3H28V29H4Z M9 3V29 M4 7H9 M4 13H9 M4 19H9 M4 25H9"/></g>'

crest='<g transform="rotate(45 16 16)">'+''.join(f'<path fill-rule="evenodd" d="M{x} {y}h9v9h-9Z M{x+2.5} {y+2.5}h4v4h-4Z"/>' for x,y in [(6,6),(17,6),(6,17),(17,17)])+'</g>'
soil='<path d="M14 3H18V11H26V15H18V25H29V29H3V25H14V15H6V11H14Z"/>'
original=''.join(f'<rect x="{x}" y="{y}" width="4" height="{h}" rx="2"/>' for x,y,h in [(2,14,14),(8,6,22),(14,18,10),(20,2,26),(26,11,17)])+'<rect x="2" y="29" width="28" height="2" rx="1"/>'
custom=[]
for x,d in [(2,'M6 5H25V19Q25 27 29 28L30 24 M6 5V16Q6 23 3 28 M11 11L21 9 M10 15H21V22H10Z M16 11V27 M9 27L23 25 M22 24L24 28'),(38,'M16 4V28 M7 15H25 M3 28H29'),(74,'M6 3L10 5 M2 8H14 M4 13H12 M4 18H12 M4 23H12V29H4Z M18 5H28V16H18V26Q18 29 21 29H29V25')]:
    custom.append(f'<path transform="translate({x} 4)" d="{d}"/>')
custom_type='<g fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="square" stroke-linejoin="miter">'+''.join(custom)+'</g>'
OPTIONS=[
 dict(id='a-seal',letter='A',name='角印',tag='記録の確かさ',why='「風」を角印のように白抜き。詰まった太いゴシックと組み、記録を確かめる道具としての重さを出す。',trade='日本らしさが最も直接的。小さな印の中では「風」の細部が潰れやすい。',mark=seal,type=type_paths(800,(4,4),.96)),
 dict(id='b-binding',letter='B',name='和綴じ',tag='記録を集め、綴じる',why='綴じ糸と背を持つ冊子。文字は少し軽く、字間を広げる。地誌としての風土記と、資料を集める仕事を結ぶ。',trade='落ち着いて親しみやすい。出版・図書館にも見え、財政データの印象は控えめ。',mark=binding,type=type_paths(600,(6,6))),
 dict(id='c-crest',letter='C',name='四つの枠',tag='家紋のような対称形',why='四つの角形を菱形に配置する。家紋のように一つの形へまとめ、異なる団体の記録を同じ枠で扱うことに重ねる。',trade='小さくても形を保ち、和と現代的なデータの両方に寄せられる。名前そのものとの結びつきは弱い。',mark=crest,type=type_paths(700,(3.5,4.5))),
 dict(id='d-soil',letter='D',name='土地の字',tag='漢字をそのまま意匠に',why='「土」を太い直線で描く。風土記の三文字も直線を基調に描き直し、土地と記録を漢字の形で伝える。',trade='日本語の名前と一体になる。独自字形のため、既成のゴシックより看板のような強い癖がある。',mark=soil,type=(custom_type,108)),
 dict(id='e-original',letter='E',name='元の短冊・単色',tag='気に入っていた形を残す',why='五本の短冊と基準線の形・角丸・間隔は元のアイコンのまま。赤い基準線も緑に揃え、ゴシックの「風土記」と組む。',trade='元の印象を保ちながら色数を減らせる。基準線は細いままなので、小サイズでは線の見え方を確認する。',mark=original,type=type_paths(700,(3,4))),
]
def svg(content,w,h,color):
    return f'<!-- Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V5 -->\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.4f} {h}" role="img" aria-label="風土記"><title>風土記</title><g fill="{color}" color="{color}">{content}</g></svg>\n'
metadata=[]
for o in OPTIONS:
    target=OUT/o['id'];target.mkdir(parents=True,exist_ok=True)
    tp,tw=o['type']
    # 本体の ink bounds は standalone 左端 x=2。横組みでは文字先頭を x=49 に揃える。
    logo=f'<g transform="scale(1.25)">{o["mark"]}</g><g transform="translate(47 0)">{tp}</g>'
    for suffix,col in [('',INK),('-dark',DARK)]:
        for n,shape,w,h in [('mark',o['mark'],32,32),('wordmark',tp,tw,40),('logo',logo,tw+47,40)]:
            (target/f'{n}{suffix}.svg').write_text(svg(shape,w,h,col))
    metadata.append({k:v for k,v in o.items() if k not in ('mark','type')})
(OUT/'options.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
print(f'{len(OPTIONS)}組 × マーク/文字/横組み × 明暗 = {len(OPTIONS)*6} SVG')
