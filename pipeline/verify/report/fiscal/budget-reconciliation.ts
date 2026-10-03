import type { BudgetReconciliation } from './schema'

type Initial = { budgetItemId: string; amount: number | null }
type Change = { changeId: string; amountDelta: number; effectiveAt: string | null }
type Settlement = { settlementLineId: string; amount: number }
export type BudgetEvidence = {
  jurisdictionCode: string
  fiscalYear: number
  fundCode: string
  target: string
  asOf: string
  initial: Initial[]
  changes: Change[]
  settlement: Settlement[]
  reportedBudgetAmount: number | null
  adoptedIssues: { number: number; effectiveAt: string | null; approvalVerified: boolean }[]
  correspondenceConfirmed: boolean
}

/** 同じ集合のIDを一度だけ集計し、補正の収録範囲と報告額の差を分ける。 */
export function reconcileBudget(evidence: BudgetEvidence): BudgetReconciliation {
  function unique<T>(values: T[], id: (value: T) => string): T[] {
    const members = new Map<string, T>()
    for (const value of values) {
      const key = id(value)
      const previous = members.get(key)
      if (previous && JSON.stringify(previous) !== JSON.stringify(value))
        throw new Error(`Conflicting adopted amount: ${key}`)
      members.set(key, value)
    }
    return [...members.values()]
  }
  const initial = unique(evidence.initial, (value) => value.budgetItemId)
  const changes = unique(evidence.changes, (value) => value.changeId)
  const settlement = unique(evidence.settlement, (value) => value.settlementLineId)
  const issues = unique(evidence.adoptedIssues, (value) => String(value.number))
  const supplementaryCoverageStatus =
    initial.length > 0 && initial.every((value) => value.amount !== null) &&
    issues.length === 8 && issues.every((issue) =>
      issue.number >= 0 && issue.number <= 7 && issue.effectiveAt !== null && issue.approvalVerified) &&
    changes.every((change) => change.effectiveAt !== null)
      ? 'complete' : 'unconfirmed'
  const initialAmount = initial.length > 0 && initial.every((value) => value.amount !== null)
    ? initial.reduce((total, value) => total + value.amount!, 0) : null
  const supplementaryKnown = supplementaryCoverageStatus === 'complete'
  const supplementaryAmount = supplementaryKnown ? changes.filter((value) => value.effectiveAt !== null && value.effectiveAt <= evidence.asOf)
    .reduce((total, value) => total + value.amountDelta, 0) : null
  const budgetAmount = initialAmount !== null && supplementaryAmount !== null && evidence.asOf >= `${evidence.fiscalYear}-04-01`
    ? initialAmount + supplementaryAmount : null
  const comparable = supplementaryCoverageStatus === 'complete' && evidence.correspondenceConfirmed &&
    evidence.asOf === `${evidence.fiscalYear + 1}-03-31` && budgetAmount !== null && evidence.reportedBudgetAmount !== null
  const difference = comparable ? evidence.reportedBudgetAmount! - budgetAmount! : null
  return {
    jurisdictionCode: evidence.jurisdictionCode, fiscalYear: evidence.fiscalYear, fundCode: evidence.fundCode, target: evidence.target,
    asOf: evidence.asOf, granularity: 'moku', expenditureSetsuStatus: 'unconfirmed',
    budgetItemIds: initial.map((value) => value.budgetItemId).sort(),
    settlementLineIds: settlement.map((value) => value.settlementLineId).sort(),
    initialAmount, supplementaryAmount, budgetAmount,
    reportedBudgetAmount: evidence.reportedBudgetAmount,
    settlementAmount: settlement.length ? settlement.reduce((total, value) => total + value.amount, 0) : null,
    difference, supplementaryCoverageStatus,
    reconciliationStatus: difference === null ? 'unconfirmed' : difference === 0 ? 'matched' : 'difference',
  }
}
