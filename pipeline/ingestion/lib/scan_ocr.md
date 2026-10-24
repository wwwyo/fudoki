# scan PDFのOCRを選ぶ

新しい取得の依頼は `engine: "paddle"` と書く（[ADR 0032](../../../docs/adr/0032-paddle-onnx-for-new-scan-acquisitions.md)）。例: `{"engine":"paddle","pages":[31,32]}`（既定は縦2分割・上限1920・pypdfium2の300dpi。変えるときだけ `config` に書く）。既に `engine: "vision"` で固定した冊は、観測IDと訂正の宣言が結び付くのでそのまま残す。`column_tiles` はVisionの取りこぼしへの対処で、Paddleの依頼には使えない（頁の縦分割は `config.page_strips`）。

取得の依頼に `column_tiles:true` を書くと、罫線で区切った列を文字のない行間で分割し、白い余白を付けてVisionで読む。文書ごとに選ぶ取得条件であり、省略時の頁全体の読みは変えない。`regions` との併用は不可。`vlm_fallback:false` はVisionの再読までで止め、未読の墨を観測に残す。木の検査後に必要なセルだけ別途再読し、答えを固定する場合に使う。例: `{"engine":"vision","pages":[31,32],"column_tiles":true,"vlm_fallback":false}`。

共通入口は `ingestion.lib.scan_ocr`。既定は **PaddleOCR PP-OCRv6 small（ONNX Runtime、CPU）**（`paddle_ocr`）。Apple Visionは `backend="vision"` で選ぶ。失敗時に別エンジンへ自動で切り替えない。既存の `vision_ocr`・`paddle_ocr` のAPI・CLIも残す。

```python
from pathlib import Path
from ingestion.lib.scan_ocr import OcrRegion, recognize_pdf

result = recognize_pdf(Path("settlement.pdf"), pages=[1, 2])          # 既定はPaddle
vision = recognize_pdf(Path("settlement.pdf"), pages=[1, 2], backend="vision")
```

`backend` を省略して `config` に `VisionConfig` を渡した場合はVisionを、`PaddleConfig` ならPaddleを選ぶ。型が使うエンジンを一意に決める。`backend` を明示して `config` の型と食い違う場合は拒否する。

Paddleを既定にした理由は、頁を縦に分けて検出すると金額の誤りが訂正前のVisionの数百件から6〜12件に減るためである（[ADR 0032](../../../docs/adr/0032-paddle-onnx-for-new-scan-acquisitions.md)）。Visionの弱点であるmacOS限定は、OCRを変換器の外で一度だけ実行し観測を固定して補助入力にする方針（[ADR 0019](../../../docs/adr/0019-freeze-scan-ocr-observations.md)）で小さくなっていた。取得の入口は `acquire`（`ingestion:ocr` から呼ぶ）で、観測は内容だけの正規化JSON、所要時間や環境は実行記録に分ける。Visionが頁全体を空で返したら、罫線で決めた列の帯で読み直し、それでも空なら止める。Visionは **accurate、revision 3、日本語・英語** を初期条件にし、OSの版・build、revision、言語補正を記録する。内部重みは固定できるとは扱わない。設定は [vision_ocr.md](vision_ocr.md) を参照する。

## Paddle が中国語の字形で読む字

Paddle は日本語の名称・見出しを、徵・產・查・增のような中国語の字形で読むことがある。日本の科目名で正字として使われない字形だけを、[ocr_variant_chars.json](ocr_variant_chars.json) の対応表で1字ずつ置き換える。迷う字は入れず、`name_corrections` に個別に宣言する。当たるのは engine paddle の観測だけで、当たった観測 ID は変換の受領書の注記に残る。

## 見落とした墨を読み直す

以下の再読の手順はVisionの説明で、Paddleの依頼でも同じ段を踏む。違いは、段1の再読がPaddleの切り出し読み（罫線を白く消した頁から、見落とした墨の範囲を白い余白なしで切り出し、64pxまで拡大して読む。領域 `ink-<n>`、観測IDは `p<頁>:ink-<n>:a0:result0:r<i>`）になることと、取得時の `attempts[].native` を観測に残さないことである。

