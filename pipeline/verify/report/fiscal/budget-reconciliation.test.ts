import { expect, test } from 'bun:test'
import { reconcileBudget, type BudgetEvidence } from './budget-reconciliation'
const evidence = (): BudgetEvidence => ({
  jurisdictionCode: '132195', fiscalYear: 2023, fundCode: '1', target: '7-1-2', asOf: '2024-03-31',
  initial: [{ budgetItemId: 'a', amount: 34553000 }],
  changes: [
    { changeId: 'c3', amountDelta: 148300000, effectiveAt: '2023-08-31' },
    { changeId: 'c6', amountDelta: -115000000, effectiveAt: '2024-02-01' },
  ],
  settlement: [{ settlementLineId: 'x', amount: 66261365 }],
  reportedBudgetAmount: 68814000, correspondenceConfirmed: true,
  adoptedIssues: Array.from({ length: 8 }, (_, number) => ({ number, effectiveAt: '2023-04-01', approvalVerified: true })),
})
test('年度末の差額は補正へ追加されず、収録完了と不一致を区別する', () => {
  expect(reconcileBudget(evidence())).toMatchObject({ budgetAmount: 67853000, difference: 961000,
    supplementaryCoverageStatus: 'complete', reconciliationStatus: 'difference', settlementAmount: 66261365 })
})
test('適用日の前日と当日で符号付き補正だけが予算小計へ入る', () => {
  const e = evidence()
  expect(reconcileBudget({ ...e, asOf: '2023-08-30' }).budgetAmount).toBe(34553000)
  expect(reconcileBudget({ ...e, asOf: '2023-08-31' }).budgetAmount).toBe(182853000)
  expect(reconcileBudget({ ...e, asOf: '2024-02-01' }).budgetAmount).toBe(67853000)
  expect(reconcileBudget({ ...e, asOf: '2023-08-31' }).difference).toBeNull()
  expect(reconcileBudget({ ...e, asOf: '2023-03-31' }).budgetAmount).toBeNull()
})
test('欠号・日付不明・集合対応不明は比較を未確認にする', () => {
  const e = evidence()
  expect(reconcileBudget({ ...e, adoptedIssues: e.adoptedIssues.slice(1) }).difference).toBeNull()
  expect(reconcileBudget({ ...e, changes: [{ ...e.changes[0]!, effectiveAt: null }] })).toMatchObject({
    supplementaryAmount: null, supplementaryCoverageStatus: 'unconfirmed', difference: null })
  expect(reconcileBudget({ ...e, correspondenceConfirmed: false }).difference).toBeNull()
})
test('当初不明と実績欠落をゼロとして扱わない', () => {
  expect(reconcileBudget({ ...evidence(), initial: [{ budgetItemId: 'a', amount: null }], settlement: [] }))
    .toMatchObject({ initialAmount: null, budgetAmount: null, settlementAmount: null, difference: null })
})
test('M:Nのリンク展開でも両側の集合は一度ずつ集計する', () => {
  const e = evidence()
  const initial = [{ budgetItemId: 'a', amount: 60000 }, { budgetItemId: 'b', amount: 40000 }]
  const settlement = [{ settlementLineId: 'x', amount: 30000 }, { settlementLineId: 'y', amount: 70000 }]
  expect(reconcileBudget({ ...e, initial: [...initial, ...initial], changes: [],
    settlement: [...settlement, ...settlement], reportedBudgetAmount: 100000 }))
    .toMatchObject({ initialAmount: 100000, settlementAmount: 100000, difference: 0, reconciliationStatus: 'matched' })
})
test('採用額が競合する同一IDを黙って上書きしない', () => {
  const e = evidence()
  expect(() => reconcileBudget({ ...e, changes: [...e.changes, { ...e.changes[0]!, amountDelta: 1 }] })).toThrow('Conflicting')
})
