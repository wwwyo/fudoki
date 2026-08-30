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
 * `reason` は 401 の詳細（キーが未知か revoked かなど）。クライアントへの応答は
 * 一律 `invalid API key` にするが、運用側の追跡のためログにだけ詳細を残す。
 */
type AccessLogEntry = {
  path: string
  method: string
  status: number
  keyId: string | undefined
  rateLimited: boolean
  ipHash: string
  reason?: string
}

function logAccess(entry: AccessLogEntry): void {
  console.log(JSON.stringify(entry))
}

/**
 * Rate Limiting binding の period（秒）。429 の Retry-After をここから
 * 組み立てる ── wrangler.jsonc の `ratelimits[].simple.period` を手で
 * コピーしてハードコードすると、片方だけ変えたときに Retry-After が
 * 黙って嘘の値になる（simple.period は 10 か 60 しか選べないので、
 * 匿名側だけ 10 に変える判断は普通に起こりうる）。
 * ⚠️ TypeScript から wrangler.jsonc の値を直接参照する経路は無いので、
 * 対応関係はコメントでしか保証できない。wrangler.jsonc 側を変えたら
 * 必ずここも合わせて変えること。
 */
const RATE_LIMIT_PERIOD_SECONDS = {
  /** wrangler.jsonc: ratelimits[name=RATE_LIMIT_ANONYMOUS].simple.period */
  anonymous: 60,
  /** wrangler.jsonc: ratelimits[name=RATE_LIMIT_AUTHENTICATED].simple.period */
  authenticated: 60,
} as const

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

/**
 * 認証失敗（401）を返す前に、必ず匿名 limiter を1回消費させる。
 *
 * ⚠️ これが無いと、不正なキーを送り続けるだけで limiter を経由せずに
 * KV 参照 + SHA-256 計算を無制限に走らせられる ── 濫用を止めるための機能に
 * 無制限に叩ける口が開くことになる。認証**成功**したリクエストは別途 keyId で
 * 認証済み limiter を消費するので、失敗経路だけ匿名側に載せても
 * 「キーを取ると緩和される」という設計（キー有りは高レート）は壊れない。
 * 全リクエストの先頭に匿名 limiter を置く案は採らない ── それだとキー有りの
 * リクエストまで匿名レートで頭打ちになってしまう。
 *
 * `logReason` は運用側の追跡用にログにだけ残す詳細（例: revoked / unknown）。
 * `publicMessage` はクライアントへの応答。キーの状態に関する理由
 * （unknown / revoked / malformed record）は一律 `invalid API key` に統一し、
 * 「そのキーが存在するか」を外部から判別できないようにする。
 * ただし Authorization ヘッダの形式ミスはクライアントの実装ミスであって
 * キーの情報を漏らさないので、区別したまま返してよい。
 */
async function unauthorized(
  c: Context<{ Bindings: Env }>,
  ipHash: string,
  logReason: string,
  publicMessage: string,
): Promise<Response> {
  const limited = await c.env.RATE_LIMIT_ANONYMOUS.limit({ key: ipHash })
  if (!limited.success) return tooManyRequests(c, undefined, ipHash)
  logAccess({ path: c.req.path, method: c.req.method, status: 401, keyId: undefined, rateLimited: false, ipHash, reason: logReason })
  return c.json({ error: 'UNAUTHORIZED', message: publicMessage }, 401)
}

function tooManyRequests(
  c: Context<{ Bindings: Env }>,
  keyId: string | undefined,
  ipHash: string,
): Response {
  logAccess({ path: c.req.path, method: c.req.method, status: 429, keyId: shortKeyId(keyId), rateLimited: true, ipHash })
  // ⚠️ Rate Limiting binding の limit() は成功/失敗の boolean しか返さず、
  // 残量やウィンドウ長を持たない。したがって「残量ヘッダ」は正確な値を作れない。
  // 429 のときだけ Retry-After を付ける。keyId の有無で「どちらの limiter が
  // 発火したか」を判定する（keyId 有り = 認証済み limiter、無し = 匿名 limiter。
  // 呼び出し元2箇所とも、その対応で呼んでいる）
  const period = keyId !== undefined ? RATE_LIMIT_PERIOD_SECONDS.authenticated : RATE_LIMIT_PERIOD_SECONDS.anonymous
  return c.json({ error: 'RATE_LIMITED', message: 'too many requests' }, 429, { 'Retry-After': String(period) })
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
      if (match === null) return await unauthorized(c, ipHash, 'malformed Authorization header', 'malformed Authorization header')
      const hash = await sha256Hex(match[1]!)
      const raw = await c.env.API_KEYS.get(hash)
      if (raw === null) return await unauthorized(c, ipHash, 'unknown API key', 'invalid API key')

      // ⚠️ JSON.parse は例外を投げうる（KV の値が壊れている場合）。ここで
      // catch しないと unauthorized() に到達せずアクセスログも残らないまま
      // 例外が上へ抜ける。壊れたレコードは 401 として扱い、必ずログを残す。
      let parsedJson: unknown
      try {
        parsedJson = JSON.parse(raw)
      } catch {
        return await unauthorized(c, ipHash, 'malformed API key record (invalid JSON)', 'invalid API key')
      }
      const parsed = apiKeyEntrySchema.safeParse(parsedJson)
      if (!parsed.success) return await unauthorized(c, ipHash, 'malformed API key record (schema)', 'invalid API key')
      // ⚠️ KV の書き込み反映は最大60秒。revoke 直後の数十秒はここが古い active を読み、
      // 失効前のキーを一時的に通すことがある（即時性は保証しない）
      if (parsed.data.status !== 'active') return await unauthorized(c, ipHash, 'revoked API key', 'invalid API key')
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
