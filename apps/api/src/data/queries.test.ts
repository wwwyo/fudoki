import { beforeEach, afterEach, expect, test } from 'bun:test'
import { Database } from 'bun:sqlite'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { sqliteD1 } from '../../test/database'
import { fixture } from '../../../../pipeline/verify/fixture'
import { publish } from '../../../../pipeline/publish/publish'
import { initializeSchema } from '../../../../pipeline/publish/cloudflare'
import { aggregate, pageLines, listDatasets, queryLines } from './queries'
import { aggregateQuerySchema, lineQuerySchema } from '../contract'
let directory: string, sqlite: Database, db: ReturnType<typeof sqliteD1>
const secret = 'test-cursor-secret-with-at-least-32-characters'
beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), 'fudoki-query-'))
  await fixture(directory, 'r-' + '1'.repeat(32), 100, 3)
  sqlite = new Database(':memory:')
  db = sqliteD1(sqlite)
  await initializeSchema(db)
  const objects = new Map<string, Uint8Array>()
  await publish(
    directory,
    db,
    {
      read: async (key) => objects.get(key) ?? null,
      put: async (key, path) => {
        objects.set(key, new Uint8Array(await readFile(path)))
      },
    },
    'https://example.org/manifest.json'
  )
})
afterEach(async () => {
  sqlite.close()
  await rm(directory, { recursive: true, force: true })
})
test('coarse assignments and unclassifiable expenditure each retain exactly one amount', async () => {
  sqlite.run(
    "UPDATE fiscal_settlement_expenditure_lines SET cofog_code='09' WHERE source_row=1"
  )
  sqlite.run(
    "UPDATE fiscal_settlement_expenditure_lines SET cofog_code=NULL,cofog_status='unclassifiable' WHERE source_row=2"
  )
  sqlite.run(
    "UPDATE fiscal_settlement_expenditure_lines SET cofog_code='09.1' WHERE source_row=3"
  )
  const input = lineQuerySchema.parse({ datasetIds: ['000001:settlement'] })
  const lines = await queryLines(db, await listDatasets(db), input)
  expect(lines.map((line) => line.cofog)).toMatchObject([
    { status: 'assigned', division: '09', group: '', class: '' },
    { status: 'unclassifiable', division: '', group: '', class: '' },
    { status: 'assigned', division: '09', group: '09.1', class: '' },
  ])
  expect(
    lines.every(
      (line) =>
        !('ruleId' in line.cofog!) &&
        !('phase' in line) &&
        !('sourceAmount' in line)
    )
  ).toBe(true)
  const result = await aggregate(
    db,
    aggregateQuerySchema.parse({
      datasetIds: input.datasetIds,
      groupBy: ['cofog.group'],
    })
  )
  expect(result.total).toEqual({ amount: 300, lineCount: 3 })
  expect(result.cells).toEqual([
    { keys: ['09.1'], amount: 100, lineCount: 1 },
    { keys: ['not-descended'], amount: 100, lineCount: 1 },
    { keys: ['unclassifiable'], amount: 100, lineCount: 1 },
  ])
})
test('keyset pagination rejects altered filters and cursors, and name search binds SQL metacharacters', async () => {
  const input = lineQuerySchema.parse({
    datasetIds: ['000001:settlement'],
    pageSize: 1,
  })
  const first = await pageLines(db, secret, input),
    second = await pageLines(db, secret, {
      ...input,
      cursor: first.nextCursor,
    })
  expect(first.lines[0]!.id).not.toBe(second.lines[0]!.id)
  await expect(
    pageLines(db, secret, { ...input, fund: '02', cursor: first.nextCursor })
  ).rejects.toThrow('mismatched cursor')
  await expect(
    pageLines(db, secret, {
      ...input,
      cursor: first.nextCursor!.slice(0, -6) + 'invalid',
    })
  ).rejects.toThrow('cursor')
  expect(
    (await pageLines(db, secret, { ...input, name: "' OR 1=1 --" })).lines
  ).toEqual([])
  expect(
    (await pageLines(db, secret, { ...input, name: '教育' })).lines
  ).toHaveLength(1)
})
test('strict query contracts reject obsolete amount phases and ambiguous aggregates', async () => {
  expect(() =>
    lineQuerySchema.parse({
      datasetIds: ['000001:settlement'],
      phase: 'executed',
    })
  ).toThrow()
  await expect(
    aggregate(
      db,
      aggregateQuerySchema.parse({
        datasetIds: ['000001:settlement', '000001:settlement'],
        groupBy: ['year'],
      })
    )
  ).rejects.toThrow('duplicates')
  await expect(
    aggregate(
      db,
      aggregateQuerySchema.parse({
        datasetIds: ['000001:settlement'],
        groupBy: ['year', 'year'],
      })
    )
  ).rejects.toThrow('duplicates')
  await expect(
    aggregate(
      db,
      aggregateQuerySchema.parse({
        datasetIds: ['000001:settlement'],
        groupBy: ['kan'],
      })
    )
  ).rejects.toThrow('unavailable')
})
test('hierarchy grouping keeps repeated child codes in different parent branches separate', async () => {
  sqlite.run(
    'UPDATE fiscal_settlement_expenditure_line_hierarchy SET ordinal=1'
  )
  const parent = sqlite.query(
    'INSERT INTO fiscal_settlement_expenditure_line_hierarchy VALUES(?,0,?,?,?,?)'
  )
  const lines = sqlite
    .query(
      'SELECT fiscal_line_id,source_row FROM fiscal_settlement_expenditure_lines'
    )
    .all() as {
    fiscal_line_id: string
    source_row: number
  }[]
  for (const line of lines)
    parent.run(
      line.fiscal_line_id,
      'kan',
      String(line.source_row),
      '親',
      'canonical'
    )
  const result = await aggregate(
    db,
    aggregateQuerySchema.parse({
      datasetIds: ['000001:settlement'],
      groupBy: ['moku'],
    })
  )
  expect(result.cells).toHaveLength(3)
  expect(result.cells.reduce((sum, cell) => sum + cell.amount, 0)).toBe(300)
})

