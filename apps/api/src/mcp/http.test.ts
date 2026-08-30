/**
 * `/mcp`（remote MCP サーバ）の HTTP レベル統合テスト。
 * `../index.test.ts` と同じ流儀 ── dist/assets を本物の assets として読み、
 * Worker の fetch（Hono の app オブジェクト）を直接叩く。JSON-RPC のボディを
 * 素朴に POST し、`WebStandardStreamableHTTPServerTransport` が返す応答を検査する。
 */
import { beforeAll, describe, expect, test } from 'bun:test'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import app from '../index'
import type { Env, KVNamespaceLike, RateLimiterLike } from '../assets'

const ASSETS_DIR = join(import.meta.dir, '../../dist/assets')

const alwaysAllow: RateLimiterLike = {
  async limit() {
    return { success: true }
  },
}

const neverGet: KVNamespaceLike = {
  async get() {
    return null
  },
  async put() {},
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
  API_KEYS: neverGet,
  RATE_LIMIT_ANONYMOUS: alwaysAllow,
  RATE_LIMIT_AUTHENTICATED: alwaysAllow,
}

beforeAll(() => {
  if (!existsSync(join(ASSETS_DIR, 'meta/jurisdictions.json'))) {
    throw new Error('dist/assets is missing. Run `bun run build` first (the test script does this).')
  }
})

/**
 * MCP Streamable HTTP の POST は `Accept: application/json, text/event-stream` を
 * 要求する（無いと 406）。transport 側は `enableJsonResponse: true` で構成しているので
 * （index.ts）、成功応答は SSE ではなく単発の JSON で返る。
 */
async function rpc(body: unknown, headers: Record<string, string> = {}): Promise<Response> {
  return app.request(
    'https://api.fudoki.dev/mcp',
    {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream', ...headers },
      body: JSON.stringify(body),
    },
    env,
  )
}

const initializeBody = {
  jsonrpc: '2.0' as const,
  id: 1,
  method: 'initialize',
  params: {
    protocolVersion: '2025-11-25',
    capabilities: {},
    clientInfo: { name: 'test-client', version: '0.0.0' },
  },
}

