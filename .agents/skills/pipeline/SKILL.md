---
name: pipeline
description: 風土記の原典調査、取り込み・PDF抽出、候補の検査、原典からの再抽出、固定入力の保存・採用、dbt構築、収録範囲監査を行うときに参照する。現在のA〜Gの評価フローと、各工程で実測した注意点を扱う。
user-invocable: false
---

# pipeline

全体の流れを確認するときは [評価フロー](references/workflow.md) を読み、作業する工程の reference へ進む。途中から続けるときは、その工程へ渡された入力と検査記録を確認する。

## Routing table

| やること | 読む reference |
| --- | --- |
| 全体の流れ・工程間の受け渡しを確認する | [references/workflow.md](references/workflow.md) |
| A. 公式原典と探索範囲を調べ、coverageへ記録する | [references/source-discovery.md](references/source-discovery.md) |
| B. 取り込み・抽出候補と追加案を作る | [references/budget-extraction.md](references/budget-extraction.md) |
| C. 原典の意味、実データ、登録・SQLを検査する | [references/candidate-validation.md](references/candidate-validation.md) |
| D. 原典だけから別の場所で再抽出する | [references/reconstruction.md](references/reconstruction.md) |
| E. 固定予定の保存物を非公開R2へ保存し、読み戻す | [references/input-storage.md](references/input-storage.md) |
| F. 入力と各層を本体へ採用し、全量構築・再構築する | [references/dbt.md](references/dbt.md) |
| G. 通常監査と検証報告で提供先・収録範囲を確認する | [references/coverage-audit.md](references/coverage-audit.md) |

## 関連 skill

- 全体設計・データ層の境界は repo root の `AGENTS.md`、実行手順は `pipeline/README.md` を参照する。
- ワーカーを監督する場合は共有の `orchestration` skill、Orcaの状態操作は共有の `orca-cli` skillを参照する。このskillから新たなワーカー起動を必須にしない。
