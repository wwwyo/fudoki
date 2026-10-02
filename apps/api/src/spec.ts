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
 * MCP Streamable HTTP 仕様の Security Considerations「Origin Header Validation」は、
 * サーバが Origin ヘッダを検証し、不正なら 403 を返すことを MUST としている ── ブラウザから DNS rebinding 等で叩かれたときに、匿名のレート制限枠
 * （access-control.ts）を第三者のサイトが被害者のブラウザ経由で消費できてしまうのを防ぐため。
 * 検証点は2つある（どちらもこの allowlist を見る）。preflight の CORS（index.ts の cors()）が
 * ブラウザ経路を絞り、`app.all(MCP_PATH, ...)` の検証が preflight を通らない
 * 非ブラウザ経路を含む実リクエストを絞る。
 * Origin ヘッダが無い呼び出し（curl・ネイティブの MCP client など非ブラウザ）は検証の対象外
 * （仕様が検証を求めているのはブラウザ由来の Origin ヘッダに対してであり、ヘッダを送らない
 * client まで締め出すと PRD の Goal「URL を登録するだけで鍵無しに使える」を壊す）。
 * RPC の allowlist（index.ts の RPC_ALLOWED_ORIGINS）とは目的が違うので値は揃えているが
 * 宣言は分ける ── こちらはブラウザから直接 `/mcp` を叩く fudoki 自身のオリジンを許す口。
 */
export const MCP_ALLOWED_ORIGINS = new Set([
  'https://fudoki.dev',
  'http://localhost:5173',
  'http://127.0.0.1:5173',
])

/**
 * 実行時（/v0/openapi.json）とビルド時（generate-spec.ts）の両方が使う converter 構成。
 * 片方だけ変えると静的な spec と配信される spec が乖離するので、ここに一本化する。
 */
export const specSchemaConverters = [new ZodToJsonSchemaConverter()]

const V0_NOTICE =
  '原典の文書種別・版を区別する fiscal API。データ応答の releaseId は R2 の公開版と D1 の参照版を対応づける。金額は円単位の整数。集計は datasetIds を明示して行う。配布ファイルは独立した download Worker から取得する。'

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
}
