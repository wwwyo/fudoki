/**
 * budget-api の contract。**API の入出力はここが唯一の定義**で、
 * 実装（../router.ts）も OpenAPI（../spec.ts）もここから導出する。
 * 形は Google AIP に倣う（リソース名 AIP-122、List/Get、ページング AIP-158、
 * ワイルドカード親 AIP-159、filter AIP-160 の部分集合）。
 *
 * ファイルは集約ごとに1つ（jurisdictions / budgets）。budgetLines は
 * budget 集約の内部なので budgets.ts に同居する。
 * 集約を足すときはファイルを足し、ここの contract に載せる。
 */
import { getJurisdiction, listJurisdictions } from './jurisdictions'
import { aggregateBudgets, getBudget, getBudgetLines, listBudgets, searchBudgetLines } from './budgets'

export const contract = {
  listJurisdictions,
  getJurisdiction,
  listBudgets,
  getBudget,
  getBudgetLines,
  aggregateBudgets,
  searchBudgetLines,
}
export type Contract = typeof contract

export {
  caveatSchema,
  jurisdictionSchema,
  listJurisdictionsOutput,
  type Jurisdiction,
} from './jurisdictions'
export {
  aggregateBudgetsInput,
  aggregateBudgetsOutput,
  aggregateOmittedCode,
  aggregateWarningCode,
  budgetIdOf,
  budgetLinesViewEnum,
  budgetLineSchema,
  budgetSchema,
  cofogDepthOf,
  CROSS_JURISDICTION_GROUPINGS,
  getBudgetLinesInput,
  getBudgetLinesOutput,
  groupingKey,
  hierarchyChildLevel,
  hierarchyParentPathString,
  judgmentKind,
  JURISDICTION_YEARS_GROUPINGS,
  listBudgetsOutput,
  namedCoverageCode,
  nameFieldEnum,
  parseBudgetId,
  parseBudgetLineId,
  parseHierarchyParent,
  searchMatchSchema,
  SINGLE_BUDGET_GROUPINGS,
  storedBudgetLineSchema,
  storedCrossBudgetLineSchema,
  SUPPORTED_AGGREGATE_DIRECTIONS,
  SUPPORTED_GROUPINGS,
  type AggregateBudgetsOutput,
  type Budget,
  type BudgetDirectionScope,
  type BudgetLine,
  type BudgetLinesView,
  type BudgetScopes,
  type GetBudgetLinesOutput,
  type GroupingKey,
  type HierarchyParentSegment,
  type NameFieldValue,
  type SearchBudgetLinesOutput,
  type SearchMatch,
  type StoredBudgetLine,
  type StoredCrossBudgetLine,
} from './budgets'
export {
  cofogConsolidation,
  direction,
  cofogDecidedAtLevel,
  cofogStatus,
  dimensionName,
  levelName,
  phaseId,
  type PhaseId,
} from './shared'