test('verified many-to-many correspondence counts actuals once, applies signed changes by date, and keeps unknown initial amounts unknown', async () => {
  const { version_id: version } = sqlite
    .query('SELECT version_id FROM fiscal_jurisdiction_data')
    .get() as { version_id: string }
  const original = sqlite
    .query('SELECT * FROM fiscal_datasets')
    .get() as Record<string, unknown>
  const addDataset = (id: string, kind: string) => {
    const row = {
      ...original,
      dataset_id: id,
      document_kind: kind,
      line_count: 1,
      source_amount_kind: kind === 'budget' ? 'initial' : 'delta',
      coverage_json:
        '{"budgetHistory":"complete","verifiedThrough":"2026-12-31"}',
    }
    sqlite
      .query(
        `INSERT INTO fiscal_datasets (${Object.keys(row).join(',')}) VALUES(${Object.keys(
          row
        )
          .map(() => '?')
          .join(',')})`
      )
      .run(...(Object.values(row) as any[]))
  }
  addDataset('initial', 'budget')
  addDataset('amendment', 'supplementary')
  for (const [id, initial] of [
    ['item-a', 200],
    ['item-b', 400],
  ] as const) {
    sqlite.run(
      'INSERT INTO fiscal_expenditure_budget_items VALUES(?,?,?,?,?,?,?,?,?)',
      [id, '000001', 2026, '01', '一般会計', '[]', '[]', '[]', 'recorded']
    )
    sqlite.run(
      'INSERT INTO fiscal_initial_expenditure_budget_lines VALUES(?,?,?,?,?,?,?,?,?,?)',
      [id, 'initial', id, 1, initial, 'retained', '', '09', 'assigned', '根拠']
    )
    for (let index = 0; index < 3; index++)
      sqlite.run(
        'INSERT INTO fiscal_expenditure_settlement_links VALUES(?,?,?,?,?)',
        [
          id,
          `000001:${String(index).padStart(6, '0')}`,
          'verified',
          'group-a',
          '原典で対応を確認',
        ]
      )
  }
  for (const [id, delta, date] of [
    ['change-a', -20, '2026-05-01'],
    ['change-b', 30, '2026-10-01'],
  ] as const) {
    sqlite.run(
      'INSERT INTO fiscal_expenditure_budget_changes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
      [
        id,
        'amendment',
        'item-a',
        delta,
        'supplementary',
        date,
        1,
        1,
        null,
        null,
        null,
        '09',
        'assigned',
        '根拠',
      ]
    )
  }
  const { budgetHistory } = await import('./queries'),
    { budgetHistoryQuerySchema, budgetHistorySchema } =
      await import('../contract')
  const input = budgetHistoryQuerySchema.parse({
    jurisdictionCode: '000001',
    fiscalYear: 2026,
    direction: 'expenditure',
    asOf: '2026-06-01',
  })
  const result = budgetHistorySchema.parse(await budgetHistory(db, input))
  expect(result.comparisons[0]).toMatchObject({
    budgetAmount: 580,
    recordedChangeSubtotal: -20,
    actualAmount: 300,
    status: 'complete',
  })
  expect(result.changes).toHaveLength(1)
  expect(
    (await budgetHistory(db, { ...input, fundCode: 'missing' })).items
  ).toHaveLength(0)
  expect(
    (
      await budgetHistory(
        db,
        budgetHistoryQuerySchema.parse({ ...input, fundCode: '' })
      )
    ).items
  ).toHaveLength(0)
  for (const table of [
    'fiscal_expenditure_budget_items',
    'fiscal_expenditure_budget_changes',
  ]) {
    const rows = sqlite.query(`SELECT * FROM ${table}`).all()
    await writeFile(
      join(directory, 'api', table + '.jsonl'),
      rows.map((r) => JSON.stringify(r)).join('\n') + '\n'
    )
  }
  const { verifyBudgetChanges } =
    await import('../../../../pipeline/verify/budget-changes')
  const versions = [{ jurisdictionCode: '000001', versionId: version }]
  expect(
    (
      await verifyBudgetChanges(directory, versions, (q) =>
        budgetHistory(db, q)
      )
    )[0]!.rows
  ).toBe(2)
  await expect(
    verifyBudgetChanges(directory, versions, async (q) => {
      const response = await budgetHistory(db, q)
      response.changes[0]!.amountDelta += 1
      return response
    })
  ).rejects.toThrow('differs from built changes')

  sqlite.run(
    "UPDATE fiscal_datasets SET coverage_json='{}' WHERE dataset_id='amendment'"
  )
  expect((await budgetHistory(db, input)).comparisons[0]).toMatchObject({
    budgetAmount: null,
    actualAmount: 300,
    status: 'unconfirmed',
  })
  sqlite.run(
    'INSERT INTO fiscal_expenditure_budget_items VALUES(?,?,?,?,?,?,?,?,?)',
    ['new-item', '000001', 2026, '01', '一般会計', '[]', '[]', '[]', 'unknown']
  )
  sqlite.run(
    'INSERT INTO fiscal_expenditure_settlement_links VALUES(?,?,?,?,?)',
    ['new-item', '000001:000000', 'verified', 'group-a', '初期入力欠落']
  )
  expect(
    (await budgetHistory(db, input)).comparisons[0]!.budgetAmount
  ).toBeNull()
})

