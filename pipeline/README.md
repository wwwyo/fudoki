# 原典から提供用データを構築する

現在は **ingestion → staging → intermediate → marts の完成を優先する**。配布・検索の保存先、公開方式、配布版の保持・反映手順はその後に検討する。

原典・取り込み済み Parquet は非公開 R2、コード・宣言・判断・入力一覧は Git に置く。金額・対応は [財政明細の設計](../docs/prd/fiscal-records/design-doc.md) に、個別の決定は `docs/adr/` にある。

管理中の5団体の全公開年度・全会計・当初／補正／決算の拡張は[全年度収録のPRD](../docs/prd/fiscal-coverage/prd.md)で管理する。構築成功は全公開資料の収録完了を意味しない。

## 固定入力から構築する

ツールは root の mise、依存は Bun と uv で管理する。Python は3.13。

```bash
mise install
bun install --frozen-lockfile
uv sync --frozen
bun run pipeline:inputs
bun run pipeline:build
bun run pipeline:build --rebuild
```

`pipeline:inputs` は ingestion の `sources.lock.json` が指定する原典・表を R2 から復元し、入力一覧が固定する原典・Parquetのハッシュを照合する。復元先は `.cache/inputs/<入力一覧のhash>/raw/`。必要な入力が欠けた場合は停止し、自治体サイトの最新版で補わない。

`build.ts` は復元済みの固定入力を使い、ネットワークなしで dbt の変換・検査と marts の CSV 生成を実行する。結果は `.build/builds/b-<内部構築ID>/` に入る。毎回 `.build/workspace/` を作り直して生成し、同じ構築 ID が既にある場合は CSV のハッシュを照合する。`--rebuild` でも同じ検査を行う。`.build/warehouse.duckdb` は検証画面用の再生成可能な DB である。

財政の表は `dbt/models/marts/records/`、団体別 CSV は `dbt/models/marts/csv/` で定義する。任意の FDP descriptor 整形は `bun run pipeline:fdp` で実行できる。公開 web・API・MCP・docs は一時的に HTTP 500 を返す。

千代田区の当初予算は右頁の事業別説明と左頁の目×節別内訳が独立した分解になっている。
左頁の観測は `statement-moku-setsu/` の固定入力から `fiscal_initial_expenditure_moku_setsu` と
`131016/initial_expenditure_moku_setsu.csv` へ渡す。粒度は `independent-moku-setsu` で、
原典の節コード・名称・金額・頁・bboxを保持する。`explanation_dataset_id` は同じ原典の
事業別説明datasetへの参照で、事業×節の対応を表さない。両CSVの金額を足し合わせない。
原典に節がない目を補完せず、原典に印字された範囲を保持する。

2026-10-04のPDF拡張では新規45会計年度90方向表と上記16側表を固定入力へ追加した。
従来106入力はそのバイト列・識別子を維持し、既存一般会計に `table=fund-general` を
重複採用していない。新規表だけ dataset/明細IDに表IDを追加する。年度・会計・頁・公式URLと
文字層の不備による未採用範囲は各団体の取り込みノートを参照する。全体buildの完了とは別である。

提供モデルは決算・当初予算・変更・対応を分ける。決算明細は実績の `amount` 一つを持ち、歳出の COFOG コード・状態・根拠は明細・変更と同じ CSV に含める。歳出の分類は当面 COFOG のみとし、GFSM は提供しない。歳出の当初予算は確認できた対象を事業×歳出の節へ集約し、節の参照は `expenditure_setsu_id`（`fiscal_expenditure_setsu_master`）、節より下の内訳と原典行の対応は `details_json` に保持する。対応を確認できない行は原典行の粒度（`line_granularity = origin_line`、`expenditure_setsu_id = NULL`）で残す。原典の節コード・名称は取り込み・内部検証と `details_json` の内訳経路に残し、歳入の節は財源の内訳として保持する。規則ファイル・規則 ID は公開しない。原典の複数金額列は取り込み表と候補の `internal/fiscal/` に残し、公開する実績と混在させない。

狛江市2023年度一般会計の商工業振興費・予備費は、当初2件・補正3件・決算との集合対応10件を収録している。第1〜7号の採用版と適用日を保持し、当初＋補正の小計と決算書の報告予算現額の差を内部検証報告に残す。目単位であり歳出の節への対応は未確認。繰越・充用・流用と他対象の変更は未収録なので、datasetの `coverage_json.budgetHistory` は `unconfirmed` とする。詳細は [補正予算の設計](../docs/prd/fiscal-budget-history/design-doc.md) を参照。

