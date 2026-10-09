# PDFの表を組み立てる共通モジュール

`pipeline/ingestion/lib/pdf_table.py` は、単語・OCR観測を同じ座標系へ配置し、書式設定に従って行・列へまとめる。階層見出しの継承と確認済みの折り返し結合も提供する。`pipeline/ingestion/lib/parquet.py` は、明示した型の表をParquetへ保存する。

原典別の抽出器から呼ぶための新しいライブラリであり、既存の抽出器には接続していない。財政科目や事業・節の意味、罫線の自動検出、折り返しかどうかの判定は呼び出し側が担当する。

変換レイヤーは、渡されたCSV/PDFを読み取り、原典の表を復元してrawのParquetへ保存する。団体・年度・会計・資料区分・補正号・歳入／歳出などの対象情報は上流から受け取り、その対応を管理情報として保持する。対象情報を固定値の財政データ列として追加せず、原典の値の共通形式への正規化は後段で行う。印字された年度・会計・方向は原文として残す。原典の取得や情報の判定、`sources.toml`などの入力一覧の管理は上流が担当する。

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
- `tokens_from_ocr(result, kind=..., region_ids=..., unit=...)` は [共通OCR入口](../pipeline/ingestion/lib/scan_ocr.md) のPaddle・Apple Visionの出力を読む。region・word・numberのいずれか一種類と領域を明示し、親観測と部分観測の重複を避ける。ptはPDFだけに使える。既存の `tokens_from_vision` も同じ処理の入口として残す。

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

## 見開きtext PDFの取り込み構造（2026-10-09）

`project_raw_tables()` は内部の構築・検査用に目・財源内訳・法定節・説明欄を独立して取り出す。後段に渡す `assemble_raw_expenditure()` は、説明欄の確認済みの末端19行に目と各階層の名称・金額を展開した一つの表を作る。法定節一覧の区分・金額と継続中の1項目は検査用の観測に残し、末端明細へ追加しない。財源内訳は目の文脈であり、細目への配分額を作らない。

Parquetは全列VARCHARで、名称・金額は原典の文字列またはNULLを保持する。説明欄は `説明1_名称`・`説明1_金額` から第3階層まで通常の列へ展開する。その他の総額は原典の `その他` 列に残し、財源内訳の項目も `その他_内訳1_名称`・`その他_内訳1_金額` のように通常の列へ展開する。財源項目が複数でも列を増やし、末端行との直積を作らない。JSON・配列・STRUCT列は後段への明細に使わない。生成した原典行IDは観測と検査に留め、明細には含めない。列の粒度は款・項・目と説明の名称の階層経路で示す。現在はこの経路で対象を識別できる確認済み範囲に限定する。

階層番号と名称・金額を区別する列名は取り込み時の補助名であり、原典に印字された見出しと区別する。`raw_expenditure_metadata()` は単位・注記・原典見出しへの対応・列の粒度を管理JSONの `tables[].metadata` に受け渡せる形で返す。展開列の `header_path` は原典の見出し「説明」などを含む。この書式で確認した「説明の第1階層は事業・経費のまとまり」「第2階層は歳出の節」という解釈は、それぞれ `column_contexts[].semantic_role: project` と `setsu` に保持し、rawの列名を節へ変更しない。法定節一覧のコード・総額を説明内の印字値の代わりに使わない。共通分類・単位換算はここへ追加しない。`verify_raw_expenditure()` は観測を原典XMLと照合し、保存後の全値・行順・所属・階層とmetadataの解釈を検査する。単語・ヘッダー・頁・座標は内部の観測表に残す。抽出元の欄と末端確認の状態を示す `_source_region`・`_scope_end` は明細列へ入れない。欄への対応はmetadata、範囲の終了状態は観測の `closure` と検査結果の未完了項目で扱う。

`pipeline/ingestion/fiscal/layouts/statement/text_spread.py` は、既存の単語・表構築・Parquet保存を組み合わせて、渡された2ページの取り込み構造を作る。旧 `statement/convert.py` の出力や採用済み入力は変更しない。書式設定は `fiscal/jurisdictions/132071/layouts/budget_spread.json` に置く。現在の適用範囲は、昭島市2025年度当初予算の物理108–109頁で確認した書式であり、見開きの先頭で1つの目が始まる場合に限定する。

