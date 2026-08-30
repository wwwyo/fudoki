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
import { accessControl } from './access-control'
import { type Env, type FilesFile, paths, readAsset, readJsonAsset } from './assets'
import { router } from './router'
import {
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
 *   キー無しでも外部開発者のブラウザベースのツールから叩けることを維持する
 * - /rpc/*: 自前フロント専用の口なので fudoki のオリジンだけに絞る。
 *   防御ではなく「公式クライアント以外はここを使わない」という契約の表明
 *   （CORS はブラウザにしか効かないので、curl 等は元から制限対象外）
 * allowHeaders に Authorization を足しているのは、ブラウザから
 * `Authorization: Bearer <key>` を送れるようにするため（無いと preflight で弾かれる）。
 * exposeHeaders はパススルーの revision と、429 の Retry-After をブラウザから読むために要る。
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
    allowHeaders: ['Content-Type', 'Authorization'],
    exposeHeaders: ['X-Fudoki-Revision', 'ETag', 'Retry-After'],
  }),
)

// ⚠️ アクセス制御は cors の直後・個別ルートより前に置く。Hono は登録順に評価し、
// マッチしたハンドラが応答を返すとそこで止まるので、後ろに置くと
// それより前に定義したルートには一切効かないまま黙って通ってしまう
// （detail は access-control.ts 冒頭のコメント）。
app.use('*', accessControl())

app.get(ROOT_PATH, (c) => c.redirect(`${V0_PREFIX}${V0_DOCS_PATH}`, 302))
app.get(ROOT_SPEC_REDIRECT_PATH, (c) => c.redirect(`${V0_PREFIX}${V0_SPEC_PATH}`, 302))

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
