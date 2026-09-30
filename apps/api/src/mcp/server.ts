import { McpServer } from '@modelcontextprotocol/server'
import { contract } from '../contract'
import type { ApiClient } from './client'
import { runTool } from './result'

export function createMcpServer(client: ApiClient): McpServer {
  const server = new McpServer({ name: 'fudoki-mcp', version: '0.2.0' })
  for (const name of Object.keys(contract) as (keyof typeof contract)[]) {
    const procedure = contract[name]
    server.registerTool(
      name.replace(/[A-Z]/g, (c) => '_' + c.toLowerCase()),
      {
        title: name,
        description:
          name === 'aggregateFiscalDatasets'
            ? '明示した datasetIds の金額を集計する。同じ団体・年度・歳出歳入から複数の文書や版を選ばない。文書種別と金額段階は別。'
            : '風土記の公開版を参照する。最初に listJurisdictions と listFiscalDatasets で収録範囲・原典・注意点を確認する。releaseId を指定するとその版を参照する。',
        inputSchema: procedure['~orpc'].inputSchema!,
        outputSchema: procedure['~orpc'].outputSchema!,
        annotations: { readOnlyHint: true, openWorldHint: false },
      },
      async (input: unknown) =>
        runTool(() =>
          (
            client[name] as (value: unknown) => Promise<Record<string, unknown>>
          )(input)
        )
    )
  }
  return server
}
