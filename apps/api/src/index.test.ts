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
import type { Env, KVNamespaceLike, RateLimiterLike } from './assets'
import { sha256Hex } from './lib/apiKey'

const ASSETS_DIR = join(import.meta.dir, '../dist/assets')
const DATA_DIR = join(import.meta.dir, '../../../data/budget/datapackages')

/**
 * KV の fake。access-control.ts のキー検証テスト用に、
 * active な1件と revoked な1件をあらかじめ仕込む。
 */
const VALID_KEY = 'test-valid-key'
const REVOKED_KEY = 'test-revoked-key'
const CORRUPT_KEY = 'test-corrupt-key'
const apiKeysStore = new Map<string, string>()
apiKeysStore.set(
  await sha256Hex(VALID_KEY),
  JSON.stringify({ label: 'test-suite', issuedAt: '2026-01-01T00:00:00.000Z', status: 'active' }),
)
apiKeysStore.set(
  await sha256Hex(REVOKED_KEY),
  JSON.stringify({ label: 'test-suite', issuedAt: '2026-01-01T00:00:00.000Z', status: 'revoked' }),
)
// KV の値が壊れているケース（JSON として parse できない）を再現する
apiKeysStore.set(await sha256Hex(CORRUPT_KEY), 'not-json{')
const fakeApiKeys: KVNamespaceLike = {
  async get(key) {
    return apiKeysStore.get(key) ?? null
  },
  async put(key, value) {
    apiKeysStore.set(key, value)
  },
}

/**
 * ⚠️ 既定は常時 success の fake にする。そうしないと、同じエンドポイントを
 * 何度も叩く既存テスト（CORS のテストなど）が同一ウィンドウでレート制限に
 * 掛かってフレーキーになる。レート制限そのものを検証するテストだけ、
 * 個別に呼び出し回数を数える fake（makeCountingLimiter）に差し替える。
 */
const alwaysAllow: RateLimiterLike = {
  async limit() {
    return { success: true }
  },
}

function makeCountingLimiter(allowUpTo: number): RateLimiterLike {
  let count = 0
  return {
    async limit() {
      count++
      return { success: count <= allowUpTo }
    },
  }
}

