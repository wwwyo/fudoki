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

  type Scopes = {
    expenditure?: {
      amountPhase: string
      phases: { id: string; label: string; isPrimary: boolean }[]
      funds: { code: string; label: string | null }[]
      consolidation: { retained: { lineCount: number; amount: number }; eliminated: { lineCount: number; amount: number } }
      cofogDepth:
        | { applicable: true; division: { lineCount: number; amount: number; rate: number }; group: { rate: number }; class: { rate: number } }
        | { applicable: false }
      names: { hierarchy: { level: string; hasName: boolean; source: string | null }[]; projectName: { hasName: true; funds: string[]; fiscalYears: string[] } | null }
      nextHierarchyLevel: { level: string; available: true; aggregateSupported: false; namedAmountRate: number } | null
    }
    revenue?: {
      amountPhase: string
      cofogDepth: { applicable: boolean }
      nextHierarchyLevel: unknown
    }
  }

  test('scopes: 三鷹市（連結消去あり・COFOG は canonical な款項目名から）', async () => {
    const { budget } = await (await get('/v0/budgets/132047:2024')).json() as { budget: { scopes: Scopes } }
    const exp = budget.scopes.expenditure!
    // amountPhase は phases[].isPrimary の phase と同じ値でなければならない（build.ts が検査している）
    expect(exp.amountPhase).toBe('approved')
    expect(exp.phases.find((p) => p.isPrimary)?.id).toBe(exp.amountPhase)
    expect(exp.phases).toEqual([{ id: 'approved', label: '当初予算', isPrimary: true }])
    expect(exp.consolidation.eliminated.lineCount).toBe(29)
    expect(exp.consolidation.eliminated.amount).toBe(7_732_576_000)
    expect(exp.cofogDepth).toMatchObject({ applicable: true, division: { rate: 1 } })
    expect(exp.names.hierarchy).toEqual([
      { level: 'kan', hasName: true, source: 'canonical' },
      { level: 'kou', hasName: true, source: 'canonical' },
      { level: 'moku', hasName: true, source: 'canonical' },
    ])
    expect(exp.names.projectName).toBeNull()
    // 目の下は事項（jikou）で、原典に直接名称があるので nextHierarchyLevel は 100% named
    expect(exp.nextHierarchyLevel).toMatchObject({ level: 'jikou', aggregateSupported: false, namedAmountRate: 1 })
    expect(budget.scopes.revenue!.cofogDepth).toEqual({ applicable: false })
    expect(budget.scopes.revenue!.nextHierarchyLevel).toBeNull()
  })

  test('scopes: 多摩市（会計コードが空文字。存在しない値として落とさない）', async () => {
    const { budget } = await (await get('/v0/budgets/132241:2021')).json() as { budget: { scopes: Scopes } }
    expect(budget.scopes.expenditure!.funds).toEqual([{ code: '', label: '一般会計' }])
    expect(budget.scopes.expenditure!.nextHierarchyLevel).toMatchObject({ level: 'saimoku' })
  })

  test('scopes: 狛江市（款・項・目は判断由来、事業名は年度で割れる）', async () => {
    const early = await (await get('/v0/budgets/132195:2018')).json() as { budget: { scopes: Scopes } }
    // 決算資料 PDF が無い年度は款・項・目の名称も事業名も無い
    expect(early.budget.scopes.expenditure!.names.hierarchy.every((h) => h.hasName === false)).toBe(true)
    const withPdf = await (await get('/v0/budgets/132195:2020')).json() as { budget: { scopes: Scopes } }
    expect(withPdf.budget.scopes.expenditure!.names.hierarchy.every((h) => h.hasName && h.source === 'judgment')).toBe(true)
    // 事業名（project_names.csv）の収録範囲は団体×direction 全体で一定（年度を絞っても同じ値が返る）
    expect(early.budget.scopes.expenditure!.names.projectName).toEqual(withPdf.budget.scopes.expenditure!.names.projectName)
    expect(early.budget.scopes.expenditure!.names.projectName!.fiscalYears).toEqual(['2020', '2021', '2022', '2023'])
    expect(early.budget.scopes.expenditure!.names.projectName!.funds).toEqual(['1'])
    expect(early.budget.scopes.expenditure!.nextHierarchyLevel).toMatchObject({ level: 'daijigyo' })
    // 歳出は3段階（design doc の実測: adjusted-before-transfer / adjusted / executed）、歳入は2段階
    expect(early.budget.scopes.expenditure!.phases.map((p) => p.id).sort()).toEqual(['adjusted', 'adjusted-before-transfer', 'executed'])
  })
})

