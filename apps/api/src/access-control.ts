/**
 * ベータ期間のアクセス制御。Hono の `app.use` 層に1本だけ差す middleware。
 *
 * ⚠️ oRPC の middleware ではなくここに置く理由: `/v0/datapackages/*` の
 * パススルー（配布物ダウンロード。index.ts の `app.on(['GET','HEAD'], '/v0/datapackages/...')`）は
 * oRPC router を経由しないので、oRPC 層に掛けると配布物ダウンロードだけ素通りする。
 *
 * ⚠️ 登録位置は `index.ts` で `app.use('*', cors(...))` の直後・
 * 個別ルート（`app.get('/')` 等）より前に置くこと。Hono は登録順に評価し、
 * マッチしたハンドラが応答を返すとそこで止まる。これより後ろに置くと、
 * 先に定義したルートには一切効かないまま黙って通ってしまう。
 *
 * ⚠️ CORS の preflight（OPTIONS）は `hono/cors` が `next()` を呼ばずに
 * 204 を返して短絡するため、この middleware を通らない。
 * つまり preflight はレート制限を消費しない（意図した挙動）。
 */
import type { Context, MiddlewareHandler } from 'hono'
import type { Env } from './assets'
import { apiKeyEntrySchema, sha256Hex } from './lib/apiKey'
import { classifyPath } from './lib/path-class'

/**
 * 構造化ログ（Workers Logs 経由の console.log）。
 * ⚠️ 生 IP は載せない。載せるのは ipHash（IP の SHA-256）だけ。
 */
type AccessLogEntry = {
  path: string
  method: string
  status: number
  keyId: string | undefined
  rateLimited: boolean
  ipHash: string
}

function logAccess(entry: AccessLogEntry): void {
  console.log(JSON.stringify(entry))
}

function clientIp(c: Context<{ Bindings: Env }>): string {
  // ⚠️ x-forwarded-for へはフォールバックしない。このヘッダはクライアントが
  // 自由に詐称できるので、フォールバックに使うと「CF-Connecting-IP が付かない
  // 環境」でリクエストごとに違う値を名乗るだけで匿名レート制限のバケツを
  // 好きなだけ分けられてしまう（回避口になる）。
  // 本番は Cloudflare 経由なので CF-Connecting-IP が必ず付き、ここには落ちない。
  // 無い環境（ローカル実行・テスト）では全員が 'unknown' という同じバケツを
  // 共有する ── 詐称可能なヘッダで個別に分けられるより、その方が安全。
  return c.req.header('CF-Connecting-IP') ?? 'unknown'
}

/**
 * ログに出す keyId は先頭12文字だけにする。KV のキー名（＝生のキーの SHA-256）を
 * まるごとログへ出すこと自体に実害は薄い（ログ閲覧権限だけでは KV を引けない）が、
 * 識別には12文字で十分なので、必要以上に長い秘密由来の値を書き残さない。
 */
function shortKeyId(keyId: string | undefined): string | undefined {
  return keyId?.slice(0, 12)
}

function unauthorized(
  c: Context<{ Bindings: Env }>,
  ipHash: string,
  reason: string,
): Response {
  logAccess({ path: c.req.path, method: c.req.method, status: 401, keyId: undefined, rateLimited: false, ipHash })
  return c.json({ error: 'UNAUTHORIZED', message: reason }, 401)
}

function tooManyRequests(
  c: Context<{ Bindings: Env }>,
  keyId: string | undefined,
  ipHash: string,
): Response {
  logAccess({ path: c.req.path, method: c.req.method, status: 429, keyId: shortKeyId(keyId), rateLimited: true, ipHash })
  // ⚠️ Rate Limiting binding の limit() は成功/失敗の boolean しか返さず、
  // 残量やウィンドウ長を持たない。したがって「残量ヘッダ」は正確な値を作れない。
  // 429 のときだけ Retry-After を付ける（period と同じ 60 秒。実際の値は wrangler.jsonc 側の宣言）
  return c.json({ error: 'RATE_LIMITED', message: 'too many requests' }, 429, { 'Retry-After': '60' })
}

export function accessControl(): MiddlewareHandler<{ Bindings: Env }> {
  return async (c, next) => {
    const cls = classifyPath(c.req.path)
    if (cls === 'excluded') {
      await next()
      return
    }

    const ipHash = await sha256Hex(clientIp(c))

    // /rpc はフロント専用の口で API キーを埋め込めない（公開バンドルに漏れる）設計なので、
    // Authorization ヘッダが付いていても無視し、IP だけで制限する。
    const authHeader = cls === 'rpc' ? undefined : c.req.header('Authorization')

    let keyId: string | undefined
    if (authHeader !== undefined) {
      const match = /^Bearer (.+)$/.exec(authHeader)
      if (match === null) return unauthorized(c, ipHash, 'malformed Authorization header')
      const hash = await sha256Hex(match[1]!)
      const raw = await c.env.API_KEYS.get(hash)
      if (raw === null) return unauthorized(c, ipHash, 'unknown API key')
      const parsed = apiKeyEntrySchema.safeParse(JSON.parse(raw))
      if (!parsed.success) return unauthorized(c, ipHash, 'malformed API key record')
      // ⚠️ KV の書き込み反映は最大60秒。revoke 直後の数十秒はここが古い active を読み、
      // 失効前のキーを一時的に通すことがある（即時性は保証しない）
      if (parsed.data.status !== 'active') return unauthorized(c, ipHash, 'revoked API key')
      keyId = hash
    }

    // ⚠️ キーごとにレートを変えたくなっても、Rate Limiting binding は
    // limit/period をデプロイ時（wrangler.jsonc）に固定する仕組みで、
    // 実行時にキー単位でパラメータを変えることはできない
    // （変えるならキー単位のカウンタを KV 等で自前実装する必要がある）。
    const limiter = keyId !== undefined ? c.env.RATE_LIMIT_AUTHENTICATED : c.env.RATE_LIMIT_ANONYMOUS
    const limitKey = keyId ?? ipHash
    const result = await limiter.limit({ key: limitKey })
    if (!result.success) return tooManyRequests(c, keyId, ipHash)

    // ⚠️ ログは finally で残す。await next() の後ろに直接書くと、下流のハンドラが
    // 例外を投げた経路（Hono の onError が 500 を返すケース）でログが1行も残らない。
    // 濫用の追跡がこの機能の目的なので、500 を吐いている経路こそ記録が要る。
    let threw = false
    try {
      await next()
    } catch (err) {
      threw = true
      throw err
    } finally {
      logAccess({
        path: c.req.path,
        method: c.req.method,
        // 例外の時点では Hono がまだ 500 応答を組み立てていない（この finally は
        // その前の巻き戻しで実行される）ので c.res は当てにならず、500 で決め打つ
        status: threw ? 500 : c.res.status,
        keyId: shortKeyId(keyId),
        rateLimited: false,
        ipHash,
      })
    }
  }
}
