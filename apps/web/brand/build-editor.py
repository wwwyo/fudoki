"""既存フォントの輪郭と採用設定を、単体で使えるロゴ調整画面へ埋め込む。"""
import json
from pathlib import Path
from geometry import geometries
from fonts import load_glyphs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
config = json.loads((HERE / 'config.json').read_text())
weights = range(500, 901, 50) if config['font'] == 'noto' else [config['weight']]
glyphs = {str(weight): load_glyphs(config['font'], weight) for weight in weights}
html = (HERE / 'editor.html').read_text().replace('__GLYPHS__', json.dumps(glyphs, ensure_ascii=False)).replace('__GEOMETRIES__', json.dumps(geometries())).replace('__CONFIG__', (HERE / 'config.json').read_text())
(ROOT / 'docs/brand/logo-editor.html').write_text(html)
print('docs/brand/logo-editor.html を生成')
