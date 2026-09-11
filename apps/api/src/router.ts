/**
 * contract → procedure → router の router 層。
 * procedure を contract の形に束ねるだけで、処理は持たない。
 * `os.router()` が contract との完全一致（実装漏れ・余剰）を型検査する。
 */
import { aggregateBudgets, getBudget, getBudgetLines, listBudgets, searchBudgetLines } from './procedure/budgets'
import { getJurisdiction, listJurisdictions } from './procedure/jurisdictions'
import { os } from './procedure/shared'

export const router = os.router({
  listJurisdictions,
  getJurisdiction,
  listBudgets,
  getBudget,
  getBudgetLines,
  aggregateBudgets,
  searchBudgetLines,
})
export type Router = typeof router
