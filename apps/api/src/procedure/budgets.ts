/**
 * budgets リソースの procedure。収録年度（カバレッジ）と年度スコープのメタを返す。
 */
import { os, readMeta } from './os'

export const listBudgets = os.listBudgets.handler(async ({ context, input, errors }) => {
  const meta = await readMeta(context.env)
  const budgets = meta.budgets[input.jurisdiction]
  if (budgets === undefined) throw errors.NOT_FOUND({ message: `unknown jurisdiction: ${input.jurisdiction}` })
  return { budgets, revision: meta.revision }
})

export const getBudget = os.getBudget.handler(async ({ context, input, errors }) => {
  const meta = await readMeta(context.env)
  const budgets = meta.budgets[input.jurisdiction]
  if (budgets === undefined) throw errors.NOT_FOUND({ message: `unknown jurisdiction: ${input.jurisdiction}` })
  const budget = budgets.find((b) => b.fiscalYear === input.budget)
  if (!budget) throw errors.NOT_FOUND({ message: `fiscal year ${input.budget} is not covered for ${input.jurisdiction}` })
  return { budget, revision: meta.revision }
})
