---
name: web-frontend-ops
description: fudoki の apps/web（Vite + React、Cloudflare Workers 静的アセット配信）を触るときに参照する。デプロイ後の見た目を確認しようとして curl の結果に惑わされた、DESIGN.md に何を書くか迷った、といった非自明なハマりどころを持つ。
user-invocable: false
---

# web-frontend-ops

`apps/web`（fudoki.dev）の運用で得た、コードや AGENTS.md からは読めないハマりどころの正本。

## Routing table

| やること | 読む reference |
| --- | --- |
| デプロイ後に本番の見た目・DOM を確認したい | [references/deploy-verification.md](references/deploy-verification.md) |
| `DESIGN.md` に何を書くか・書かないかを判断したい | [references/design-md.md](references/design-md.md) |

## 関連 skill

- 全体設計・配布の方針は repo ルートの `AGENTS.md` が正本（このスキルは重複させない）
- apps/api 側の運用ハマりどころは `.agents/skills/cloudflare-api-ops/`
