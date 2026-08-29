/**
 * budget-api の contract。**API の入出力はここが唯一の定義**で、
 * 実装（../router.ts）も OpenAPI（../spec.ts）もここから導出する。
 * 形は Google AIP に倣う（リソース名 AIP-122、List/Get、ページング AIP-158、
 * ワイルドカード親 AIP-159、filter AIP-160 の部分集合）。
 *
 * リソースごとに1ファイル。リソースを足すときはファイルを足し、
 * ここの contract に載せる。
 */
import { getJurisdiction, listJurisdictions } from './jurisdictions'
import { getBudgetLine, listBudgetLines } from './budget-lines'

export const contract = {
  listJurisdictions,
  getJurisdiction,
  listBudgetLines,
  getBudgetLine,
}
export type Contract = typeof contract

export {
  caveatSchema,
  classificationRateSchema,
  jurisdictionSchema,
  type ClassificationRate,
  type Jurisdiction,
} from './jurisdictions'
export {
  cofogConsolidation,
  cofogDecidedAtLevel,
  cofogStatus,
  dimensionName,
  levelName,
  phaseId,
} from './shared'
export {
  budgetLineSchema,
  crossJurisdictionLineSchema,
  listBudgetLinesResponseSchema,
  type BudgetLine,
  type CrossJurisdictionLine,
  type ListBudgetLinesResponse,
} from './budget-lines'