describe('cross-budget budgetLines (wildcard parent)', () => {
  test('division filter returns all matching lines across pages, without silent truncation', async () => {
    const seen = new Set<string>()
    let pageToken: string | undefined
    let pages = 0
    let revision = ''
    do {
      const params = q('cofog.division = "09"', pageToken ? { pageToken } : {})
      const res = await get(`/v0/budgets/-/budgetLines?${params}`)
      expect(res.status).toBe(200)
      const body = await res.json() as { lines: { budgetLineId: string; budget: string; direction: string }[]; nextPageToken?: string; revision: string }
      revision = body.revision
      for (const line of body.lines) {
        expect(seen.has(line.budgetLineId)).toBe(false)
        seen.add(line.budgetLineId)
        expect(line.direction).toBe('expenditure')
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
    const res = await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09" AND fiscalYear = 2023')}`)
    const body = await res.json() as { lines: { fiscalYear: string }[] }
    expect(body.lines.length).toBeGreaterThan(0)
    expect(body.lines.every((l) => l.fiscalYear === '2023')).toBe(true)
  })

  test('empty result set: 200 with empty array and no token', async () => {
    const res = await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09" AND fiscalYear = 1999')}`)
    expect(res.status).toBe(200)
    const body = await res.json() as { lines: unknown[]; nextPageToken?: string }
    expect(body.lines).toEqual([])
    expect(body.nextPageToken).toBeUndefined()
  })

  test('missing division / unsupported fields / bad syntax are 400', async () => {
    expect((await get('/v0/budgets/-/budgetLines')).status).toBe(400)
    expect((await get(`/v0/budgets/-/budgetLines?${q('fiscalYear = 2023')}`)).status).toBe(400)
    expect((await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09" AND direction = expenditure')}`)).status).toBe(400)
    expect((await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "99"')}`)).status).toBe(400)
    expect((await get(`/v0/budgets/-/budgetLines?${q('cofog.division != "09"')}`)).status).toBe(400)
    expect((await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09" AND jurisdiction = "132195"')}`)).status).toBe(400)
  })

  test('view=FULL is rejected for the wildcard parent (400)', async () => {
    const res = await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09"', { view: 'FULL' })}`)
    expect(res.status).toBe(400)
  })

  test('view defaults to BASIC: no hierarchy/dimensions/judgments, a single-phase amount', async () => {
    const res = await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09"', { pageSize: '1' })}`)
    const body = await res.json() as { lines: Record<string, unknown>[] }
    const line = body.lines[0]!
    expect(line['name']).toMatch(/^budgets\/\d{6}:\d{4}\/budgetLines\//)
    expect(line['amount']).toMatchObject({ phase: expect.any(String), amount: expect.any(Number) })
    expect(line['hierarchy']).toBeUndefined()
    expect(line['dimensions']).toBeUndefined()
    expect(line['amounts']).toBeUndefined()
    expect(line['judgments']).toBeUndefined()
  })

  test('pageToken bound to another filter is 400; another revision is 410', async () => {
    const first = await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09"', { pageSize: '10' })}`)
    const { nextPageToken } = await first.json() as { nextPageToken: string }
    expect(nextPageToken).toBeDefined()

    const misused = await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "10"', { pageToken: nextPageToken })}`)
    expect(misused.status).toBe(400)

    const decoded = JSON.parse(atob(nextPageToken.replaceAll('-', '+').replaceAll('_', '/'))) as Record<string, unknown>
    const stale = btoa(JSON.stringify({ ...decoded, rev: '0'.repeat(40) }))
    const staleRes = await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09"', { pageToken: stale })}`)
    expect(staleRes.status).toBe(410)

    const garbage = await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09"', { pageToken: '!!!' })}`)
    expect(garbage.status).toBe(400)

    // 負の offset や非整数を細工したトークンは 500 ではなく 400 で弾く
    for (const off of [-1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
      const crafted = btoa(JSON.stringify({ ...decoded, off }))
      const res = await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09"', { pageToken: crafted })}`)
      expect(res.status).toBe(400)
    }
  })

  test('pageSize: clamps above 1000, rejects negatives', async () => {
    const res = await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09"', { pageSize: '2' })}`)
    const body = await res.json() as { lines: unknown[] }
    expect(body.lines.length).toBe(2)
    expect((await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09"', { pageSize: '-1' })}`)).status).toBe(400)
    expect((await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09"', { pageSize: '5000' })}`)).status).toBe(200)
  })
})

describe('budget budgetLines', () => {
  test('view=FULL preserves jurisdiction-specific shape and completeness', async () => {
    const seen: string[] = []
    let pageToken: string | undefined
    do {
      const params = q('direction = expenditure', { view: 'FULL', ...(pageToken ? { pageToken } : {}) })
      const res = await get(`/v0/budgets/132195:2023/budgetLines?${params}`)
      expect(res.status).toBe(200)
      const body = await res.json() as { lines: { budgetLineId: string; hierarchy: { level: string }[]; dimensions: { name: string }[]; amounts: { phase: string }[] }[]; nextPageToken?: string }
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

  test('view=BASIC returns a single-phase amount and no FULL-only fields', async () => {
    const res = await get(`/v0/budgets/132195:2023/budgetLines?${q('direction = expenditure', { pageSize: '3' })}`)
    const body = await res.json() as { lines: Record<string, unknown>[] }
    expect(body.lines.length).toBe(3)
    for (const line of body.lines) {
      expect(line['amount']).toMatchObject({ phase: expect.any(String), amount: expect.any(Number) })
      expect(line['hierarchy']).toBeUndefined()
      expect(line['dimensions']).toBeUndefined()
      expect(line['amounts']).toBeUndefined()
      expect(line['judgments']).toBeUndefined()
    }
  })

  test('phase filter matches lines but returns all phases (view=FULL)', async () => {
    const res = await get(`/v0/budgets/132195:2023/budgetLines?${q('direction = expenditure AND phase = executed', { view: 'FULL', pageSize: '5' })}`)
    const body = await res.json() as { lines: { amounts: { phase: string }[] }[] }
    expect(body.lines.length).toBe(5)
    for (const line of body.lines) {
      expect(line.amounts.some((a) => a.phase === 'executed')).toBe(true)
      expect(line.amounts.length).toBe(3)
    }
  })

  test('cofog.division filter within a budget (view=FULL)', async () => {
    const res = await get(`/v0/budgets/132047:2024/budgetLines?${q('direction = expenditure AND cofog.division = "09"', { view: 'FULL' })}`)
    const body = await res.json() as { lines: { judgments: { cofog: { division: string } } }[] }
    expect(body.lines.length).toBeGreaterThan(0)
    expect(body.lines.every((l) => l.judgments.cofog.division === '09')).toBe(true)
  })

  test('missing direction is 400, redundant fiscalYear is 400, unknown budget is 404', async () => {
    expect((await get('/v0/budgets/132195:2023/budgetLines')).status).toBe(400)
    expect((await get(`/v0/budgets/132195:2023/budgetLines?${q('direction = expenditure AND fiscalYear = 2023')}`)).status).toBe(400)
    expect((await get(`/v0/budgets/132195:1999/budgetLines?${q('direction = expenditure')}`)).status).toBe(404)
    expect((await get(`/v0/budgets/garbage/budgetLines?${q('direction = expenditure')}`)).status).toBe(400)
  })

  test('cross line resolves to the full line via its parent budgetLines (view=FULL)', async () => {
    const cross = await get(`/v0/budgets/-/budgetLines?${q('cofog.division = "09"', { pageSize: '1' })}`)
    const { lines } = await cross.json() as { lines: { budget: string; budgetLineId: string }[] }
    const entry = lines[0]!
    expect(entry.budget).toMatch(/^budgets\/\d{6}:\d{4}$/)
    const budgetId = entry.budget.split('/')[1]!
    // 横断応答の budget 参照 → その budgetLines(view=FULL) から同じ行を特定できる
    let found = false
    let pageToken: string | undefined
    do {
      const params = q('direction = expenditure', { view: 'FULL', ...(pageToken ? { pageToken } : {}) })
      const res = await get(`/v0/budgets/${budgetId}/budgetLines?${params}`)
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

  test('a pageToken issued for one query is rejected under a different one (fingerprint covers view, not just filter)', async () => {
    const basic = await get(`/v0/budgets/132195:2023/budgetLines?${q('direction = expenditure', { pageSize: '1' })}`)
    const { nextPageToken } = await basic.json() as { nextPageToken: string }
    expect(nextPageToken).toBeDefined()
    // 同じ budget・同じ filter で view だけ変えると、fingerprint が一致せず 400 になる
    // (design doc「ページトークンには問い合わせ全体の指紋を入れる」)
    const reused = await get(`/v0/budgets/132195:2023/budgetLines?${q('direction = expenditure', { view: 'FULL', pageToken: nextPageToken })}`)
    expect(reused.status).toBe(400)
  })

  test('an asset revision that disagrees with meta is a 500, not a silently wrong answer', async () => {
    const linesPath = '/lines/132195/2023-expenditure/0.json'
    const tamperedEnv: Env = {
      ...env,
      ASSETS: {
        async fetch(input: Request | URL | string) {
          const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url)
          if (url.pathname === linesPath) {
            const body = JSON.parse(readFileSync(join(ASSETS_DIR, linesPath), 'utf8')) as { revision: string }
            return new Response(JSON.stringify({ ...body, revision: '0'.repeat(40) }))
          }
          return env.ASSETS.fetch(input)
        },
      },
    }
    const res = await app.request(
      `https://api.fudoki.dev/v0/budgets/132195:2023/budgetLines?${q('direction = expenditure')}`,
      { method: 'GET' },
      tamperedEnv,
    )
    expect(res.status).toBe(500)
  })
})

/**
 * 集計（budgets:aggregate）の独立検算用ヘルパ。build.ts の検査と同じ発想で、
 * API が返した値を dist/assets の生成物からではなく **配布物 CSV から直接** 数え直す。
 * 132047 は expenditure.csv / cofog.csv のどちらにも引用符付きコンマが無い
 * （実測: grep -c '"' expenditure.csv === 0）ので、naive な split で列が崩れない。
 */
function sumExpenditureByDivision(
  jurisdiction: string,
  year: string,
  phase: string,
): { byDivision: Map<string, { amount: number; lineCount: number }>; unclassifiable: number; outOfScope: number; total: number } {
  const cofogLines = readFileSync(join(DATA_DIR, jurisdiction, 'cofog.csv'), 'utf8').trimEnd().split('\n')
  const cofogHeader = cofogLines[0]!.split(',')
  const col = (h: string[], name: string) => h.indexOf(name)
  const cId = col(cofogHeader, 'budget_line_id')
  const cYear = col(cofogHeader, 'fiscal_year')
  const cDir = col(cofogHeader, 'direction')
  const cStatus = col(cofogHeader, 'cofog_status')
  const cDivision = col(cofogHeader, 'cofog_division')
  const cofogByLineId = new Map<string, { status: string; division: string }>()
  for (const line of cofogLines.slice(1)) {
    const cells = line.split(',')
    if (cells[cYear] !== year || cells[cDir] !== 'expenditure') continue
    cofogByLineId.set(cells[cId]!, { status: cells[cStatus]!, division: cells[cDivision]! })
  }

  const expLines = readFileSync(join(DATA_DIR, jurisdiction, 'expenditure.csv'), 'utf8').trimEnd().split('\n')
  const expHeader = expLines[0]!.split(',')
  const eId = col(expHeader, 'budget_line_id')
  const eYear = col(expHeader, 'fiscal_year')
  const ePhase = col(expHeader, 'phase_id')
  const eValue = col(expHeader, 'value')

  const byDivision = new Map<string, { amount: number; lineCount: number }>()
  let unclassifiable = 0
  let outOfScope = 0
  let total = 0
  for (const line of expLines.slice(1)) {
    const cells = line.split(',')
    if (cells[eYear] !== year || cells[ePhase] !== phase) continue
    const cofogRow = cofogByLineId.get(cells[eId]!)
    if (!cofogRow) throw new Error(`test helper: no cofog row for ${cells[eId]}`)
    const amount = Number(cells[eValue])
    total += amount
    if (cofogRow.status === 'unclassifiable') {
      unclassifiable += amount
      continue
    }
    if (cofogRow.status === 'out-of-scope') {
      outOfScope += amount
      continue
    }
    const entry = byDivision.get(cofogRow.division) ?? { amount: 0, lineCount: 0 }
    entry.amount += amount
    entry.lineCount += 1
    byDivision.set(cofogRow.division, entry)
  }
  return { byDivision, unclassifiable, outOfScope, total }
}

type AggregateResponse = {
  cells: { dimensions: { dimension: string; code: string; label: string | null }[]; amount: number; lineCount: number }[]
  residual: { unclassifiable: { amount: number; lineCount: number }; outOfScope: { amount: number; lineCount: number }; notDescended: { amount: number; lineCount: number } }
  total?: { amount: number; lineCount: number }
  supportedGroupings: string[][]
  query: { budgets: string[]; groupBy: string[] }
  warnings: { code: string; message: string }[]
  omitted: { budget: string; code: string }[]
  revision: string
}

/**
 * budgets:aggregate は typed field の groupBy を配列として受け取る。oRPC の OpenAPIHandler は
 * 配列を `key[]=value` の繰り返し（bracket notation）で読む ── 単一要素でも `key=value` の
 * ままだと「配列でなく文字列」として拒否される（実測）ので、配列値は必ず `${key}[]` で積む。
 */
const aggQuery = (params: Record<string, string | string[]>) => {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) v.forEach((x) => usp.append(`${k}[]`, x))
    else usp.set(k, v)
  }
  return usp.toString()
}

describe('budgets:aggregate (COFOG axis)', () => {
  test('三鷹市: division 別合計が配布物 CSV から直接数えた値と一致する', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', groupBy: ['cofog.division'] })}`,
    )
    expect(res.status).toBe(200)
    const body = await res.json() as AggregateResponse
    const expected = sumExpenditureByDivision('132047', '2024', 'approved')

    expect(body.cells.length).toBe(expected.byDivision.size)
    for (const cell of body.cells) {
      expect(cell.dimensions.length).toBe(1)
      expect(cell.dimensions[0]!.dimension).toBe('cofog.division')
      const code = cell.dimensions[0]!.code
      const exp = expected.byDivision.get(code)
      expect(exp).toBeDefined()
      expect(cell.amount).toBe(exp!.amount)
      expect(cell.lineCount).toBe(exp!.lineCount)
    }

    expect(body.residual.unclassifiable.amount).toBe(expected.unclassifiable)
    expect(body.residual.outOfScope.amount).toBe(expected.outOfScope)
    expect(body.total?.amount).toBe(expected.total)
    expect(body.query.budgets).toEqual(['budgets/132047:2024'])
    expect(body.revision).toMatch(/^[0-9a-f]{40}/)
  })

  test('cells + residual = total（範囲が単一団体のとき）', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', groupBy: ['cofog.division'] })}`,
    )
    const body = await res.json() as AggregateResponse
    const cellsSum = body.cells.reduce((s, c) => s + c.amount, 0)
    const cellsLines = body.cells.reduce((s, c) => s + c.lineCount, 0)
    const residualSum = body.residual.unclassifiable.amount + body.residual.outOfScope.amount + body.residual.notDescended.amount
    const residualLines = body.residual.unclassifiable.lineCount + body.residual.outOfScope.lineCount + body.residual.notDescended.lineCount
    expect(body.total).toBeDefined()
    expect(cellsSum + residualSum).toBe(body.total!.amount)
    expect(cellsLines + residualLines).toBe(body.total!.lineCount)
  })

  test('groupBy=cofog.group のとき、division までしか降りていない行が residual.notDescended に入る', async () => {
    const [divisionRes, groupRes] = await Promise.all([
      get(`/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', groupBy: ['cofog.division'] })}`),
      get(`/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', groupBy: ['cofog.group'] })}`),
    ])
    const divisionBody = await divisionRes.json() as AggregateResponse
    const groupBody = await groupRes.json() as AggregateResponse
    // division 集計では全割当済み行が cells に入る（division は必ず埋まっている）ので notDescended は 0
    expect(divisionBody.residual.notDescended.amount).toBe(0)
    // group 集計では、division までしか降りていない行が notDescended に落ちる
    expect(groupBody.residual.notDescended.amount).toBeGreaterThan(0)
    // 割当済み総量（cells + notDescended）は division/group で変わらない
    const divisionAssigned = divisionBody.cells.reduce((s, c) => s + c.amount, 0)
    const groupAssigned = groupBody.cells.reduce((s, c) => s + c.amount, 0) + groupBody.residual.notDescended.amount
    expect(groupAssigned).toBe(divisionAssigned)
  })

  test('複数団体にまたがるのに jurisdiction が groupBy に無いと 400（supportedGroupings 付き）', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'fiscalYear = 2024', direction: 'expenditure', phase: 'approved', groupBy: ['cofog.division'] })}`,
    )
    expect(res.status).toBe(400)
    const body = await res.json() as { data?: { supportedGroupings?: string[][] } }
    expect(body.data?.supportedGroupings).toEqual([['jurisdiction', 'cofog.division'], ['jurisdiction', 'cofog.group'], ['jurisdiction', 'cofog.class']])
  })

  test('jurisdiction axis を含めれば、団体を絞らない横断集計が引ける（total は返らない）', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'fiscalYear = 2024', direction: 'expenditure', phase: 'approved', groupBy: ['jurisdiction', 'cofog.division'] })}`,
    )
    expect(res.status).toBe(200)
    const body = await res.json() as AggregateResponse
    expect(body.total).toBeUndefined()
    expect(new Set(body.cells.map((c) => c.dimensions.find((d) => d.dimension === 'jurisdiction')!.code))).toEqual(new Set(['132047', '132241']))
    expect(body.query.budgets.sort()).toEqual(['budgets/132047:2024', 'budgets/132241:2024'])
  })

  test('歳入に COFOG の軸を要求すると 400（歳入は not-applicable）', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'revenue', phase: 'approved', groupBy: ['cofog.division'] })}`,
    )
    expect(res.status).toBe(400)
  })

  test('団体を絞らずに fund を指定すると 400', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'fiscalYear = 2024', direction: 'expenditure', phase: 'approved', fund: '01', groupBy: ['jurisdiction', 'cofog.division'] })}`,
    )
    expect(res.status).toBe(400)
  })

  test('サポートしていない groupBy は 400 UNSUPPORTED_AGGREGATION', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', groupBy: ['hierarchy'] })}`,
    )
    expect(res.status).toBe(400)
  })

  test('direction / phase が typed field で必須。filter に埋めても効かない', async () => {
    expect((await get(`/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', groupBy: ['cofog.division'] })}`)).status).toBe(400)
    expect(
      (
        await get(
          `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024 AND direction = expenditure', phase: 'approved', groupBy: ['cofog.division'] })}`,
        )
      ).status,
    ).toBe(400)
  })

  test('実在しない団体・年度は 404', async () => {
    expect(
      (await get(`/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "999999" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', groupBy: ['cofog.division'] })}`)).status,
    ).toBe(404)
    expect(
      (await get(`/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 1999', direction: 'expenditure', phase: 'approved', groupBy: ['cofog.division'] })}`)).status,
    ).toBe(404)
  })

  test('provenance と warnings、ページングが応答に含まれる', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132195" AND fiscalYear = 2023', direction: 'expenditure', phase: 'adjusted', groupBy: ['cofog.division'], pageSize: '2' })}`,
    )
    expect(res.status).toBe(200)
    const body = await res.json() as AggregateResponse & { provenance: { sources: unknown[]; byBudget: Record<string, string[]> }; judgment: string[]; nextPageToken?: string }
    expect(body.cells.length).toBe(2)
    expect(body.nextPageToken).toBeDefined()
    expect(body.judgment).toEqual(['cofog'])
    expect(body.provenance.sources.length).toBeGreaterThan(0)
    expect(Object.keys(body.provenance.byBudget)).toEqual(['budgets/132195:2023'])
    // 狛江市は連結消去の対象外（三鷹市だけ eliminated がある）なので警告は立たない
    expect(body.warnings).toEqual([])
  })
})

