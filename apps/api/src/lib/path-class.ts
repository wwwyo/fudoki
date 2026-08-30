/**
 * アクセス制御 middleware がパスをどう扱うかの分類。
 *
 * `/v0/` (docs UI) と `/v0/openapi.json` は oRPC の procedure ではなく
 * OpenAPIReferencePlugin が `app.all('/v0/*')` の中で処理する（index.ts 参照）ため、
 * Hono のルーティング構造では除外を表現できない。ここで文字列比較として
 * 切り出し、単体テストで漏れを検査できるようにする。
 */
export type PathClass =
  /** ドキュメント UI・spec・ルートリダイレクト。キーもレート制限も掛けない */
  | 'excluded'
  /** 自前フロント専用の口。API キーを埋め込めない設計なので IP だけで制限する */
  | 'rpc'
  /** それ以外（`/v0/*` のクエリ API・配布物パススルー）。キー任意・レート制限あり */
  | 'keyed'

const EXCLUDED_PATHS = new Set(['/', '/openapi.json', '/v0', '/v0/', '/v0/openapi.json'])

export function classifyPath(path: string): PathClass {
  if (EXCLUDED_PATHS.has(path)) return 'excluded'
  if (path === '/rpc' || path.startsWith('/rpc/')) return 'rpc'
  return 'keyed'
}
