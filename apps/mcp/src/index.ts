#!/usr/bin/env bun
/**
 * fudoki の予算 API を束ねる stdio MCP サーバのエントリ（ローカル開発用）。
 *
 * 本番は Cloudflare Workers 上の remote サーバ（apps/api/src/index.ts の `/mcp`）。
 * tool の定義（apps/api/src/mcp/）は remote と共有しており、ここでは
 * stdio 固有のもの（ASSETS をファイルシステムから読む Env）だけを組み立てる
 * （AGENTS.md「同じ事実を2箇所で宣言しない」）。
 * `serveStdio` が接頭の exchange から era（legacy / 2026-07-28）を決め、
 * 以後その1インスタンスに通す ── remote と同じく1つの factory で2 era を出す。
 */
import { serveStdio } from '@modelcontextprotocol/server/stdio'
import { createApiClient } from '../../api/src/mcp/client'
import { createMcpServer } from '../../api/src/mcp/server'
import { assertAssetsBuilt, createEnv } from './env'

async function main(): Promise<void> {
  await assertAssetsBuilt()

  const env = createEnv()
  const client = createApiClient(env)

  serveStdio(() => createMcpServer(client))
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
