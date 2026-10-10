---
name: pipeline
description: 風土記の原典選定（source_selection）、CSV・text PDF・scan PDFの取り込みと形式別検査、保存・採用、staging定義・dbt構築、収録範囲監査を行うときに参照する。CSVの全セル保持検査と、PDFの階層別合計検査・修正の手順を扱う。
user-invocable: false
---

# pipeline

全体の流れを確認するときは [形式別のフロー](references/workflow.md) を読み、作業する工程の reference へ進む。CSVは変換時の全セル保持検査で取り込みを完了する。PDFは階層ごとの合計検査→不一致の修正→再検査で確かめる。

## Routing table

取り込みの責務は、原典から表を構築・検査し、Parquetと管理情報を保存するところまで。保存済みParquetの読み込み・入力準備・後段の構築はdbt側の責務として [references/dbt.md](references/dbt.md) に分ける。

| やること | 読む reference |
| --- | --- |
| 全体の流れ・工程間の受け渡しを確認する | [references/workflow.md](references/workflow.md) |
| A. source_selection — 原典の情報を埋め、1資料を選定・保存する。選べなければ理由を残す | [references/source-selection.md](references/source-selection.md) |
| B. ingestion：保存済みCSV・text PDF・scan PDFから取り込みParquetを作り、形式別に検査する | [references/ingestion.md](references/ingestion.md) |
| C. dbt：stagingを定義し、入力と各層を本体へ採用して全量構築・再構築する | [references/dbt.md](references/dbt.md) |
| D. 通常監査と検証報告で提供先・収録範囲を確認する | [references/coverage-audit.md](references/coverage-audit.md) |

## 関連 skill

- 全体設計・データ層の境界は repo root の `AGENTS.md`、実行コマンドは各 `package.json` を参照する。
