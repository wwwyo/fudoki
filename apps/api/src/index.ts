/**
 * Worker のエントリ。Hono は CORS・パススルー・リダイレクトだけを持ち、
 * API 本体は oRPC の OpenAPIHandler（prefix /v0）へ委ねる。
 * `run_worker_first` なので、ここを通らずにアセットが露出することはない。
 */
import { OpenAPIHandler } from '@orpc/openapi/fetch'
import { OpenAPIReferencePlugin } from '@orpc/openapi/plugins'
import { ZodToJsonSchemaConverter } from '@orpc/zod/zod4'
import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { type Env, type FilesFile, paths, readAsset, readJsonAsset } from './assets'
import { router } from './router'
import { specGenerateOptions } from './spec'

const handler = new OpenAPIHandler(router, {
  plugins: [
    new OpenAPIReferencePlugin({
      schemaConverters: [new ZodToJsonSchemaConverter()],
      specGenerateOptions,
      docsPath: '/',
      specPath: '/openapi.json',
    }),
  ],
})

const app = new Hono<{ Bindings: Env }>()

// 公開 API（認証なし・読み取り専用）なので全開でよい。
// exposeHeaders はパススルーの revision をブラウザから読むために要る。
app.use(
  '*',
  cors({
    origin: '*',
    allowMethods: ['GET', 'HEAD', 'OPTIONS'],
    allowHeaders: ['Content-Type'],
    exposeHeaders: ['X-Fudoki-Revision', 'ETag'],
  }),
)

app.get('/', (c) => c.redirect('/v0/', 302))
app.get('/openapi.json', (c) => c.redirect('/v0/openapi.json', 302))

app.on(['GET', 'HEAD'], '/v0/datapackages/:jurisdiction/:file', async (c) => {
  const { jurisdiction, file } = c.req.param()
  const filesMeta = await readJsonAsset<FilesFile>(c.env, paths.files)
  if (filesMeta === null) throw new Error('meta/files.json is missing from assets')
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
  const { matched, response } = await handler.handle(c.req.raw, {
    prefix: '/v0',
    context: { env: c.env },
  })
  if (matched) return response
  return c.json({ error: 'NOT_FOUND', message: 'no such endpoint' }, 404)
})

app.notFound((c) => c.json({ error: 'NOT_FOUND', message: 'no such endpoint. See /v0/openapi.json' }, 404))

export default app
