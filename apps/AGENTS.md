# apps

公開 web・API・MCP・docs は**一時的に HTTP 500 を返す**。パイプライン完成後に公開・反映の方式を検討する。`availability.test.ts` がその確認で、root の `bun run test` から実行される。

- `api/`（`@fudoki/api`）: Cloudflare Workers + oRPC + Hono。デプロイ・運用のハマりどころは `.agents/skills/cloudflare-api-ops/`
- `web/`（`@fudoki/web`）: Vite + React、Cloudflare Workers 静的アセット配信（`deploy/` が wrangler 設定を持つ）。brand・map の資産生成（`build:brand` / `fetch:boundaries`）はこの package の script。DESIGN.md とデプロイ後の確認は `.agents/skills/web-frontend-ops/`
- `docs/`（`@fudoki/docs`）: ドキュメント app。同じく一時的に 500