/**
 * hierarchy / fiscalYear 軸の独立検算用ヘルパ。sumExpenditureByDivision と同じ発想で、
 * dist/assets の生成物からではなく配布物 CSV から直接数え直す（132047 は引用符付きコンマが無い）。
 */
function sumExpenditureByKan(
  jurisdiction: string,
  year: string,
  phase: string,
  fund: string,
): Map<string, { amount: number; lineCount: number }> {
  const expLines = readFileSync(join(DATA_DIR, jurisdiction, 'expenditure.csv'), 'utf8').trimEnd().split('\n')
  const header = expLines[0]!.split(',')
  const col = (name: string) => header.indexOf(name)
  const eYear = col('fiscal_year')
  const ePhase = col('phase_id')
  const eFund = col('fund_code')
  const eKan = col('kan_code')
  const eValue = col('value')

  const byKan = new Map<string, { amount: number; lineCount: number }>()
  for (const line of expLines.slice(1)) {
    const cells = line.split(',')
    if (cells[eYear] !== year || cells[ePhase] !== phase || cells[eFund] !== fund) continue
    const entry = byKan.get(cells[eKan]!) ?? { amount: 0, lineCount: 0 }
    entry.amount += Number(cells[eValue])
    entry.lineCount += 1
    byKan.set(cells[eKan]!, entry)
  }
  return byKan
}

