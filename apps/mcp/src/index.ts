#!/usr/bin/env bun
/**
 * fudoki の予算 API を束ねる stdio MCP サーバのエントリ（ローカル開発用）。
 *
 * 本番は Cloudflare Workers 上の remote サーバ（apps/api/src/index.ts の `/mcp`）。
 * tool の定義（apps/api/src/mcp/）は remote と共有しており、ここでは
 * stdio 固有のもの（ASSETS をファイルシステムから読む Env、StdioServerTransport）
 * だけを組み立てる（AGENTS.md「同じ事実を2箇所で宣言しない」）。
 */
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { createApiClient } from '../../api/src/mcp/client'
import { createMcpServer } from '../../api/src/mcp/server'
import { assertAssetsBuilt, createEnv } from './env'

async function main(): Promise<void> {
  await assertAssetsBuilt()

  const env = createEnv()
  const client = createApiClient(env)
  const server = createMcpServer(client)

  const transport = new StdioServerTransport()
  await server.connect(transport)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
