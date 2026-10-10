# 原典から提供用データを構築する

現在は **ingestion → staging → intermediate → marts の完成を優先する**。配布・検索の保存先、公開方式、配布版の保持・反映手順はその後に検討する。

原典・取り込み済み Parquet は非公開 R2、コード・宣言・判断・入力一覧は Git に置く。金額・対応は [財政明細の設計](../docs/prd/fiscal-records/design-doc.md) に、個別の決定は `docs/adr/` にある。

管理中の5団体の全公開年度・全会計・当初／補正／決算の拡張は[全年度収録のPRD](../docs/prd/fiscal-coverage/prd.md)で管理する。構築成功は全公開資料の収録完了を意味しない。

## 選定済み原典から取り込みParquetを作る

Bの入口は対象別JSONと `ingestion:convert` である。まず構造と上流の選定との対応を確認する。

```bash
bun run --cwd pipeline ingestion:check
```

対象JSONは `ingestion/fiscal/jurisdictions/<団体>/<年度>/<initial|settlement|supplementary-号>/<方向>.json` に置く。型は [manifest.schema.json](ingestion/fiscal/manifest.schema.json)、配置・表の所有者等の制約は [manifest.py](ingestion/fiscal/manifest.py) が正本である。

以下の `TARGET` はpipelineからの相対パス。`LOCAL_INPUTS` は原典SHAとローカルパスの対応を持つJSON、`OUT` は新しい候補ディレクトリを指定する。すべて `pipeline/` から実行する。

```bash
bun run ingestion:originals --manifest "$TARGET" --output "$LOCAL_INPUTS" --remote
bun run ingestion:convert --manifest "$TARGET" --inputs "$LOCAL_INPUTS" --output "$OUT"
```

ローカルに原典がある場合は、SHAからファイルパスへの対応JSONを渡して `originals` を省略できる。原典の選定やURLの探索は行わない。出力は候補Parquetと候補 `manifest.json` で、Gitの管理JSONは更新しない。

ヘッダー付きCSVは変換時に原典を読み直し、原典列の名前・順序・型、全セル値、行順、空文字、重複行、物理行範囲がParquetに保持されたかを自動検査する。原典SHAは変換前後に照合する。不一致は保存前に停止し、検査で拒否した新規Parquetを除去する。成否と原典・表のSHA、成功時の行数は候補dirの `<表ID>.checks.json` に出す。原典自体の合計一致や別工程の再抽出をCSVの取り込み条件にしない。年度・会計・単位・金額段階の解釈とdbtの検査は後段で行う。PDFの共通の内容検査・合否条件は未確定である。

保存時は新しい `OUT` を指定して変換コマンドに `--remote` を付ける。全表のアップロード成功後に管理JSONを更新し、同じ対象・方向の不要表を削除する。`--conversion <ID>` で局所再処理できるが、変更しない表も現在の条件と一致し、全表が揃っている必要がある。同じ対象を並行更新しない。

保存済み表を復元する場合は次を実行する。

```bash
bun run ingestion:restore --manifest "$TARGET" --remote
```

保存後の掃除だけ失敗した場合は次を実行する。

```bash
bun run ingestion:cleanup --manifest "$TARGET"
```

CSV用と既存の見開きPDF用の入口は `fiscal/layouts/csv/` と `fiscal/layouts/statement/`。他の書式は `convert(inputs, destination, options)` と同じフォルダの `options.schema.json` を定義し、受け取った原典から表IDとローカルParquetの対応を返す。既存表の移行用 `retained` は原典から再抽出するコードではない。移動した旧抽出器のCLIはローカル候補用に残す。

管理JSONは `schema_version: 1` で、`expected_tables` は表IDだけを持つ。`inputs` は原典SHAだけを持ち、形式・会計・ページ範囲はselectionから解決する。変換設定と保存表の属性を管理し、dbt用の宣言は含めない。列名・型はParquetから取得し、管理JSONには保存しない。`options.schema.json` は変換器と同じフォルダから読む。原典の選定候補はselectionから取得し、保存完了は全表の登録で判定する。`declaration`・`definition_files`・`legacy_path` を戻すとschema検査で拒否する。

