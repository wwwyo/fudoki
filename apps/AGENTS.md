# apps

公開 web・API・MCP・docs は**一時的に HTTP 500 を返す**。パイプライン完成後に公開・反映の方式を検討する。`availability.test.ts` がその確認で、root の `bun run test` から実行される。

- `api/`（`@fudoki/api`）: Cloudflare Workers + oRPC + Hono。デプロイ・運用のハマりどころは `.agents/skills/cloudflare-api-ops/`
- `web/`（`@fudoki/web`）: Vite + React、Cloudflare Workers 静的アセット配信（`deploy/` が wrangler 設定を持つ）。brand・map の資産生成（`build:brand` / `fetch:boundaries`）はこの package の script。DESIGN.md とデプロイ後の確認は `.agents/skills/web-frontend-ops/`
- `docs/`（`@fudoki/docs`）: ドキュメント app。同じく一時的に 500

## 公開 web の配信

**ダッシュボードは `https://fudoki.dev/` で配信する。** これは派生物であって正本ではない。公開 web の絶対 URL（`canonical` / `og:image` / `sitemap.xml`）はこのドメインを指す。

- ⚠️ **ルートパス（`https://fudoki.dev/`）で配信する前提**なので、`vite.config.ts` の `base` は `/` のままでよい。`base` に効くのはパスであって DNS 名ではない。`www.fudoki.dev` のようなサブドメインへ移しても `/` のまま。サブパス（`example.github.io/fudoki/` のような形）へ移すときだけ、`base` と上記3箇所を同時に変える（片方だけだと静的アセットが 404 になる）
- 置き場は Cloudflare。apex をそのまま向けられるのは Cloudflare が CNAME flattening をするからで、`CNAME` ファイルは要らない（GitHub Pages なら要る）
- 配信は **Cloudflare Workers の静的アセット**（`web/deploy/cloudflare.config.ts`）。`entrypoint` を持たないアセットだけの Worker で、画面はサーバ側で何もしないのでスクリプトは置かない
- 公開 web は API から dataset と現在のデータ版を参照し、SQL 集計の応答を表示する。build/deploy は公開 UI のコードだけを扱い、dbt・報告・原典の全量生成は実行しない
- ローカル検証画面（`pipeline/verify/view/`）、報告（`pipeline/.build/report/`）、PDF 閲覧レイヤ（`pipeline/.cache/pdf/`）は公開 web の配信物に含めない

```bash
bun run deploy:web    # vite build → cf deploy
```