function sumExpenditureByKou(
  jurisdiction: string,
  year: string,
  phase: string,
  fund: string,
  kan: string,
): Map<string, { amount: number; lineCount: number }> {
  const expLines = readFileSync(join(DATA_DIR, jurisdiction, 'expenditure.csv'), 'utf8').trimEnd().split('\n')
  const header = expLines[0]!.split(',')
  const col = (name: string) => header.indexOf(name)
  const eYear = col('fiscal_year')
  const ePhase = col('phase_id')
  const eFund = col('fund_code')
  const eKan = col('kan_code')
  const eKou = col('kou_code')
  const eValue = col('value')

  const byKou = new Map<string, { amount: number; lineCount: number }>()
  for (const line of expLines.slice(1)) {
    const cells = line.split(',')
    if (cells[eYear] !== year || cells[ePhase] !== phase || cells[eFund] !== fund || cells[eKan] !== kan) continue
    const entry = byKou.get(cells[eKou]!) ?? { amount: 0, lineCount: 0 }
    entry.amount += Number(cells[eValue])
    entry.lineCount += 1
    byKou.set(cells[eKou]!, entry)
  }
  return byKou
}

describe('budgets:aggregate (hierarchy axis)', () => {
  test('三鷹市: groupBy=hierarchy（根）の各セルが、配布物 CSV から直接数えた款別の値と一致する', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', fund: '01', groupBy: ['hierarchy'] })}`,
    )
    expect(res.status).toBe(200)
    const body = await res.json() as AggregateResponse
    const expected = sumExpenditureByKan('132047', '2024', 'approved', '01')

    expect(body.cells.length).toBe(expected.size)
    for (const cell of body.cells) {
      expect(cell.dimensions.length).toBe(1)
      expect(cell.dimensions[0]!.dimension).toBe('hierarchy')
      const exp = expected.get(cell.dimensions[0]!.code)
      expect(exp).toBeDefined()
      expect(cell.amount).toBe(exp!.amount)
      expect(cell.lineCount).toBe(exp!.lineCount)
    }
    // hierarchy 単独に COFOG の残余は無い
    expect(body.residual).toEqual({
      unclassifiable: { amount: 0, lineCount: 0 },
      outOfScope: { amount: 0, lineCount: 0 },
      notDescended: { amount: 0, lineCount: 0 },
    })
  })

  test('hierarchyParent=kan=10 で教育費の直下（項）が返り、その合計が款の合計と一致する', async () => {
    const kanRes = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', fund: '01', groupBy: ['hierarchy'] })}`,
    )
    const kanBody = await kanRes.json() as AggregateResponse
    const kanCell = kanBody.cells.find((c) => c.dimensions[0]!.code === '10')!
    expect(kanCell).toBeDefined()

    const kouRes = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', fund: '01', groupBy: ['hierarchy'], hierarchyParent: 'kan=10' })}`,
    )
    expect(kouRes.status).toBe(200)
    const kouBody = await kouRes.json() as AggregateResponse
    const expected = sumExpenditureByKou('132047', '2024', 'approved', '01', '10')

    expect(kouBody.cells.length).toBe(expected.size)
    let sumAmount = 0
    let sumLines = 0
    for (const cell of kouBody.cells) {
      expect(cell.dimensions[0]!.dimension).toBe('hierarchy')
      const exp = expected.get(cell.dimensions[0]!.code)
      expect(exp).toBeDefined()
      expect(cell.amount).toBe(exp!.amount)
      sumAmount += cell.amount
      sumLines += cell.lineCount
    }
    expect(sumAmount).toBe(kanCell.amount)
    expect(sumLines).toBe(kanCell.lineCount)
  })

  test('目（moku）を hierarchyParent に指定すると400（本文に理由が入る）', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', fund: '01', groupBy: ['hierarchy'], hierarchyParent: 'kan=10/kou=01/moku=01' })}`,
    )
    expect(res.status).toBe(400)
    const body = await res.json() as { message: string }
    expect(body.message.length).toBeGreaterThan(0)
  })

  test('hierarchy 以外の軸で hierarchyParent を渡すと400', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', groupBy: ['cofog.division'], hierarchyParent: 'kan=10' })}`,
    )
    expect(res.status).toBe(400)
  })

  test('fund=all のまま hierarchy を集計すると400（款・項のコードは会計内でしか一意でない）', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132047" AND fiscalYear = 2024', direction: 'expenditure', phase: 'approved', groupBy: ['hierarchy'] })}`,
    )
    expect(res.status).toBe(400)
  })
})

