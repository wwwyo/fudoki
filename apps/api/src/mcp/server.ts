/**
 * fudoki の予算 tool を登録した McpServer を組み立てる、唯一の場所。
 *
 * remote（Workers の `/mcp`）と stdio（apps/mcp）の両方がこの1関数を呼ぶ。
 * tool の定義を2箇所に持たない（AGENTS.md「同じ事実を2箇所で宣言しない」）。
 * サーバは集計も判断も持たない ── tool は `ApiClient`（apps/api の router を
 * プロセス内でそのまま呼ぶクライアント）を right-through で呼ぶだけ。
 */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { ApiClient } from './client'
import { registerAggregateBudgets } from './tools/aggregate'
import { registerGetBudgetLines } from './tools/budgetLines'
import { registerListBudgets } from './tools/budgets'
import { registerListJurisdictions } from './tools/jurisdictions'
import { registerSearchBudgetLines } from './tools/search'

export function createMcpServer(client: ApiClient): McpServer {
  const server = new McpServer({ name: 'fudoki-mcp', version: '0.0.1' })
  registerListJurisdictions(server, client)
  registerListBudgets(server, client)
  registerGetBudgetLines(server, client)
  registerAggregateBudgets(server, client)
  registerSearchBudgetLines(server, client)
  return server
}
