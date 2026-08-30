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
 * 実行時（/v0/openapi.json）とビルド時（generate-spec.ts）の両方が使う converter 構成。
 * 片方だけ変えると静的な spec と配信される spec が乖離するので、ここに一本化する。
 */
export const specSchemaConverters = [new ZodToJsonSchemaConverter()]

const V0_NOTICE =
  '**実験版（v0）**。URL と応答スキーマには破壊的変更があり得る。' +
  'ただしデータの識別子（budget_line_id、団体コード）は配布物側の契約であり、' +
  'API の版とは独立に安定している。' +
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