describe('/mcp (remote MCP server)', () => {
  test('initialize negotiates a protocol version the SDK supports (<= 2025-11-25)', async () => {
    const res = await rpc(initializeBody)
    expect(res.status).toBe(200)
    const body = (await res.json()) as { result: { protocolVersion: string; serverInfo: { name: string } } }
    expect(body.result.serverInfo.name).toBe('fudoki-mcp')
    // SDK 1.30.0 が知っている最大の仕様版（AGENTS.md の実測どおり、2026-07-28 ではない）
    expect(body.result.protocolVersion).toBe('2025-11-25')
  })

  test('tools/list exposes the 5 budget tools', async () => {
    const res = await rpc({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} })
    expect(res.status).toBe(200)
    const body = (await res.json()) as { result: { tools: { name: string }[] } }
    const names = body.result.tools.map((t) => t.name).sort()
    expect(names).toEqual([
      'aggregate_budgets',
      'get_budget_lines',
      'list_budgets',
      'list_jurisdictions',
      'search_budget_lines',
    ])
  })

  test('tools/call aggregate_budgets (三鷹市 2024 歳出 approved / cofog.division) matches independently verified totals', async () => {
    const res = await rpc({
      jsonrpc: '2.0',
      id: 3,
      method: 'tools/call',
      params: {
        name: 'aggregate_budgets',
        arguments: {
          filter: 'jurisdiction = "132047" AND fiscalYear = "2024"',
          direction: 'expenditure',
          phase: 'approved',
          groupBy: ['cofog.division'],
        },
      },
    })
    expect(res.status).toBe(200)
    const body = (await res.json()) as {
      result: {
        structuredContent: {
          cells: { dimensions: { dimension: string; code: string }[]; amount: number; lineCount: number }[]
          total?: { amount: number; lineCount: number }
        }
      }
    }
    const cells = body.result.structuredContent.cells
    const division01 = cells.find((c) => c.dimensions.some((d) => d.dimension === 'cofog.division' && d.code === '01'))
    expect(division01).toBeDefined()
    expect(division01?.amount).toBe(10_997_811_000)
    expect(division01?.lineCount).toBe(1_422)
    expect(body.result.structuredContent.total?.amount).toBe(122_908_044_000)
  })

  test('tools/call aggregate_budgets with groupBy=hierarchy (三鷹市 2024 歳出 approved fund=01) matches independently verified totals', async () => {
    const res = await rpc({
      jsonrpc: '2.0',
      id: 8,
      method: 'tools/call',
      params: {
        name: 'aggregate_budgets',
        arguments: {
          filter: 'jurisdiction = "132047" AND fiscalYear = "2024"',
          direction: 'expenditure',
          phase: 'approved',
          fund: '01',
          groupBy: ['hierarchy'],
        },
      },
    })
    expect(res.status).toBe(200)
    const body = (await res.json()) as {
      result: {
        structuredContent: {
          cells: { dimensions: { dimension: string; code: string }[]; amount: number; lineCount: number }[]
        }
      }
    }
    const cells = body.result.structuredContent.cells
    const kan01 = cells.find((c) => c.dimensions.some((d) => d.dimension === 'hierarchy' && d.code === '01'))
    const kan03 = cells.find((c) => c.dimensions.some((d) => d.dimension === 'hierarchy' && d.code === '03'))
    expect(kan01?.amount).toBe(529_109_000)
    expect(kan01?.lineCount).toBe(59)
    expect(kan03?.amount).toBe(43_047_116_000)
    expect(kan03?.lineCount).toBe(1_344)
  })

  test('tools/call aggregate_budgets with groupBy=hierarchy and fund omitted (defaults to "all") is rejected', async () => {
    const res = await rpc({
      jsonrpc: '2.0',
      id: 9,
      method: 'tools/call',
      params: {
        name: 'aggregate_budgets',
        arguments: {
          filter: 'jurisdiction = "132047" AND fiscalYear = "2024"',
          direction: 'expenditure',
          phase: 'approved',
          groupBy: ['hierarchy'],
        },
      },
    })
    expect(res.status).toBe(200)
    const body = (await res.json()) as { result: { isError: boolean; content: { text: string }[] } }
    expect(body.result.isError).toBe(true)
    expect(body.result.content[0]!.text).toContain('BAD_REQUEST')
  })

  test('tools/call aggregate_budgets with hierarchyParent pointing at moku is rejected', async () => {
    const res = await rpc({
      jsonrpc: '2.0',
      id: 10,
      method: 'tools/call',
      params: {
        name: 'aggregate_budgets',
        arguments: {
          filter: 'jurisdiction = "132047" AND fiscalYear = "2024"',
          direction: 'expenditure',
          phase: 'approved',
          fund: '01',
          groupBy: ['hierarchy'],
          hierarchyParent: 'kan=10/kou=04/moku=01',
        },
      },
    })
    expect(res.status).toBe(200)
    const body = (await res.json()) as { result: { isError: boolean; content: { text: string }[] } }
    expect(body.result.isError).toBe(true)
    expect(body.result.content[0]!.text).toContain('BAD_REQUEST')
  })

  test('tools/call search_budget_lines finds "いじめ" in both 三鷹市 (canonical) and 狛江市 (judgment) in a single call', async () => {
    // 名称索引は1リクエストで全チャンクを走査して該当を集めるので（design doc の直し。旧実装は
    // 明細チャンク単位でしか走査せず、ページングを何十回も回す必要があった）、ページングは回さない。
    type Match = { budget: string; nameSource: string; matched: { value: string } }
    const res = await rpc({
      jsonrpc: '2.0',
      id: 11,
      method: 'tools/call',
      params: {
        name: 'search_budget_lines',
        arguments: { query: 'いじめ' },
      },
    })
    expect(res.status).toBe(200)
    const body = (await res.json()) as {
      result: { structuredContent: { matches: Match[]; nextPageToken?: string } }
    }
    expect(body.result.structuredContent.nextPageToken).toBeUndefined()

    const matches = body.result.structuredContent.matches
    const mitaka = matches.find((m) => m.budget.startsWith('budgets/132047'))
    const komae = matches.find((m) => m.budget.startsWith('budgets/132195'))
    expect(mitaka).toBeDefined()
    expect(mitaka?.nameSource).toBe('canonical')
    expect(komae).toBeDefined()
    expect(komae?.nameSource).toBe('judgment')
  })

  test('tools/call get_budget_lines returns BASIC by default and FULL when requested', async () => {
    const basic = await rpc({
      jsonrpc: '2.0',
      id: 6,
      method: 'tools/call',
      params: {
        name: 'get_budget_lines',
        arguments: { budget: '132195:2023', filter: 'direction = "expenditure"', pageSize: 1 },
      },
    })
    expect(basic.status).toBe(200)
    const basicBody = (await basic.json()) as {
      result: { structuredContent: { lines: Record<string, unknown>[]; revision: string } }
    }
    const basicLine = basicBody.result.structuredContent.lines[0]!
    expect(basicLine['amount']).toMatchObject({ phase: expect.any(String), amount: expect.any(Number) })
    expect(basicLine['hierarchy']).toBeUndefined()

    const full = await rpc({
      jsonrpc: '2.0',
      id: 7,
      method: 'tools/call',
      params: {
        name: 'get_budget_lines',
        arguments: { budget: '132195:2023', filter: 'direction = "expenditure"', view: 'FULL', pageSize: 1 },
      },
    })
    expect(full.status).toBe(200)
    const fullBody = (await full.json()) as { result: { structuredContent: { lines: { hierarchy: unknown[] }[] } } }
    expect(fullBody.result.structuredContent.lines[0]!.hierarchy.length).toBeGreaterThan(0)
  })

  test('no API key required (PRD Goal: 鍵の設定なしに使える)', async () => {
    // env.API_KEYS.get は常に null を返す fake ── Authorization ヘッダを付けずに叩けることを見る
    const res = await rpc({ jsonrpc: '2.0', id: 4, method: 'tools/list', params: {} })
    expect(res.status).toBe(200)
  })

  test('two consecutive tools/call requests both succeed (stateless: no session carried between calls)', async () => {
    const callOnce = () =>
      rpc({
        jsonrpc: '2.0',
        id: 5,
        method: 'tools/call',
        params: {
          name: 'list_jurisdictions',
          arguments: {},
        },
      })
    const first = await callOnce()
    const second = await callOnce()
    expect(first.status).toBe(200)
    expect(second.status).toBe(200)
    const firstBody = (await first.json()) as { result: { structuredContent: { jurisdictions: unknown[] } } }
    const secondBody = (await second.json()) as { result: { structuredContent: { jurisdictions: unknown[] } } }
    expect(firstBody.result.structuredContent.jurisdictions.length).toBe(3)
    expect(secondBody.result.structuredContent.jurisdictions.length).toBe(3)
  })

  test('missing Accept header is rejected (transport requirement, not a session artifact)', async () => {
    const res = await app.request(
      'https://api.fudoki.dev/mcp',
      { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(initializeBody) },
      env,
    )
    expect(res.status).toBe(406)
  })
})