原典で確認した単位・注記・列の所属と粒度・原典内の役割の解釈は、保存表の任意項目 `tables[].metadata` に保持する。正本は [manifest.schema.json](ingestion/fiscal/manifest.schema.json)、具体例は [保存設計](../docs/prd/ingestion-storage/design-doc.md)。変換器は表IDの値としてパスだけ、または `{"path": path, "metadata": metadata}` を返す。管理側が実際のParquet列への参照を検査する。補足情報が未確認の既存表には推定で追加しない。集計方法・単位換算・共通分類は後段で扱う。

設計と失敗時の再実行は [保存設計](../docs/prd/ingestion-storage/design-doc.md)、旧表の移行範囲は [移行記録](../docs/prd/ingestion-storage/migration.md)、CSV・text PDF・scan PDFの作業は [ingestion手順](../.agents/skills/pipeline/references/ingestion.md) を参照する。

## 自治体の取り込みJSONとParquetを後段へ渡す

Cの入口は `ingestion/fiscal/jurisdictions/<団体>/<年度>/<資料区分>/<方向>.json`。別の `sources.json`・`history.json`、宣言ディレクトリ、Bの検査の再実行は要求しない。

```bash
bun run pipeline:inputs
```

入力準備だけを確認する場合は `pipeline/` で実行する。

```bash
uv run python -m build_inputs prepare --manifest <対象JSON>
```

`pipeline:inputs` は対象別JSONに登録されたParquetをprivate R2から復元する。`build_inputs prepare` はネットワークを使わず、管理JSON全体・selectionから解決した原典情報・C側の配置対応・Parquetを `.cache/inputs/<入力fingerprint>/` に固定する。表・原典・対象の対応は `catalog.json`、dbtへの表は `raw/` に保存する。表のSHA・サイズと準備中の参照変更を検査し、再利用時も照合する。catalogは再生成可能なローカル入力一覧であり、GitやR2へ保存する別の管理情報ではない。

既存表のdbt用partitionは `dbt/inputs/<団体>/<年度>/<資料区分>/<方向>.json` が表IDごとに保持する。項目は `table_id` と `raw_path` だけ。型は [bindings.schema.json](dbt/inputs/bindings.schema.json)、検査は `bun run --cwd pipeline dbt:inputs:check`。管理値 `initial` は既存dbtの `document_kind=budget` に対応する。

Cは `bun run pipeline:build` で構築する。旧 `sources.json`・`history.json` の直接読み取りと、その依存先の381モデル・5検査は削除した。旧JSONの存在を要求する構築前の停止処理も削除した。残った152モデルは既存のdbt設定・Parquet・共通マスタを使う。単位・金額段階・階層の解釈を一律にBの別ファイルへ要求しない。

`--manifest <対象JSON>` は入力範囲だけを指定し、モデルの実行範囲は自動で絞らない。構築成功時は `.build/builds/<構築ID>/` にCSVを保存し、同じ構築IDの再実行ではハッシュを照合する。旧処理で生成した全202CSVが残ったモデルで再生成されるとは扱わない。原典・取り込みParquetを削除する操作ではなく、旧モデルと検査の廃止である。

## ローカルで原典との対応を確認する

決算の事業×歳出の節の集約は `fiscal_settlement_expenditure_setsu_lines` と団体別 `settlement_expenditure_setsu.csv` で提供する。支出済額だけを集約し、`account_path_json`・`dimensions_json`・`details_json` から経路・追加区分・原典行の内訳を辿れる。節や分類の対応を確認できない行は `origin_line` のまま残す。原典行の `settlement_expenditure.csv` と集約CSVは同じ実績の別の表現なので、両方の金額を足さない。全公開年度の収録・検査の完了は全年度収録のPRDで管理する。

```bash
bun run dev                  # 原典・dbt の検証画面、127.0.0.1:5174
```

PDF 閲覧レイヤは `.cache/pdf/`、報告は `.build/report/` に置く。系統は dbt の `manifest.json` から生成する。原典の行・頁、取り込み表、提供用データの対応と注意点を確認する。

## 検査する

