/**
 * list_jurisdictions tool。`listJurisdictions` procedure をそのまま呼ぶだけ。
 */
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { listJurisdictionsOutput } from '../../contract'
import type { ApiClient } from '../client'
import { runTool } from '../result'

export function registerListJurisdictions(server: McpServer, client: ApiClient): void {
  server.registerTool(
    'list_jurisdictions',
    {
      title: 'List jurisdictions',
      description:
        // ⚠️ 具体的な収録団体（名称・コード）はここに書かない ── 団体を足すたびに
        // 説明文だけが古くなる（PR #27 レビュー指摘）。収録範囲はこの tool の応答そのものが正
        'fudoki が収録している地方公共団体の一覧を返す。収録範囲はこの応答そのものが正（現時点でどの団体を' +
        '扱えるかは、この tool を呼んで確かめること）。各団体の caveats に、予算段階や会計範囲など' +
        '数値の意味を変える注意事項が入っている。団体ごとに実際に収録している年度は list_budgets で' +
        '確認すること（このリストからは分からない）。',
      outputSchema: listJurisdictionsOutput,
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async () => runTool(() => client.listJurisdictions()),
  )
}
