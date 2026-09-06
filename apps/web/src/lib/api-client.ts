/**
 * apps/api への RPC クライアント。
 *
 * `@fudoki/api` の contract 型（`Router`）をそのまま import するので、
 * API 側でフィールドを変えれば web 側の呼び出しはコンパイルエラーで気づける
 * （AGENTS.md の「食い違いをコンパイラに捕まえさせる」）。実行時の処理は
 * `@orpc/client` の RPCLink 経由で `/rpc` を叩くだけで、ここでは持たない。
 *
 * ⚠️ **エンドポイントは `import.meta.env.DEV` で切り替える。** vite が
 * `vite dev` では true、`vite build` の成果物では false を埋め込むビルド時定数なので、
 * ランタイムの分岐が消えて本番バンドルには本番 URL だけが残る。`.env` を増やさずに済む
 * （切替の軸が「開発中か本番ビルドか」の1つしか無いため、環境変数にする理由が無い）。
 * - 本番（`vite build` の成果物 = fudoki.dev で配信）: `https://api.fudoki.dev/rpc`
 * - 開発（`vite dev`）: `http://localhost:8787/rpc`（`wrangler dev` の既定ポート。
 *   `bun run --cwd apps/api dev` で起動する）
 *
 * ⚠️ **dev サーバは 5173 番ポートで動かすこと。** apps/api の CORS は `/rpc` を
 * `https://fudoki.dev` と `http://localhost:5173` にしか許していない
 * （apps/api/src/index.ts の `RPC_ALLOWED_ORIGINS`）。他のポートで vite を上げると
 * preflight で弾かれる。
 */
import { createORPCClient } from "@orpc/client"
import { RPCLink } from "@orpc/client/fetch"
import type { RouterClient } from "@orpc/server"
import type { Router } from "@fudoki/api/router"

const API_RPC_URL = import.meta.env.DEV
  ? "http://localhost:8787/rpc"
  : "https://api.fudoki.dev/rpc"

const link = new RPCLink({ url: API_RPC_URL })

export const apiClient: RouterClient<Router> = createORPCClient(link)
