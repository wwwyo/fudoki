# 昭島市のtext PDF予算見開き

一般会計当初予算の文字層を、測定した書式 `../budget_spread.json` と共通処理 `fiscal/layouts/statement/text_document.py` で取り込む。年度別のコードは作らない。`../budget_spread.py` は書式設定の参照を管理入口の依存ハッシュへ含めるための宣言である。

2025年度の原典SHAは `4662197051b0ec0d9c50e1690c5804d0b31e17dd7d35b972fd272e03068507f8`。469物理頁のうち、歳出明細は108–449頁（紙面104–445頁）、450頁からは給与費明細書である。選定から渡す10–11頁と18–19頁は款・項や総括の独立観測として保存し、歳出末端明細に混ぜない。

正式管理入口のconverterは `fiscal/jurisdictions/132071/layouts/text_budget/convert.py`、optionsは次の形にする。原典の会計・方向・物理頁範囲は選定から受け取り、`detail_pages` はその中の一つの連続範囲に完全一致させる。

```json
{"table_id":"akishima-text-budget-expenditure","detail_pages":[108,449]}
```

款・項・目の所属、説明内の親名称と金額、財源内訳を通常の文字列列へ展開する。独立した法定節一覧は検算用観測であり、説明末端行へコードや総額を足さない。財源内訳は目の情報として反復し、説明末端へ配賦しない。節・説明のy座標を直接結合しない。金額の桁区切り、△符号、印字0と空欄のNULLを保持し、円換算しない。

目・財源・説明は継続頁を含めて復元する。説明名称だけの行と次行の金額は、字下げと金額右端の一致で確認し、未解決の継続を末端明細にしない。予備費と、物理184頁にある目番号のない前年のみの東京都知事選挙費・市長選挙費は説明欄が空白なので、目を最小粒度の一行とし説明列をNULLにする。法定節内訳がないこれら三目の節→目は検算不可であり、0同士の一致と扱わない。

候補は新しい出力dirを指定して再生成する。正式登録・R2保存は既存 `ingestion:convert` を使い、以下の直接実行は構築・原典検査用である。

```sh
mise exec -- uv run --project pipeline python -m ingestion.fiscal.layouts.statement.text_document \
  --source .agent/pdf-samples/akishima-2025-general-initial.pdf \
  --output .agent/formal-text-pdf-ingestion/new-candidate \
  --profile pipeline/ingestion/fiscal/jurisdictions/132071/layouts/budget_spread.json \
  --pages 108 449 --observation-pages 10 11 --observation-pages 18 19 \
  --origin-sha256 4662197051b0ec0d9c50e1690c5804d0b31e17dd7d35b972fd272e03068507f8
```

`expenditure.parquet` は3590行34列、全VARCHAR（説明末端3587行と説明空白の目3行）。観測の `detail_index.parquet` は一始まりの `raw_row` と目・説明・法定節の観測IDを対応させる。観測側のID、物理頁・紙面頁・座標はrawへ混ぜない。`checks.json` のreadback検査は保存値の保持確認であり、原典に照らした階層合計の最終合否は検査担当が別途判断する。


## 独立した原典観測・保存済み候補の検査

検査コードの正本はこのdirの `inspect_origin.py`、`inspect_detail_origin.py`、`validate_candidate.py` である。構築moduleをimportせず、pdftotextの独立した原典文字・座標と保存済みParquetを読む。昭島の上記原典・頁・書式に固有であり、別の原典への一般化や全PDF共通の停止条件は未完了である。構築・修正はsubagent、候補の検査・不一致一覧・修正依頼・完了判断は親agentが担当する。

下記は2026-10-09に実行したコマンド。repo rootで実行する例で、すべての入力・出力は引数で渡す。出力dirは存在しないpathに限り、再実行では新しいpathへ替える。絶対pathを使えば別cwdでも同じ入口を実行できる。観測の `--observations` は候補に付随する検査用Parquetであり、原典から新しく生成する `--origin-observations` と区別する。`--raw` は保存済みrawを直接指定し、表IDや原典・正式登録を変更しない。

