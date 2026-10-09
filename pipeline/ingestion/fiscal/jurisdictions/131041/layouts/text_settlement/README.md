# 新宿区の text 決算書

原典 SHA `ca3f8658f6dbe295978db484227ec1c7adbdc15eeb136f109fa406798511c1eb` の一般会計歳出、物理3頁と65–147頁で測定した書式。原典1頁に「令和７年度新宿区一般会計歳入歳出決算事項別明細書総括」と印字されている。処理範囲は管理側から渡された selection の一般会計 scope と照合する。同じ冊子の特別会計は処理しない。

`convert.py` は Poppler の `pdftotext -bbox-layout` の単語から、右揃えの金額欄と番号の印字位置を読み取る。名称の印字上の折り返しは改行として保持する。金額のカンマと、数値の前の別行に印字された `△` は文字列として保持する。座標は PDF の左上を原点とするポイント、物理頁は1始まり。対象頁には印刷頁番号がないため、その列を作らない。

## 正式rawとローカル検算観測

- `general-expenditure-detail` が唯一の正式raw。備考の `001` 等の事業番号・名称・金額を一行にする。同じ高さにある節との関係は作らない。931事業明細と内訳のない予備費の目1行、計932行。
- `shinjuku-observations/general-summary.parquet` は物理3頁の13款と歳出合計を保持するローカル検算観測。各予算現額欄、支出済額、3種類の翌年度繰越額、不用額を保持する。歳出合計行は `款_番号` が NULL。
- `shinjuku-observations/general-setsu.parquet` は法定節欄の区分と金額・支出済額・翌年度繰越額・不用額を保持するローカル検算観測。総括と法定節は converter の返却表一覧と正式manifestに含めず、正式R2保存の対象にしない。

正式明細には、確認した所属の款・項・目の番号・名称、各親の8金額欄、備考、翌年度繰越額の区分、物理頁と縦座標を通常の scalar 列へ展開する。親の名称・金額は葉ごとに反復する。番号付きの備考がない目は、目の原典粒度の一行にし、葉の番号・名称・金額は NULL とする。予備費を推定の節や金額0の事業へ変換しない。

総括に独自の印字がある継続費逓次繰越・繰越明許費・事故繰越しは、款の番号と名称が明細と一致することを確認し、正式明細の `款_継続費逓次繰越`・`款_繰越明許費`・`款_事故繰越し` に反復する。その原典位置は `款_総括_物理頁`・`款_総括_上端`・`款_総括_下端` に保持する。総括の歳出合計は独立検算観測に残す。

親の備考には議決等の印字注記がある。「前年度繰越事業費不用額」とその金額は親の `備考_注記名称`・`備考_注記金額` にも分離して保持する。目の備考欄の流用注記は `備考_流用注記名称`・`備考_流用注記金額` に分離して保持し、同じ高さにある節に結合しない。これらの注記額は支出済額の内訳ではない。単位・印字の所属・粒度は管理 JSON の `tables[].metadata` へ返す。正式明細の `備考_金額` と反復した親金額・繰越区分額、独立した法定節一覧は相互に加算しない。

## 通常 CLI

`pipeline/` から実行し、SHA から復元済み PDF の絶対パスへの対応 JSON と、未使用の出力先を渡す。

```sh
bun run ingestion:check --manifest ingestion/fiscal/jurisdictions/131041/2025/settlement/expenditure.json
bun run ingestion:convert \
  --manifest ingestion/fiscal/jurisdictions/131041/2025/settlement/expenditure.json \
  --inputs ingestion/fiscal/observations/131041-settlement/builder-inputs.json \
  --output ingestion/fiscal/observations/131041-settlement/new-candidate
```

候補の `shinjuku-observations/` に全対象の Poppler 単語観測、親欄の観測 JSON、総括・法定節の検算用Parquetを残す。候補manifestの `tables` は正式明細1表だけ。構築器の動作確認を独立検査の代わりにしない。保存の可否、別経路の原典照合、各階層の比較と不一致一覧、R2 保存は検査 operator が担当する。

## 独立検査

`inspect_origin.py` は macOS PDFKit の列領域選択から原典を観測する。Poppler の構築観測・構築 module は利用しない。Swift helper は `xcrun swift` で実行する。原典の SHA、物理1頁の年度・一般会計表記、明細83頁の円表記を確認する。

repo root から実行する。`--output` の観測 directory と検査 JSON は未使用の場所を指定する。

```sh
mise exec -- uv run python pipeline/ingestion/fiscal/jurisdictions/131041/layouts/text_settlement/inspect_origin.py \
  --pdf pipeline/ingestion/fiscal/observations/131041-settlement/origin.pdf \
  --output pipeline/ingestion/fiscal/observations/131041-settlement/new-inspection
mise exec -- uv run python pipeline/ingestion/fiscal/jurisdictions/131041/layouts/text_settlement/validation.py \
  --origin pipeline/ingestion/fiscal/observations/131041-settlement/new-inspection/origin.json \
  --candidate pipeline/ingestion/fiscal/observations/131041-settlement/new-candidate \
  --output pipeline/ingestion/fiscal/observations/131041-settlement/new-validation.json
```

検査は正式明細1表の Parquet を読み戻す。総括・法定節は PDFKit の独立原典観測から検算し、事業明細の集計と区別する。候補のローカル検算表も照合する場合は `--controls <候補dir>/shinjuku-observations` を付ける。R2 GET の正式明細1表だけでも検査できる。全親・全葉の文字、金額、所属、親の原典位置、注記と繰越区分を独立観測と照合する。親の反復値が一致することを確認し、所属経路ごとに一度だけ数え、独立法定節→目、備考→目、目→項、項→款、款→総括、総括→歳出合計を検算する。親の8金額欄、節の4金額欄、総括の10金額欄を検査し、備考の支出実績と前年度不用額・流用注記を分ける。文字比較は PDF の空間的な空白・折り返しを除いて文字の順序を照合し、raw の文字列は書き換えない。

不一致・保留があれば非ゼロ終了する。原典に節・備考の内訳がない予備費は、節の4金額列と備考支出実績の5比較を理由付きの検算不可とする。検算不可を印字ゼロの葉へ置き換えない。検査の詳細は指定した JSON に出す。検査 code は原典・候補 Parquet・管理 JSON を書き換えず、観測と検査結果だけを新しく作る。
