/**
 * budget-api の contract。**API の入出力はここが唯一の定義**で、
 * 実装（../router.ts）も OpenAPI（../spec.ts）もここから導出する。
 * 形は Google AIP に倣う（リソース名 AIP-122、List/Get、ページング AIP-158、
 * ワイルドカード親 AIP-159、filter AIP-160 の部分集合）。
 *
 * ファイルは集約ごとに1つ（jurisdictions / budgets）。statement は
 * budget 集約の内部なので budgets.ts に同居する。
 * 集約を足すときはファイルを足し、ここの contract に載せる。
 */
import { getJurisdiction, listJurisdictions } from './jurisdictions'
import { getBudget, getStatement, listBudgets } from './budgets'

export const contract = {
  listJurisdictions,
  getJurisdiction,
  listBudgets,
  getBudget,
  getStatement,
}
export type Contract = typeof contract

export {
  caveatSchema,
  jurisdictionSchema,
  type Jurisdiction,
} from './jurisdictions'
export {
  budgetIdOf,
  budgetLineSchema,
  budgetSchema,
  crossBudgetLineSchema,
  parseBudgetId,
  statementSchema,
  type Budget,
  type BudgetLine,
  type CrossBudgetLine,
  type Statement,
} from './budgets'
export {
  cofogConsolidation,
  cofogDecidedAtLevel,
  cofogStatus,
  dimensionName,
  levelName,
  phaseId,
} from './shared'
