# PDFの表を組み立てる共通モジュール

`pipeline/ingestion/lib/pdf_table.py` は、単語・OCR観測を同じ座標系へ配置し、書式設定に従って行・列へまとめる。階層見出しの継承と確認済みの折り返し結合も提供する。`pipeline/ingestion/lib/parquet.py` は、明示した型の表をParquetへ保存する。

原典別の抽出器から呼ぶための新しいライブラリであり、既存の抽出器には接続していない。財政科目や事業・節の意味、罫線の自動検出、折り返しかどうかの判定は呼び出し側が担当する。

変換レイヤーは、渡されたCSV/PDFを読み取り、表を組み立ててParquetへ保存する。団体・年度・会計・資料区分・補正号・歳入／歳出などの原典情報は上流から受け取り、その対応を保持する。原典の取得や情報の判定、`sources.toml`などの入力一覧の管理は上流が担当する。

## 共通処理と書式設定の分担

| 共通処理 | 呼び出し側が指定するもの |
| --- | --- |
| 単語・OCR観測の取り込み | 原典ID・物理頁、OCRの観測種別と対象領域 |
| 頁・見開きの座標合わせ | 頁ごとのcanvas ID、倍率、平行移動、入力・出力の単位 |
| 行・列の組み立て | 列境界と基準点、行の許容差または既知の行境界、文字間の区切り |
| 名称の折り返し結合 | 続きと確認した行、結合してよい列 |
| 階層の継承 | 階層の順序、確認した見出し、会計・表の終了時のリセット |
| Parquet保存 | 列名・型・NULL許可、保存先、保存する各行 |

書式の違いはまず設定で表現する。設定で対応できない規則は、書式別コードから共通関数を組み合わせる。LLMはコード・設定の作成支援に使い、各原典の取り込み実行は確定したコードで行う。

layoutの区分は年度・会計ではなく書式で決める。同じ列配置・見出し判定・階層表現なら、別年度・別会計でも同じlayoutを使う。列境界などの値の違いは設定で渡し、組み立て規則が変わる場合は別のlayoutにする。一つのPDFに複数の書式があれば、頁・表ごとにlayoutを選ぶ。会計・独立した表が切り替わる際は階層の文脈をリセットし、年度・会計自体はlayoutから推定しない。

## 入力を元の頁の座標で保持する

`Token` は原典ID・物理頁・観測ID・`raw_text`・元のbbox・単位を持つ。OCRではkind・confidence・parent IDも保持する。座標は正立した表示頁の左上原点、単位はptまたはpx。CropBox・回転の反映は抽出側で済ませる。

- `tokens_from_bbox_layout(xml, origin_id=..., first_page=...)` はPoppler XMLの単語を読む。文字単位に分割せず、同じ文字・位置の観測も黙って削除しない。
- `tokens_from_vision(result, kind=..., region_ids=..., unit=...)` は [Vision OCRモジュール](../pipeline/ingestion/lib/vision_ocr.md) の出力を読む。region・word・numberのいずれか一種類と領域を明示し、親観測と部分観測の重複を避ける。ptはPDFだけに使える。

枠のないOCR観測はbboxをNoneにして保持する。同じ原典内の観測IDが重複した入力は表の組み立て時に拒否する。異なるIDで重複印字された文字は自動削除せず、呼び出し側で原典の印字層を確認する。

## 座標を合わせて行・列を作る

`place_tokens` は `(origin_id, physical_page)` ごとの `Placement` を適用する。単位変換の倍率と見開きの位置合わせは明示し、配置後も元の頁・枠を保持する。`assemble_table` には同じcanvas・単位の観測だけを渡す。独立した頁は別canvasとして処理する。

```python
from ingestion.lib.pdf_table import Column, Placement, TableLayout, assemble_table, place_tokens

placed = place_tokens(tokens, {
    (origin_id, 109): Placement("spread-109"),
    (origin_id, 110): Placement("spread-109", offset_x=600),
})
layout = TableLayout(
    columns=(Column("name", 0, 600, anchor="left"),
             Column("amount", 600, 1200, anchor="right")),
    row_tolerance=2,
)
table = assemble_table(placed, layout)
```

上の位置・許容差はAPIの使用例であり、実際の原典向けの値ではない。列の基準点はleft・center・rightを選べる。center/leftは左境界を含み右境界を含まない。rightは左境界を含まず右境界を含む。複数列に該当する観測や列に該当しない観測は `TableResult.unassigned` に残る。

