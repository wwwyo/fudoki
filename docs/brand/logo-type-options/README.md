# 文字と下線の丸みの比較

2026-10-04。候補比較であり、採用済みの `config.json` は変更していない。

- A: Noto Sans JP 700（現在の書体）
- B: BIZ UDPゴシック Bold
- C: M PLUS 1 700
- D: Zen Kaku Gothic New Bold

マークはcompact、字面の高さ約30.572153・中心y=21.5、輪郭間の字間3.5／3.5、マークとの間隔8、基調色とオレンジを共通にする。下線は角丸0.25／0.6／1.0を比較。各書体のemサイズは字面の高さへ合わせた実数値を各config.jsonに記録する。

SVGは輪郭で保存し、OSの代替書体には依存しない。フォント原本は再生成用の`.cache/logo-fonts/`に置き、追加3書体は`apps/web/brand/type-fonts.json`の固定commitとSHA-256から取得する。OFLは各候補フォルダに保存する。

実画面の静的な抜粋は `/pipeline/` に下線0.6で各候補を適用したもの。ライト・ダークを同じ領域で撮影し、寸法と画像の読み込み状態を `product-*-state.json` に保存する。比較ページの「実画面へ」は選んだ書体と下線をローカルの検証画面iframeへそのまま適用する。

生成: `UV_CACHE_DIR="$PWD/.cache/uv" mise exec -- uv run --no-project --exclude-newer 2026-09-26 --with fonttools==4.66.0 --with brotli==1.2.0 python apps/web/brand/build-type-options.py`

書体の出典:
- [Noto Sans JP](https://github.com/notofonts/noto-cjk)
- [BIZ UDPゴシック](https://github.com/google/fonts/tree/9710da1eacb3be272583c3224dcb70f9da6eadbb/ofl/bizudpgothic)
- [M PLUS 1](https://github.com/google/fonts/tree/9710da1eacb3be272583c3224dcb70f9da6eadbb/ofl/mplus1)
- [Zen角ゴシック New](https://github.com/google/fonts/tree/9710da1eacb3be272583c3224dcb70f9da6eadbb/ofl/zenkakugothicnew)
