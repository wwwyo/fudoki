import { describe, expect, test } from 'bun:test'
import { nodeRows, type Node } from './common'

const node = (over: Partial<Node>): Node => ({
  id: 'model.fudoki.x', label: 'x', kind: 'model', jurisdictionCode: null, stage: 'core',
  rows: 0, rowsByJurisdiction: null, description: '', introducesJudgment: false,
  containsJudgment: false, artifact: null, ...over,
})

describe('nodeRows', () => {
  test('団体 × 年度で切った行数を返す', () => {
    const n = node({
      rows: 31106,
      rowsByJurisdiction: {
        '132241': { total: 7634, byYear: { '2023': 1425, '2024': 1579 } },
        '132047': { total: 5613, byYear: { '2024': 5613 } },
      },
    })
    expect(nodeRows(n, '132241', 2023)).toEqual({ rows: 1425, scopedToYear: true })
    expect(nodeRows(n, '132241', null)).toEqual({ rows: 7634, scopedToYear: false })
    expect(nodeRows(n, '132047', null)).toEqual({ rows: 5613, scopedToYear: false })
  })

  test('収録していない年度は 0 行', () => {
    const n = node({ rows: 10, rowsByJurisdiction: { '132241': { total: 10, byYear: { '2023': 10 } } } })
    expect(nodeRows(n, '132241', 2019)).toEqual({ rows: 0, scopedToYear: true })
  })

  test('年度を持たない規則表は、年度を選んでも合計のまま', () => {
    const rule = node({ rows: 146, rowsByJurisdiction: null })
    expect(nodeRows(rule, '132241', 2023)).toEqual({ rows: 146, scopedToYear: false })
    const perJurisdiction = node({ rows: 255, rowsByJurisdiction: { '132241': { total: 77, byYear: null } } })
    expect(nodeRows(perJurisdiction, '132241', 2023)).toEqual({ rows: 77, scopedToYear: false })
  })

  test('その団体の行が無いモデルで、全団体の合計へ落ちない', () => {
    const n = node({ rows: 405, rowsByJurisdiction: { '132195': { total: 405, byYear: { '2023': 405 } } } })
    expect(nodeRows(n, '132241', null).rows).toBe(0)
  })
})
