# scan PDFのOCRを選ぶ

共通入口は `ingestion.lib.scan_ocr`。既定はPaddleOCRのPP-OCRv6 small、`backend="vision"` でApple Visionを選ぶ。失敗時に別エンジンへ自動で切り替えない。既存の `vision_ocr` のAPI・CLIも残す。

採用理由と比較の限界は[ADR 0018](../../../docs/adr/0018-paddle-small-for-scan-pdf.md)に記録する。

```python
from pathlib import Path
from ingestion.lib.scan_ocr import OcrRegion, recognize_pdf

result = recognize_pdf(Path("settlement.pdf"), pages=[1, 2])
apple = recognize_pdf(Path("settlement.pdf"), pages=[1, 2], backend="vision")
```

## 縮小検出と原画像の再読を組み合わせる

Paddleは文字を探す検出工程だけ長辺1280pxへ縮小する。見つけた文字の認識には、元の画像から切り出した画像を使う。MacのPDF描画は実験と同じCoreGraphics・300dpiを既定とする。

見出しなどの再読領域は、原典の配置を確認した書式設定から明示的に渡す。モジュールが見出しや欠落セルを自動で発見するわけではない。`retry_regions` を省略した場合は縮小検出のみになる。

```python
result = recognize_pdf(
    Path("settlement.pdf"), pages=[1, 2],
    retry_regions={1: [
        OcrRegion("header-band", (164/2480, 263/3509, 2304/2480, 720/3509)),
        OcrRegion("header-cell", (1440/2480, 550/3509, 1712/2480, 720/3509)),
    ]},
)
```

この座標は多摩市2020年度決算の実験対象（物理1・2頁、印刷74・75頁）だけの例。他の頁・書式へそのまま適用しない。再読は指定順に行い、原解像度の見出し帯を再読した後、残った不一致の1セルを再読する。再読前後の観測とnative出力を保持し、原ページ上の座標へ戻して、領域内に中心がある親観測とその子を一緒に置き換える。

2026-10-09の比較では同じ2頁の金額124/124、全174項目中171項目が一致し、残る差は中点2件・括弧1件だけだった。通常設定33.1秒に対し、この組み合わせは推論時間の合算17.3秒。初期化・描画・検査・Parquet作成は含まず、各条件1回の測定である。原典画像を親AIが読んだ正解表による評価で、人のレビューはない。別の原典で同じ精度・時間を保証しない。

組み込み後も同じPDFの2頁を共通入口で再検査し、金額124/124、全項目171/174、空欄3/3、未対応領域0を確認した。最終コードでの推論は15.6秒、初期化・描画を含む入口全体は20.9秒だった。最初の実行は推論18.7秒・入口全体42.1秒で、起動状態による時間差がある。2回のnative文字・polygon・word・confidenceは完全一致し、描画画素も従来の実験と一致した。Parquet作成や後段の検査時間は含まない。

## インストールと結果の利用

Paddleの任意依存は `mise exec -- uv sync --extra paddle-ocr --frozen` で導入する。実行時も `uv run --extra paddle-ocr --frozen` を使う。Appleだけを使う場合は不要。モデルは [固定宣言](paddle_ocr_models.json) のものをローカルへ明示的に用意する。OCR実行中のダウンロードは行わない。

Paddleのモデル指定・常駐engine・CLIは [paddle_ocr.md](paddle_ocr.md)、Appleの設定・語彙・CLIは [vision_ocr.md](vision_ocr.md) を参照する。複数画像を処理する場合は `PaddleOcr` のcontext内でengineを使い回す。PDF入口は同じengineで全指定頁と再読を処理する。

両エンジンの有効な観測は `pages[].regions[].observations[]` に返る。`pdf_table.tokens_from_ocr(result, kind="region", region_ids=["full-page"], unit="pt")` で表の組み立てへ渡せる。画像入力では `unit="px"` を指定する。原文・金額の補正は行わず、名称辞書の適用や原典照合は呼び出し側で行う。