test('a version registered during budget history lookup cannot mix the response versions', async () => {
  const { budgetHistory } = await import('./queries')
  const { budgetHistoryQuerySchema } = await import('../contract')
  const old = sqlite
    .query('SELECT version_id FROM fiscal_jurisdiction_data')
    .get() as { version_id: string }
  let registered = false
  const racingDB = {
    ...db,
    prepare(sql: string) {
      if (
        !registered &&
        sql.startsWith('SELECT d.*,v.version_id FROM fiscal_datasets')
      ) {
        registered = true
        sqlite.run(
          `UPDATE fiscal_jurisdiction_data SET version_id=?,registered_at=? WHERE version_id=?`,
          ['v-' + 'b'.repeat(64), '2099-01-01T00:00:00.000Z', old.version_id]
        )
      }
      return db.prepare(sql)
    },
  }
  await expect(
    budgetHistory(
      racingDB,
      budgetHistoryQuerySchema.parse({
        jurisdictionCode: '000001',
        fiscalYear: 2026,
        direction: 'expenditure',
        asOf: '2026-06-01',
      })
    )
  ).rejects.toMatchObject({ code: 'VERSION_EXPIRED' })
  expect(registered).toBe(true)
  expect(() =>
    budgetHistoryQuerySchema.parse({
      jurisdictionCode: '000001',
      fiscalYear: 2026,
      direction: 'expenditure',
      asOf: '2026-02-30',
    })
  ).toThrow()
})
