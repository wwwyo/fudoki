---
name: pipeline
description: 風土記の原典選定（source_selection）、CSV・text PDF・scan PDFの取り込みと形式別検査、保存・採用、staging定義・dbt構築、収録範囲監査を行うときに参照する。CSVの原典からParquetへの保持検査と、PDFの原典照合・再抽出の手順を扱う。
user-invocable: false
---

# pipeline

全体の流れを確認するときは [形式別のフロー](references/workflow.md) を読み、作業する工程の reference へ進む。途中から続けるときは、その工程へ渡された入力と検査記録を確認する。CSVは変換時の全セル保持検査で取り込みを完了し、候補検査・再抽出を独立した必須工程にしない。PDFはsubagentが構築・修正し、親agentが階層ごとの合計検査、不一致の整理、再検査と完了判断を行う。不一致が繰り返す場合は親agentが構築・検査の前提を見直す。共通実装と書式別の停止条件は未完了である。

## Routing table

| やること | 読む reference |
| --- | --- |
| 全体の流れ・工程間の受け渡しを確認する | [references/workflow.md](references/workflow.md) |
| A. source_selection — 原典の情報を埋め、1資料を選定・保存する。選べなければ理由を残す | [references/source-selection.md](references/source-selection.md) |
| B. ingestion：保存済みCSV・text PDF・scan PDFから取り込みParquetを作る | [references/ingestion.md](references/ingestion.md) |
| CSVの保持検査、PDFの階層別合計・不一致の整理と修正ループ、後段検査との境界 | [references/candidate-validation.md](references/candidate-validation.md) |
| PDFの抽出器変更・移設時に再現性を検査する | [references/reconstruction.md](references/reconstruction.md) |
| 旧固定入力の保存・読み戻し（新しい保存はBを参照） | [references/input-storage.md](references/input-storage.md) |
| F. 入力と各層を本体へ採用し、全量構築・再構築する | [references/dbt.md](references/dbt.md) |
| ingestionのJSON・Parquetからstagingモデルを定義・検証する | [references/staging.md](references/staging.md) |
| G. 通常監査と検証報告で提供先・収録範囲を確認する | [references/coverage-audit.md](references/coverage-audit.md) |

## 関連 skill

- 全体設計・データ層の境界は repo root の `AGENTS.md`、実行手順は `pipeline/README.md` を参照する。
- PDFの構築を行うときは上記の分担に従ってsubagentへ依頼する。手順の確認・skillの編集だけでは構築担当を起動しない。独立したOrcaワーカーを監督する場合は共有の `orchestration` skill、Orcaの状態操作は共有の `orca-cli` skillを参照する。
