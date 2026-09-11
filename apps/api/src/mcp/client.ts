/**
 * apps/api の router をプロセス内で直接呼ぶクライアント。
 *
 * MCP サーバは集計も判断も持たない（AGENTS.md「集計は1箇所」）。tool のロジックは
 * 「入力を router に渡し、応答をそのまま返す」だけにするため、HTTP を経由せず
 * `createRouterClient` で contract 型のまま呼べる形にする。
 *
 * remote（Workers）と stdio の両方がこのファイルを使う。Workers 版は Hono の
 * `c.env` をそのまま渡し、stdio 版は apps/mcp/src/env.ts が組み立てた
 * ファイルシステム版の Env を渡す。
 */
import { createRouterClient } from '@orpc/server'
import type { Env } from '../assets'
import { router } from '../router'

export type ApiClient = ReturnType<typeof createApiClient>

export function createApiClient(env: Env) {
  return createRouterClient(router, { context: { env } })
}
