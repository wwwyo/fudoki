---
name: cloudflare-api-ops
description: fudoki の apps/api（Cloudflare Workers + oRPC + Hono）をデプロイ・運用するときに参照する。公開直後に想定外の 403 が出た、oRPC のパフォーマンス系オプションを探して無いことに気づいた、といった非自明なハマりどころを持つ。
user-invocable: false
---

# cloudflare-api-ops

`apps/api`（api.fudoki.dev）の運用で得た、コードや AGENTS.md からは読めないハマりどころの正本。設計判断そのもの（why この形にしたか）は `decision.log` が正本なので、ここは重複させない。

## Routing table

| やること | 読む reference |
| --- | --- |
| 公開直後に特定クライアントだけ 403 になる | [references/cloudflare-zone.md](references/cloudflare-zone.md) |
| oRPC でリクエストごとの CPU コストを削りたい | [references/orpc-perf.md](references/orpc-perf.md) |

## 関連 skill

- apps/api の設計判断・トレードオフは repo 直下の `decision.log` が正本（このスキルは重複させない）
- dbt / duckdb 側のハマりどころは `.agents/skills/dbt-pipeline/`