`bun run --cwd pipeline sources:plan --json` は `ingestion/fiscal/management/sources.json` に登録した有効な取り込み宣言を表示する。原典選定の手順は [pipeline skill](../.agents/skills/pipeline/references/source-selection.md) を参照する。

公開資料の収録範囲は `bun run --cwd pipeline coverage:fiscal --json` で、原典一覧のスキーマ、現在の入力一覧と原典宣言、現行コード・入力に対応する全量buildとCSVハッシュを照合する。`--require-complete` は未収録・未検証・探索未完了があれば終了コード2を返す。`--limit` は表示件数だけを変え、完了判定の母集団は変えない。原典一覧に保存された過去の採用・marts状態だけでは完了にしない。

```bash
bun run test
bun run typecheck:all
bun run --cwd pipeline test:python
```

検証画面の E2E はローカル専用の `bun run test:e2e` に統一し、CI では実行しない。
固定入力と PDF レイヤの準備・検査範囲は [E2E の手順](../tests/README.md) を参照する。

まず staging の1対1・原典の値と単位の保持、intermediate の単位換算・分類・連結判断、marts の件数・金額・識別子と上流の対応を確認する。小さな fixture の成功と固定原典を使った全量 build の成功を区別する。

CI の全量 job は `FUDOKI_FIXED_INPUTS_READY=true` と非公開入力の読取権限がある場合だけ動く。固定入力からの build・再構築・報告を検査する。収録範囲と未完了項目は [全年度収録のPRD](../docs/prd/fiscal-coverage/prd.md) で管理する。

## 旧入力一覧を使う互換経路

新しいBの保存情報は対象別JSONに置く。旧検査・監査の固定入力はschemaVersion 3の `sources.lock.json` で原典・Parquetのハッシュ、保存先、source宣言を管理する。候補抽出は `inputs.lock.json` を生成し、provenanceの別ファイルは生成・復元しない。行数・型はParquetから読み、検査結果は再生成するレポートへ出す。`uv run python -m ingestion.inputs describe` で現在の入力宣言と表の情報を確認できる。

## 宣言と再生成する検査結果の保存

| 保存対象 | 置き場と更新方法 |
| --- | --- |
| `sources.json` | Git。既存の取り込み宣言と固定入力・収録監査が参照する原典情報。構造は [sources.schema.json](ingestion/fiscal/management/sources.schema.json) を参照する。 |
| `sources.lock.json`、原典別の宣言・ハッシュ一覧 | Git。採用した版と取り込み表、コード・訂正の対応を固定する入力。旧検査・監査の互換入力であり、新しいCの入力採用には使わない。コードを変更した場合は、参照する宣言のハッシュも更新し、原典・表・財政値を変えていないか差分を確認する。 |
| 転記・セル台帳の JSON | 原典の画像から確認した訂正や、採用済みの明細と原典位置を結ぶ宣言は Git。原典だけから同じ判断を自動生成できるとは扱わない。宣言が参照するPDF・画像・文字観測のバイト列は非公開 R2。 |
| dbt、CSV、検証報告、実行時の比較結果 | 再生成する検査結果は `.build/`、試作・未採用の比較結果は `.agent/`。生成した全量DB・CSVや作業記録をGitへ追加しない。構築・再構築・`pipeline:report`・`coverage:fiscal --json` の結果と対象headをPRのQA欄で記録する。 |

大きなJSONでも、原典の版・判断の根拠を固定する宣言は保持する。レビューでは対象の原典・年度・会計・表を絞り、ハッシュ更新と財政内容の変更を分けて確認する。宣言の分割や重複削減は、参照先とハッシュの移行を伴うため、今回の停止時点を保存した後の課題とする。

多摩の2019〜2020年度通常履歴は、原典・取り込み表に加えて、検証時のリポジトリ位置とPython・DuckDB・Popplerの実体を固定している。この経路は検証済みのローカル環境で再構築し、現状の宣言のままで別worktreeやCIへ移設できるとは主張しない。環境を変更する場合は、原典と表の同一性を保持した宣言の更新と、変更後の全量構築・再構築の確認が必要である。
