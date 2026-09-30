import type { D1Database } from '@fudoki/data-contracts'

export interface KVNamespaceLike {
  get(key: string): Promise<string | null>
  put(key: string, value: string): Promise<void>
}
export interface RateLimiterLike {
  limit(options: { key: string }): Promise<{ success: boolean }>
}
export interface Env {
  DB: D1Database
  QUERY_FINGERPRINT: string
  CURSOR_SECRET: string
  DOWNLOAD_BASE_URL: string
  API_KEYS: KVNamespaceLike
  RATE_LIMIT_ANONYMOUS: RateLimiterLike
  RATE_LIMIT_AUTHENTICATED: RateLimiterLike
}
