"""書体の字面の高さを揃え、丸みを比べるロゴ候補をSVGとして生成する。"""
from pathlib import Path
import json,hashlib,shutil,urllib.request,base64
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen
from geometry import geometries

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'docs/brand/logo-type-options'
CONFIG=json.loads((HERE/'config.json').read_text())
NAME='風土記'
CHOICES=[('a','Noto Sans JP',None),('b','BIZ UDPゴシック','biz'),('c','M PLUS 1','mplus'),('d','Zen角ゴシック New','zen')]
SOURCES=json.loads((HERE/'type-fonts.json').read_text())
CACHE=ROOT/'.cache/logo-fonts'
CACHE.mkdir(parents=True,exist_ok=True)
for source in SOURCES:
    font=CACHE/f'{source["id"]}.ttf'
    license_file=CACHE/f'{source["id"]}-OFL.txt'
    if not font.exists():font.write_bytes(urllib.request.urlopen(source['url'],timeout=45).read())
    if hashlib.sha256(font.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('フォントのハッシュが一致しません')
    if not license_file.exists():license_file.write_bytes(urllib.request.urlopen(source['url'].rsplit('/',1)[0]+'/OFL.txt',timeout=45).read())
FONT_DIR=ROOT/'pipeline/verify/view/node_modules/@fontsource-variable/noto-sans-jp/files'


def glyphs(paths):
    """静的／可変フォントの700ウェイトから三文字の輪郭と実寸を取得する。"""
    found={}
    for path in paths:
        with TTFont(path) as font:
            cmap=font.getBestCmap()
            gs=font.getGlyphSet(location={'wght':700} if 'fvar' in font else None)
            for ch in NAME:
                if ch in found or ord(ch) not in cmap:continue
                pen,bounds=SVGPathPen(gs),BoundsPen(gs)
                gs[cmap[ord(ch)]].draw(pen);gs[cmap[ord(ch)]].draw(bounds)
                found[ch]={'d':pen.getCommands(),'bounds':list(bounds.bounds),'upm':font['head'].unitsPerEm}
        if len(found)==3:break
    if len(found)!=3:raise ValueError('三文字の字形が足りません')
    return [found[ch] for ch in NAME]


noto=glyphs(sorted(FONT_DIR.glob('*-wght-normal.woff2')))
def extent(gs):return max(g['bounds'][3]/g['upm'] for g in gs)-min(g['bounds'][1]/g['upm'] for g in gs)
TARGET_HEIGHT=extent(noto)*CONFIG['textSize']
RECTS=geometries()[CONFIG['markProportion']]


def rule_color(ink,dark):
    rgb=[int(ink[i:i+2],16) for i in (1,3,5)];contrast=CONFIG['ruleContrast']
    return '#'+''.join(f'{int((v+(255-v)*contrast if dark else v*(1-contrast))+.5):02x}' for v in rgb)


def mark(ink,dark,radius):
    """短めのマークに共通色と指定の下線角丸を適用する。"""
    out=[]
    for i,(x,y,w,h,r) in enumerate(RECTS):
        extra=f' fill="{rule_color(ink,dark)}"' if i==5 else ''
        out.append(f'<rect x="{x:.8f}" y="{y:.8f}" width="{w:.8f}" height="{h:.8f}" rx="{(radius if i==5 else r):.8f}"{extra}/>')
    return ''.join(out)


def svg(gs,size,kind,dark,radius):
    """各書体を同じ字面中心・輪郭間の空きへ配置する。"""
    ink=CONFIG['inkDark'] if dark else CONFIG['ink']
    cy=CONFIG['canvasHeight']/2+.5+CONFIG['textOffsetY']
    top=max(g['bounds'][3]/g['upm'] for g in gs);bottom=min(g['bounds'][1]/g['upm'] for g in gs)
    base=cy+(top+bottom)*size/2
    x=CONFIG['markOffsetX']+(RECTS[-1][0]+RECTS[-1][2])*CONFIG['markScale']+CONFIG['gap'] if kind=='logo' else 2
    content=[]
    if kind=='mark':
        width=height=32;content.append(mark(ink,dark,radius))
    else:
        height=CONFIG['canvasHeight']
        if kind=='logo':content.append(f'<g transform="translate({CONFIG["markOffsetX"]} {CONFIG["markOffsetY"]}) scale({CONFIG["markScale"]})">{mark(ink,dark,radius)}</g>')
        for i,g in enumerate(gs):
            scale=size/g['upm'];content.append(f'<path transform="translate({x-g["bounds"][0]*scale:.6f} {base:.6f}) scale({scale:.9f} {-scale:.9f})" d="{g["d"]}"/>')
            x+=(g['bounds'][2]-g['bounds'][0])*scale
            if i<2:x+=CONFIG['pairGaps'][i]
        width=x+2
    return f'<!-- Hallmark · pre-emit critique: P4 H4 E5 S5 R5 V4 -->\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.6f} {height}" role="img" aria-label="風土記"><title>風土記</title><g fill="{ink}">{"".join(content)}</g></svg>\n'


OUT.mkdir(exist_ok=True)
manifest=[]
for ident,label,key in CHOICES:
    d=OUT/ident;d.mkdir(exist_ok=True)
    gs=noto if key is None else glyphs([ROOT/f'.cache/logo-fonts/{key}.ttf'])
    size=TARGET_HEIGHT/extent(gs)
    meta={'id':ident,'font':label,'weight':700,'textSize':size,'visibleHeight':TARGET_HEIGHT,'ruleRadius':.6,'textOffsetY':CONFIG['textOffsetY'],'gap':CONFIG['gap'],'pairGaps':CONFIG['pairGaps'],'ink':CONFIG['ink'],'inkDark':CONFIG['inkDark'],'accent':CONFIG['accent']}
    if key:
        source=next(s for s in SOURCES if s['id']==key)
        assert hashlib.sha256((ROOT/f'.cache/logo-fonts/{key}.ttf').read_bytes()).hexdigest()==source['sha256']
        meta['source']=source
        shutil.copyfile(ROOT/f'.cache/logo-fonts/{key}-OFL.txt',d/'OFL.txt')
    else:
        meta['source']={'source':'https://github.com/notofonts/noto-cjk','package':'@fontsource-variable/noto-sans-jp'}
        shutil.copyfile(FONT_DIR.parent/'LICENSE',d/'OFL.txt')
    for dark in (False,True):
        suffix='-dark' if dark else ''
        for kind in ('mark','wordmark','logo'):(d/f'{kind}{suffix}.svg').write_text(svg(gs,size,kind,dark,.6))
    for radius in (.25,.6,1.):
        for dark in (False,True):
            suffix='-dark' if dark else ''
            for kind in ('mark','logo'):(d/f'{kind}-r{radius:g}{suffix}.svg').write_text(svg(gs,size,kind,dark,radius))
    (d/'config.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n');manifest.append(meta)
(OUT/'variants.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print('4書体 × 下線角丸0.25/0.6/1.0: 同じ字面高さでSVGを生成')

preview=[]
for meta in manifest:
    d=OUT/meta['id']
    assets={p.stem:'data:image/svg+xml;base64,'+base64.b64encode(p.read_bytes()).decode() for p in d.glob('*.svg')}
    products={theme:'data:image/jpeg;base64,'+base64.b64encode((d/f'product-{theme}.jpg').read_bytes()).decode() if (d/f'product-{theme}.jpg').exists() else '' for theme in ('light','dark')}
    preview.append({**meta,'assets':assets,'products':products})
html=(HERE/'type-options.html').read_text().replace('__DATA__',json.dumps(preview,ensure_ascii=False))
(ROOT/'docs/brand/logo-type-options.html').write_text(html)
print('文字と下線を別々に比較するページを生成')
