# 再利用するVision OCR

`ingestion.lib.vision_ocr` はmacOS上でPDFの指定頁・領域を読み、OCRエンジンが返した文字と座標を返す。特定の自治体・表書式に依存しない。後処理で原典の金額や名称を書き換えず、既存の抽出器・固定入力へはまだ接続していない。

SwiftのApple Vision・CoreGraphics・ImageIOを使い、追加のPython依存やモデルのダウンロードは不要。macOSのCommand Line Tools（`xcrun swift`）が必要。Vision revision 3、accurate、日本語・英語、言語補正offを既定にする。設定は原典別に変更できる。

## PDFを読む

repo rootで実行する。ページ番号は印刷番号ではなく、PDF内の物理ページ番号（1始まり）。全ページの無条件実行を避けるため、明示指定を必須にする。

```python
from pathlib import Path
from ingestion.lib.vision_ocr import recognize_pdf

result = recognize_pdf(Path("budget.pdf"), pages=[109])
```

CLIは結果JSONをstdoutへ返す。入力・OCRの失敗はJSONをstderrへ返し、終了コード1にする。ファイル保存は呼び出し側が行う。

```bash
mise exec -- uv run --frozen python -m ingestion.lib.vision_ocr schema
mise exec -- uv run --frozen python -m ingestion.lib.vision_ocr recognize \
  --params '{"kind":"pdf","path":"budget.pdf","pages":[109]}'
```

`--params @request.json` でも指定できる。画像の場合は `kind: "image"` にし、`pages` は省略する。画像のEXIF回転は先に正立へ変換する。

## 列や領域を切り出す

```python
from ingestion.lib.vision_ocr import OcrRegion, recognize_pdf

result = recognize_pdf(
    Path("settlement.pdf"), pages=[2],
    regions=[OcrRegion("money-column", (0.32, 0.20, 0.43, 0.90))],
)
```

領域は左上原点の `(xMin, yMin, xMax, yMax)`、ページ全体に対する0〜1の比率。指定した領域を各対象ページに適用する。書式が違うページには別の呼び出し・領域指定を使う。複数領域が重なる場合の観測は重複排除しない。

PDFは表示されるCropBox・回転を反映して300dpiで描画する。画像は元のpixel寸法のまま使う。切り出した観測の座標はページ全体へ戻す。

結果は `pages[].regions[].observations[]` にあり、以下を保持する。

- `raw_text`、候補の `confidence`、観測 `id` と部分文字列の `parent_id`。
- `kind`: `region` / `word` / `number`。numberは連続する数字・カンマの範囲であり、節コード・頁番号も含む。スペースで分割された数値は呼び出し側で扱う。
- `bbox_px`: 左上原点のページ全体pixel座標。
- `bbox_normalized`: 同じ枠のページ全体に対する0〜1の座標。
- `bbox_pdf_pt`: 表示CropBoxの左上原点のpt。画像入力ではnull。
- `bbox_status`: `available` / `unavailable`。有効な枠が取れない観測も文字は保持し、座標はnullにする。空白だけのwordは出さず、空白を含む親領域の `raw_text` は保持する。
- 原典のSHA-256、実際のOSの版・build、revision、認識設定、抽出コードのハッシュ、領域ごとの推論時間。

word・numberは親候補のconfidenceを引き継ぐ。文字ごとの独立した確率ではない。accurateの枠は単語精度で、日本語の意味上の単語や文字の厳密な境界とは限らない。

## 正しい名称を認識用の語彙として渡す

```python
from ingestion.lib.vision_ocr import VisionConfig, recognize_pdf

result = recognize_pdf(
    Path("settlement.pdf"), pages=[2],
    config=VisionConfig(language_correction=True),
)
```

言語補正をonにすると、モジュールと同じディレクトリの [ocr_vocabulary.json](ocr_vocabulary.json) を毎回読み、`request.customWords` に自動で渡す。offでは辞書を読み込まない。語彙はコードから分離したJSONで管理し、名称を追加・変更するときはこのファイルを編集する。

```json
{"schema_version": 1, "words": ["備品購入費", "償還金", "共済費"]}
```

同梱辞書の初期内容は、今回の実スキャンで確認した正しい名称18語。誤読と正解の対応表ではなく、認識時の語彙の補助であり、指定語への変換を保証しない。法定節マスタや事後の名称訂正辞書とは独立して管理する。

別のPDFの用途では `VisionConfig(language_correction=True, vocabulary_path="path/to/vocabulary.json")` で辞書を差し替えられる。相対パスは実行時のcwdが基準。`custom_words=("追加の事業名",)` を指定すれば、ファイルの語彙に追加して渡す。同じ文字列は重複排除する。語彙を使わず補正だけをonにする比較では、`words: []` の辞書ファイルを指定する。

CLIは `config.language_correction`、`config.vocabulary_path`、`config.custom_words` で同じ設定ができる。補正onで辞書が存在しない・形式が不正な場合は、OCRを開始せず失敗を返す。

