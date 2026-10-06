import { describe, expect, test } from 'bun:test'
import type { Node, SourceInput } from './common'
import {
  assertNoNullKeyRows,
  assertRowSumsConsistent,
  collectOriginGroups,
  leadOf,
  stageOf,
} from './lineage'

describe('stageOf', () => {
  test('モデルの実際のディレクトリを dbt の層として表示する', () => {
    for (const stage of ['staging', 'intermediate', 'marts'] as const) {
      expect(
        stageOf({
          name: 'example',
          resource_type: 'model',
          path: `${stage}/budget/example.sql`,
        })
      ).toBe(stage)
    }
  })

  test('取り込みと参照表をモデルの層と区別して配置する', () => {
    expect(stageOf({ name: 'raw', resource_type: 'source' })).toBe('ingestion')
    expect(stageOf({ name: 'account_map', resource_type: 'seed' })).toBe(
      'intermediate'
    )
  })

  test('旧ディレクトリや未宣言の層を推測で割り当てない', () => {
    for (const stage of ['core', 'package', 'unknown']) {
      expect(() =>
        stageOf({
          name: 'example',
          resource_type: 'model',
          path: `${stage}/budget/example.sql`,
        })
      ).toThrow('置き場が段の宣言に無い')
    }
  })
})

const node = (over: Partial<Node>): Node => ({
  id: 'model.fudoki.x',
  label: 'x',
  kind: 'model',
  jurisdictionCode: null,
  stage: 'intermediate',
  rows: 0,
  rowsByJurisdiction: null,
  description: '',
  introducesJudgment: false,
  containsJudgment: false,
  artifact: null,
  ...over,
})

describe('leadOf', () => {
  test('冒頭の `--` 行をリードとして取る', () => {
    expect(leadOf('-- 科目の名称と法定マスタへの対応\nselect 1')).toBe(
      '科目の名称と法定マスタへの対応'
    )
  })

  test('config の jinja と空行は飛ばして最初の `--` 行に着く', () => {
    const sql =
      "{{ config(materialized = 'external') }}\n\n-- 正本（歳出）\nselect 1"
    expect(leadOf(sql)).toBe('正本（歳出）')
  })

  test('複数行の jinja ブロックも丸ごと飛ばす', () => {
    const sql = '{% set x =\n  1 %}\n-- リード\nselect 1'
    expect(leadOf(sql)).toBe('リード')
  })

  test('コメントの前に別の文があるならリードとはみなさない', () => {
    expect(leadOf('select 1\n-- 説明')).toBe('')
  })

  test('リードの無い SQL では空を返す', () => {
    expect(leadOf('{{ config() }}\nselect 1')).toBe('')
    expect(leadOf(undefined)).toBe('')
  })
})

describe('assertNoNullKeyRows', () => {
  test('列がある行に NULL が無ければ何もしない', () => {
    const counts = [
      { node: 0, fiscal_year: '2023', jurisdiction_code: '132241', n_rows: 10 },
    ]
    expect(() =>
      assertNoNullKeyRows(
        counts,
        () => true,
        () => true
      )
    ).not.toThrow()
  })

  test('列を持たないと分かっているノードの NULL は無視する（列そのものが無い）', () => {
    const counts = [
      { node: 0, fiscal_year: null, jurisdiction_code: null, n_rows: 146 },
    ]
    expect(() =>
      assertNoNullKeyRows(
        counts,
        () => false,
        () => false
      )
    ).not.toThrow()
  })

  test('fiscal_year 列があるのに値が NULL の行があれば止める', () => {
    const counts = [
      { node: 0, fiscal_year: null, jurisdiction_code: '132241', n_rows: 1 },
    ]
    expect(() =>
      assertNoNullKeyRows(
        counts,
        () => true,
        () => true
      )
    ).toThrow(/fiscal_year/)
  })

  test('jurisdiction_code 列があるのに値が NULL の行があれば止める', () => {
    const counts = [
      { node: 0, fiscal_year: '2023', jurisdiction_code: null, n_rows: 1 },
    ]
    expect(() =>
      assertNoNullKeyRows(
        counts,
        () => true,
        () => true
      )
    ).toThrow(/jurisdiction_code/)
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
      rowsByJurisdiction: {
        '132241': { total: 7634, byYear: { '2023': 1, '2024': 2 } },
      },
    })
    expect(() => assertRowSumsConsistent([n])).toThrow(/total/)
  })

  test('団体にも年度にも依らない規則表（rowsByJurisdiction が null）はスキップする', () => {
    const n = node({ rows: 146, rowsByJurisdiction: null })
    expect(() => assertRowSumsConsistent([n])).not.toThrow()
  })

  test('行数を数えようが無いノード（rows も rowsByJurisdiction も null）は通す', () => {
    const n = node({ rows: null, rowsByJurisdiction: null })
    expect(() => assertRowSumsConsistent([n])).not.toThrow()
  })

  test('団体の total が数値でなければ止める', () => {
    const n = node({
      rows: null,
      rowsByJurisdiction: { '132195': { total: Number.NaN, byYear: null } },
    })
    expect(() => assertRowSumsConsistent([n])).toThrow(/数値でない/)
  })

  test('年度の行数が数値でなければ止める', () => {
    const n = node({
      rows: 10,
      rowsByJurisdiction: {
        '132195': { total: 10, byYear: { '2020': Number.NaN } },
      },
    })
    expect(() => assertRowSumsConsistent([n])).toThrow(/2020年度/)
  })
})

describe('collectOriginGroups', () => {
  const src = (id: string, label = 'expenditure'): Node =>
    node({
      id,
      label,
      kind: 'source',
      jurisdictionCode: /\.raw_(\d{6})/.exec(id)?.[1] ?? null,
      stage: 'ingestion',
    })
  const prov = (sha: string, over: Partial<SourceInput> = {}): SourceInput => ({
    jurisdiction_code: '999999',
    fiscal_year: 2024,
    direction: 'expenditure',
    resource_name: 'r',
    request_url: 'u',
    status: 200,
    bytes: 1,
    sha256: sha.repeat(64),
    fetched_at: 't',
    roundtrip_verified: true,
    rows: 1,
    ...over,
  })

  test('1ソースが複数年度のファイルを持つとき、証跡（ファイル）ごとに別グループ', () => {
    const groups = collectOriginGroups(
      [src('source.fudoki.raw_999999.expenditure')],
      [prov('a', { fiscal_year: 2023 }), prov('b', { fiscal_year: 2024 })]
    )
    expect(groups.size).toBe(2)
  })

  test('同じファイルを歳出・歳入が共有するときは1グループ', () => {
    const groups = collectOriginGroups(
      [
        src('source.fudoki.raw_999999.expenditure'),
        src('source.fudoki.raw_999999.revenue', 'revenue'),
      ],
      [prov('a'), prov('a', { direction: 'revenue', resource_name: 'r2' })]
    )
    expect(groups.size).toBe(1)
    expect([...groups.values()][0]!.map((m) => m.src.id)).toEqual([
      'source.fudoki.raw_999999.expenditure',
      'source.fudoki.raw_999999.revenue',
    ])
  })

  test('同じ sha256 でも団体が違えば別グループ', () => {
    const groups = collectOriginGroups(
      [
        src('source.fudoki.raw_999999.expenditure'),
        src('source.fudoki.raw_888888.expenditure'),
      ],
      [prov('a'), prov('a', { jurisdiction_code: '888888' })]
    )
    expect(groups.size).toBe(2)
  })
})
