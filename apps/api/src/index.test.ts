/**
 * HTTP レベルの統合テスト。dist/assets（`bun run build` の生成物）を
 * 本物の assets として読み、Worker の fetch を直接叩く。
 * PRD の Acceptance Criteria と design doc の異常系の応答表に対応する。
 */
import { beforeAll, describe, expect, test } from 'bun:test'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import app from './index'
import type { Env } from './assets'

const ASSETS_DIR = join(import.meta.dir, '../dist/assets')
const DATA_DIR = join(import.meta.dir, '../../../data/budget/datapackages')

const env: Env = {
  ASSETS: {
    async fetch(input: Request | URL | string) {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url)
      const path = join(ASSETS_DIR, url.pathname)
      if (!path.startsWith(ASSETS_DIR) || !existsSync(path)) return new Response(null, { status: 404 })
      return new Response(readFileSync(path))
    },
  },
}

const get = (path: string) => app.request(`https://api.fudoki.dev${path}`, { method: 'GET' }, env)

const q = (filter: string, extra: Record<string, string> = {}) =>
  new URLSearchParams({ filter, ...extra }).toString()

/**
 * テスト内の独立算出用の素朴な CSV 分割。cofog.csv の引用符セルは空の
 * cofog_division（`""`）だけでコンマを含まない（実測: 全行で列数が一致）ため、
 * 素朴な split でも列は崩れない。`""` は2文字の文字列として読まれるが、
 * division の比較値（"09" など）と衝突しないので数え上げに影響しない。
 */
function countCofogRows(jurisdictions: string[], division: string): number {
  let count = 0
  for (const j of jurisdictions) {
    const lines = readFileSync(join(DATA_DIR, j, 'cofog.csv'), 'utf8').trimEnd().split('\n')
    const header = lines[0]!.split(',')
    const iDir = header.indexOf('direction')
    const iDiv = header.indexOf('cofog_division')
    for (const line of lines.slice(1)) {
      const cells = line.split(',')
      if (cells[iDir] === 'expenditure' && cells[iDiv] === division) count++
    }
  }
  return count
}

beforeAll(() => {
  if (!existsSync(join(ASSETS_DIR, 'meta/jurisdictions.json'))) {
    throw new Error('dist/assets is missing. Run `bun run build` first (the test script does this).')
  }
})

describe('jurisdictions', () => {
  test('list returns both jurisdictions with revision and discovery path', async () => {
    const res = await get('/v0/jurisdictions')
    expect(res.status).toBe(200)
    const body = await res.json() as { jurisdictions: { id: string; datapackagePath: string; resources: string[] }[]; revision: string }
    expect(body.revision).toMatch(/^[0-9a-f]{40}/)
    const ids = body.jurisdictions.map((j) => j.id).sort()
    expect(ids).toEqual(['132047', '132195'])
    for (const j of body.jurisdictions) {
      expect(j.resources).toContain('datapackage.json')
      expect(j.datapackagePath).toBe(`/v0/datapackages/${j.id}/datapackage.json`)
    }
  })

  test('detail carries required caveat categories, and no per-year state', async () => {
    const res = await get('/v0/jurisdictions/132195')
    expect(res.status).toBe(200)
    const { jurisdiction } = await res.json() as { jurisdiction: { caveats: { category: string }[] } & Record<string, unknown> }
    const categories = new Set(jurisdiction.caveats.map((c) => c.category))
    for (const required of ['coverage', 'phaseSemantics', 'classification', 'sourceAndLicense']) {
      expect(categories.has(required)).toBe(true)
    }
    // 年度は budgets へ移した。団体の表現は収録が増えても変わらない
    expect(jurisdiction['fiscalYears']).toBeUndefined()
    expect(jurisdiction['classificationRates']).toBeUndefined()
  })

  test('unknown jurisdiction is 404', async () => {
    expect((await get('/v0/jurisdictions/999999')).status).toBe(404)
  })
})