Visionは単独の「0」、横棒1本の「一」、均等割付の名前の1字、ときには備考の行まるごとを、エラーなしに読み落とす。`acquire` は頁ごとに、OCRの箱にも罫線にも覆われない墨を探し（`missed_ink`）、次の順で読み直す。

1. 同じ行・同じセルの墨をまとめ、左右6pt広げて（3ptでは金額の頭の1が切れる）、罫線を白く消した頁の画像で、その範囲だけをVisionで読み直す（`ink_areas`・`_read_without_rules`、領域 `ink-<n>`）。罫線を残すと、際の0を `0一`・`10` と読む。見落とした墨に重ならない読み（読めている行の端など）と、既にある箱と重なる読みは捨てる。
2. それでも覆われない数字の大きさの墨は、PaddleOCRの文字認識だけ（検出なし、PP-OCRv6 small、1か所約130ms）で読み、1桁の数字だけを採る（`_read_zeros`、領域 `digit-<n>`）。残る墨の約4分の3は単独の0で、試しでは345か所すべてcodexと一致した。数字だけの認識は、既定のONNX Runtimeで動かす。取得には `--extra paddle-ocr` が要る。
3. 残りの墨は、その行のセル幅をVLM（`vlm_ocr`、既定はcodex経由のgpt-6-luna。OpenCode Goの上限の間の代わりで、`pi` 経由にはモデル名で戻す）に読ませ、OCRが読んだ文字との差が1か所の挿入に定まるときだけ、その文字を補う（`_fill`、領域 `vlm-<n>`）。1字だけを切り出すと形の似た字を取り違える（繕→繰、工→十）ため、行の文脈で読ませる。
4. 定まらない墨は `unread_ink` に範囲だけ残す。合計の差から値を逆算しない。モデルが答えなかった範囲（混雑・時間切れ）は `vlm_failed` に残し、次の取得で聞き直す。モデルは「一」を「ー」「―」と答えることがあるため、語頭や漢字の後の横棒は「一」とする。

VLMの答えは観測に固定される。再取得では、同じモデル・プロンプト・答えの作り方（観測の `vlm`）で得た固定済みの答えを使い回し、聞き直さない。`--verify` はVisionの再現性を確かめ、VLMの答えは固定値として扱う。2026-10-12の青梅・教育費（60頁）では、墨205か所のうち196か所をVisionの読み直しで、残る7か所をVLMで補い、出典画像と一致した。

## Paddleの縮小検出・頁の縦分割・原画像の再読

Paddleは文字を探す検出工程だけ長辺1280pxへ縮小する（`detection_limit_side_len`）。`page_strips`（既定2）で各領域を縦に等分し、隣へ`strip_overlap_px`（既定60）だけ重ねて別々に検出する。上限は分割片ごとに効き、既定は1920である（132152・131181で全件一致、頁あたり5.6〜7.6秒、RSS 1.3〜1.7GB。比較は[ADR 0032](../../../docs/adr/0032-paddle-onnx-for-new-scan-acquisitions.md)）。重なりの帯で二重に観測された行は取得時に除く。描画は既定でpypdfium2の300dpiで、`pdf_renderer`で`coregraphics`・`poppler`を明示できる。描画方法は観測の`render`に残る。見つけた文字の認識には、元の画像から切り出した画像を使う。MacのPDF描画は実験と同じCoreGraphics・300dpiを既定とする。

見出しなどの再読領域は、出典の配置を確認した書式設定から明示的に渡す。モジュールが見出しや欠落セルを自動で発見するわけではない。`retry_regions` を省略すると、縮小検出と原解像度認識だけを行い、追加のcrop再読は行わない。

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