[Appleの仕様](https://developer.apple.com/documentation/vision/vnrecognizetextrequest/customwords)では `usesLanguageCorrection=false` のとき無視されるため、非空の `custom_words` を直接指定する場合は `language_correction=True` を必須とする。不整合は呼び出し前に拒否する。語彙だけで言語補正を暗黙にonへ変えない。設定と実際に渡した語彙、読んだ辞書のパス・バイト列のSHA-256を結果の `engine` に記録する。offでは `engine.vocabulary` はnull。補正onの場合、`raw_text` はVision内の言語補正を含む出力であり、補正前候補ではない。

多摩市の実スキャンの同じ物理2ページを、言語補正off・on・on＋正しい名称18語で比較した。全ページの金額一致は各91/109、金額4列を切り出した場合は各107/109で、検出した値の不一致は各0件だった。欠落は改善せず、今回のCoreGraphics描画で生じた `備品購入費 → 備品媾入費` も3設定すべてで残った。この1ページでは語彙追加による改善を確認できなかった。言語補正offの既定値と後処理の訂正辞書を維持する。

比較コードと未訂正の出力は `.agent/pdf-samples/vision-real-scan/test_custom_words.py`、`custom-words-{off,on,on-vocabulary}.json`、`custom-words-evaluation.json`。300dpi・revision 3・日本語/英語、macOS 27.0 build 26A428で実測した。以前のPoppler描画での誤読とは区別する。

## 名称を辞書で訂正する

`ingestion.lib.ocr_names` はOCRとは別に使う。呼び出し側が行の結合・節コードの分離を行い、論理的な名称を作ってから適用する。

```python
from ingestion.lib.ocr_names import correct_name, load_name_dictionary

dictionary = load_name_dictionary(
    Path("pipeline/ingestion/lib/fiscal_setsu_name_corrections.json")
)
name = correct_name("備品入費", dictionary)
# raw_name: 備品入費 / corrected_name: 備品購入費
# rule_id、reason、dictionary_sha256も返る。
```

同梱辞書は今回原典で確認した歳出の節名称の誤読3件だけ。自治体固有の事業名への適用は別の辞書を宣言する。辞書は `schema_version: 1`、`normalization: "NFKC_REMOVE_WHITESPACE"`、`rules`（id・observed_name・corrected_name・reason）のJSONで定義する。

照合時だけNFKCと空白除去を使い、名称全体の一致だけを訂正する。部分置換・あいまい一致・連鎖置換はしない。未一致の名称はそのまま返す。訂正候補と根拠を別フィールドへ残し、`raw_name`・OCRの `raw_text`・金額は上書きしない。数値だけの辞書キーと、同じ正規化キーの重複定義は拒否する。

## 再利用できる範囲

読み取り可能な別のPDFでもOCRの入口と出力形式は再利用できる。PDFの文字層を優先する判断、表の列・セル・階層・見開きの復元は呼び出し側の責務である。暗号化PDFは拒否する。入力が処理中に変わった場合も結果を返さない。

実スキャンの比較では、全ページで109金額セル中18セル、列ごとの切り出しでも2セルの0を検出できなかった。OCR成功は全セルの検出を意味しない。欠落を空欄や0で自動補完せず、原典との確認を別に行う。

内部重みの名前・版は公開APIで取得できない。OS更新後の再評価は必要で、Linuxでは動かない。方針と実測は[ADR 0017](../../../docs/adr/0017-vision-for-coordinate-preserving-ocr.md)を参照する。

## 小さい文字の閾値と未検出セルの再読

`VisionConfig(minimum_text_height=0.001)` で `request.minimumTextHeight` を指定できる。値は切り出した入力画像の高さに対する0〜1の比率。`None`（既定）はVisionの値を変更しない。`engine.requested_minimum_text_height` は指定値、`pages[].regions[].minimum_text_height` は実際のリクエストの値を記録する。

[Appleの文書](https://developer.apple.com/documentation/vision/vnrecognizetextrequest/minimumtextheight)は既定値を0.03125としているが、今回のOS・revision 3・accurateでは未指定時の実測値は0だった。全ページと列ごとの両方で、0.003・0.001・0.0001・0を各2回比較しても、金額一致はそれぞれ91/109・107/109のままだった。0.01や0.03125に上げると全ページの結果は悪化した。この環境では閾値を下げるだけで欠落は解消しない。

別案として600dpi描画、行ごと・セルごとの切り出し、数字欄の英語設定も比較した。最も良かったのは、300dpiの列ごとの抽出を保ち、観測がない2セルだけセル内を切り出して再読する方法だった。実際に2つの「0」を取得し、追加後は109/109セルが一致した（2回とも、数値の不一致0）。空欄を0で補完した結果ではない。

全セルを切り出す単独の試行は104/109だったため、すべてをセルOCRへ置き換える方針にはしない。今回のセル枠は原典の罫線を見て宣言した既知の座標であり、一般的なセル検出器は未実装。別の原典でも同じ結果になる保証はない。再読の自動実装・既存取り込みへの接続はしていない。

実験コードと出力は `.agent/pdf-samples/vision-real-scan/` の `test_minimum_height.py`、`test_zero_alternatives.py`、`test_missing_cell_retry.py` と、それぞれの評価JSON・OCR結果に保存した。
