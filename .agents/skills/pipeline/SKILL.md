---
name: pipeline
description: fudoki のパイプライン（取得・PDF抽出・dbt）を触るときに参照する。dbt build や seed が原因不明で落ちた、抽出器が想定と違う原典に当たった、といった非自明なハマりどころを持つ。
user-invocable: false
---

# pipeline

fudoki のパイプライン運用で得た、コードや AGENTS.md からは読めないハマりどころ・想定外の正本。

## Routing table

| やること | 読む reference |
| --- | --- |
| dbt build / seed が原因不明で失敗する | [references/dbt.md](references/dbt.md) |
| 予算の取得・PDF抽出で想定と違う原典・年度割れ・組版に当たる | [references/budget-extraction.md](references/budget-extraction.md) |

## 関連 skill

- 全体設計・データ層の境界は repo ルートの `AGENTS.md` が正本（このスキルは重複させない）
