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
        '例: `jurisdiction = "132195"`、`jurisdiction = "132195" AND fiscalYear = "2023"`',
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
        '収録している予算（団体×年度）の一覧。件数が少ないためページングは無く、fudoki が収録している' +
        '全範囲がこの1回の呼び出しで分かる（何が無いかもこれで分かる）。\n\n' +
        '⚠️ 予算段階が団体で違うので、budgets を横断して amountPhase を混同しないこと。' +
        '三鷹市（132047）は令和6年度（2024年度）の当初予算のみを収録し、amountPhase は approved。' +
        '狛江市（132195）は2018〜2023年度の決算を収録し、amountPhase は adjusted（補正まで反映した予算現額。' +
        '当初予算ではない）。多摩市（132241）は令和3〜7年度（2021〜2025年度）の当初予算（一般会計のみ）を収録し、' +
        'amountPhase は approved。三鷹市の approved と狛江市の adjusted を単純に合算・比較すると、' +
        'どの団体も公表していない数値になる。\n\n' +
        '各 budget の scopes に、direction ごとの会計範囲・COFOG 到達度・名称の収録状況が入っている。' +
        '明細は /budgets/{id}/budgetLines に相当する get_budget_lines tool から取得する。',
      inputSchema,
      outputSchema,
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