```sh
mise exec -- uv run --project pipeline python pipeline/ingestion/fiscal/jurisdictions/132071/layouts/text_budget/inspect_origin.py \
  --source .agent/pdf-samples/akishima-2025-general-initial.pdf \
  --origin-sha256 4662197051b0ec0d9c50e1690c5804d0b31e17dd7d35b972fd272e03068507f8 \
  --output .agent/inspection-code-migration/implementation-origin

mise exec -- uv run --project pipeline python pipeline/ingestion/fiscal/jurisdictions/132071/layouts/text_budget/inspect_detail_origin.py \
  --source .agent/pdf-samples/akishima-2025-general-initial.pdf \
  --origin-sha256 4662197051b0ec0d9c50e1690c5804d0b31e17dd7d35b972fd272e03068507f8 \
  --origin-observations .agent/inspection-code-migration/implementation-origin \
  --output .agent/inspection-code-migration/implementation-detail

mise exec -- uv run --project pipeline python pipeline/ingestion/fiscal/jurisdictions/132071/layouts/text_budget/validate_candidate.py \
  --source .agent/pdf-samples/akishima-2025-general-initial.pdf \
  --origin-sha256 4662197051b0ec0d9c50e1690c5804d0b31e17dd7d35b972fd272e03068507f8 \
  --raw .agent/formal-text-pdf-ingestion/r2-readback/akishima-text-budget-expenditure.parquet \
  --observations .agent/formal-text-pdf-ingestion/r2-readback \
  --origin-observations .agent/inspection-code-migration/implementation-origin \
  --detail-controls .agent/inspection-code-migration/implementation-detail/independent-detail-controls.json \
  --output .agent/inspection-code-migration/implementation-validation
```

`inspect_origin.py` は物理10–11/18–19/108–449頁のbboxと `independent-origin-controls.json` を出す。`inspect_detail_origin.py` はその原典SHA・bbox SHAを確認して `independent-detail-controls.json` を出す。`validate_candidate.py` は明示された原典SHAと独立観測の同一性を確認し、rawおよび候補観測11表（words、control_words、detail_index、moku、explanation、setsu、funding、headers、totals、context、moku_occurrences）を読む。候補dirに別のrawがあっても `--raw` で指定した表だけを検査する。出力は `validation.json` の全比較・不一致一覧と `inspection.html`、stdoutは簡潔なJSON一件である。入力不足・欠落・同一性不一致・既存出力先は終了コード2、検査の不一致・保留は1、完了は0。既存出力先は書き換えず拒否するため、終了コードとstdoutのstatusを必ず確認し、旧レポートを今回の結果と扱わない。

今回の保存済みrawはSHA `727821f4763bcc50137bb448b90a26393f9319b332145f325ddf591b85d81068` のまま。一般会計・本年度予算額・千円の全量検算は説明親子2247、末端→節819、節→目107、目→項29、項→款13、款→会計1、計3216一致・不一致0・保留0・検算不可3、会計額56,360,000千円となった。文字・原典位置・所属の不一致も0。前年度・比較・財源は文字保持までの確認であり、その金額合計を検算済みとは扱わない。検算不可3件は物理184頁の東京都知事選挙費・市長選挙費と448頁の予備費で、原典に法定節の内訳がないため理由付きで残し、全体failedにしない。反復親金額が矛盾する場合は任意の値を選ばず一覧と保留にし、非ゼロ終了する。

同じ引数で `validate_candidate.py` を `cli_checks.py` に替え、`--output` を `.agent/inspection-code-migration/implementation-cli-checks` にして実行した最小CLIブラックボックス検証は5件成功した。テストは別cwdで、合計が3216一致のままの名称変更、真の金額不一致、入力欠落、原典SHA違い、既存出力先の再利用を拒否し、raw不変を確認する。変種と検査記録は指定した新dirへだけ保存する。独立した親agentの全量検査は、この実装担当の確認とは別に行う。