describe('budgets:aggregate (fiscalYear axis)', () => {
  test('狛江市: groupBy=fiscalYear が6年度ぶん返り、2018/2019 の fundScope にだけ公共下水道特別会計が入る', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132195"', direction: 'expenditure', phase: 'adjusted', groupBy: ['fiscalYear'] })}`,
    )
    expect(res.status).toBe(200)
    const body = await res.json() as AggregateResponse & { cells: (AggregateResponse['cells'][number] & { fundScope: { funds: { code: string }[] } })[] }
    expect(body.cells.length).toBe(6)
    expect(body.cells.map((c) => c.dimensions[0]!.code).sort()).toEqual(['2018', '2019', '2020', '2021', '2022', '2023'])

    const sewerFundCode = '21'
    for (const cell of body.cells) {
      const year = cell.dimensions[0]!.code
      const hasSewer = cell.fundScope.funds.some((f) => f.code === sewerFundCode)
      if (year === '2018' || year === '2019') {
        expect(hasSewer).toBe(true)
      } else {
        expect(hasSewer).toBe(false)
      }
    }
    expect(body.total).toBeDefined()
  })

  test('groupBy=fiscalYear,cofog.division はセルごとに division と fundScope を持つ', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132195"', direction: 'expenditure', phase: 'adjusted', groupBy: ['fiscalYear', 'cofog.division'] })}`,
    )
    expect(res.status).toBe(200)
    const body = await res.json() as AggregateResponse & { cells: (AggregateResponse['cells'][number] & { fundScope: unknown })[] }
    expect(body.cells.length).toBeGreaterThan(0)
    for (const cell of body.cells) {
      expect(cell.dimensions.map((d) => d.dimension)).toEqual(['fiscalYear', 'cofog.division'])
      expect(cell.fundScope).toBeDefined()
    }
  })

  test('jurisdiction と fiscalYear を同時に軸にする組み合わせは v1 では未対応（400）', async () => {
    const res = await get(
      `/v0/budgets:aggregate?${aggQuery({ filter: 'jurisdiction = "132195"', direction: 'expenditure', phase: 'adjusted', groupBy: ['jurisdiction', 'fiscalYear'] })}`,
    )
    expect(res.status).toBe(400)
  })
})