describe('budgets (root collection = coverage)', () => {
  test('list with jurisdiction filter is the coverage, with classification rates', async () => {
    const res = await get(`/v0/budgets?${q('jurisdiction = "132195"')}`)
    expect(res.status).toBe(200)
    const body = await res.json() as { budgets: { id: string; name: string; fiscalYear: string; directions: string[]; amountPhase: string; classificationRate: Record<string, { lines: number; amount: number }> }[]; revision: string }
    expect(body.budgets.map((b) => b.fiscalYear)).toEqual(['2018', '2019', '2020', '2021', '2022', '2023'])
    const b2023 = body.budgets.find((b) => b.fiscalYear === '2023')!
    expect(b2023.id).toBe('132195:2023')
    expect(b2023.name).toBe('budgets/132195:2023')
    expect(b2023.directions.sort()).toEqual(['expenditure', 'revenue'])
    expect(b2023.amountPhase).toBe('adjusted')
    expect(b2023.classificationRate['assigned']!.lines).toBeGreaterThan(0)
    expect(b2023.classificationRate['unclassifiable']!.lines).toBeGreaterThan(0)
  })

  test('unfiltered list spans jurisdictions; fiscalYear narrows it', async () => {
    const all = await (await get('/v0/budgets')).json() as { budgets: { jurisdictionId: string }[] }
    expect(new Set(all.budgets.map((b) => b.jurisdictionId))).toEqual(new Set(['132047', '132195']))
    const y = await (await get(`/v0/budgets?${q('fiscalYear = 2024')}`)).json() as { budgets: { id: string }[] }
    expect(y.budgets.map((b) => b.id)).toEqual(['132047:2024'])
  })

  test('get by id; unknown budget and unsupported filters fail', async () => {
    const res = await get('/v0/budgets/132195:2023')
    expect(res.status).toBe(200)
    const { budget } = await res.json() as { budget: { fiscalYear: string } }
    expect(budget.fiscalYear).toBe('2023')
    expect((await get('/v0/budgets/132195:1999')).status).toBe(404)
    expect((await get(`/v0/budgets?${q('direction = expenditure')}`)).status).toBe(400)
  })
})

