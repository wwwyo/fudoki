import { describe, expect, test } from 'bun:test'
import type { Node } from './common'
import { assertNoNullKeyRows, assertRowSumsConsistent } from './lineage'

const node = (over: Partial<Node>): Node => ({
  id: 'model.fudoki.x', label: 'x', kind: 'model', jurisdictionCode: null, stage: 'core',
  rows: 0, rowsByJurisdiction: null, description: '', introducesJudgment: false,
  containsJudgment: false, artifact: null, ...over,
})

describe('assertNoNullKeyRows', () => {
  test('列がある行に NULL が無ければ何もしない', () => {
    const counts = [{ node: 0, fiscal_year: '2023', jurisdiction_code: '132241', n_rows: 10 }]
    expect(() => assertNoNullKeyRows(counts, () => true, () => true)).not.toThrow()
  })

  test('列を持たないと分かっているノードの NULL は無視する（列そのものが無い）', () => {
    const counts = [{ node: 0, fiscal_year: null, jurisdiction_code: null, n_rows: 146 }]
    expect(() => assertNoNullKeyRows(counts, () => false, () => false)).not.toThrow()
  })

  test('fiscal_year 列があるのに値が NULL の行があれば止める', () => {
    const counts = [{ node: 0, fiscal_year: null, jurisdiction_code: '132241', n_rows: 1 }]
    expect(() => assertNoNullKeyRows(counts, () => true, () => true)).toThrow(/fiscal_year/)
  })

  test('jurisdiction_code 列があるのに値が NULL の行があれば止める', () => {
    const counts = [{ node: 0, fiscal_year: '2023', jurisdiction_code: null, n_rows: 1 }]
    expect(() => assertNoNullKeyRows(counts, () => true, () => true)).toThrow(/jurisdiction_code/)
  })
})

describe('assertRowSumsConsistent', () => {
  test('rows と Σ(rowsByJurisdiction) が一致すれば通る', () => {
    const n = node({
      rows: 13247,
      rowsByJurisdiction: {
        '132241': { total: 7634, byYear: { '2023': 1425, '2024': 6209 } },
        '132047': { total: 5613, byYear: { '2024': 5613 } },
      },
    })
    expect(() => assertRowSumsConsistent([n])).not.toThrow()
  })

  test('rows が Σ(rowsByJurisdiction) と食い違えば止める', () => {
    const n = node({
      rows: 999,
      rowsByJurisdiction: { '132241': { total: 7634, byYear: null } },
    })
    expect(() => assertRowSumsConsistent([n])).toThrow(/rows/)
  })

  test('byYear の合計が total と食い違えば止める', () => {
    const n = node({
      rows: 7634,
      rowsByJurisdiction: { '132241': { total: 7634, byYear: { '2023': 1, '2024': 2 } } },
    })
    expect(() => assertRowSumsConsistent([n])).toThrow(/total/)
  })

  test('団体にも年度にも依らない規則表（rowsByJurisdiction が null）はスキップする', () => {
    const n = node({ rows: 146, rowsByJurisdiction: null })
    expect(() => assertRowSumsConsistent([n])).not.toThrow()
  })

  test('total が null（行数が取れていない）なら、そこは比較せず通す', () => {
    const n = node({
      rows: null,
      rowsByJurisdiction: { '132195': { total: null as unknown as number, byYear: { '2020': null as unknown as number } } },
    })
    expect(() => assertRowSumsConsistent([n])).not.toThrow()
  })
})