const env: Env = {
  ASSETS: {
    async fetch(input: Request | URL | string) {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url)
      const path = join(ASSETS_DIR, url.pathname)
      if (!path.startsWith(ASSETS_DIR) || !existsSync(path)) return new Response(null, { status: 404 })
      return new Response(readFileSync(path))
    },
  },
  API_KEYS: fakeApiKeys,
  RATE_LIMIT_ANONYMOUS: alwaysAllow,
  RATE_LIMIT_AUTHENTICATED: alwaysAllow,
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
    expect(ids).toEqual(['132047', '132195', '132241'])
    for (const j of body.jurisdictions) {
      expect(j.resources).toContain('datapackage.json')
      expect(j.datapackagePath).toBe(`/v0/datapackages/${j.id}/datapackage.json`)
    }
  })

  test('detail carries interpretation-relevant caveats only, and no per-year state', async () => {
    const res = await get('/v0/jurisdictions/132195')
    expect(res.status).toBe(200)
    const { jurisdiction } = await res.json() as { jurisdiction: { caveats: { topic: string }[] } & Record<string, unknown> }
    // API の caveats は「データから見えず解釈を変えるもの」だけ（基準は report/budget/schema.ts）。
    // 全量（経緯・吸収済み込み）は報告側が持ち、必須カテゴリの検査は build がそちらに掛ける
    const topics = jurisdiction.caveats.map((c) => c.topic)
    expect(topics).toContain('予算額は当初予算ではない')
    expect(topics.length).toBeLessThan(6)
    // 年度は budgets へ移した。団体の表現は収録が増えても変わらない
    expect(jurisdiction['fiscalYears']).toBeUndefined()
    expect(jurisdiction['classificationRates']).toBeUndefined()
  })

  test('mitaka also carries the statutory kan-code caveat (団体をまたいで出さない原則の裏)', async () => {
    const res = await get('/v0/jurisdictions/132047')
    expect(res.status).toBe(200)
    const { jurisdiction } = await res.json() as { jurisdiction: { caveats: { topic: string }[] } }
    expect(jurisdiction.caveats.map((c) => c.topic)).toContain('款コードは法定の款番号と一致しない')
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
    expect(new Set(all.budgets.map((b) => b.jurisdictionId))).toEqual(new Set(['132047', '132195', '132241']))
    const y = await (await get(`/v0/budgets?${q('fiscalYear = 2024')}`)).json() as { budgets: { id: string }[] }
    expect(y.budgets.map((b) => b.id)).toEqual(['132047:2024', '132241:2024'])
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
    expect(new Set([...seen].map((n) => n.split(':')[0]))).toEqual(new Set(['132047', '132195', '132241']))
    // 独立に cofog リソースから数えた行数と一致する（黙った欠落が無い）
    expect(seen.size).toBe(countCofogRows(['132047', '132195', '132241'], '09'))
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

describe('cofog breakdown', () => {
  type ClassificationRate = Record<'assigned' | 'unclassifiable' | 'outOfScope', { lines: number; amount: number }>
  type CofogBreakdownBody = {
    cofog: {
      byDivision: { division: string; divisionLabel: string; count: number; sum: number }[]
      assigned: { count: number; sum: number }
      total: { count: number; sum: number }
      assignedShare: { count: number; sum: number }
    }
    revision: string
  }

  for (const budgetId of ['132047:2024', '132195:2023', '132241:2023']) {
    test(`expenditure: byDivision folds to assigned, and assigned/total match the budget's classificationRate (${budgetId})`, async () => {
      const budgetRes = await get(`/v0/budgets/${budgetId}`)
      expect(budgetRes.status).toBe(200)
      const { budget } = await budgetRes.json() as { budget: { classificationRate: ClassificationRate } }
      const { classificationRate } = budget

      const res = await get(`/v0/budgets/${budgetId}/cofog?direction=expenditure`)
      expect(res.status).toBe(200)
      const { cofog, revision } = await res.json() as CofogBreakdownBody
      expect(revision).toMatch(/^[0-9a-f]{40}/)

      // 独立に計算した2つの数字（budgets の分類率 と cofog の集計）が一致する。
      // どちらかが壊れたら build 自体が止まるが、ここでも API 応答レベルで確かめる
      expect(cofog.assigned).toEqual({ count: classificationRate.assigned.lines, sum: classificationRate.assigned.amount })
      const expectedTotalLines =
        classificationRate.assigned.lines + classificationRate.unclassifiable.lines + classificationRate.outOfScope.lines
      const expectedTotalAmount =
        classificationRate.assigned.amount + classificationRate.unclassifiable.amount + classificationRate.outOfScope.amount
      expect(cofog.total).toEqual({ count: expectedTotalLines, sum: expectedTotalAmount })

      // ⚠️ 分類できなかった分（unclassifiable + outOfScope）を落としていないこと。
      // byDivision（割当済みだけ）の総和は total より必ず小さく、その差が
      // ちょうど分類できなかった分の金額と行数に一致する
      expect(classificationRate.unclassifiable.lines + classificationRate.outOfScope.lines).toBeGreaterThan(0)
      const unclassifiedLines = cofog.total.count - cofog.assigned.count
      const unclassifiedAmount = cofog.total.sum - cofog.assigned.sum
      expect(unclassifiedLines).toBe(classificationRate.unclassifiable.lines + classificationRate.outOfScope.lines)
      expect(unclassifiedAmount).toBe(classificationRate.unclassifiable.amount + classificationRate.outOfScope.amount)

      // byDivision は割当済みの内訳の分解 — 足し戻すと assigned に一致する
      const byDivisionCount = cofog.byDivision.reduce((s, d) => s + d.count, 0)
      const byDivisionSum = cofog.byDivision.reduce((s, d) => s + d.sum, 0)
      expect(byDivisionCount).toBe(cofog.assigned.count)
      expect(byDivisionSum).toBe(cofog.assigned.sum)
      expect(cofog.byDivision.length).toBeGreaterThan(0)
      // division の昇順、01〜10 の範囲
      expect(cofog.byDivision.map((d) => d.division)).toEqual([...cofog.byDivision].map((d) => d.division).sort())
      for (const d of cofog.byDivision) {
        expect(d.division).toMatch(/^(0[1-9]|10)$/)
        expect(d.divisionLabel.length).toBeGreaterThan(0)
      }
    })
  }

  test('revenue: cofog_status is always not-applicable, so assigned is zero but total is not (nothing dropped)', async () => {
    const res = await get('/v0/budgets/132195:2023/cofog?direction=revenue')
    expect(res.status).toBe(200)
    const { cofog } = await res.json() as CofogBreakdownBody
    expect(cofog.assigned).toEqual({ count: 0, sum: 0 })
    expect(cofog.byDivision).toEqual([])
    expect(cofog.total.count).toBeGreaterThan(0)
    expect(cofog.total.sum).toBeGreaterThan(0)
  })

  test('unknown budget is 404, malformed budget id is 400, missing/invalid direction is 400', async () => {
    expect((await get('/v0/budgets/132195:1999/cofog?direction=expenditure')).status).toBe(404)
    expect((await get('/v0/budgets/garbage/cofog?direction=expenditure')).status).toBe(400)
    expect((await get('/v0/budgets/132195:2023/cofog')).status).toBe(400)
    expect((await get('/v0/budgets/132195:2023/cofog?direction=nonsense')).status).toBe(400)
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
    expect((await get('/lines/132195/2023-expenditure/0.json')).status).toBe(404)
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
      '/budgets/{budget}/cofog',
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

    // 収録済み3団体それぞれで、COFOG 別内訳が RPC 経由でも取れ、
    // 分類できなかった分（total - assigned）が合計に残っていること
    for (const budget of ['132047:2024', '132195:2023', '132241:2023']) {
      const cofog = await client.getCofogBreakdown({ budget, direction: 'expenditure' })
      expect(cofog.cofog.total.sum).toBeGreaterThan(cofog.cofog.assigned.sum)
      expect(cofog.cofog.total.count).toBeGreaterThan(cofog.cofog.assigned.count)
      expect(cofog.revision).toMatch(/^[0-9a-f]{40}/)
    }

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

  test('CORS: /rpc is restricted to fudoki origins, /v0 stays open', async () => {
    const rpc = (origin: string) =>
      app.request('https://api.fudoki.dev/rpc/listJurisdictions', {
        method: 'POST',
        headers: { 'content-type': 'application/json', origin },
        body: '{}',
      }, env)
    expect((await rpc('https://fudoki.dev')).headers.get('Access-Control-Allow-Origin')).toBe('https://fudoki.dev')
    expect((await rpc('https://evil.example')).headers.get('Access-Control-Allow-Origin')).toBeNull()
    // /v0 は Origin が何であっても全開のまま
    const open = await app.request('https://api.fudoki.dev/v0/jurisdictions', { headers: { origin: 'https://evil.example' } }, env)
    expect(open.headers.get('Access-Control-Allow-Origin')).toBe('*')
  })
})

describe('access control (beta)', () => {
  test('no key: 200 (anonymous is allowed, just at a lower rate)', async () => {
    expect((await get('/v0/jurisdictions')).status).toBe(200)
  })

  test('valid key: 200', async () => {
    const res = await app.request(
      'https://api.fudoki.dev/v0/jurisdictions',
      { headers: { Authorization: `Bearer ${VALID_KEY}` } },
      env,
    )
    expect(res.status).toBe(200)
  })

  test('revoked key: 401', async () => {
    const res = await app.request(
      'https://api.fudoki.dev/v0/jurisdictions',
      { headers: { Authorization: `Bearer ${REVOKED_KEY}` } },
      env,
    )
    expect(res.status).toBe(401)
  })

  test('unknown key: 401', async () => {
    const res = await app.request(
      'https://api.fudoki.dev/v0/jurisdictions',
      { headers: { Authorization: 'Bearer no-such-key' } },
      env,
    )
    expect(res.status).toBe(401)
  })

  test('malformed Authorization header (no Bearer): 401', async () => {
    const res = await app.request(
      'https://api.fudoki.dev/v0/jurisdictions',
      { headers: { Authorization: VALID_KEY } },
      env,
    )
    expect(res.status).toBe(401)
  })

  test('corrupt KV record (invalid JSON): 401, not a 500, and it is logged', async () => {
    const lines: string[] = []
    const original = console.log
    console.log = (...args: unknown[]) => {
      lines.push(args.map(String).join(' '))
    }
    let res: Response
    try {
      res = await app.request(
        'https://api.fudoki.dev/v0/jurisdictions',
        { headers: { Authorization: `Bearer ${CORRUPT_KEY}` } },
        env,
      )
    } finally {
      console.log = original
    }
    expect(res.status).toBe(401)
    expect(lines.length).toBeGreaterThan(0)
    const entry = JSON.parse(lines[lines.length - 1]!) as { status: number; reason?: string }
    expect(entry.status).toBe(401)
    expect(entry.reason).toContain('malformed API key record')
  })

  test('key-state 401 reasons are unified in the response, not leaked to the client', async () => {
    const unknown = await app.request(
      'https://api.fudoki.dev/v0/jurisdictions',
      { headers: { Authorization: 'Bearer no-such-key' } },
      env,
    )
    const revoked = await app.request(
      'https://api.fudoki.dev/v0/jurisdictions',
      { headers: { Authorization: `Bearer ${REVOKED_KEY}` } },
      env,
    )
    const unknownBody = await unknown.json() as { message: string }
    const revokedBody = await revoked.json() as { message: string }
    expect(unknownBody.message).toBe('invalid API key')
    expect(revokedBody.message).toBe('invalid API key')
    // malformed header はクライアント側の実装ミスなので区別したままでよい
    const malformed = await app.request(
      'https://api.fudoki.dev/v0/jurisdictions',
      { headers: { Authorization: VALID_KEY } },
      env,
    )
    const malformedBody = await malformed.json() as { message: string }
    expect(malformedBody.message).toBe('malformed Authorization header')
  })

  test('repeated invalid keys are throttled by the anonymous limiter, not left unbounded: 429', async () => {
    // unauthorized() は 401 を返す前に匿名 limiter を消費する。3回目以降は
    // limiter が枯渇しているので、無効なキーを送り続けても 429 になり、
    // 401 だけを無限に返し続ける（レート制限が効かない）ことはない。
    const limitedEnv: Env = { ...env, RATE_LIMIT_ANONYMOUS: makeCountingLimiter(2) }
    const attempt = () =>
      app.request(
        'https://api.fudoki.dev/v0/jurisdictions',
        { headers: { Authorization: 'Bearer no-such-key' } },
        limitedEnv,
      )
    expect((await attempt()).status).toBe(401)
    expect((await attempt()).status).toBe(401)
    expect((await attempt()).status).toBe(429)
  })

  test('over the limit: 429, with Retry-After', async () => {
    const limitedEnv: Env = { ...env, RATE_LIMIT_ANONYMOUS: makeCountingLimiter(0) }
    const res = await app.request('https://api.fudoki.dev/v0/jurisdictions', {}, limitedEnv)
    expect(res.status).toBe(429)
    expect(res.headers.get('Retry-After')).toBeTruthy()
  })

  test('/rpc ignores an Authorization header and is limited by IP only', async () => {
    // 認証済み用のリミッタを枯渇させても /rpc には効かない（IP のみで判定するため）
    const limitedEnv: Env = { ...env, RATE_LIMIT_AUTHENTICATED: makeCountingLimiter(0) }
    const res = await app.request(
      'https://api.fudoki.dev/rpc/listJurisdictions',
      {
        method: 'POST',
        headers: { 'content-type': 'application/json', Authorization: `Bearer ${VALID_KEY}` },
        body: '{}',
      },
      limitedEnv,
    )
    expect(res.status).toBe(200)
  })

  test('docs UI (/v0/) and /v0/openapi.json are excluded: they never consume the anonymous limiter', async () => {
    // 「ステータスが 200 か」だけでは弱い ── excluded の判定が壊れて
    // keyed に落ちても、キーは任意なので同じ 200 が返り、テストが偶然通る。
    // 代わりに RATE_LIMIT_ANONYMOUS を必ず失敗させ、除外パスがそれでも
    // 通ることを見る。これは limiter に一切触れていないことの直接証拠になる。
    const neverAllow: RateLimiterLike = {
      async limit() {
        return { success: false }
      },
    }
    const excludedEnv: Env = { ...env, RATE_LIMIT_ANONYMOUS: neverAllow }
    expect((await app.request('https://api.fudoki.dev/v0/', {}, excludedEnv)).status).toBe(200)
    expect((await app.request('https://api.fudoki.dev/v0/openapi.json', {}, excludedEnv)).status).toBe(200)
    expect((await app.request('https://api.fudoki.dev/openapi.json', {}, excludedEnv)).status).toBe(302)
    expect((await app.request('https://api.fudoki.dev/', {}, excludedEnv)).status).toBe(302)
    // 対照実験: 除外されていない /v0/jurisdictions は同じ limiter で 429 になる
    // （neverAllow 自体が効いていることの確認。そうでないと上の 200 が
    // 「limiter が壊れているだけ」で通っている可能性を消せない）
    expect((await app.request('https://api.fudoki.dev/v0/jurisdictions', {}, excludedEnv)).status).toBe(429)
  })

  test('access log is structured JSON and never carries the raw IP', async () => {
    const rawIp = '203.0.113.42'
    const lines: string[] = []
    const original = console.log
    console.log = (...args: unknown[]) => {
      lines.push(args.map(String).join(' '))
    }
    try {
      await app.request(
        'https://api.fudoki.dev/v0/jurisdictions',
        { headers: { 'CF-Connecting-IP': rawIp } },
        env,
      )
    } finally {
      console.log = original
    }
    expect(lines.length).toBeGreaterThan(0)
    expect(lines.some((l) => l.includes(rawIp))).toBe(false)
    const entry = JSON.parse(lines[lines.length - 1]!) as { path: string; status: number; ipHash: string }
    expect(entry.path).toBe('/v0/jurisdictions')
    expect(entry.status).toBe(200)
    expect(entry.ipHash).toMatch(/^[0-9a-f]{64}$/)
  })
})