歳出の節マスタ `fiscal_expenditure_setsu_master` と事業×歳出の節への集約は実装済みである。節マスタは `packages/fiscal/setsu-master.ts` の Git 定義（地方自治法施行規則 別記の現行28区分と改正前の旧体系・適用期間つき）から生成し、原典の節名称との対応は `pipeline/dbt/seeds/fiscal/expenditure_setsu_map.csv` に宣言する。集約の規則は `int_expenditure_setsu_lines`・`int_expenditure_setsu_groups` が正本であり、同じ経路・追加区分・節で分類（COFOG・連結判断）を共有する末端行だけをまとめる。契約と検査条件は [財政データの設計](../docs/prd/fiscal-records/design-doc.md) を参照。

## ローカルで原典との対応を確認する

決算の事業×歳出の節の集約は `fiscal_settlement_expenditure_setsu_lines` と団体別 `settlement_expenditure_setsu.csv` で提供する。支出済額だけを集約し、`account_path_json`・`dimensions_json`・`details_json` から経路・追加区分・原典行の内訳を辿れる。節や分類の対応を確認できない行は `origin_line` のまま残す。原典行の `settlement_expenditure.csv` と集約CSVは同じ実績の別の表現なので、両方の金額を足さない。全公開年度の収録・検査の完了は全年度収録のPRDで管理する。

```bash
bun run dev                  # 原典・dbt の検証画面、127.0.0.1:5174
```

PDF 閲覧レイヤは `.cache/pdf/`、報告は `.build/report/` に置く。系統は dbt の `manifest.json` から生成する。原典の行・頁、取り込み表、提供用データの対応と注意点を確認する。

## 検査する

`bun run --cwd pipeline sources:plan --json` は `ingestion/fiscal/sources.json` に登録した有効な取り込み宣言を表示する。原典選定の手順は [pipeline skill](../.agents/skills/pipeline/references/source-selection.md) を参照する。

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

## 入力一覧の形式

固定入力はschemaVersion 3の `sources.lock.json` で原典・Parquetのハッシュ、保存先、source宣言を管理する。候補抽出は `inputs.lock.json` を生成し、provenanceの別ファイルは生成・復元しない。行数・型はParquetから読み、検査結果は再生成するレポートへ出す。`uv run python -m ingestion.inputs describe` で現在の入力宣言と表の情報を確認できる。

## 宣言と再生成する検査結果の保存

| 保存対象 | 置き場と更新方法 |
| --- | --- |
| `sources.json` | Git。既存の取り込み宣言と固定入力・収録監査が参照する原典情報。構造は [sources.schema.json](ingestion/fiscal/sources.schema.json) を参照する。 |
| `sources.lock.json`、原典別の宣言・ハッシュ一覧 | Git。採用した版と取り込み表、コード・訂正の対応を固定する入力。`pipeline:inputs` はその指定を復元する処理であり、公開サイトの現在の内容から一覧を書き直す処理ではない。コードを変更した場合は、参照する宣言のハッシュも更新し、原典・表・財政値を変えていないか差分を確認する。 |
| 転記・セル台帳の JSON | 原典の画像から確認した訂正や、採用済みの明細と原典位置を結ぶ宣言は Git。原典だけから同じ判断を自動生成できるとは扱わない。宣言が参照するPDF・画像・文字観測のバイト列は非公開 R2。 |
| dbt、CSV、検証報告、実行時の比較結果 | 再生成する検査結果は `.build/`、試作・未採用の比較結果は `.agent/`。生成した全量DB・CSVや作業記録をGitへ追加しない。構築・再構築・`pipeline:report`・`coverage:fiscal --json` の結果と対象headをPRのQA欄で記録する。 |

大きなJSONでも、原典の版・判断の根拠を固定する宣言は保持する。レビューでは対象の原典・年度・会計・表を絞り、ハッシュ更新と財政内容の変更を分けて確認する。宣言の分割や重複削減は、参照先とハッシュの移行を伴うため、今回の停止時点を保存した後の課題とする。

多摩の2019〜2020年度通常履歴は、原典・取り込み表に加えて、検証時のリポジトリ位置とPython・DuckDB・Popplerの実体を固定している。この経路は検証済みのローカル環境で再構築し、現状の宣言のままで別worktreeやCIへ移設できるとは主張しない。環境を変更する場合は、原典と表の同一性を保持した宣言の更新と、変更後の全量構築・再構築の確認が必要である。