type SearchResponse = {
  matches: {
    name: string
    budget: string
    fiscalYear: string
    direction: string
    fund: { code: string; label: string | null }
    matched: { field: string; level: string; value: string }
    nameSource: string
    hierarchy: unknown[]
    amounts: { phase: string; amount: number }[]
  }[]
  coverage: { searchedNameFields: string[]; namedCoverage: { budget: string; field: string; code: string; message: string }[] }
  judgment: string[]
  provenance: { sources: unknown[]; byBudget: Record<string, string[]> }
  revision: string
  nextPageToken?: string
}

/**
 * budgetLines:search は1回のリクエストで名称索引の全チャンクを走査し、該当を集めてから
 * pageSize で切る（design doc「名称の検索」の直し。旧実装は明細チャンク単位でしか走査せず、
 * 該当が複数チャンクに散らばると空の matches を何度も返した）。それでも pageSize を超える
 * 該当がある場合の複数ページ分は、このヘルパーで nextPageToken が無くなるまで集める。
 */
async function collectSearchMatches(params: Record<string, string | string[]>): Promise<SearchResponse> {
  let pageToken: string | undefined
  const matches: SearchResponse['matches'] = []
  let last: SearchResponse | undefined
  do {
    const res = await get(`/v0/budgets/-/budgetLines:search?${aggQuery(pageToken ? { ...params, pageToken } : params)}`)
    expect(res.status).toBe(200)
    const body = await res.json() as SearchResponse
    last = body
    matches.push(...body.matches)
    pageToken = body.nextPageToken
  } while (pageToken !== undefined)
  return { ...last!, matches }
}

