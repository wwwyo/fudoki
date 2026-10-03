import { expect, test } from 'bun:test'
import { buildColumnDocs } from './columns'
import type { Manifest } from './lineage'

test('marts retain column meanings without descriptors and distinguish expenditure from revenue', () => {
  const manifest: Manifest = {
    nodes: {
      expenditure: {
        name: 'csv_132195_initial_expenditure_budget',
        resource_type: 'model',
        path: 'marts/csv/expenditure.sql',
        columns: {},
      },
      revenue: {
        name: 'csv_132195_initial_revenue_budget',
        resource_type: 'model',
        path: 'marts/csv/revenue.sql',
        columns: {},
      },
    },
    sources: {},
  }
  const fields = {
    'expenditure:setsu_code': { title: '節', description: '歳出の経済的性質' },
    'revenue:setsu_code': { title: '節', description: '歳入の財源' },
    amount: { title: '金額', description: '円' },
  }
  const columns = new Map(
    Object.values(manifest.nodes).map((node) => [
      node.name,
      ['setsu_code', 'amount'],
    ])
  )
  const docs = buildColumnDocs(manifest, fields, columns)
  expect(
    docs.resources.csv_132195_initial_expenditure_budget?.setsu_code
      ?.description
  ).toBe('歳出の経済的性質')
  expect(
    docs.resources.csv_132195_initial_revenue_budget?.setsu_code?.description
  ).toBe('歳入の財源')
  expect(docs.canonical.setsu_code).toBeUndefined()
  expect(docs.canonical.amount?.description).toBe('円')
})
