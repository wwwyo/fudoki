# PaddleOCR の取り込み用入口

`paddle_ocr` はPP-OCRv6 smallの検出・認識をCPUで実行する。通常は検出だけ長辺1280pxへ縮小し、認識には元画像から切り出した画素を渡す。原典の文字・符号を後処理で変更しない。Apple Visionの既存入口も残す。

optional依存を含めて実行する。

```bash
mise exec -- uv run --frozen --extra paddle-ocr python -m ingestion.lib.paddle_ocr schema
mise exec -- uv run --frozen --extra paddle-ocr python -m ingestion.lib.paddle_ocr recognize \
  --params '{"kind":"pdf","path":"budget.pdf","pages":[1,2]}' > ocr.json
```

`--params @request.json`も使える。CLIのJSON保存先はcallerが指定する。失敗はstderrのJSONと終了コード1で返す。

モデルは[paddle_ocr_models.json](paddle_ocr_models.json)に宣言した公式URLから明示的に取得し、`~/.paddlex/official_models/PP-OCRv6_small_det`と`PP-OCRv6_small_rec`へ用意する。`detection_model_dir` / `recognition_model_dir`で別のローカル配置を指定できるが、宣言した3ファイルのSHA・サイズは必ず照合する。モデル不足・不一致で停止し、暗黙にダウンロードしたり他の重みに切り替えたりしない。

Pythonではengineを再利用できる。PDFは物理頁番号を明示し、再読する領域は頁ごとに宣言する。

```python
from pathlib import Path
from ingestion.lib.paddle_ocr import PaddleConfig, PaddleOcr, OcrRegion

with PaddleOcr(PaddleConfig()) as ocr:
    result = ocr.recognize_pdf(
        Path("budget.pdf"), pages=[1, 2],
        retry_regions={1: [OcrRegion("header-cell", (0.1, 0.1, 0.2, 0.2))]},
    )
    another = ocr.recognize_image(Path("upright.png"))
```

画像は元の寸法を使う。画像の`retry_regions`はpageキーを持たない`Sequence[OcrRegion]`。PDFのCLIでは`"retry_regions":{"1":[{"id":"header-cell","bbox_normalized":[0.1,0.1,0.2,0.2]}]}`、画像のCLIでは同じregion配列を直接渡す。通常の`regions`で全頁共通の列・領域を指定することもできる。

座標は左上原点のページ全体pixel・0〜1の比率・表示CropBoxのpt。画像ではptはnull。再読は元のページ画素をfloor/ceilの枠で切り出し、通常の検出条件（64/min、最大4000）で実行する。原典別の見出し・セル枠の自動検出は未実装で、callerが再読ROIを指定する。再読ROIはちょうど一つの通常領域の中に入る必要がある。

`pages[].regions[].observations`が採用中の観測、`pages[].attempts`が全試行の変更していないnative JSONと座標化した観測。ROI内に**親regionの中心**がある観測を、親と全child一緒に再読結果へ置き換える。各観測の`attempt_id`、試行の`superseded_observation_ids`から採用元と外した観測を確認できる。ROIを跨ぎ中心が外にある親は残り、再読と重複し得るため、callerが安全な枠を選び原典照合する。空の再読結果も補完せず保存する。

`region` / `word`はPaddleのnative文字を保持し、子のconfidenceは親regionのscoreを継承する。`number`はnative word全体が数字・カンマだけの場合に限る。符号付きwordから部分文字列やその座標を推測しない。採用する観測の階層は一つ選び、親とchildを同時に集計しない。

PDFの既定描画はmacOSのCoreGraphicsで、既存Vision・実験と同じCropBox・回転・sRGB・白背景・ceil寸法を使う。OCRを行わない[pdf_render.swift](pdf_render.swift)がPNGと表示geometryだけを返す。`pdf_renderer="poppler"`は明示選択できる（`pdfinfo`と`pdftoppm`が必要）。描画器を自動で切り替えない。PopplerはCropBox・回転を反映するがCoreGraphicsとは画素が異なり得るため、同じ精度・速度を保証しない。

CoreGraphicsのhelperは初回にSwift compiler（`xcrun`で解決、`-Onone`）でコンパイルし、以後はバイナリを再利用する。SwiftソースSHA、compiler版・path、macOS SDK版・path、OS・CPU、compile flagsとtoolchain環境をキャッシュキーに含める。キャッシュ取得時の不足・破損は再コンパイルする。実行前後にもバイナリSHAを照合し、不一致はエラーにする。並行構築は排他ロックで待ち、一時ファイルの構築後にatomic publishする。コンパイル・ロック待ちには`render_timeout_seconds`の共通上限を使い、描画には同じ値の別の上限を使う。失敗時にSwiftインタプリタへ切り替えない。Xcode Command Line ToolsとmacOS SDKが必要。

再生成可能なキャッシュはソースrepoの`pipeline/.cache/pdf-render/`に置く。インストール先や読み取り専用repoでは`$XDG_CACHE_HOME/fudoki/pdf-render/`（未設定時は`~/.cache/fudoki/pdf-render/`）を使う。Gitや配布物には含めない。結果の`renderer.compiled_renderer`にはbuild条件、binary SHA、cache key・hitとローカルbinary pathを残し、従来の`renderer`・`backend_sha256`・頁geometryも保持する。

入力SHA、描画PNG/RGB画素SHA、モデル・宣言・コードSHA、package版、各試行の設定・時間を結果に保持する。numpy入力はRGBからBGRへ変換し、PaddleのPNGファイル読込と同じ色順で渡す。再読・頁ごとのOCRでもengineは一度だけロードする。PDF描画subprocessにはtimeoutを設けるが、process内のPaddle推論には強制timeoutを設けない。

採用判断の約17.3秒は、同じ見開きの1280px検出と見出しband＋1セル再読を**別の実験callの時間から合算した値**だった。統合後の入口を親agentが同じ実PDFで独立検査した初回実測は、coldの全所要時間42.06秒・推論18.69秒、金額124/124一致・全確認項目171/174一致だった。3項目の不一致は既存のsmall通常読みと同じで、原典確認を要する。Swiftのコンパイル導入前の再実行は全所要時間20.90秒・推論15.56秒で、初回とnative文字・座標・confidenceが完全一致した。一般の資料の精度・速度を保証する値ではない。取り込み時は原典照合・欠落確認・階層別合計検査を継続する。
