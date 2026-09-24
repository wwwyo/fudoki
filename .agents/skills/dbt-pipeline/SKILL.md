---
name: dbt-pipeline
description: fudoki の dbt パイプライン（seed / build / duckdb 実行環境）を触るときに参照する。dbt build や seed が原因不明で落ちた、列数や型が合わないエラーが出た、といった非自明なハマりどころを持つ。
user-invocable: false
---

# dbt-pipeline

fudoki の dbt パイプライン運用で得た、コードや AGENTS.md からは読めないハマりどころの正本。

## Routing table

| やること | 読む reference |
| --- | --- |
| dbt build / seed が原因不明で失敗する | [references/dbt.md](references/dbt.md) |

## 関連 skill

- 全体設計・データ層の境界は repo ルートの `AGENTS.md` が正本（このスキルは重複させない）