- 原典からヘッダー・単位を取り、複数段の親子関係と範囲を保持する。設定は期待する印字文字と座標を宣言し、出力値は取得した原文を使う。本文列が対応するヘッダーの範囲内にあることと、保存後のヘッダー・単位・セル対応も検査する。
- 内部の観測は目の金額・財源、財源の内訳、法定節一覧、説明欄に分けて検査する。後段へは確認済みの所属と原典階層経路を組み込んだ一つの明細表を渡す。この確認済み書式では説明内の中段見出しが節を表すため、検査で当該目の節一覧の名称・コードへ一意に対応させる。明細には説明内の名称・金額を保持し、中段が節であるという解釈をmetadataへ持たせる。単に同じ高さの行を結合せず、事業・節・細目の親子関係から説明の経路を構築する。節一覧の区分・金額は検査用に留め、末端行の説明内の金額を法定節総額へ置き換えない。
- 節名称の折り返しを結合し、元の印字行・単語を保持する。説明欄の階層は名称の字下げと金額の右端を合わせて判定する。範囲末尾の未完の階層は `open_at_scope_end` とし、葉や完結した内訳とは断定しない。
- 款・項の原文、物理頁、印刷頁を区別して保持する。原文・位置は観測表に残し、本文・ヘッダー・文脈の全単語が各原典セルに一度ずつ属することを、Parquetを読み戻して確かめる。
- 検査用にだけ金額を数値化し、目と節合計、財源合計、比較額、閉じた説明階層の内訳を照合する。独立した節一覧と説明欄を足し合わせない。継続中の階層の検算は保留する。原典の不整合は `mismatch` として報告し、保存した原文を書き換えない。

ローカル検証の入口（`pipeline/` から実行）:

```sh
mise exec -- uv run python -m ingestion.fiscal.layouts.statement.text_spread \
  --source ../.agent/pdf-samples/akishima-2025-general-initial.pdf \
  --profile ingestion/fiscal/jurisdictions/132071/layouts/budget_spread.json \
  --pages 108 109 \
  --origin-sha256 4662197051b0ec0d9c50e1690c5804d0b31e17dd7d35b972fd272e03068507f8 \
  --output ../.agent/text-pdf-spread-pilot/structured-new
```

これは過去の固定入力を用いたローカル変換である。現在の選定対象への採用・R2保存・dbt接続は行わない。出力表と検査結果はGit管理外に生成し、専用のprovenanceファイルは作らない。出力先は新規ディレクトリを指定する。

2026-10-08のこの見開きの確認では、目1行・財源内訳1行・法定節12行・説明欄36項目を構築した。取得した178語（本文119語、ヘッダー・単位40語、款・項・頁番号など19語）に欠落・重複使用はなかった。金額照合19件が一致し、末尾で開いている説明階層2件は対象範囲の終端として保留した。これは全文書の収録完了や、他のページにも設定をそのまま適用できることを示す結果ではない。

2026-10-09に同じ目「1 議会費」の続き（物理111・113頁、紙面107・109頁）を含めて確認した。説明欄の事業内の中段見出しは節名称と対応し、その金額を目・節ごとに合計すると、左側の法定節12区分すべての金額と一致した。例えば報酬は141,600＋3,413＝145,013、需用費は199＋1,242＋4,635＝6,076。これは当該目の説明欄を「事業→節→細目」と読める根拠であり、すべての説明欄を名前だけで節へ自動対応させる根拠ではない。再実行は `.agent/text-pdf-spread-pilot/check_setsu_breakdown.py`、結果は同dirの `setsu-breakdown.checks.json`（いずれもローカル試作）で確認できる。

この確認後も、印字の同じ高さの行を結合しない原則は変わらない。節一覧は目×節の集計、説明欄は目×事業×節×細目、財源内訳は目×財源の分解である。説明側を目×節へ集約してから法定節一覧と照合する。原典に細目ごとの財源配分がなければ財源を細目へ割り当てない。説明の末端を行にする構築では説明内の確認済み節見出しを保持できるが、法定節の検算用の区分・金額を末端明細に入れず、境界で継続中の項目を葉と断定しない。`assemble_raw_expenditure()` はこの確認を反映して、説明の確認済みの末端項目だけを行にする形式へ変更した。継続中の境界項目は検査結果に構築待ちとして示す。現在の適用範囲外で、節の対応が曖昧な説明を名前だけで結合することはしない。保存した19行の原文・所属・親経路・単位を再検査し、節の取り違え・財源の誤配分・継続中の項目を末端扱いする変更など11種類の破損を拒否した。