行はtop・center・bottomの基準点でまとめる。動的な行結合は先頭とのy差を許容差内に限定し、隣同士の近さが連鎖して別行まで結合するのを避ける。罫線などから行境界が分かる場合は `row_bands=(RowBand(top, bottom), ...)` を渡す。この場合は文字が取れていない行も出力する。行境界の外やbboxなしの観測もunassignedへ残す。

セルの `text` は指定したseparatorで連結した表示用文字列、元の文字と枠は `Cell.tokens` に残る。観測がないセルは `text=None, status="unobserved"`、印字された0は `text="0", status="observed"`。未検出セルが本当の空欄かは、この処理だけでは判定しない。

## 確認した折り返しと階層を反映する

`join_wrapped_rows(rows, columns=("name",))` は、呼び出し側が続きと確認した行だけを結合する。元の行番号・観測を保持し、指定外の列に複数の観測済みセルがある場合は拒否する。複数の金額を誤って連結しないため、金額列を名称の結合対象に含めない。

`HierarchyContext(("kan", "kou", "moku"))` は階層の順序を受け取り、`update(level, Heading(value, token_ids))` で見出しを継承する。親の値が変わると下位を消し、同じ値の再掲は下位を保つ。会計・独立した表が終わったら `reset()` を呼ぶ。原典のコードを含めた一意な見出し値を渡し、同名の別科目を同じ見出しとして扱わない。

`snapshot()` は現在の見出しと未確認のNoneを返す。見出しかどうかの判定、事業階層数、事業と法定節の対応は推測しない。名称の折り返しを確定してから見出しを更新する。

## 型を指定してParquetへ保存する

