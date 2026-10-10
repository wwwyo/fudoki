# 企業会計の決算報告書と費用明細

`convert(inputs, destination, options)` は保存済みPDF、凍結native OCR、書式設定を受け取り、新しいローカルParquetと原典で確認したmetadataを返す。共通 `scan_ocr`、`pdf_table`、`conversion` と `fiscal/layouts/statement/text_spread` を利用する。R2、選定、正式管理JSON、dbtは変更しない。

年度・会計ごとのコード複製を行わず、支出の行帯・列境界、見開き対応、罫線の階層、継続頁、原典限定訂正を設定で渡す。別原典への適用には、その原典画像による設定と独立検査が必要。

## 今回の固定範囲

132012 八王子市、FY2025 下水道事業会計。原典SHAは `8b1475f40fb2a048d3555035769dddb338107c21618505f618d24ecff2807d36`、物理6–9・34–37の歳出側のみ。同頁上部の収入と他の附属表は対象外。原典goldは構築入力にしない。

- `revenue_expenditure_statement`：税込の収益的支出、10印字行。予算の各列・決算額・繰越額・不用額・備考を分離。
- `capital_expenditure_statement`：税込の資本的支出、8印字行。予算と翌年度の繰越列を区別。
- `expense_printed_rows`：税抜の費用、122印字行。親・節・所属のない費用合計を保持。
- `expense_details`：税抜の97節末端。罫線から確認した款・項・目と、その原文金額を展開。総係費は物理35から36へ継続。
- `statement_notes`：物理8の支出表下の注記。注記の数字を財政明細の金額列へ分解しない。

金額は文字列で、カンマ・符号・印字0を保持する。確認した空欄は空文字、適用されない所属はNULL、未観測金額はNULLと観測の `missing` に分ける。取り込み列へ管理値、換算、分類、検査状態を加えない。`cell_refs` と `hierarchy_refs` は原典対応参照であり、財政値をJSONへ格納しない。補助列名と金額の粒度はmetadataへ記載する。

## 再構築

repo rootから、未使用出力dirを指定する。

```bash
mise exec -- uv run --frozen --extra paddle-ocr --directory pipeline python \
  -m ingestion.fiscal.jurisdictions.132012.layouts.enterprise_statement.convert \
  --request ingestion/fiscal/observations/scan-2025-codex-2026-10-09/132012/sewer/request-002.json \
  --output ingestion/fiscal/observations/scan-2025-codex-2026-10-09/132012/sewer/candidate-NEW
```

`request-002.json` はローカル変換契約用であり正式管理JSONではない。原典・native・追加crop native・設定のSHAを検査する。候補は上書きせず、訂正も別番号候補で再構築する。`conversion.json` は表SHA・schema・metadata・金額列、`observations.json` は全セルbinding・未割当・除外ID・未観測・適用訂正を保持する。元nativeの文字・ID・座標は書き換えない。

凍結nativeからの再構築は、原典PDFからのOCR再抽出とは区別する。初回8頁と欠落80cropのnative、時間・PID・RSS・exitは同観測dirへ保存。追加OCRは外側parentのslot許可後にのみ実行し、`ocr.py` のPDF入口またはcrop入口を使う。

```bash
cd pipeline
/usr/bin/time -l mise exec -- uv run --frozen --extra paddle-ocr python \
  -m ingestion.fiscal.jurisdictions.132012.layouts.enterprise_statement.ocr \
  --source .cache/objects/fiscal/source-selection/132012/2025/settlement-2.pdf \
  --sha256 8b1475f40fb2a048d3555035769dddb338107c21618505f618d24ecff2807d36 \
  --pages 6 7 8 9 34 35 36 37 --output /absolute/unused/native-dir
```

PP-OCRv6 small、300dpi、長辺1280検出・原解像度認識、CPU10、batch6、単一context。Swiftを変更せずcompiled renderer cacheを利用する。crop入口は `--crop-request` を追加し、固定した欠落領域だけを読む。エンジンの自動切替・全頁の再読・推定補完を行わない。

`settlement-8b1475f4.json` の訂正は原典SHA・物理頁・セルbbox・元値・訂正値・主native SHA・観測IDと実native SHAに限定。横棒の `一→－`、画像で確認した資産・償却の字形、画像確認空欄を区別する。訂正候補の受容と最終合否は独立operatorが判断する。

候補002では予算額・翌年度繰越額の上位見出し、p7の法26条第2項ヘッダー、祖先を含むgrainをmetadataへ保持。27列のheader_pathには原典SHA、native SHA、頁・bbox・元観測ID/文字のbindingを付け、元文字は保持する。expenseの節は企業会計の原典見出しとして扱う。候補001とnative、旧支持snapshotは不変保持。
