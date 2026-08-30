/**
 * OpenAPI 生成の設定。**contract から生成する**（手書きの spec を持たない）。
 * パススルーは oRPC の procedure ではないので、ここで base.paths として足す
 * （手書き YAML ではなくコードで合成する。判断の経緯は repo 直下の decision.log）。
 */
import type { OpenAPIGeneratorGenerateOptions } from '@orpc/openapi'
import { ZodToJsonSchemaConverter } from '@orpc/zod/zod4'

// budget に限定した名前にしない — 歳出だけでなく歳入も配っており、レイヤも拡張していくため
export const API_TITLE = '風土記 API'
export const API_VERSION = '0.1.0'

/**
 * ルーティングの構成。index.ts のルート定義と、access-control.ts が使う
 * path-class.ts の除外判定は、ここを唯一の宣言元として組み立てる。
 * ⚠️ 個別にリテラルを書き写さないこと ── docsPath 等を変えても
 * TypeScript は検知せずテストも通り続けるので、除外が黙って壊れる
 * （AGENTS.md「同じ事実を2箇所で宣言しない」）。
 */
export const ROOT_PATH = '/'
export const ROOT_SPEC_REDIRECT_PATH = '/openapi.json'
export const V0_PREFIX = '/v0'
/** OpenAPIReferencePlugin の docsPath（Scalar のドキュメント UI）。/v0 prefix 配下にマウントされる */
export const V0_DOCS_PATH = '/'
/** OpenAPIReferencePlugin の specPath */
export const V0_SPEC_PATH = '/openapi.json'
/**
 * MCP（remote）のエンドポイント。oRPC の router 外（index.ts が直接ハンドリングする）
 * ので、除外判定と同じ理由でここに1つだけ宣言する。鍵不要（PRD の Goal）で
 * アクセス制御は既定の keyed のまま通す ── path-class.ts がここを参照して
 * 明示することで、将来 classifyPath の既定分岐を変えても `/mcp` の扱いが
 * 黙って変わらないようにする。
 */
export const MCP_PATH = '/mcp'

/**
 * `/mcp` の Origin allowlist（PR #27 レビュー指摘）。
 *
 * MCP Streamable HTTP 仕様（2025-11-25 の Security Considerations「Origin
 * Header Validation」）は、サーバが Origin ヘッダを検証し、不正なら 403 を返すことを
 * MUST としている ── ブラウザから DNS rebinding 等で叩かれたときに、匿名のレート制限枠
 * （access-control.ts）を第三者のサイトが被害者のブラウザ経由で消費できてしまうのを防ぐため。
 * ⚠️ CORS の `origin: '*'`（index.ts）とは別レイヤ。CORS はブラウザの読み取りを許すかどうかで、
 * Origin 検証はリクエストそのものを受け付けるかどうか。両方を満たして初めて
 * ブラウザからの `/mcp` 利用が成立する。
 * Origin ヘッダが無い呼び出し（curl・ネイティブの MCP client など非ブラウザ）は検証の対象外
 * （仕様が検証を求めているのはブラウザ由来の Origin ヘッダに対してであり、ヘッダを送らない
 * client まで締め出すと PRD の Goal「URL を登録するだけで鍵無しに使える」を壊す）。
 * RPC の allowlist（index.ts の RPC_ALLOWED_ORIGINS）とは目的が違うので値は揃えているが
 * 宣言は分ける ── こちらはブラウザから直接 `/mcp` を叩く fudoki 自身のオリジンを許す口。
 */
export const MCP_ALLOWED_ORIGINS = new Set(['https://fudoki.dev', 'http://localhost:5173'])

/**
 * 実行時（/v0/openapi.json）とビルド時（generate-spec.ts）の両方が使う converter 構成。
 * 片方だけ変えると静的な spec と配信される spec が乖離するので、ここに一本化する。
 */
export const specSchemaConverters = [new ZodToJsonSchemaConverter()]

const V0_NOTICE =
  '**実験版（v0）**。URL と応答スキーマには破壊的変更があり得る。' +
  'ただしデータの識別子（budget_line_id、団体コード）は配布物側の契約であり、API の版とは独立。' +
  '安定するのは同一原典・同一の導出規則の範囲で、自治体が原典の科目名称を改めると変わりうる（詳細は jurisdiction の caveats）。' +
  '正本はリポジトリ（https://github.com/wwwyo/fudoki）の配布物で、この API はその派生物。' +
  'すべてのデータ応答は、由来する配布物の revision（git commit）を持つ。'

/** パススルー（配布物をそのまま返す）の spec。procedure ではないのでここで宣言する */
const passthroughPath = {
  '/datapackages/{jurisdiction}/{file}': {
    get: {
      operationId: 'getDatapackageFile',
      summary: 'Get a distribution file as-is',
      description:
        '配布物（datapackage.json と各リソース CSV）をバイト同一で返す。' +
        '応答ヘッダ X-Fudoki-Revision が由来する配布物の revision、' +
        'ETag がファイルの SHA-256。HEAD も受ける。',
      tags: ['datapackages'],
      parameters: [
        { name: 'jurisdiction', in: 'path', required: true, schema: { type: 'string' } },
        {
          name: 'file',
          in: 'path',
          required: true,
          schema: { type: 'string' },
          description: 'datapackage.json または resources のファイル名（一覧は listJurisdictions の resources）',
        },
      ],
      responses: {
        '200': {
          description: '配布物のファイル。リポジトリの該当 revision のファイルとバイト同一',
          headers: {
            'X-Fudoki-Revision': { schema: { type: 'string' }, description: '配布物の revision（git commit）' },
            'ETag': { schema: { type: 'string' }, description: 'ファイル内容の SHA-256' },
          },
          content: {
            'application/json': {},
            'text/csv': {},
          },
        },
        '404': { description: '未収録の団体、または契約外のファイル名' },
      },
    },
    head: {
      operationId: 'headDatapackageFile',
      summary: 'Get distribution file headers without the body',
      description: '本文なしで ETag（SHA-256）と X-Fudoki-Revision を返す。巨大 CSV の同一性確認用。',
      tags: ['datapackages'],
      parameters: [
        { name: 'jurisdiction', in: 'path', required: true, schema: { type: 'string' } },
        { name: 'file', in: 'path', required: true, schema: { type: 'string' } },
      ],
      responses: {
        '200': {
          description: 'ヘッダのみ（本文なし）',
          headers: {
            'X-Fudoki-Revision': { schema: { type: 'string' }, description: '配布物の revision（git commit）' },
            'ETag': { schema: { type: 'string' }, description: 'ファイル内容の SHA-256' },
          },
        },
        '404': { description: '未収録の団体、または契約外のファイル名' },
      },
    },
  },
} as const

export const specGenerateOptions: OpenAPIGeneratorGenerateOptions = {
  info: {
    title: API_TITLE,
    version: API_VERSION,
    description: V0_NOTICE,
  },
  servers: [{ url: 'https://api.fudoki.dev/v0' }],
  components: {
    securitySchemes: {
      apiKey: {
        type: 'http',
        scheme: 'bearer',
        description:
          'ベータ用 API キー（任意）。無くても匿名レートで叩けるが、' +
          'キーを送ると高いレート制限が適用される。手動発行で、GitHub の Issue で申請する。',
      },
    },
  },
  // `{}` を含む配列は「キー無しでも呼べる」ことを表す OpenAPI 3 の慣用表現。
  // 必須にしないこと（キーは任意なので、これを外すと「必須」という嘘になる）
  security: [{ apiKey: [] }, {}],
  paths: structuredClone(passthroughPath) as never,
}
