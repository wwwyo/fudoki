/**
 * budgets リソースの procedure。root の一覧（filter で絞る）と Get。
 * 一覧の存在がカバレッジそのもの。
 */
import { os, parseFilterOr400, readMeta } from './os'

export const listBudgets = os.listBudgets.handler(async ({ context, input, errors }) => {
  const filter = parseFilterOr400(input.filter, errors)
  if (filter.direction !== undefined || filter.phase !== undefined || filter.cofogDivision !== undefined) {
    throw errors.BAD_REQUEST({
      message: 'only jurisdiction and fiscalYear filters are supported for budgets',
      data: { reason: 'unsupported filter field' },
    })
  }
  const meta = await readMeta(context.env)
  const budgets = meta.budgets.filter(
    (b) =>
      (filter.jurisdiction === undefined || b.jurisdictionId === filter.jurisdiction) &&
      (filter.fiscalYear === undefined || b.fiscalYear === filter.fiscalYear),
  )
  return { budgets, revision: meta.revision }
})

export const getBudget = os.getBudget.handler(async ({ context, input, errors }) => {
  const meta = await readMeta(context.env)
  const budget = meta.budgets.find((b) => b.id === input.budget)
  if (!budget) throw errors.NOT_FOUND({ message: `unknown budget: ${input.budget}` })
  return { budget, revision: meta.revision }
})
