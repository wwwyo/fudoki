# 目黒区 text PDF 決算歳出

`convert.py` は一般会計歳出の物理42–91頁（事項別明細）をPopplerの`-bbox-layout`から組み立てる。測定した頁幅は1190.55pt、左上原点。対象の団体・資料区分・会計・方向・選定された全頁範囲が異なる入力では停止する。総括の物理8–10頁と事項別明細末尾の歳出合計は、検査operatorの独立原典観測で検算に用い、正式rawや追加の候補表には出力しない。

原典では法定節が最細明細で、事業別の説明欄はない。正式rawは`general-setsu`の1表866行60列を保持する。

款・項・目の予算現額5列、支出済額、繰越3列、不用額、備考を所属経路として展開する。節には金額（予算現額）、支出済額、繰越3列、不用額と備考を持たせる。

金額は桁区切り・△を含む原表記の文字列。円は原典の欄見出しから管理JSONのmetadataへ記録する。節の名称・備考の折り返しは改行で残す。款・項・目の金額は反復されるので、原典の所属経路ごとに一度だけ数える。11款・38項・117目の経路を保持する。

本文の最初の折り返し行は通貨見出し直下、番号・金額行より6.7pt上にある。科目名の3行目は節の番号行と同じ高さになり得るため、科目欄自身の次の科目行までを名称範囲とする。備考の開始は番号・金額行より6.7pt上で、次の行の備考開始までを同一の印字所属として保持する。予備費の「0△181,846,590」は2欄に跨がるPoppler単語であり、測定した305pt境界と印字文字から分離する。

## 再構築

`pipeline/`をcwdにし、保存済み原典のSHAと絶対パスを対応させたJSONを渡す。出力先には未使用のディレクトリを指定する。

```sh
bun run ingestion:convert \
  --manifest ingestion/fiscal/jurisdictions/131105/2025/settlement/expenditure.json \
  --inputs .cache/meguro-2025-settlement-inputs.json \
  --output .cache/meguro-2025-settlement-candidate-new
```

入力原典のSHAは`f519167e438c0ee25e1cfcae0d3c940e748002a02929c893cb727cb3fa8594fb`。通常CLIが原典SHA・scope・管理構造を検査する。変換器の`meguro-observations/parents.json`とbbox HTMLは再生成可能な構築観測であり、独立検査の合格根拠として扱わない。

独立した原典観測と保存候補の内容照合・階層合計検査、最終判断は検査operatorが担当する。変換器はR2・管理JSONを更新しない。

## 独立した原典観測と候補検査

`pipeline/`をcwdにして実行する。`PDF`は保存済み原典、`CANDIDATE`は通常CLIが生成した候補ディレクトリ。各出力には未使用のディレクトリを指定する。

```sh
PDF=.cache/objects/fiscal/source-selection/131105/2025/settlement.pdf
LAYOUT=ingestion/fiscal/jurisdictions/131105/layouts/text_settlement
ORIGIN=.cache/meguro-origin-new
REMARKS=.cache/meguro-remarks-new
CANDIDATE=.cache/meguro-2025-settlement-candidate-new
CHECKS=.cache/meguro-checks-new
SMOKE=.cache/meguro-smoke-new

uv run python "$LAYOUT/inspect_origin.py" \
  --pdf "$PDF" --output "$ORIGIN"
uv run python "$LAYOUT/inspect_remarks.py" \
  --pdf "$PDF" --origin "$ORIGIN/origin.json" --output "$REMARKS"
uv run python "$LAYOUT/validate_candidate.py" \
  --pdf "$PDF" --origin "$ORIGIN/origin.json" \
  --remarks-origin "$REMARKS/remarks.json" \
  --candidate "$CANDIDATE" --output "$CHECKS"
uv run python "$LAYOUT/validation_smoke.py" \
  --pdf "$PDF" --origin "$ORIGIN/origin.json" \
  --remarks-origin "$REMARKS/remarks.json" \
  --candidate "$CANDIDATE" --output "$SMOKE"
```

検査コードは構築moduleを使用せず、原典から別の規則で観測する。金額は原表記文字列の完全一致、名称・備考は非空白文字の一致を検査し、画像罫線から備考の所属を確認する。

同書式の介護保険特別会計には `inspect_origin.py --summary-pages 138 139 --detail-pages 150 159` を指定する。備考観測はこの独立観測の範囲を読み、`validate_candidate.py` と `validation_smoke.py` には `--table-id long-term-care-setsu` を渡す。引数省略時の一般会計の範囲・表IDは維持する。名称に含む全角数字（例「第１号被保険」）は金額行として除外しない。
