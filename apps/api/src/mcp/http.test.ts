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

/**
 * legacy era（〜2025-11-25）の initialize。envelope claim を持たないので
 * 旧来どおり transport の stateless serving に回る（index.ts の isLegacyRequest 分岐）。
 */
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

/**
 * modern era（2026-07-28）の envelope。modern には initialize が無く、
 * 毎リクエストが params._meta で版と client capabilities を主張する
 * （必須キーは io.modelcontextprotocol/protocolVersion と
 * io.modelcontextprotocol/clientCapabilities。clientInfo は SHOULD）。
 */
const modernEnvelope = {
  'io.modelcontextprotocol/protocolVersion': '2026-07-28',
  'io.modelcontextprotocol/clientCapabilities': {},
  'io.modelcontextprotocol/clientInfo': { name: 'test-client', version: '0.0.0' },
}

/**
 * modern リクエストのヘッダ。`mcp-protocol-version` は envelope との cross-check、
 * `Mcp-Method` は全リクエスト必須、`Mcp-Name` は tools/call のように params.name を
 * 持つ method で必須（SEP-2243。欠落・不一致は -32020）。
 */
function modernHeaders(method: string, name?: string): Record<string, string> {
  return {
    'mcp-protocol-version': '2026-07-28',
    'mcp-method': method,
    ...(name !== undefined ? { 'mcp-name': name } : {}),
  }
}

const discoverBody = {
  jsonrpc: '2.0' as const,
  id: 1,
  method: 'server/discover',
  params: { _meta: modernEnvelope },
}

describe('/mcp (remote MCP server)', () => {
  test('legacy initialize negotiates 2025-11-25 (claim-less request → legacy serving)', async () => {
    const res = await rpc(initializeBody)
    expect(res.status).toBe(200)
    const body = (await res.json()) as { result: { protocolVersion: string; serverInfo: { name: string } } }
    expect(body.result.serverInfo.name).toBe('fudoki-mcp')
    expect(body.result.protocolVersion).toBe('2025-11-25')
  })

  test('modern server/discover answers the 2026-07-28 revision', async () => {
    const res = await rpc(discoverBody, modernHeaders('server/discover'))
    expect(res.status).toBe(200)
    const body = (await res.json()) as {
      result: { resultType: string; supportedVersions: string[]; _meta?: Record<string, unknown> }
    }
    expect(body.result.resultType).toBe('complete')
    expect(body.result.supportedVersions).toContain('2026-07-28')
  })

  test('modern tools/call reaches the same tool handlers (aggregate_budgets)', async () => {
    const res = await rpc(
      {
        jsonrpc: '2.0',
        id: 12,
        method: 'tools/call',
        params: {
          name: 'aggregate_budgets',
          arguments: {
            filter: 'jurisdiction = "132047" AND fiscalYear = "2024"',
            direction: 'expenditure',
            phase: 'approved',
            groupBy: ['cofog.division'],
          },
          _meta: modernEnvelope,
        },
      },
      modernHeaders('tools/call', 'aggregate_budgets'),
    )
    expect(res.status).toBe(200)
    const body = (await res.json()) as {
      result: {
        resultType: string
        structuredContent: { cells: { dimensions: { dimension: string; code: string }[]; amount: number }[] }
      }
    }
    expect(body.result.resultType).toBe('complete')
    const division01 = body.result.structuredContent.cells.find((c) =>
      c.dimensions.some((d) => d.dimension === 'cofog.division' && d.code === '01'),
    )
    expect(division01?.amount).toBe(10_997_811_000)
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
    expect(firstBody.result.structuredContent.jurisdictions.length).toBe(5)
    expect(secondBody.result.structuredContent.jurisdictions.length).toBe(5)
  })

  test('missing Accept header is rejected (transport requirement, not a session artifact)', async () => {
    const res = await app.request(
      'https://api.fudoki.dev/mcp',
      { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(initializeBody) },
      env,
    )
    expect(res.status).toBe(406)
  })

  // PR #27 レビュー指摘: MCP Streamable HTTP 仕様の Security Considerations が Origin ヘッダの
  // 検証を MUST としている（不正なら 403）。第三者のサイトが被害者のブラウザ経由で `/mcp` を叩き、
  // 匿名のレート制限枠を消費できてしまうのを防ぐため。
  test('Origin validation: disallowed browser Origin is rejected with 403', async () => {
    const res = await rpc(initializeBody, { origin: 'https://evil.example' })
    expect(res.status).toBe(403)
    const body = (await res.json()) as { error: string }
    expect(body.error).toBe('FORBIDDEN')
  })

  test('Origin validation: allowlisted Origin (fudoki.dev) passes through', async () => {
    const res = await rpc(initializeBody, { origin: 'https://fudoki.dev' })
    expect(res.status).toBe(200)
  })

  test('Origin validation: request with no Origin header (non-browser client) passes through', async () => {
    // rpc() ヘルパーは既定で origin ヘッダを付けない ── curl やネイティブの MCP client を模す
    const res = await rpc(initializeBody)
    expect(res.status).toBe(200)
  })

  // `/mcp` の preflight も同じ allowlist に絞る（index.ts の cors()）。mcp-method 等の
  // カスタムヘッダを使う modern client は必ず preflight を踏むので、不許可のオリジンは
  // ブラウザが実リクエストを送る前にここで止まる。
  async function preflight(origin: string): Promise<Response> {
    return app.fetch(
      new Request('http://localhost/mcp', {
        method: 'OPTIONS',
        headers: {
          origin,
          'access-control-request-method': 'POST',
          'access-control-request-headers': 'content-type, mcp-protocol-version, mcp-method',
        },
      }),
      env,
    )
  }

  test('CORS preflight: allowlisted Origin gets ACAO for /mcp', async () => {
    const res = await preflight('https://fudoki.dev')
    expect(res.headers.get('access-control-allow-origin')).toBe('https://fudoki.dev')
    expect(res.headers.get('access-control-allow-headers')).toContain('mcp-method')
  })

  test('CORS preflight: disallowed Origin gets no ACAO for /mcp', async () => {
    const res = await preflight('https://evil.example')
    expect(res.headers.get('access-control-allow-origin')).toBeNull()
  })
})