2026-10-09の比較では同じ2頁の金額124/124、全174項目中171項目が一致し、残る差は中点2件・括弧1件だけだった。通常設定33.1秒に対し、この組み合わせは推論時間の合算17.3秒。初期化・描画・検査・Parquet作成は含まず、各条件1回の測定である。出典画像を親AIが読んだ正解表による評価で、人のレビューはない。正解表は先頭0の付いた連結誤りが値として同値になり、木の検査を通る（[ADR 0032](../../../docs/adr/0032-paddle-onnx-for-new-scan-acquisitions.md) の 2026-10-19〜20 の比較で、正解側の誤り `04,069,726,000` に偶然一致した例）。正解表を根拠にするときは、金額の代表を原典画像で抜き取って確かめる。別の出典で同じ精度・時間を保証しない。

組み込み後も同じPDFの2頁を共通入口で再検査し、金額124/124、全項目171/174、空欄3/3、未対応領域0を確認した。最終コードでの推論は15.6秒、初期化・描画を含む入口全体は20.9秒だった。最初の実行は推論18.7秒・入口全体42.1秒で、起動状態による時間差がある。2回のnative文字・polygon・word・confidenceは完全一致し、描画画素も従来の実験と一致した。Parquet作成や後段の検査時間は含まない。

## 小さい印字の scan を Paddle で読む依頼の宣言

A4縦2頁を横に並べた見開きは、`page_strips=2` で横に2つの帯（幅約1814px）に分かれ、帯の幅は検出の上限1920に収まる。縮むのは帯の高さ（2481px）で、既定では 0.774 倍（実効約232dpi）になり、5pt の印字は約16pxで読まれる。印字が小さい冊は依頼の `config` に `detection_limit_side_len: 2560`（帯の長辺以上）を書く（RSS は約2.0〜2.3GB）。既定は変えない。

取得の依頼には、既定では何もしない次の宣言がある（[ADR 0032](../../../docs/adr/0032-paddle-onnx-for-new-scan-acquisitions.md)）。
- `ink_dark`（129〜255）: 見落とした墨を探すときの濃さの上限。薄い小さい印字は既定の128では墨と見られない。指定すると、金額欄の小さい横棒（「－」）は見落とした墨に数えない。
- `unit_marks`: 金額の上に小さく印字された「円」を、頁の読みが `川` `间` `1` と読むとき、1字の読みと「円」と横棒の積みを文字認識だけで読み直し、「円」のときだけ置き換える（領域 `unit-mark-<n>`）。
- `merged_lines`: 2行に折り返した名称を検出が1つの箱にして混ぜて読むとき、頁の通常の行の1.7倍以上の高さで、幅が3行分以上の箱を、行の間の空白行で切って行ごとに読み直す（領域 `lines-<n>`）。

## インストールと結果の利用

Paddleの任意依存（onnxruntimeを含む）は `mise exec -- uv sync --extra paddle-ocr --frozen` で導入する。実行時も `uv run --extra paddle-ocr --frozen` を使う。Visionだけを使うなら、数字の認識（段2）以外は不要。Paddle本体で動かす `runtime="paddle"` だけは `--extra paddle-native` も要る。モデルは [固定宣言](paddle_ocr_models.json) のものをローカルへ明示的に用意する。OCR実行中のダウンロードは行わない。

Paddleのモデル指定・常駐engine・CLIは [paddle_ocr.md](paddle_ocr.md)、Appleの設定・語彙・CLIは [vision_ocr.md](vision_ocr.md) を参照する。複数画像を処理する場合は `PaddleOcr` のcontext内でengineを使い回す。PDF入口は同じengineで全指定頁と再読を処理する。

両エンジンの有効な観測は `pages[].regions[].observations[]` に返る。`pdf_table.tokens_from_ocr(result, kind="region", region_ids=["full-page"], unit="pt")` で表の組み立てへ渡せる。画像入力では `unit="px"` を指定する。原文・金額の補正は行わず、名称辞書の適用や出典照合は呼び出し側で行う。

## OCR後の名称と金額に共通訂正辞書を使う

PaddleとVisionのどちらでも、名称の補正には共通の `ingestion.lib.ocr_names` を使う。呼び出し側が折り返しを結合し、番号欄を確認して番号と名称を分けた後、名称全体を辞書と照合する。[節名称辞書](fiscal_setsu_name_corrections.json) と [科目名辞書](fiscal_subject_name_corrections.json) に、出典画像で確認した誤読パターンを蓄積し、条件が合う別PDFでも再利用する。

