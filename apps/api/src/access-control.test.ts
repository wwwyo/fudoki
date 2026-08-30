/**
 * accessControl() 単体のテスト。production の router（index.ts）には
 * 意図的に例外を投げるルートが無いので、ここでは middleware だけを
 * 最小の Hono app に差して検証する（本番ルートを汚さない）。
 */
import { describe, expect, test } from 'bun:test'
import { Hono } from 'hono'
import { accessControl } from './access-control'
import type { Env, KVNamespaceLike, RateLimiterLike } from './assets'

const alwaysAllow: RateLimiterLike = {
  async limit() {
    return { success: true }
  },
}
const emptyKv: KVNamespaceLike = {
  async get() {
    return null
  },
  async put() {},
}
const env: Env = {
  ASSETS: { async fetch() { return new Response(null, { status: 404 }) } },
  API_KEYS: emptyKv,
  RATE_LIMIT_ANONYMOUS: alwaysAllow,
  RATE_LIMIT_AUTHENTICATED: alwaysAllow,
}

function buildApp() {
  const app = new Hono<{ Bindings: Env }>()
  app.use('*', accessControl())
  app.get('/v0/boom', () => {
    throw new Error('boom')
  })
  app.onError((_err, c) => c.json({ error: 'INTERNAL' }, 500))
  return app
}

describe('accessControl: logging survives a downstream exception', () => {
  test('a route that throws still produces exactly one access log line, with status 500', async () => {
    const app = buildApp()
    const lines: string[] = []
    const original = console.log
    console.log = (...args: unknown[]) => {
      lines.push(args.map(String).join(' '))
    }
    let res: Response
    try {
      res = await app.request('https://api.fudoki.dev/v0/boom', {}, env)
    } finally {
      console.log = original
    }
    expect(res.status).toBe(500)
    expect(lines.length).toBe(1)
    const entry = JSON.parse(lines[0]!) as { path: string; status: number }
    expect(entry.path).toBe('/v0/boom')
    expect(entry.status).toBe(500)
  })
})
