/**
 * list_jurisdictions tool。`listJurisdictions` procedure をそのまま呼ぶだけ。
 */
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import * as z from 'zod'
import { jurisdictionSchema } from '../../contract'
import type { ApiClient } from '../client'
import { fromApiError, ok } from '../result'

const outputSchema = z.object({
  jurisdictions: z.array(jurisdictionSchema),
  revision: z.string().describe('由来する配布物の revision（git commit）'),
})

export function registerListJurisdictions(server: McpServer, client: ApiClient): void {
  server.registerTool(
    'list_jurisdictions',
    {
      title: 'List jurisdictions',
      description:
        'fudoki が収録している地方公共団体の一覧を返す。' +
        '収録は東京都の3団体だけ（三鷹市 132047 / 狛江市 132195 / 多摩市 132241）で、それ以外の団体の予算は扱えない。' +
        '各団体の caveats に、予算段階や会計範囲など数値の意味を変える注意事項が入っている。' +
        '団体ごとに実際に収録している年度は list_budgets で確認すること（このリストからは分からない）。',
      outputSchema,
    },
    async () => {
      try {
        const result = await client.listJurisdictions()
        return ok(result)
      } catch (error) {
        return fromApiError(error)
      }
    },
  )
}
