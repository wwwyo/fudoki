import { bindings, defineConfig } from '@cloudflare/config/public'

import { API_KEYS_NAMESPACE_ID, D1_DATABASE_ID } from './resources.ts'
import { rateLimitRules } from './src/lib/rate-limit-rules.ts'
import { randomBytes } from 'node:crypto'
import { queryFingerprint } from './scripts/query-fingerprint.ts'

export default defineConfig(async (ctx) => ({
  worker: {
    name: 'fudoki-api',
    compatibilityDate: '2026-08-18',
    entrypoint: 'src/index.ts',
    observability: {
      enabled: true,
    },
    domains: ['api.fudoki.dev'],
    env: {
      DOWNLOAD_BASE_URL: bindings.text(
        ctx.mode === 'development'
          ? 'http://127.0.0.1:8788'
          : 'https://download.fudoki.dev'
      ),
      QUERY_FINGERPRINT: bindings.text(await queryFingerprint()),
      CURSOR_SECRET:
        ctx.mode === 'development'
          ? bindings.text(randomBytes(32).toString('hex'))
          : bindings.secret(),
      DB: bindings.d1({
        name: 'fudoki',
        id: D1_DATABASE_ID,
      }),
      API_KEYS: bindings.kv({
        id: API_KEYS_NAMESPACE_ID,
      }),
      RATE_LIMIT_ANONYMOUS: bindings.rateLimit({
        namespace: '1001',
        simple: rateLimitRules.anonymous,
      }),
      RATE_LIMIT_AUTHENTICATED: bindings.rateLimit({
        namespace: '1002',
        simple: rateLimitRules.authenticated,
      }),
    },
  },
}))
