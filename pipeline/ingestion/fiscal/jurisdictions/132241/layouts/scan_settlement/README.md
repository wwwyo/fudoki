# Scan 決算書の見開き取り込み

`convert(inputs, destination, options)` は選定・保存済みPDF一件と単一会計の非連続頁範囲を受け取り、未使用dirへ直接Parquetを書く。原典のSHAを入力の `sha256` と照合する。対象の団体・年度・会計・方向の共通codeはrawへ追加しない。

共通 `scan_ocr.PaddleOcr` を一つのcontextで使い、small・300dpi・1280px検出と原解像度認識、layout指定の領域再読を行う。表示用画像も共通描画器からcacheへ保存し、OCR描画のPNG SHAと照合する。OCR native試行と観測はcacheのJSONに保持する。旧OCR、転記、既存Parquetは入力にしない。

`layout.json` の見開き、列の境界、水平罫線の帯、親行の役割を設定し、共通 `pdf_table` のcanvasと表組み立てを使う。左右のOCR観測番号でjoinしない。款・項・目の親欄は次の同位または上位項目までの原典欄を読む。頁を跨いだ継続目は同じ原典所属を維持する。表を組み立てた後、確認済みの番号付き科目名・法定節名だけに共有名称辞書を適用する。表紙や金額欄は対象にしない。

- `details.parquet`: 法定節と全款・項・目の所属、印字された親金額。節のない予備費は目の明細。
- `parents.parquet`: 各款・項・目の印字小計。
- `detail_totals.parquet`: 事項別明細書末尾の会計歳出合計。
- `summary.parquet`: 歳出総括表の款・項・会計歳出合計。
- `marginalia.parquet`: 対象頁の表外の年度・会計・タイトル・見出し・単位・注記・印刷頁の観測。
- `cell_observations.parquet`: 表/行/fieldとnative OCR観測id・原典位置の対応。

金額はOCR文字列のまま。原典の符号、桁区切りを変更しない。未観測セルはNULL。親AIが原典画像で印字なしを確認し、layoutに宣言した備考セルだけ空文字にする。印字0は文字列 `0`。節のない目の区分/節額はNULLで、該当列がない旨をmetadataへ記す。親額は反復して保持し、明細との同時加算をしない。検査列や数値化した合計はrawへ追加しない。

2026-10-09設定は、多摩市2020決算の後期高齢者医療特別会計、物理5–9/16–19頁を対象にする。5頁は表紙、6–7頁は歳入総括表のため歳出表へ取り込まないが除外理由をreceiptへ残す。頁対応・列・罫線・親行宣言を別layoutへ差し替えれば年度・会計を変えられ、変換コードは複製しない。

再現には2026-10-09の保存済み実験の [inputs.json](../../../../observations/scan-account-2026-10-09/inputs.json) と [options-009.json](../../../../observations/scan-account-2026-10-09/options-009.json) を使う。文書の相対リンクはこのlayoutディレクトリを起点とする。リンク先の `observations/` はGit管理外のローカル報告で、この実験を保存した作業環境でだけ参照できる。原典PDFと固定OCRキャッシュもその環境に必要となる。

次のコマンドはrepo rootから実行する。例の `candidate-rebuild-009` が未使用であることを確認し、既存なら別の未使用dir名に変える。

```bash
mise exec -- uv run --frozen --extra paddle-ocr python pipeline/ingestion/fiscal/jurisdictions/132241/layouts/scan_settlement/convert.py \
  --inputs pipeline/ingestion/fiscal/observations/scan-account-2026-10-09/inputs.json \
  --options pipeline/ingestion/fiscal/observations/scan-account-2026-10-09/options-009.json \
  --output pipeline/ingestion/fiscal/observations/scan-account-2026-10-09/candidate-rebuild-009
```

再現用入力・options・実際のcommandは候補dir隣とreceiptに保持する。Parquetのschemaと保存後のreadbackは構築側が確認し、原典・文字・所属・合計は親agentが保存済みParquetから独立して検査する。

`convert` の各表の戻り値は `{path, metadata}`。`metadata` は管理schemaの `units`・`notes`・`column_contexts` で、実Parquet列名を渡した `manifest.validate_metadata()` に通す。同じmetadataをreceiptの各 `tables[表ID].metadata` へ保持する。金額のunitは原典確認の `（単位：円）`。原典確認ヘッダーのbindingとnative OCRの字形差はnotesへ記し、nativeは変更しない。親の反復額のgrainは款、款・項、款・項・目で、節の区分を含まない。

共有辞書は `ingestion/lib/ocr_names.py` から読み込む。法定節名は `fiscal_setsu_name_corrections.json`、科目名は `fiscal_subject_name_corrections.json` と役割を分け、`layout.name_dictionaries` で宣言する。既存の `correct_name()` は全名称をNFKCと空白除去で照合するAPIを維持し、追加した `correct_name_preserving_layout()` は同じ全名称照合の後、文字数が同じなら原文の空白・改行と未変更の字形を保持する。文字数が変わる既存ルールでは位置を推定せず宣言済みの完全名称を返し、その方針も記録する。