`write_parquet(path, records, columns=...)` はDuckDBで保存し、行数を返す。金額の型はVARCHARにし、カンマ・符号・単位を保持する。NULLと空文字、行の並び、重複も保持する。[DuckDBのParquet書き出し](https://duckdb.org/docs/current/data/parquet/overview#writing-to-parquet-files)を使用する。

```python
from ingestion.lib.parquet import ParquetColumn, write_parquet

records = ({"name": row.cell("name").text,
            "amount": row.cell("amount").text} for row in table.rows)
write_parquet(path, records,
    columns=(ParquetColumn("name"), ParquetColumn("amount")))
```

例は保存APIだけを示す。実際の取り込み表には原典ID・頁・元の座標・セル状態・階層との対応も明示して渡す。`TableResult.unassigned` と未訂正の観測を捨てず、別の観測表などとして保存してCへ渡す。Parquet保存関数は渡された列だけを保存し、これらの対応を自動生成しない。

対応する型はVARCHAR・BIGINT・INTEGER・DOUBLE・BOOLEAN。各行は全列を明示し、NULLもNoneとして渡す。型の暗黙変換・余分な列の削除は拒否する。保存は一時ファイルから新規作成し、既存ファイルの上書きと失敗時の部分出力を避ける。

## 変換結果を呼び出し側へ返す

Aの受け渡し入口は `pipeline/ingestion/selection.ts` の `prepareIngestion()`。選定情報は上流のスキーマで検査し、保存記録のSHAと呼び出し側が用意したローカル原典を照合する。対象・分冊・会計別の歳出範囲を返し、台帳を更新しない。CSVの行絞り込みやPDFの自動変換、R2取得は行わない。

新しい変換入口は `pipeline/ingestion/lib/conversion.py` に置く。`write_conversion()` は明示した行・列を `write_parquet()` で保存し、`ConversionContext` の原典ID・表ID・抽出コード・layout設定への参照と、出力の絶対パス・SHA-256・サイズ・行数を `ConversionResult` として返す。`ConversionContext.selection_ref` はAの対象への参照、`origins` は使用した原典のbucket・key・SHA・サイズの組で、`OriginReference` として渡す。原典のキーが上書きされても、どのバイト列から変換したかを保持する。ローカルの単独検証ではこの参照を省略できるが、Aからの受け渡しでは全使用原典を渡す。`dataclasses.asdict(result)` はJSONにできる辞書になる。年度・会計などは原典IDを通して管理側の情報に対応付け、変換側で推定・定義しない。

```python
from dataclasses import asdict
from ingestion.lib.conversion import ConversionContext, convert_csv, write_conversion

context = ConversionContext(origin_id, table_id, extractor_ref="csv-reader@1")
result = convert_csv(csv_path, parquet_path, context=context, encoding="utf-8-sig")
output_info = asdict(result)

# PDFは、書式別コードで組み立てた行・元の頁や座標を渡す。
pdf_context = ConversionContext(origin_id, table_id, extractor_ref="adapter@1", layout_ref="layout@1")
result = write_conversion(pdf_parquet_path, records, columns=columns, context=pdf_context)
```

`convert_csv()` はヘッダー付きCSVを読み、原典の列をVARCHARで保存する。空欄は空文字、文字列のNULLは文字列のまま保持し、数値型を推測しない。データレコードの物理行範囲を `source_line_start`・`source_line_end` として追加する。引用符内の改行も範囲に含める。追加列名は `source_line_columns` で指定でき、原典の列名との衝突・重複列名・列数不一致・不正な引用符・文字コード不一致は失敗として扱う。ヘッダーだけなら型付きの空表を作る。ヘッダーなしや前置きがある書式は呼び出し側で読み、`write_conversion()` へ明示した行・列を渡す。

PDFの観測・セル・階層の処理は既存の共通関数を組み合わせ、Parquetへの保存と出力情報の返却にこの入口を使う。一般的なPDF書式の自動選択や罫線の自動検出は、この入口の機能ではない。

非公開R2への保存は後続の対応とし、今回のコードは受け取った原典参照を保持する。提案する保存構造は [取り込み保存の設計案](prd/ingestion-storage/design-doc.md) を参照する。出力情報の永続管理・入力一覧への登録・採用は別レイヤーが担当する。既存のR2保存コード・固定入力一覧・抽出器は変更していない。

## 検証記録（2026-10-07）

- 公開APIの13テストが通過した。見開き・行結合・未割当・折り返し・階層継承・未検出と0の区別、Parquetの型・NULL・空文字・重複・上書き防止を確認した。実行は `mise exec -- uv run --frozen python -m unittest ingestion.lib.pdf_table_test`。
- 昭島市2025年度一般会計予算書の物理109頁をPopplerで実際に抽出し、124単語を新しいアダプターで読み取った。原文・物理頁・枠をParquet保存後に照合した。財政明細への意味付けを検査した結果ではない。
- 多摩市の保存済みOCR出力と手動で宣言したセル座標を使い、列ごとの107/109、再読後の109/109の金額一致を再現した。28行×4列の112セルを保存し、印字された109金額以外の3セルも観測なしのNULLとして保持した。OCRは再実行していない。原典と評価条件は [Vision OCRの検証記録](vision-ocr-evaluation.md) を参照する。

コードレビューでは型定義の重複と繰り返しの探索・集合生成を整理し、13テストを再実行した。全体の `bun run typecheck:all` も通過した。Python専用のlint・型検査設定はなく、対象Pythonファイルの構文検査を行った。

実データの確認出力はGit管理外の `.agent/pdf-table-module/` にある。[保存済みOCRの再検証コード](../.agent/pdf-table-module/verify_scan.py)、[再検証結果](../.agent/pdf-table-module/final/verification.json)、[取り込みParquet](../.agent/pdf-table-module/final/columns-with-retry.parquet)を残した。既存の抽出器・固定入力への採用と一般的なセル検出は、この検証の対象外である。

変換入口の追加後は、`conversion_test` の6テストと `pdf_table_test` の13テストが通過した。CSVのcp932・区切り文字・引用符内の改行・物理行範囲・空文字・文字列のNULL・重複・型付き空表、失敗時の部分出力防止、PDFの組み立てた行と未検出NULL、出力情報のJSON化を確認した。既存の `ingestion.inputs_test` の10テストも通過し、追加したPythonファイルの構文検査と `git diff --check` を行った。

昭島市の同じtext PDFの物理109頁を再度Popplerで抽出し、新しい `write_conversion()` で124単語の原文・頁・枠をParquetへ保存した。読み戻した全行・値の一致を確認した。[出力情報](../.agent/conversion-api/result.json)と[単語のParquet](../.agent/conversion-api/text-pdf-words.parquet)をGit管理外に残した。財政明細への意味付けやscan PDFのOCR再実行は、この追加検証に含めていない。R2操作・入力一覧の更新は行っていない。

main追従後（2026-10-07）は、保存済み選定情報の受け渡しを追加した。分冊・非連続の物理頁範囲・団体独自の会計名・text/scan指定の保持と、未保存・原典のSHA不一致・歳入のみの対象の拒否をfixtureで確認した。実R2取得・保存は未実行。
