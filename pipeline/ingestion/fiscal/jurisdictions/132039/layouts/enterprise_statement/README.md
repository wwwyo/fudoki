# 企業会計の決算報告書と費用明細

`convert(inputs, destination, options)` は保存済みPDF、凍結native OCR、書式設定を受け取り、新しいローカルParquetと原典で確認したmetadataを返す。共通 `scan_ocr`、`pdf_table`、`conversion` と `fiscal/layouts/statement/text_spread` を利用する。R2、選定、正式管理JSON、dbtは変更しない。

年度・会計ごとのコード複製を行わず、支出の行帯・列境界、見開き対応、罫線の階層、継続頁、原典限定訂正を設定で渡す。別原典への適用には、その原典画像による設定と独立検査が必要。

## 今回の固定範囲

132039 武蔵野市、FY2025 水道事業会計。原典SHAは `84743fdd8cf408d7c7f9cbe4e92cdea0708cabfe2407421286eb91db93e783b0`、物理6–9・38–43の歳出側のみ。同頁上部の収入表、物理38の収益費用明細書（収入のみ）、物理42上部の収入表、物理43の空白紙は対象外。原典goldは構築入力にしない。

- `suieki_shishutsu`：税込の収益的支出、物理6–7見開き5印字行。予算各列・決算額・二つの同名繰越列・不用額・備考を分離。
- `shihon_shishutsu`：税込の資本的支出、物理8–9見開き4印字行。予算側の繰越列と翌年度繰越額（3列）を区別。
- `shuueki_hiyou_meisai`：税抜の収益費用（支出）、物理39–41の112印字行。印字区分・印字名称・原典金額と、罫線から確認した款・項・目の継承値を分離して保持。
- `shuueki_hiyou_meisai_details`：節末端行に祖先経路を展開したもの。款・項・目の所属は物理40から41へ継続する（継続頁の空欄は罫線から確認した所属の継続であり、欠落ではない）。
- `shihon_shushi_meisai` / `shihon_shushi_meisai_details`：税抜の資本的支出、物理42の28印字行。
- `statement_notes`：題名・節見出し・収入/支出の表外標識・単位注記・印字頁番号・物理8の※注記。注記の数字を財政明細の金額列へ分解しない。

金額は文字列で、カンマ・符号（△）・印字0を保持する。確認した空欄は空文字（原典SHA・native SHA・bboxにbindした宣言）、適用されない所属はNULL、未観測金額はNULLと観測の `missing` に分ける。取り込み列へ管理値、換算、分類、検査状態を加えない。`cell_refs` と `hierarchy_refs` は原典対応参照であり、財政値をJSONへ格納しない。補助列名と金額の粒度はmetadataへ記載する。

列判定は全列で観測bboxの中心を罫線の列範囲と照合する（中心anchor）。左端anchorはOCR bboxの左側paddingを左隣の項・目欄へ取り込み、節・目の所属を20箇所で誤らせたため採用しない。セル文字と注記は行の上→下、行内の左→右の印字順で結合する（`cell_text`・`note_text`、同一行の断片は直接連結、行間は列別の区切り）。未割当は罫線内で列にも行帯にも収まらないnative観測で、収入表・宣言済み除外領域とは別に全件を観測JSONへ残す。

## 再構築

repo rootから、未使用出力dirを指定する。

```bash
mise exec -- uv run --frozen --extra paddle-ocr --directory pipeline python \
  -m ingestion.fiscal.jurisdictions.132039.layouts.enterprise_statement.convert \
  --request ingestion/fiscal/observations/scan-2025-devin-max-2026-10-09/132039/water/request-NNN.json \
  --output ingestion/fiscal/observations/scan-2025-devin-max-2026-10-09/132039/water/candidate-NEW
```

`request-NNN.json` はローカル変換契約用であり正式管理JSONではない。原典・native・追加crop native・設定のSHAを検査する。候補は上書きせず、訂正も別番号候補で再構築する。`conversion.json` は表SHA・schema・metadata・金額列、`observations.json` は全セルbinding・未割当・除外ID・未観測・適用訂正を保持する。元nativeの文字・ID・座標は書き換えない。

凍結nativeからの再構築は、原典PDFからのOCR再抽出とは区別する。初回10頁と欠落cropのnative、時間・PID・RSS・exitは同観測dirへ保存。追加OCRは外側parentのslot許可後にのみ実行し、`ocr.py` のPDF入口またはcrop入口を使う。

```bash
cd pipeline
/usr/bin/time -l mise exec -- uv run --frozen --extra paddle-ocr python \
  -m ingestion.fiscal.jurisdictions.132039.layouts.enterprise_statement.ocr \
  --source .cache/objects/fiscal/source-selection/132039/2025/settlement-4.pdf \
  --sha256 84743fdd8cf408d7c7f9cbe4e92cdea0708cabfe2407421286eb91db93e783b0 \
  --pages 6 7 8 9 38 39 40 41 42 43 --output /absolute/unused/native-dir
```

PP-OCRv6 small、300dpi、長辺1280検出・原解像度認識、CPU10、batch6、単一context。Swiftを変更せずcompiled renderer cacheを利用する。crop入口は `--crop-request` を追加し、固定した欠落領域だけを読む。エンジンの自動切替・全頁の再読・推定補完を行わない。

`settlement-84743fdd.json` の訂正は原典SHA・物理頁・セルbbox・元値・訂正値・主native SHA・観測IDと実native SHAに限定。画像で確認した空欄・字形・注記本文の欠落文字を区別し、注記行の訂正も同じbinding条件で宣言する。訂正候補の受容と最終合否は独立operatorが判断する。
