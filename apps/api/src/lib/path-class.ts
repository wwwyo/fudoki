/**
 * アクセス制御 middleware がパスをどう扱うかの分類。
 *
 * `/v0/` (docs UI) と `/v0/openapi.json` は oRPC の procedure ではなく
 * OpenAPIReferencePlugin が `app.all('/v0/*')` の中で処理する（index.ts 参照）ため、
 * Hono のルーティング構造では除外を表現できない。ここで文字列比較として
 * 切り出し、単体テストで漏れを検査できるようにする。
 *
 * ⚠️ 除外パスは spec.ts の定数から組み立てる。ここに独立したリテラルを
 * 書き写さないこと ── index.ts の OpenAPIReferencePlugin 設定（docsPath 等）を
 * 変えても、リテラルの写しは追随しない。型検査は通り、テストも
 * （ステータスコードの偶然の一致次第では）通り続けてしまうので、
 * 除外が黙って壊れる（AGENTS.md「同じ事実を2箇所で宣言しない」）。
 */
import { MCP_PATH, ROOT_PATH, ROOT_SPEC_REDIRECT_PATH, V0_DOCS_PATH, V0_PREFIX, V0_SPEC_PATH } from '../spec'

export type PathClass =
  /** ドキュメント UI・spec・ルートリダイレクト。キーもレート制限も掛けない */
  | 'excluded'
  /** 自前フロント専用の口。API キーを埋め込めない設計なので IP だけで制限する */
  | 'rpc'
  /** それ以外（`/v0/*` のクエリ API・配布物パススルー・`/mcp`）。キー任意・レート制限あり */
  | 'keyed'

const EXCLUDED_PATHS = new Set([
  ROOT_PATH,
  ROOT_SPEC_REDIRECT_PATH,
  V0_PREFIX,
  `${V0_PREFIX}${V0_DOCS_PATH}`,
  `${V0_PREFIX}${V0_SPEC_PATH}`,
])

export function classifyPath(path: string): PathClass {
  if (EXCLUDED_PATHS.has(path)) return 'excluded'
  if (path === '/rpc' || path.startsWith('/rpc/')) return 'rpc'
  // `/mcp` は既定の keyed 分岐に自然に落ちるが、MCP サーバは鍵無しで
  // 使えることが PRD の Goal なので、意図した分岐であることを明示する
  // （既定分岐の書き換えが `/mcp` の扱いを黙って変えないようにする）。
  if (path === MCP_PATH) return 'keyed'
  return 'keyed'
}