金額の誤読も同じ宣言の形で直す。`AmountRule`（`id`・観測した金額・正しい金額・`reason`）に、頁と観測IDを足して一つの観測に結び付ける。同じ誤読文字列が別のセルにあっても、頁と観測IDが合う規則だけを適用する。生の観測は書き換えず、補正前後・rule ID・辞書SHAを候補に残す。宣言した観測文字列が実際の観測と食い違えばエラーにし、古い宣言を黙って通さない。金額の訂正は木の検査で正しさを確かめ、誤った宣言は検査を通らない。合計の差から値を逆算して埋めることはしない。

```json
{"schema_version": 1, "normalization": "NFKC_REMOVE_WHITESPACE", "rules": [
  {"id": "amount-inter-digit-space", "page": 1,
   "observation_id": "p1:full-page:r109", "observed_amount": "84, 365, 635",
   "corrected_amount": "84,365,635", "reason": "OCRが数字の間に空白を入れた。桁と符号は出典画像で確認した。"}
]}
```

辞書にない名称や複数の解釈がある名称だけ、意味の照合や必要な領域の再読へ進む。出典が使っている旧字を新字へ一括変換しない。未訂正のOCR文字・観測ID・位置を保持し、補正前後とrule ID・辞書SHAを候補に記録して出典照合へ渡す。認識用の [ocr_vocabulary.json](ocr_vocabulary.json) はAppleの `customWords` 用で、Paddleの事後訂正にはこの語彙だけを追加しても効果はない。

## 汎用scanの科目番号の訂正

`generic_scan` の管理JSONの `conversions[].options.code_corrections` は、原画で確認した科目番号の誤読だけを固定する。組版の設定ではなく、OCRの原文を保持した別の宣言である。数字だけのOCR単語が科目欄（款・項・目）か内訳の名前欄（`kind: label`。節の番号）の中にあること、物理頁・単語ID・原文の完全一致を確かめる。対象がない、原文が違う、金額欄にある、文字を含む場合は停止する。訂正で桁が減る場合（縦罫線が数字に付いた `181` を `18` と直す）は、語の枠も印字の桁数に縮める。金額の訂正には従来の `amount_corrections` を使う。

```json
{
  "code_corrections": [{
    "id": "confirmed-continuation-codes",
    "page": 21,
    "observation_id": "p21:full-page:r11:w0",
    "observed_code": "4212",
    "corrected_code": "421",
    "reason": "原画の継続頁の科目欄で款4・項2・目1と読んだ。融合したOCR単語の誤読を訂正する。"
  }]
}
```

単語が複数の科目欄を横断した場合も、訂正した数字を同じ観測の枠のまま既存の列分割へ渡す。観測JSONを書き換えず、構築後は木・数字の網羅・単位・科目の検査を当てる。

## 汎用scanの科目名の訂正

`generic_scan` の管理JSONの `conversions[].options.name_corrections` は、原画で確認した科目名のOCRの誤読（旧字形の取り違えなど）を、字の置き換えとして固定する。同じ字数の置き換えか、OCR が落とした字を戻す字の増（`3款民生費` → `第3款民生費`）だけを許し、観測した文字が訂正後の文字の部分列であること。頁・観測ID（行または単語）・誤読した字・印字された字に結び付け、観測にその字が無ければ停止する。数字（科目番号・金額）は `code_corrections`・`amount_corrections` が受けるので、訂正の前後で数字の並びが変わる訂正は拒否する（数字を含む名称の字の増は、数字の並びが同じなら通る）。原観測は書き換えず、分類の規則へ誤読の字形を足さずに済ませる。

```json
{
  "name_corrections": [{
    "id": "confirmed-industry-promotion-name",
    "page": 122,
    "observation_id": "p122:tile-1-2:r0",
    "observed_name": "產",
    "corrected_name": "産",
    "reason": "原画の目の名称は「産業振興費」。OCR が産を旧字形の產と読んだ。"
  }]
}
```
