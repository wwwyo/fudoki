# 原典から提供用データを構築する

現在は **ingestion → staging → intermediate → marts の完成を優先する**。配布・検索の保存先、公開方式、配布版の保持・反映手順はその後に検討する。

原典・取り込み済み Parquet は非公開 R2、コード・宣言・判断・入力一覧・証跡は Git に置く。全体設計は [monorepo の設計](../docs/prd/monorepo/design-doc.md)、金額・対応は [財政明細の設計](../docs/prd/fiscal-records/design-doc.md) にある。

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

`pipeline:inputs` は ingestion の `sources.lock.json` が指定する原典・表を R2 から復元し、Git にある証跡も含めてハッシュを照合する。復元先は `.cache/inputs/<入力一覧のhash>/raw/`。必要な入力が欠けた場合は停止し、自治体サイトの最新版で補わない。

`build.ts` は復元済みの固定入力を使い、ネットワークなしで dbt の変換・検査と marts の CSV 生成を実行する。結果は `.build/builds/b-<内部構築ID>/` に入る。毎回 `.build/workspace/` を作り直して生成し、同じ構築 ID が既にある場合は CSV のハッシュを照合する。`--rebuild` でも同じ検査を行う。`.build/warehouse.duckdb` は検証画面用の再生成可能な DB である。

財政の表は `dbt/models/marts/records/`、団体別 CSV は `dbt/models/marts/csv/` で定義する。任意の FDP descriptor 整形は `bun run pipeline:fdp` で実行できる。公開 web・API・MCP・docs は一時的に HTTP 500 を返す。

提供モデルは決算・当初予算・変更・対応を分ける。決算明細は実績の `amount` 一つを持ち、歳出の COFOG コード・状態・根拠は明細・変更と同じ CSV に含める。歳出の分類は当面 COFOG のみとし、GFSM は提供しない。歳出の当初予算は確認できた対象を事業×歳出の節へ集約し、節の参照は `expenditure_setsu_id`（`fiscal_expenditure_setsu_master`）、節より下の内訳と原典行の対応は `details_json` に保持する。対応を確認できない行は原典行の粒度（`line_granularity = origin_line`、`expenditure_setsu_id = NULL`）で残す。原典の節コード・名称は取り込み・内部検証と `details_json` の内訳経路に残し、歳入の節は財源の内訳として保持する。規則ファイル・規則 ID は公開しない。原典の複数金額列は取り込み表と候補の `internal/fiscal/` に残し、公開する実績と混在させない。

狛江市2023年度一般会計の商工業振興費・予備費は、当初2件・補正3件・決算との集合対応10件を収録している。第1〜7号の採用版と適用日を保持し、当初＋補正の小計と決算書の報告予算現額の差を内部検証報告に残す。目単位であり歳出の節への対応は未確認。繰越・充用・流用と他対象の変更は未収録なので、datasetの `coverage_json.budgetHistory` は `unconfirmed` とする。詳細は [補正予算の設計](../docs/prd/fiscal-budget-history/design-doc.md) を参照。

歳出の節マスタ `fiscal_expenditure_setsu_master` と事業×歳出の節への集約は実装済みである。節マスタは `packages/fiscal/setsu-master.ts` の Git 定義（地方自治法施行規則 別記の現行28区分と改正前の旧体系・適用期間つき）から生成し、原典の節名称との対応は `pipeline/dbt/seeds/fiscal/expenditure_setsu_map.csv` に宣言する。集約の規則は `int_expenditure_setsu_lines`・`int_expenditure_setsu_groups` が正本であり、同じ経路・追加区分・節で分類（COFOG・連結判断）を共有する末端行だけをまとめる。契約と検査条件は [財政データの設計](../docs/prd/fiscal-records/design-doc.md) を参照。

## ローカルで原典との対応を確認する

```bash
bun run dev                  # 原典・dbt の検証画面、127.0.0.1:5174
```

PDF 閲覧レイヤは `.cache/pdf/`、報告は `.build/report/` に置く。系統は dbt の `manifest.json` から生成する。原典の行・頁、取り込み表、提供用データの対応と注意点を確認する。

## 検査する

```bash
bun run test
bun run typecheck:all
uv run python -m unittest discover -s pipeline -p '*_test.py'
```

まず staging の1対1・原典の値と単位の保持、intermediate の単位換算・分類・連結判断、marts の件数・金額・識別子と上流の対応を確認する。小さな fixture の成功と固定原典を使った全量 build の成功を区別する。

CI の全量 job は `FUDOKI_FIXED_INPUTS_READY=true` と非公開入力の読取権限がある場合だけ動く。固定入力からの build・再構築・報告を検査する。現在の検証結果と収録範囲は [検証記録](../docs/monorepo-migration.md) を参照する。
