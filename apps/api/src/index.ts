/**
 * Worker のエントリ。Hono は CORS・パススルー・リダイレクトだけを持ち、
 * API 本体は同じ router を3つの口で公開する。
 * - `/v0/*`: OpenAPIHandler。外部利用者向けの REST（OpenAPI ドキュメントつき）
 * - `/rpc/*`: RPCHandler。自前のフロント向け（contract を import した
 *   型付きクライアントで叩く。OpenAPI には載せない）
 * - `/mcp`: MCP（remote）。tool は apps/api/src/mcp/ が router をそのまま
 *   呼ぶだけで、集計も判断も持たない
 * `run_worker_first` なので、ここを通らずにアセットが露出することはない。
 */
import { OpenAPIHandler } from '@orpc/openapi/fetch'
import { OpenAPIReferencePlugin } from '@orpc/openapi/plugins'
import { RPCHandler } from '@orpc/server/fetch'
import { createMcpHandler, isLegacyRequest, WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/server'
import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { accessControl } from './access-control'
import { type Env, type FilesFile, paths, readAsset, readJsonAsset } from './assets'
import { createApiClient } from './mcp/client'
import { createMcpServer } from './mcp/server'
import { router } from './router'
import {
  MCP_ALLOWED_ORIGINS,
  MCP_PATH,
  ROOT_PATH,
  ROOT_SPEC_REDIRECT_PATH,
  specGenerateOptions,
  specSchemaConverters,
  V0_DOCS_PATH,
  V0_PREFIX,
  V0_SPEC_PATH,
} from './spec'

const openapiHandler = new OpenAPIHandler(router, {
  plugins: [
    new OpenAPIReferencePlugin({
      schemaConverters: specSchemaConverters,
      specGenerateOptions,
      docsPath: V0_DOCS_PATH,
      specPath: V0_SPEC_PATH,
    }),
  ],
})

const rpcHandler = new RPCHandler(router)

const app = new Hono<{ Bindings: Env }>()

/**
 * CORS は口ごとに分ける。
 * - /v0/* とパススルー: 全データ public なので origin は全開のまま。
 *   API キーは任意（ベータのアクセス制御。access-control.ts）なので、
 *   キー無しでも外部開発者のブラウザベースのツールから叩けることを維持する。
 * - /mcp: Origin の allowlist（spec.ts の MCP_ALLOWED_ORIGINS）に絞る。
 *   MCP Streamable HTTP 仕様の Security Considerations が Origin 検証を MUST とするのは、
 *   第三者のサイトが被害者のブラウザ経由で `/mcp` を叩き、匿名のレート制限枠
 *   （access-control.ts）を消費できてしまうのを防ぐため（PR #27 レビュー指摘）。
 *   preflight を allowlist に揃えておくと、不許可のオリジンはブラウザが実リクエストを
 *   送る前に止まる。実リクエスト側も下記 `app.all(MCP_PATH, ...)` で同じ allowlist を
 *   検証する（preflight を通らない非ブラウザ経路のための要件でもある）。
 * - /rpc/*: 自前フロント専用の口なので fudoki のオリジンだけに絞る。
 *   防御ではなく「公式クライアント以外はここを使わない」という契約の表明
 *   （CORS はブラウザにしか効かないので、curl 等は元から制限対象外）
 * allowHeaders に Authorization を足しているのは、ブラウザから
 * `Authorization: Bearer <key>` を送れるようにするため（無いと preflight で弾かれる）。
 * mcp-session-id / mcp-protocol-version / Last-Event-ID は MCP Streamable HTTP の
 * 仕様がクライアント→サーバで使うヘッダ（stateless 構成でもプロトコル版のネゴシエーションに
 * mcp-protocol-version が使われる）。DELETE は MCP のセッション終了リクエストで使う。
 * mcp-method / mcp-name は modern era（2026-07-28、SEP-2243）が全リクエストに
 * 要求するヘッダで、ブラウザの modern client はこれらを送る（無いと preflight で弾かれる）。
 * exposeHeaders はパススルーの revision・429 の Retry-After・MCP のセッションIDを
 * ブラウザから読むために要る。
 */
const RPC_ALLOWED_ORIGINS = new Set(['https://fudoki.dev', 'http://localhost:5173'])

app.use(
  '*',
  cors({
    origin: (origin, c) => {
      if (c.req.path === MCP_PATH) {
        return MCP_ALLOWED_ORIGINS.has(origin) ? origin : ''
      }
      if (c.req.path.startsWith('/rpc')) {
        return RPC_ALLOWED_ORIGINS.has(origin) ? origin : ''
      }
      return '*'
    },
    allowMethods: ['GET', 'HEAD', 'POST', 'DELETE', 'OPTIONS'],
    allowHeaders: ['Content-Type', 'Authorization', 'mcp-session-id', 'mcp-protocol-version', 'mcp-method', 'mcp-name', 'Last-Event-ID'],
    exposeHeaders: ['X-Fudoki-Revision', 'ETag', 'Retry-After', 'mcp-session-id', 'mcp-protocol-version'],
  }),
)

// ⚠️ アクセス制御は cors の直後・個別ルートより前に置く。Hono は登録順に評価し、
// マッチしたハンドラが応答を返すとそこで止まるので、後ろに置くと
// それより前に定義したルートには一切効かないまま黙って通ってしまう
// （detail は access-control.ts 冒頭のコメント）。
app.use('*', accessControl())

app.get(ROOT_PATH, (c) => c.redirect(`${V0_PREFIX}${V0_DOCS_PATH}`, 302))
app.get(ROOT_SPEC_REDIRECT_PATH, (c) => c.redirect(`${V0_PREFIX}${V0_SPEC_PATH}`, 302))

/**
 * MCP（remote）。仕様版が legacy（〜2025-11-25）と modern（2026-07-28）の2 era に
 * 分かれているので、`isLegacyRequest`（`createMcpHandler` と同じ分類コードを走らせる
 * predicate）で振り分ける ── modern は `initialize` を持たず、毎リクエストが
 * `_meta['io.modelcontextprotocol/protocolVersion']` の envelope で版を主張する。
 * 2 era で同じ factory（`createMcpServer`）を使う（SDK の推奨どおり。
 * 両方が同じ tool 群を出すので era 間で定義がずれない）。
 *
 * legacy leg は `createMcpHandler` の fallback（transport に enableJsonResponse を
 * 渡せず SSE 応答になる）ではなく、従来どおり `WebStandardStreamableHTTPServerTransport`
 * を直に配線する。`sessionIdGenerator` を渡さなければ既定でセッション管理が無効
 * （stateless）で、`enableJsonResponse: true` で応答を SSE ではなく単発の JSON にする ──
 * この tool 群はサーバ発の通知を送らない参照専用の request/response なので、
 * ストリームを維持する理由が無い。modern leg は `legacy: 'reject'` の
 * `createMcpHandler` で、`responseMode: 'json'` も同じ意図。
 * Workers はリクエストをまたいで状態を持てないので、transport / handler / server は
 * リクエストごとに作り直す。
 *
 * ⚠️ Origin ヘッダの検証（MCP Streamable HTTP 仕様の Security Considerations が MUST とする）を
 * transport に渡す前に行う（v2 の entry も「Origin/Host 検証は handler の前に置け」と
 * 自身では検証しない設計）。上の cors() でも同じ allowlist に絞っているが、CORS は
 * preflight を出すブラウザ経路にしか効かない ── curl 等の非ブラウザ経路はここが
 * 唯一の検証点であり、悪意あるサイトが被害者のブラウザ経由で `/mcp` を叩いて
 * 匿名のレート制限枠（access-control.ts）を消費するのをここで止める（PR #27 レビュー指摘）。
 * Origin ヘッダが無いリクエスト（curl・ネイティブの MCP client など非ブラウザ）は対象外 ──
 * ブラウザ由来でなければ DNS rebinding 等の脅威が成立せず、ここで締め出すと
 * PRD の Goal「URL を登録するだけで鍵無しに使える」を壊す。
 */
app.all(MCP_PATH, async (c) => {
  const origin = c.req.header('origin')
  if (origin !== undefined && !MCP_ALLOWED_ORIGINS.has(origin)) {
    return c.json({ error: 'FORBIDDEN', message: `origin not allowed: ${origin}` }, 403)
  }
  const client = createApiClient(c.env)
  if (await isLegacyRequest(c.req.raw)) {
    const transport = new WebStandardStreamableHTTPServerTransport({ enableJsonResponse: true })
    const server = createMcpServer(client)
    await server.connect(transport)
    return transport.handleRequest(c.req.raw)
  }
  const handler = createMcpHandler(() => createMcpServer(client), { legacy: 'reject', responseMode: 'json' })
  return handler.fetch(c.req.raw)
})

// meta/files.json はデプロイに焼き込まれた不変データなので isolate 内で1回だけ読む
let filesMetaCache: FilesFile | null = null
async function readFilesMeta(env: Env): Promise<FilesFile> {
  if (filesMetaCache !== null) return filesMetaCache
  const filesMeta = await readJsonAsset<FilesFile>(env, paths.files)
  if (filesMeta === null) throw new Error('meta/files.json is missing from assets')
  filesMetaCache = filesMeta
  return filesMeta
}

app.on(['GET', 'HEAD'], `${V0_PREFIX}/datapackages/:jurisdiction/:file`, async (c) => {
  const { jurisdiction, file } = c.req.param()
  const filesMeta = await readFilesMeta(c.env)
  // リクエスト入力をアセットのパスへ直接連結しない。宣言済みのファイルだけを返す
  const entry = filesMeta.files[jurisdiction]?.[file]
  if (entry === undefined) {
    return c.json({ error: 'NOT_FOUND', message: `no such distribution file: ${jurisdiction}/${file}` }, 404)
  }
  const asset = await readAsset(c.env, paths.passthrough(jurisdiction, file))
  if (asset.status !== 200) throw new Error(`declared distribution file is missing from assets: ${jurisdiction}/${file}`)
  const headers = new Headers({
    'Content-Type': entry.contentType,
    'Content-Length': String(entry.size),
    'ETag': `"${entry.sha256}"`,
    'X-Fudoki-Revision': filesMeta.revision,
    'Cache-Control': 'public, max-age=3600',
  })
  return new Response(c.req.method === 'HEAD' ? null : asset.body, { status: 200, headers })
})

app.all(`${V0_PREFIX}/*`, async (c) => {
  const { matched, response } = await openapiHandler.handle(c.req.raw, {
    prefix: V0_PREFIX,
    context: { env: c.env },
  })
  if (matched) return response
  return c.json({ error: 'NOT_FOUND', message: 'no such endpoint' }, 404)
})

app.all('/rpc/*', async (c) => {
  const { matched, response } = await rpcHandler.handle(c.req.raw, {
    prefix: '/rpc',
    context: { env: c.env },
  })
  if (matched) return response
  return c.json({ error: 'NOT_FOUND', message: 'no such procedure' }, 404)
})

app.notFound((c) => c.json({ error: 'NOT_FOUND', message: 'no such endpoint. See /v0/openapi.json' }, 404))

export default app