describe('cross-budget statement (wildcard parent)', () => {
  test('division filter returns all matching lines across pages, without silent truncation', async () => {
    const seen = new Set<string>()
    let pageToken: string | undefined
    let pages = 0
    let revision = ''
    do {
      const params = q('cofog.division = "09"', pageToken ? { pageToken } : {})
      const res = await get(`/v0/budgets/-/statement?${params}`)
      expect(res.status).toBe(200)
      const body = await res.json() as { scope: string; lines: { budgetLineId: string; budget: string }[]; nextPageToken?: string; revision: string }
      expect(body.scope).toBe('crossBudget')
      revision = body.revision
      for (const line of body.lines) {
        expect(seen.has(line.budgetLineId)).toBe(false)
        seen.add(line.budgetLineId)
      }
      pageToken = body.nextPageToken
      pages++
    } while (pageToken !== undefined)
    expect(pages).toBeGreaterThan(1)
    // budgetLineId の先頭セグメントが団体コード — 両団体が含まれる
    expect(new Set([...seen].map((n) => n.split(':')[0]))).toEqual(new Set(['132047', '132195']))
    // 独立に cofog リソースから数えた行数と一致する（黙った欠落が無い）
    expect(seen.size).toBe(countCofogRows(['132047', '132195'], '09'))
    expect(revision).toMatch(/^[0-9a-f]{40}/)
  })

  test('fiscalYear narrows the series', async () => {
    const res = await get(`/v0/budgets/-/statement?${q('cofog.division = "09" AND fiscalYear = 2023')}`)
    const body = await res.json() as { lines: { fiscalYear: string }[] }
    expect(body.lines.length).toBeGreaterThan(0)
    expect(body.lines.every((l) => l.fiscalYear === '2023')).toBe(true)
  })

  test('empty result set: 200 with empty array and no token', async () => {
    const res = await get(`/v0/budgets/-/statement?${q('cofog.division = "09" AND fiscalYear = 1999')}`)
    expect(res.status).toBe(200)
    const body = await res.json() as { lines: unknown[]; nextPageToken?: string }
    expect(body.lines).toEqual([])
    expect(body.nextPageToken).toBeUndefined()
  })

  test('missing division / unsupported fields / bad syntax are 400', async () => {
    expect((await get('/v0/budgets/-/statement')).status).toBe(400)
    expect((await get(`/v0/budgets/-/statement?${q('fiscalYear = 2023')}`)).status).toBe(400)
    expect((await get(`/v0/budgets/-/statement?${q('cofog.division = "09" AND direction = expenditure')}`)).status).toBe(400)
    expect((await get(`/v0/budgets/-/statement?${q('cofog.division = "99"')}`)).status).toBe(400)
    expect((await get(`/v0/budgets/-/statement?${q('cofog.division != "09"')}`)).status).toBe(400)
    expect((await get(`/v0/budgets/-/statement?${q('cofog.division = "09" AND jurisdiction = "132195"')}`)).status).toBe(400)
  })

  test('pageToken bound to another filter is 400; another revision is 410', async () => {
    const first = await get(`/v0/budgets/-/statement?${q('cofog.division = "09"', { pageSize: '10' })}`)
    const { nextPageToken } = await first.json() as { nextPageToken: string }
    expect(nextPageToken).toBeDefined()

    const misused = await get(`/v0/budgets/-/statement?${q('cofog.division = "10"', { pageToken: nextPageToken })}`)
    expect(misused.status).toBe(400)

    const decoded = JSON.parse(atob(nextPageToken.replaceAll('-', '+').replaceAll('_', '/'))) as Record<string, unknown>
    const stale = btoa(JSON.stringify({ ...decoded, rev: '0'.repeat(40) }))
    const staleRes = await get(`/v0/budgets/-/statement?${q('cofog.division = "09"', { pageToken: stale })}`)
    expect(staleRes.status).toBe(410)

    const garbage = await get(`/v0/budgets/-/statement?${q('cofog.division = "09"', { pageToken: '!!!' })}`)
    expect(garbage.status).toBe(400)

    // 負の offset や非整数を細工したトークンは 500 ではなく 400 で弾く
    for (const off of [-1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
      const crafted = btoa(JSON.stringify({ ...decoded, off }))
      const res = await get(`/v0/budgets/-/statement?${q('cofog.division = "09"', { pageToken: crafted })}`)
      expect(res.status).toBe(400)
    }
  })

  test('pageSize: clamps above 1000, rejects negatives', async () => {
    const res = await get(`/v0/budgets/-/statement?${q('cofog.division = "09"', { pageSize: '2' })}`)
    const body = await res.json() as { lines: unknown[] }
    expect(body.lines.length).toBe(2)
    expect((await get(`/v0/budgets/-/statement?${q('cofog.division = "09"', { pageSize: '-1' })}`)).status).toBe(400)
    expect((await get(`/v0/budgets/-/statement?${q('cofog.division = "09"', { pageSize: '5000' })}`)).status).toBe(200)
  })
})

describe('budget statement', () => {
  test('full listing preserves jurisdiction-specific shape and completeness', async () => {
    const seen: string[] = []
    let pageToken: string | undefined
    do {
      const params = q('direction = expenditure', pageToken ? { pageToken } : {})
      const res = await get(`/v0/budgets/132195:2023/statement?${params}`)
      expect(res.status).toBe(200)
      const body = await res.json() as { scope: string; lines: { budgetLineId: string; hierarchy: { level: string }[]; dimensions: { name: string }[]; amounts: { phase: string }[] }[]; nextPageToken?: string }
      expect(body.scope).toBe('budget')
      for (const line of body.lines) {
        seen.push(line.budgetLineId)
        expect(line.hierarchy.map((h) => h.level)).toContain('daijigyo')
        expect(line.dimensions.map((d) => d.name).sort()).toEqual(['budget_class', 'org'])
        expect(line.amounts.length).toBe(3) // 予算現額・流用前・執行済
      }
      pageToken = body.nextPageToken
    } while (pageToken !== undefined)
    expect(seen.length).toBe(new Set(seen).size)
    expect(seen.length).toBe(2224) // 2023 歳出の原典行数（AGENTS.md の実測値）
  })

  test('phase filter matches lines but returns all phases', async () => {
    const res = await get(`/v0/budgets/132195:2023/statement?${q('direction = expenditure AND phase = executed', { pageSize: '5' })}`)
    const body = await res.json() as { lines: { amounts: { phase: string }[] }[] }
    expect(body.lines.length).toBe(5)
    for (const line of body.lines) {
      expect(line.amounts.some((a) => a.phase === 'executed')).toBe(true)
      expect(line.amounts.length).toBe(3)
    }
  })

  test('cofog.division filter within a budget', async () => {
    const res = await get(`/v0/budgets/132047:2024/statement?${q('direction = expenditure AND cofog.division = "09"')}`)
    const body = await res.json() as { lines: { judgments: { cofog: { division: string } } }[] }
    expect(body.lines.length).toBeGreaterThan(0)
    expect(body.lines.every((l) => l.judgments.cofog.division === '09')).toBe(true)
  })

  test('missing direction is 400, redundant fiscalYear is 400, unknown budget is 404', async () => {
    expect((await get('/v0/budgets/132195:2023/statement')).status).toBe(400)
    expect((await get(`/v0/budgets/132195:2023/statement?${q('direction = expenditure AND fiscalYear = 2023')}`)).status).toBe(400)
    expect((await get(`/v0/budgets/132195:1999/statement?${q('direction = expenditure')}`)).status).toBe(404)
    expect((await get(`/v0/budgets/garbage/statement?${q('direction = expenditure')}`)).status).toBe(400)
  })

  test('cross line resolves to the full line via its parent budget statement', async () => {
    const cross = await get(`/v0/budgets/-/statement?${q('cofog.division = "09"', { pageSize: '1' })}`)
    const { lines } = await cross.json() as { lines: { budget: string; budgetLineId: string }[] }
    const entry = lines[0]!
    expect(entry.budget).toMatch(/^budgets\/\d{6}:\d{4}$/)
    const budgetId = entry.budget.split('/')[1]!
    // 横断応答の budget 参照 → その statement から同じ行を特定できる
    let found = false
    let pageToken: string | undefined
    do {
      const params = q('direction = expenditure', pageToken ? { pageToken } : {})
      const res = await get(`/v0/budgets/${budgetId}/statement?${params}`)
      const body = await res.json() as { lines: { budgetLineId: string; hierarchy: unknown[] }[]; nextPageToken?: string }
      const hit = body.lines.find((l) => l.budgetLineId === entry.budgetLineId)
      if (hit) {
        expect(hit.hierarchy.length).toBeGreaterThan(0)
        found = true
        break
      }
      pageToken = body.nextPageToken
    } while (pageToken !== undefined)
    expect(found).toBe(true)
  })
})

describe('distribution passthrough', () => {
  test('files are byte-identical, with revision and ETag headers (AC 5)', async () => {
    for (const [j, file] of [['132047', 'expenditure.csv'], ['132195', 'datapackage.json']] as const) {
      const res = await get(`/v0/datapackages/${j}/${file}`)
      expect(res.status).toBe(200)
      const body = Buffer.from(await res.arrayBuffer())
      const original = readFileSync(join(DATA_DIR, j, file))
      expect(body.equals(original)).toBe(true)
      const sha256 = createHash('sha256').update(original).digest('hex')
      expect(res.headers.get('ETag')).toBe(`"${sha256}"`)
      expect(res.headers.get('X-Fudoki-Revision')).toMatch(/^[0-9a-f]{40}/)
      expect(res.headers.get('Access-Control-Expose-Headers')).toContain('X-Fudoki-Revision')
    }
  })

  test('HEAD returns headers without a body', async () => {
    const res = await app.request('https://api.fudoki.dev/v0/datapackages/132047/expenditure.csv', { method: 'HEAD' }, env)
    expect(res.status).toBe(200)
    expect(res.headers.get('ETag')).toBeTruthy()
    expect(await res.text()).toBe('')
  })

  test('undeclared files and traversal are 404', async () => {
    expect((await get('/v0/datapackages/132047/secret.txt')).status).toBe(404)
    expect((await get('/v0/datapackages/132047/..%2F..%2Fmeta%2Fjurisdictions.json')).status).toBe(404)
    expect((await get('/v0/datapackages/999999/datapackage.json')).status).toBe(404)
  })
})

describe('contract-only surface', () => {
  test('internal partitions are not exposed as URLs', async () => {
    expect((await get('/meta/jurisdictions.json')).status).toBe(404)
    expect((await get('/lines/132195/2023-expenditure.json')).status).toBe(404)
    expect((await get('/cofog/09/all/0.json')).status).toBe(404)
    expect((await get('/v0/meta/jurisdictions.json')).status).toBe(404)
  })

  test('openapi.json documents the endpoints, the union, and the passthrough (AC 8)', async () => {
    const res = await get('/v0/openapi.json')
    expect(res.status).toBe(200)
    const spec = await res.json() as { info: { description: string }; paths: Record<string, unknown> }
    expect(spec.info.description).toContain('v0')
    expect(Object.keys(spec.paths)).toEqual(expect.arrayContaining([
      '/jurisdictions',
      '/jurisdictions/{jurisdiction}',
      '/budgets',
      '/budgets/{budget}',
      '/budgets/{budget}/statement',
      '/datapackages/{jurisdiction}/{file}',
    ]))
    const raw = JSON.stringify(spec)
    expect(raw).toContain('oneOf')
    // フィールドの .describe() が description として出ていること
    expect(raw).toContain('円に正規化した金額')
    expect(raw).toContain('全国地方公共団体コード')
  })

  test('root and /openapi.json redirect into /v0', async () => {
    expect((await get('/')).status).toBe(302)
    expect((await get('/openapi.json')).status).toBe(302)
  })

  test('RPC endpoint (/rpc) serves the same router for first-party clients', async () => {
    const { createORPCClient } = await import('@orpc/client')
    const { RPCLink } = await import('@orpc/client/fetch')
    const { router } = await import('./router')
    type RouterClient = import('@orpc/server').RouterClient<typeof router>
    const link = new RPCLink({
      url: 'https://api.fudoki.dev/rpc',
      fetch: async (request, init) => app.request(request, init, env),
    })
    const client: RouterClient = createORPCClient(link)

    const listed = await client.listBudgets({ filter: 'jurisdiction = "132195"' })
    expect(listed.budgets.map((b) => b.fiscalYear)).toContain('2023')
    expect(listed.revision).toMatch(/^[0-9a-f]{40}/)

    const cross = await client.getStatement({
      budget: '-',
      filter: 'cofog.division = "09"',
      pageSize: 3,
    })
    expect(cross.scope).toBe('crossBudget')
    expect(cross.lines.length).toBe(3)

    // 型付きエラーも RPC 経由で届く
    await expect(client.getBudget({ budget: '999999:1999' })).rejects.toThrow()
  })

  test('CORS: OPTIONS preflight and headers on responses', async () => {
    const preflight = await app.request('https://api.fudoki.dev/v0/jurisdictions', { method: 'OPTIONS' }, env)
    expect(preflight.status).toBe(204)
    expect(preflight.headers.get('Access-Control-Allow-Origin')).toBe('*')
    const res = await get('/v0/jurisdictions')
    expect(res.headers.get('Access-Control-Allow-Origin')).toBe('*')
  })
})
