/**
 * Worker のエントリ。Hono は CORS・パススルー・リダイレクトだけを持ち、
 * API 本体は同じ router を2つの口で公開する。
 * - `/v0/*`: OpenAPIHandler。外部利用者向けの REST（OpenAPI ドキュメントつき）
 * - `/rpc/*`: RPCHandler。自前のフロントと MCP 向け（contract を import した
 *   型付きクライアントで叩く。OpenAPI には載せない）
 * `run_worker_first` なので、ここを通らずにアセットが露出することはない。
 */
import { OpenAPIHandler } from '@orpc/openapi/fetch'
import { OpenAPIReferencePlugin } from '@orpc/openapi/plugins'
import { RPCHandler } from '@orpc/server/fetch'
import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { type Env, type FilesFile, paths, readAsset, readJsonAsset } from './assets'
import { router } from './router'
import { specGenerateOptions, specSchemaConverters } from './spec'

const openapiHandler = new OpenAPIHandler(router, {
  plugins: [
    new OpenAPIReferencePlugin({
      schemaConverters: specSchemaConverters,
      specGenerateOptions,
      docsPath: '/',
      specPath: '/openapi.json',
    }),
  ],
})

const rpcHandler = new RPCHandler(router)

const app = new Hono<{ Bindings: Env }>()

/**
 * CORS は口ごとに分ける。
 * - /v0/* とパススルー: 公開 API（認証なし・全データ public）なので全開。
 *   外部開発者のブラウザベースのツールが一次利用者のため `*` を維持する
 * - /rpc/*: 自前フロント専用の口なので fudoki のオリジンだけに絞る。
 *   防御ではなく「公式クライアント以外はここを使わない」という契約の表明
 *   （CORS はブラウザにしか効かないので、curl 等は元から制限対象外）
 * exposeHeaders はパススルーの revision をブラウザから読むために要る。
 */
const RPC_ALLOWED_ORIGINS = new Set(['https://fudoki.dev', 'http://localhost:5173'])

app.use(
  '*',
  cors({
    origin: (origin, c) => {
      if (!c.req.path.startsWith('/rpc')) return '*'
      return RPC_ALLOWED_ORIGINS.has(origin) ? origin : ''
    },
    allowMethods: ['GET', 'HEAD', 'POST', 'OPTIONS'],
    allowHeaders: ['Content-Type'],
    exposeHeaders: ['X-Fudoki-Revision', 'ETag'],
  }),
)

app.get('/', (c) => c.redirect('/v0/', 302))
app.get('/openapi.json', (c) => c.redirect('/v0/openapi.json', 302))

// meta/files.json はデプロイに焼き込まれた不変データなので isolate 内で1回だけ読む
let filesMetaCache: FilesFile | null = null
async function readFilesMeta(env: Env): Promise<FilesFile> {
  if (filesMetaCache !== null) return filesMetaCache
  const filesMeta = await readJsonAsset<FilesFile>(env, paths.files)
  if (filesMeta === null) throw new Error('meta/files.json is missing from assets')
  filesMetaCache = filesMeta
  return filesMeta
}

app.on(['GET', 'HEAD'], '/v0/datapackages/:jurisdiction/:file', async (c) => {
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

app.all('/v0/*', async (c) => {
  const { matched, response } = await openapiHandler.handle(c.req.raw, {
    prefix: '/v0',
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