describe('budgetLines:search (名称の検索)', () => {
  test('「いじめ」で三鷹市（accountLabel/canonical）と狛江市（projectName/judgment）の両方が引ける', async () => {
    const body = await collectSearchMatches({ query: 'いじめ' })
    expect(body.matches.length).toBeGreaterThan(0)

    const mitaka = body.matches.filter((m) => m.budget.startsWith('budgets/132047'))
    expect(mitaka.length).toBeGreaterThan(0)
    for (const m of mitaka) {
      expect(m.matched.field).toBe('accountLabel')
      expect(m.nameSource).toBe('canonical')
      expect(m.matched.value).toContain('いじめ')
    }

    const komae = body.matches.filter((m) => m.budget.startsWith('budgets/132195'))
    expect(komae.length).toBeGreaterThan(0)
    for (const m of komae) {
      expect(m.matched.field).toBe('projectName')
      expect(m.nameSource).toBe('judgment')
      expect(m.matched.value).toContain('いじめ')
    }
  })

  test('「いじめ」は1回の呼び出し（ページングを回さずに）で三鷹市と狛江市の両方を返す', async () => {
    // 名称索引は数千件のオーダーで、1リクエストで全チャンクを走査して該当を集める
    // （design doc の直し。旧実装は明細チャンク単位でしか走査せず60回超のページングが要った）。
    const res = await get(`/v0/budgets/-/budgetLines:search?${aggQuery({ query: 'いじめ' })}`)
    expect(res.status).toBe(200)
    const body = await res.json() as SearchResponse
    expect(body.nextPageToken).toBeUndefined()
    expect(body.matches.some((m) => m.budget.startsWith('budgets/132047'))).toBe(true)
    expect(body.matches.some((m) => m.budget.startsWith('budgets/132195'))).toBe(true)
  })

  test('ページングは該当に対して行う: 0件のページを返さず、nextPageToken は続きがあるときだけ返る', async () => {
    // 1回の呼び出し（pageSize 省略）で得られる総数を基準に、pageSize=2 で強制的に
    // 複数ページへ割り、各ページが実際に埋まっていること・合計が一致することを見る。
    const wholeRes = await get(`/v0/budgets/-/budgetLines:search?${aggQuery({ query: 'いじめ' })}`)
    const whole = await wholeRes.json() as SearchResponse
    expect(whole.matches.length).toBeGreaterThan(2) // pageSize=2 で複数ページに割れることの前提

    let pageToken: string | undefined
    let pages = 0
    let totalMatches = 0
    do {
      const res = await get(`/v0/budgets/-/budgetLines:search?${aggQuery(pageToken ? { query: 'いじめ', pageSize: '2', pageToken } : { query: 'いじめ', pageSize: '2' })}`)
      expect(res.status).toBe(200)
      const body = await res.json() as SearchResponse
      // 該当が尽きて0件になるページは無い。最後のページも「続きが無い」だけで、matches 自体は空にならない
      expect(body.matches.length).toBeGreaterThan(0)
      totalMatches += body.matches.length
      pageToken = body.nextPageToken
      pages++
    } while (pageToken !== undefined && pages < 20)
    expect(pages).toBeLessThan(20)
    expect(pages).toBeGreaterThan(1)
    expect(totalMatches).toBe(whole.matches.length)
  })

  test('各 match に fiscalYear / direction / fund が入っている', async () => {
    const body = await collectSearchMatches({ query: 'いじめ' })
    expect(body.matches.length).toBeGreaterThan(0)
    for (const m of body.matches) {
      expect(m.fiscalYear).toMatch(/^\d{4}$/)
      expect(['expenditure', 'revenue']).toContain(m.direction)
      expect(typeof m.fund.code).toBe('string')
    }
  })

  test('狛江市の款を level に指定した検索は400になり、projectName で引ける旨が本文に入る（決算資料PDFの無い2018年度）', async () => {
    const res = await get(
      `/v0/budgets/-/budgetLines:search?${aggQuery({ query: '教育', filter: 'jurisdiction = "132195" AND fiscalYear = 2018', level: 'kan' })}`,
    )
    expect(res.status).toBe(400)
    const body = await res.json() as { message: string }
    expect(body.message).toContain('projectName')
  })

  test('決算資料PDFのある2023年度は款に判断由来の名称があるので同じ level 指定でも400にならない', async () => {
    const res = await get(
      `/v0/budgets/-/budgetLines:search?${aggQuery({ query: '教育', filter: 'jurisdiction = "132195" AND fiscalYear = 2023', level: 'kan' })}`,
    )
    expect(res.status).toBe(200)
  })

  test('jurisdiction を伴わない fund 指定は400', async () => {
    const res = await get(`/v0/budgets/-/budgetLines:search?${aggQuery({ query: 'いじめ', fund: '01' })}`)
    expect(res.status).toBe(400)
  })

  test('coverage は filter の範囲に応じて変わる', async () => {
    const mitakaRes = await get(
      `/v0/budgets/-/budgetLines:search?${aggQuery({ query: '教育', filter: 'jurisdiction = "132047" AND fiscalYear = 2024', nameField: ['accountLabel'], level: 'kan' })}`,
    )
    expect(mitakaRes.status).toBe(200)
    const mitakaBody = await mitakaRes.json() as SearchResponse
    // 三鷹市は款が canonical な名称を持つので accountLabel の欠損は無い
    expect(mitakaBody.coverage.namedCoverage.filter((c) => c.budget === 'budgets/132047:2024')).toEqual([])

    const komaeRes = await get(
      `/v0/budgets/-/budgetLines:search?${aggQuery({ query: '教育', filter: 'jurisdiction = "132195" AND fiscalYear = 2018', nameField: ['accountLabel'], level: 'kan' })}`,
    )
    expect(komaeRes.status).toBe(400) // 2018 は款に名称が無いので level=kan 自体が 400（上のテストと同じ理由）

    const komaeNoLevelRes = await get(
      `/v0/budgets/-/budgetLines:search?${aggQuery({ query: '教育', filter: 'jurisdiction = "132195" AND fiscalYear = 2018', nameField: ['projectName'] })}`,
    )
    expect(komaeNoLevelRes.status).toBe(200)
    const komaeNoLevelBody = await komaeNoLevelRes.json() as SearchResponse
    // 2018年度は project_names.csv の収録範囲（2020〜2023年度）に無いので PARTIAL_NAMES が立つ
    expect(
      komaeNoLevelBody.coverage.namedCoverage.some(
        (c) => c.budget === 'budgets/132195:2018' && c.field === 'projectName' && c.code === 'PARTIAL_NAMES',
      ),
    ).toBe(true)

    const komaeWithNamesRes = await get(
      `/v0/budgets/-/budgetLines:search?${aggQuery({ query: '教育', filter: 'jurisdiction = "132195" AND fiscalYear = 2023', nameField: ['projectName'] })}`,
    )
    const komaeWithNamesBody = await komaeWithNamesRes.json() as SearchResponse
    // 2023年度は projectName の収録年度に入っているので、この budget には PARTIAL_NAMES が立たない
    // （fund が一般会計だけの前提。他会計が存在すれば別途 PARTIAL_NAMES が立ちうる）
    expect(
      komaeWithNamesBody.coverage.namedCoverage.filter((c) => c.budget === 'budgets/132195:2023' && c.field === 'projectName' && c.code === 'PARTIAL_NAMES' && c.message.includes('fiscal years')),
    ).toEqual([])
  })

  test('未知の団体は404、実在しない filter フィールドは400', async () => {
    expect((await get(`/v0/budgets/-/budgetLines:search?${aggQuery({ query: 'いじめ', filter: 'jurisdiction = "999999"' })}`)).status).toBe(404)
    expect((await get(`/v0/budgets/-/budgetLines:search?${aggQuery({ query: 'いじめ', filter: 'direction = expenditure' })}`)).status).toBe(400)
  })

  test('phase を指定すると、その段階を持つ明細に絞られ、amounts もその段階だけになる', async () => {
    const body = await collectSearchMatches({ query: 'いじめ', filter: 'jurisdiction = "132195"', phase: 'executed', nameField: ['projectName'] })
    expect(body.matches.length).toBeGreaterThan(0)
    for (const m of body.matches) {
      expect(m.amounts.length).toBe(1)
      expect(m.amounts[0]!.phase).toBe('executed')
    }
  })

  test('nameField=accountLabel だけに絞ると projectName の一致（狛江市）は現れない', async () => {
    const body = await collectSearchMatches({ query: 'いじめ', nameField: ['accountLabel'] })
    expect(body.matches.length).toBeGreaterThan(0)
    expect(body.matches.every((m) => m.matched.field === 'accountLabel')).toBe(true)
    expect(body.judgment).toEqual([])
  })

  test('provenance と revision が応答に含まれる', async () => {
    const res = await get(`/v0/budgets/-/budgetLines:search?${aggQuery({ query: 'いじめ' })}`)
    const body = await res.json() as SearchResponse
    expect(body.provenance.sources.length).toBeGreaterThan(0)
    expect(body.revision).toMatch(/^[0-9a-f]{40}/)
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
      '/budgets/{budget}/budgetLines',
      '/datapackages/{jurisdiction}/{file}',
    ]))
    // statement は budgetLines へ置き換えて削除した(旧 path を残さない。design doc Backward Compatibility)
    expect(Object.keys(spec.paths)).not.toContain('/budgets/{budget}/statement')
    const raw = JSON.stringify(spec)
    // budgetLines の union(旧 scope)は view に変えて廃止したが、cofogDepth の
    // discriminatedUnion(applicable)がまだ oneOf を生む
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

    const cross = await client.getBudgetLines({
      budget: '-',
      filter: 'cofog.division = "09"',
      pageSize: 3,
    })
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
