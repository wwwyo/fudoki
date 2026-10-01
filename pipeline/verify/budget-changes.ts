import { join } from 'node:path'
import { jsonLines } from '../fdp/manifest'
import {
  budgetHistoryQuerySchema,
  budgetHistorySchema,
  type BudgetHistory,
  type BudgetHistoryQuery,
} from '../../apps/api/src/contract'

type Version = { jurisdictionCode: string; versionId: string }

/** Read changes through the consumer endpoint and compare them with the built rows. */
export async function verifyBudgetChanges(
  directory: string,
  versions: Version[],
  query: (input: BudgetHistoryQuery) => Promise<BudgetHistory>
) {
  const results = []
  for (const direction of ['expenditure', 'revenue'] as const) {
    const items = new Map(
      (await jsonLines(join(directory, `api/fiscal_${direction}_budget_items.jsonl`)))
        .map((row) => [String(row.budget_item_id), row])
    )
    const scopes = new Map<string, {
      jurisdictionCode: string; fiscalYear: number; fundCode: string;
      rows: Record<string, unknown>[]
    }>()
    for (const row of await jsonLines(join(directory, `api/fiscal_${direction}_budget_changes.jsonl`))) {
      const item = items.get(String(row.budget_item_id))
      if (!item) throw new Error('Budget change lacks its built item')
      const jurisdictionCode = String(item.jurisdiction_code)
      if (!versions.some((v) => v.jurisdictionCode === jurisdictionCode)) continue
      const fiscalYear = Number(item.fiscal_year), fundCode = String(item.fund_code)
      const key = JSON.stringify([jurisdictionCode, fiscalYear, fundCode])
      const scope = scopes.get(key) ?? { jurisdictionCode, fiscalYear, fundCode, rows: [] }
      scope.rows.push(row)
      scopes.set(key, scope)
    }
    for (const scope of scopes.values()) {
      const asOf = scope.rows.map((r) => String(r.effective_at).slice(0, 10)).sort().at(-1)!
      const input = budgetHistoryQuerySchema.parse({
        versions: versions.filter((v) => v.jurisdictionCode === scope.jurisdictionCode),
        jurisdictionCode: scope.jurisdictionCode, fiscalYear: scope.fiscalYear,
        direction, fundCode: scope.fundCode, asOf,
      })
      const actual = budgetHistorySchema.parse(await query(input))
      if (JSON.stringify(actual.versions) !== JSON.stringify(input.versions))
        throw new Error('Budget history versions differ from the build')
      const expected = scope.rows.map((r) => JSON.stringify([
        r.change_id, r.budget_item_id, r.dataset_id, r.amount_delta,
        r.change_kind, r.effective_at, r.sequence, r.source_row,
        r.counterpart_budget_item_id, r.carryover_from_year, r.carryover_to_year,
        ...(direction === 'expenditure' ? [r.cofog_code ?? '', r.cofog_status, r.cofog_basis] : []),
      ])).sort()
      const received = actual.changes.map((r) => JSON.stringify([
        r.id, r.budgetItemId, r.datasetId, r.amountDelta, r.kind,
        r.effectiveAt, r.sequence, r.sourceRow, r.counterpartBudgetItemId,
        r.carryoverFromYear, r.carryoverToYear,
        ...(direction === 'expenditure' ? [r.cofog?.class || r.cofog?.group || r.cofog?.division || '', r.cofog?.status, r.cofog?.basis] : []),
      ])).sort()
      if (JSON.stringify(expected) !== JSON.stringify(received))
        throw new Error(`Budget history differs from built changes: ${scope.jurisdictionCode}/${scope.fiscalYear}/${direction}/${scope.fundCode}`)
      results.push({ jurisdictionCode: scope.jurisdictionCode, fiscalYear: scope.fiscalYear,
        direction, fundCode: scope.fundCode, rows: expected.length, asOf })
    }
  }
  return results
}
