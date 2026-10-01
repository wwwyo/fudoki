import { beforeEach, afterEach, expect, test } from 'bun:test'
import { Database } from 'bun:sqlite'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { sqliteD1 } from '../../apps/api/test/database'
import {
  jurisdictions,
  listDatasets,
  pageLines,
  aggregate,
  files,
  resolveVersions,
} from '../../apps/api/src/data/queries'
import {
  lineQuerySchema,
  aggregateQuerySchema,
} from '../../apps/api/src/contract'
import { fixture } from '../verify/fixture'
import { initializeSchema } from './cloudflare'
import { publish, type ObjectStore } from './publish'

let root: string,
  sqlite: Database,
  db: ReturnType<typeof sqliteD1>,
  store: ObjectStore,
  objects: Map<string, Uint8Array>,
  puts: number
const url = 'https://example.org/manifest.json',
  secret = 'fixture-cursor-secret-at-least-32-characters'
beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), 'fudoki-import-'))
  sqlite = new Database(':memory:')
  db = sqliteD1(sqlite)
  await initializeSchema(db)
  objects = new Map()
  puts = 0
  store = {
    read: async (key) => objects.get(key) ?? null,
    put: async (key, path) => {
      puts++
      objects.set(key, new Uint8Array(await readFile(path)))
    },
  }
})
afterEach(async () => {
  sqlite.close()
  await rm(root, { recursive: true, force: true })
})
test('new versions are visible during import, and interruption resumes without duplicate records or timestamp promotion', async () => {
  const path = join(root, 'a')
  const candidate = await fixture(path, 'r-' + '1'.repeat(32), 100, 3)
  await expect(
    publish(
      path,
      db,
      store,
      url,
      (event) => {
        if (
          event.stage === 'table' &&
          event.table === 'fiscal_settlement_expenditure_lines'
        )
          throw new Error('interrupted')
      },
      { registeredAt: '2026-01-01T00:00:00.000Z' }
    )
  ).rejects.toThrow('interrupted')
  expect((await jurisdictions(db)).jurisdictions[0]!.versionId).toBe(
    candidate.versions[0]!.versionId
  )
  expect(
    (
      await pageLines(
        db,
        secret,
        lineQuerySchema.parse({ datasetIds: ['000001:settlement'] })
      )
    ).lines
  ).toHaveLength(3)
  await publish(path, db, store, url, undefined, {
    registeredAt: '2026-02-01T00:00:00.000Z',
  })
  expect(
    sqlite
      .query('SELECT count(*) n FROM fiscal_settlement_expenditure_lines')
      .get()
  ).toEqual({ n: 3 })
  expect(
    sqlite.query('SELECT registered_at FROM fiscal_jurisdiction_versions').get()
  ).toEqual({ registered_at: '2026-01-01T00:00:00.000Z' })
  expect(puts).toBe(2)
  const result = await aggregate(
    db,
    aggregateQuerySchema.parse({
      datasetIds: ['000001:settlement'],
      groupBy: ['cofog.division'],
    })
  )
  expect(result.total).toEqual({ amount: 300, lineCount: 3 })
  expect(result.cells).toEqual([{ keys: ['09'], amount: 300, lineCount: 3 }])
})
test('each municipality updates independently; old versions and cursor selections remain readable', async () => {
  const a = await fixture(join(root, 'a'), 'r-' + '1'.repeat(32), 100, 3)
  const other = await fixture(
    join(root, 'other'),
    'r-' + '2'.repeat(32),
    400,
    2,
    '他団体',
    '000002'
  )
  await publish(join(root, 'a'), db, store, url, undefined, {
    registeredAt: '2026-01-01T00:00:00.000Z',
  })
  await publish(join(root, 'other'), db, store, url, undefined, {
    registeredAt: '2026-01-01T00:00:00.000Z',
  })
  const input = lineQuerySchema.parse({
    datasetIds: ['000001:settlement'],
    pageSize: 1,
  })
  const first = await pageLines(db, secret, input)
  const b = await fixture(join(root, 'b'), 'r-' + '3'.repeat(32), 200, 3)
  await publish(join(root, 'b'), db, store, url, undefined, {
    registeredAt: '2026-02-01T00:00:00.000Z',
  })
  expect(await resolveVersions(db)).toEqual([
    { jurisdictionCode: '000001', versionId: b.versions[0]!.versionId },
    { jurisdictionCode: '000002', versionId: other.versions[0]!.versionId },
  ])
  const second = await pageLines(db, secret, {
    ...input,
    cursor: first.nextCursor,
  })
  expect(second.lines[0]!.amount).toBe(100)
  expect(second.lines[0]!.versionId).toBe(a.versions[0]!.versionId)
  expect((await pageLines(db, secret, input)).lines[0]!.amount).toBe(200)
  expect(
    (await listDatasets(db)).find((d) => d.jurisdictionCode === '000002')!
      .versionId
  ).toBe(other.versions[0]!.versionId)
  await publish(join(root, 'a'), db, store, url, undefined, {
    registeredAt: '2026-03-01T00:00:00.000Z',
  })
  expect((await resolveVersions(db))[0]!.versionId).toBe(
    b.versions[0]!.versionId
  )
  const download = await files(db, 'https://download.example.org', {
    versions: [
      { jurisdictionCode: '000001', versionId: a.versions[0]!.versionId },
    ],
    jurisdictionCode: '000001',
  })
  expect(download.files[0]!.url).toContain(
    `/fiscal/000001/${a.versions[0]!.packageId}/`
  )
  expect(download.manifests[0]!.url).toBe(url)
})
test('retry rejects different contents at a previously registered row or immutable object', async () => {
  const path = join(root, 'a')
  await fixture(path, 'r-' + '1'.repeat(32), 100, 3)
  await publish(path, db, store, url)
  sqlite.run('UPDATE fiscal_settlement_expenditure_lines SET amount=101')
  await expect(publish(path, db, store, url)).rejects.toThrow(
    'Existing content differs'
  )
  objects.set([...objects.keys()][0]!, new TextEncoder().encode('tampered'))
  await expect(publish(path, db, store, url)).rejects.toThrow(
    'immutable object differs'
  )
})
test('wrong document direction and unknown COFOG foreign keys are rejected', async () => {
  const path = join(root, 'a')
  await fixture(path, 'r-' + '1'.repeat(32), 100, 3)
  await publish(path, db, store, url)
  expect(() =>
    sqlite.run("UPDATE fiscal_settlement_expenditure_lines SET cofog_code='99'")
  ).toThrow()
  expect(() =>
    sqlite.run(
      'INSERT INTO fiscal_settlement_revenue_lines SELECT version_id,fiscal_line_id,dataset_id,source_row,fund_code,fund_label,amount,consolidation,counterpart_fund FROM fiscal_settlement_expenditure_lines'
    )
  ).toThrow('direction or document')
})