多摩市では、表の原典欄を確認した科目名と法定節名だけで、生の数字prefixを名称から分離する。名称全体が一致したときだけ訂正し、生のprefixをそのまま戻す。部分一致、金額、不明名称、表紙の原典旧字「齡」は変更しない。元文字はnative JSONと `cell_observations.observed_text` に保持する。適用したrule ID、辞書pathとSHA、番号付きbefore/after、論理名称、適用条件、折り返しの保持方針、原典SHA・頁・native観測ID・bboxはreceiptの `dictionary_name_corrections` に保持し、正規metadataにも辞書と適用方針を記す。

候補007までの8局所訂正とその原典確認根拠は、`corrections.json` の `archived_local_corrections` に保持する。候補008以降では古いセルIDを訂正入力にせず、共通辞書で同じ名称パターンを照合する。名称10セルのcrop再読を外し、全頁と必要な見出しの読み取りによる既存OCRキャッシュを使う。これにより基礎OCRの「健康診查費」も科目名辞書で訂正する。原典照合は親AIの画像確認で、人間確認ではない。

語彙ファイル `ocr_vocabulary.json` にも「徴収費」「健康診査費」を追加した。PaddleはAppleのcustomWordsを使わないため、今回Paddleで実際に働くのは認識後の共有辞書であり、認識エンジン内で表の意味を補正しない。

親の独立検査では、保存済みの独立画像から罫線を再生成し、その出力をvalidatorへ渡す。`parent-origin/page-*.png` は親が原典を独立描画した既存PNGで、構築OCRの描画画像を入力にしない。原典referenceは親AIが画像を照合して記録したものを使い、OCRや候補から生成しない。両CLIは構築moduleをimportしない。

repo rootで、次の出力先が未使用であることを確認してから順に実行する。罫線の出力名を変える場合は、次のvalidatorの `--rules` も同じpathにする。

```bash
mise exec -- uv run --frozen --extra paddle-ocr python pipeline/ingestion/fiscal/jurisdictions/132241/layouts/scan_settlement/inspect_origin.py \
  --images pipeline/ingestion/fiscal/observations/scan-account-2026-10-09/parent-origin \
  --output pipeline/ingestion/fiscal/observations/scan-account-2026-10-09/rules-rebuilt-009.json

mise exec -- uv run --frozen --extra paddle-ocr python pipeline/ingestion/fiscal/jurisdictions/132241/layouts/scan_settlement/validate_candidate.py \
  --candidate pipeline/ingestion/fiscal/observations/scan-account-2026-10-09/candidate-009 \
  --source pipeline/.cache/objects/fiscal/source-selection/132241/2020/settlement-8.pdf \
  --reference pipeline/ingestion/fiscal/observations/scan-account-2026-10-09/parent-origin/reference-v3.json \
  --rules pipeline/ingestion/fiscal/observations/scan-account-2026-10-09/rules-rebuilt-009.json \
  --output pipeline/ingestion/fiscal/observations/scan-account-2026-10-09/validation-rebuilt-009.json
```

罫線を再生成せず、保存済みの独立罫線で再検査する場合は、validatorの `--rules` に `pipeline/ingestion/fiscal/observations/scan-account-2026-10-09/parent-origin/independent-rules-v2.json` を指定する。この場合は `inspect_origin.py` の実行を省き、検査レポートには別の未使用pathを指定する。

referenceは親AIが原典を独立描画し、全9頁から金額・名称・非金額の事実を記録したもの。OCRや候補から生成した正解表ではない。検査は候補と原典のSHAを固定し、名前・位置・metadata・合計に不一致があれば非ゼロ終了する。原典画像確認による局所訂正も含むため、全自動で100%の精度を保証する処理ではない。

候補004は、表紙のnative旧字「齡」を「齢」へ変えた誤訂正が唯一の不一致となり棄却した。親AIが原解像度cropで原典自体の「齡」を確認し、初期referenceの誤りをreference-v3へ訂正した。旧referenceと候補004は保持し、候補005では表紙の訂正宣言だけを外して原典・nativeの「齡」をそのまま保持する。他の8原典セルの局所訂正とcropで改善した健康診査費1セルを維持し、金額とその検査基準は変えない。訂正の撤回理由はcorrections.jsonのreview_historyとreceiptに記録する。

候補009は全頁＋必要なheader再読の基礎OCRを再利用し、金額・親の所属・原典reference-v3を変更せず、共有辞書の適用を保存後のParquetから再検査する。共通辞書の正例、数値・番号付き文字列・部分一致・不明名称・原典旧字齡の負例、折り返し保持は `mise exec -- uv run --frozen python -m unittest ingestion.lib.ocr_names_test ingestion.lib.vision_ocr_test.NameCorrections`（pipelineディレクトリから）で確認する。
