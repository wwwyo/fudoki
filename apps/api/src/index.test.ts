import { beforeEach, afterEach, expect, test, spyOn } from 'bun:test'
import { Database } from 'bun:sqlite'
import { readFile, mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { TABLES, TABLE_COLUMNS } from '@fudoki/data-contracts'
import { fixture } from '../../../pipeline/verify/fixture'
import { sqliteD1 } from '../test/database'
import type { Env } from './env'
import app from './index'
import { contract } from './contract'
import { z } from 'zod'

const id = 'r-' + '1'.repeat(32)
let directory: string, sqlite: Database, env: Env, log: ReturnType<typeof spyOn>
beforeEach(async () => {
  log = spyOn(console, 'log').mockImplementation(() => {})
  directory = await mkdtemp(join(tmpdir(), 'fudoki-http-test-'))
  const manifest = await fixture(directory, id, 100, 2)
  sqlite = new Database(':memory:')
  sqlite.exec(
    await readFile(
      new URL('../../../packages/data-contracts/schema.sql', import.meta.url),
      'utf8'
    )
  )
  sqlite.run("INSERT INTO releases VALUES(?,1,'published',?,NULL,?,?)", [
    id,
    `https://raw.githubusercontent.com/wwwyo/fudoki/${'a'.repeat(40)}/pipeline/publish/manifest.json`,
    'a'.repeat(40),
    'b'.repeat(64),
  ])
  const masters = (
    await readFile(join(directory, 'api/jurisdictions.jsonl'), 'utf8')
  )
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line))
  for (const master of masters)
    sqlite.run('INSERT INTO jurisdictions VALUES(?,?,?)', [
      master.jurisdiction_code,
      master.name,
      master.ocd_id,
    ])
  const codes = (
    await readFile(join(directory, 'api/cofog_codes.jsonl'), 'utf8')
  )
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line))
  for (const row of codes)
    sqlite.run('INSERT INTO cofog_codes VALUES(?,?,?,?)', [
      row.code,
      row.label,
      row.level,
      row.parent_code,
    ])
  for (const table of TABLES) {
    const columns = TABLE_COLUMNS[table],
      sql = `INSERT INTO "${table}"(release_id,${columns.map((c) => `"${c}"`).join(',')}) VALUES(${columns.map(() => '?').join(',')},?)`
    for (const text of (
      await readFile(join(directory, 'api', table + '.jsonl'), 'utf8')
    )
      .split('\n')
      .filter(Boolean)) {
      const row = JSON.parse(text)
      sqlite.run(sql, [id, ...columns.map((c) => row[c])])
    }
  }
  for (const file of manifest.files)
    sqlite.run('INSERT INTO files VALUES(?,?,?,?,?,?)', [
      id,
      file.path,
      file.objectKey,
      file.sha256,
      file.bytes,
      file.contentType,
    ])
  sqlite.run('INSERT INTO active_release(singleton,release_id) VALUES(1,?)', [
    id,
  ])
  env = {
    DB: sqliteD1(sqlite),
    QUERY_FINGERPRINT: 'e'.repeat(64),
    CURSOR_SECRET: 'test-secret-at-least-32-characters-long',
    DOWNLOAD_BASE_URL: 'https://download.example.org',
    API_KEYS: {
      async get() {
        return null
      },
      async put() {},
    },
    RATE_LIMIT_ANONYMOUS: {
      async limit() {
        return { success: true }
      },
    },
    RATE_LIMIT_AUTHENTICATED: {
      async limit() {
        return { success: true }
      },
    },
  }
})
afterEach(async () => {
  sqlite.close()
  log.mockRestore()
  await rm(directory, { recursive: true, force: true })
})
test('HTTP contract, datasets and files expose one release without an assets or R2 binding', async () => {
  const response = await app.request('/v0/contract', {}, env)
  expect(await response.json()).toMatchObject({
    contractVersion: 1,
    queryFingerprint: 'e'.repeat(64),
    databaseIdentity: expect.any(String),
  })
  const datasets = await app.request(
    '/v0/fiscal-datasets?jurisdictionCode=000001',
    {},
    env
  )
  expect(datasets.status).toBe(200)
  const data = contract.listFiscalDatasets['~orpc'].outputSchema!.parse(
    await datasets.json()
  )
  expect(data.releaseId).toBe(id)
  expect(data.datasets[0]?.documentKind).toBe('settlement')
  const files = await app.request('/v0/files', {}, env)
  expect(files.status).toBe(200)
  expect(
    contract.listFiles['~orpc'].outputSchema!.parse(await files.json())
      .manifestUrl
  ).toBe(
    `https://raw.githubusercontent.com/wwwyo/fudoki/${'a'.repeat(40)}/pipeline/publish/manifest.json`
  )
  expect((await app.request('/v0/budgets', {}, env)).status).toBe(404)
  expect(
    (await app.request('/v0/datapackages/000001/expenditure.csv', {}, env))
      .status
  ).toBe(404)
})
test('HTTP query returns bound results and rejects unknown filters and unavailable phases', async () => {
  const request = (body: unknown) =>
    app.request(
      '/v0/fiscal-lines/query',
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      },
      env
    )
  const result = await request({
    datasetIds: ['fixture-dataset'],
    phase: 'executed',
    pageSize: 1,
  })
  expect(result.status).toBe(200)
  const body = contract.getFiscalLines['~orpc'].outputSchema!.parse(
    await result.json()
  )
  expect(body.lines[0]?.value).toBe(100)
  expect(body.nextCursor).toBeString()
  expect(
    (await request({ datasetIds: ['fixture-dataset'], phase: 'approved' }))
      .status
  ).toBe(400)
  expect(
    (
      await request({
        datasetIds: ['fixture-dataset'],
        unrecognizedFilter: 'ignored?',
      })
    ).status
  ).toBe(400)
})
test('MCP exposes the same fiscal tools in legacy and modern transports', async () => {
  const legacy = await app.request(
    '/mcp',
    {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        accept: 'application/json, text/event-stream',
        'mcp-protocol-version': '2025-11-25',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'tools/list',
        params: {},
      }),
    },
    env
  )
  const list = z.object({
    result: z.object({ tools: z.array(z.object({ name: z.string() })) }),
  })
  expect(legacy.status).toBe(200)
  const old = list.parse(await legacy.json())
  const modern = await app.request(
    '/mcp',
    {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        accept: 'application/json',
        'mcp-method': 'tools/list',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 2,
        method: 'tools/list',
        params: {
          _meta: {
            'io.modelcontextprotocol/protocolVersion': '2026-07-28',
            'io.modelcontextprotocol/clientCapabilities': {},
          },
        },
      }),
    },
    env
  )
  expect(modern.status).toBe(200)
  const current = list.parse(await modern.json())
  const expected = [
    'aggregate_fiscal_datasets',
    'get_fiscal_dataset',
    'get_fiscal_lines',
    'list_files',
    'list_fiscal_datasets',
    'list_jurisdictions',
    'search_fiscal_lines',
  ]
  expect(old.result.tools.map((t: any) => t.name).sort()).toEqual(expected)
  expect(current.result.tools.map((t: any) => t.name).sort()).toEqual(expected)
  const called = await app.request(
    '/mcp',
    {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        accept: 'application/json',
        'mcp-method': 'tools/call',
        'mcp-name': 'get_fiscal_lines',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 3,
        method: 'tools/call',
        params: {
          name: 'get_fiscal_lines',
          arguments: {
            datasetIds: ['fixture-dataset'],
            phase: 'executed',
            pageSize: 1,
          },
          _meta: {
            'io.modelcontextprotocol/protocolVersion': '2026-07-28',
            'io.modelcontextprotocol/clientCapabilities': {},
          },
        },
      }),
    },
    env
  )
  expect(called.status).toBe(200)
  const tool = z
    .object({
      result: z.object({
        structuredContent: contract.getFiscalLines['~orpc'].outputSchema!,
      }),
    })
    .parse(await called.json())
  expect(tool.result.structuredContent.releaseId).toBe(id)
  expect(tool.result.structuredContent.lines[0]?.value).toBe(100)
  const rejected = await app.request(
    '/mcp',
    { method: 'POST', headers: { origin: 'https://untrusted.example.org' } },
    env
  )
  expect(rejected.status).toBe(403)
})
