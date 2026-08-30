/**
 * list_budgets tool。`listBudgets` procedure をそのまま呼ぶだけ。
 * これが収録範囲（カバレッジ）そのもの — 団体×年度がここに無ければ未収録。
 */
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import * as z from 'zod'
import { budgetSchema } from '../../contract'
import type { ApiClient } from '../client'
import { fromApiError, ok } from '../result'

const inputSchema = z.object({
  filter: z
    .string()
    .optional()
    .describe(
      'AIP-160 の部分集合（`=` と `AND` のみ）。使えるフィールドは jurisdiction / fiscalYear。' +
        '例: `jurisdiction = "<団体コード>"`、`jurisdiction = "<団体コード>" AND fiscalYear = "<年度>"`（実在する値は list_jurisdictions / list_budgets の応答で確認する）',
    ),
})

const outputSchema = z.object({
  budgets: z.array(budgetSchema).describe('id の昇順'),
  revision: z.string().describe('由来する配布物の revision（git commit）'),
})

export function registerListBudgets(server: McpServer, client: ApiClient): void {
  server.registerTool(
    'list_budgets',
    {
      title: 'List budgets',
      description:
        // ⚠️ 具体的な団体・年度・phase の組み合わせはここに書かない ── 団体や年度を足すたびに
        // 説明文だけが古くなる（PR #27 レビュー指摘）。収録範囲・amountPhase は各 budget の応答が正
        '収録している予算（団体×年度）の一覧。件数が少ないためページングは無く、fudoki が収録している' +
        '全範囲がこの1回の呼び出しで分かる（何が無いかもこれで分かる）。\n\n' +
        '⚠️ 予算段階（amountPhase。当初予算・補正後・決算など）は団体・年度で異なることがあるので、' +
        '複数の budget を横断して amountPhase が違うものを単純に合算・比較しないこと。' +
        '各 budget が実際にどの amountPhase を収録しているかは、この応答の各要素で確認すること。\n\n' +
        '各 budget の scopes に、direction ごとの会計範囲・COFOG 到達度・名称の収録状況が入っている。' +
        '明細は /budgets/{id}/budgetLines に相当する get_budget_lines tool から取得する。',
      inputSchema,
      outputSchema,
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async (input) => {
      try {
        const result = await client.listBudgets({ filter: input.filter })
        return ok(result)
      } catch (error) {
        return fromApiError(error)
      }
    },
  )
}
