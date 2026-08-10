# web — 調査ビューア

`survey.html` は `src/extract/sources/manifest.json` をブラウザで見るための単一 HTML。

```bash
python3 -c "
import json
d=json.load(open('src/extract/sources/manifest.json',encoding='utf-8'))
# … web/_data.js を生成（scripts/build-survey.ts に置き換え予定）
"
python3 -m http.server 4317 --directory web
```

`_data.js` は manifest から生成する中間物なので gitignore。

## なぜ DuckDB-Wasm を使っていないか

62行の表に WASM ランタイムを積むのは重すぎ、CDN 依存も増える。データを埋め込んだ単一 HTML なら即開けてオフラインでも動く。**発言データ（数十万行）を扱う段になったら DuckDB-Wasm を入れる**。
