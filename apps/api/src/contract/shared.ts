/**
 * リソースをまたいで共有する contract の部品。
 * エラーの語彙とページングの入力はここで1回だけ定義し、各リソースが継承する。
 */
import { oc } from '@orpc/contract'
import * as z from 'zod'

/** AIP-122 のリソース名。例: jurisdictions/132195/budgetLines/132195:2018:... */
export const resourceName = z.string()

/** 全 procedure 共通のエラー語彙 */
export const base = oc.errors({
  BAD_REQUEST: {
    data: z.object({ reason: z.string() }).optional(),
  },
  NOT_FOUND: {},
  /** deploy をまたいだ pageToken。入力誤り（400）と区別して 410 で返す */
  STALE_PAGE_TOKEN: {
    status: 410,
    message: 'pageToken was issued for a different revision. Restart from the first page.',
  },
})

/** AIP-158 のページング入力（List 系が spread して使う） */
export const pageInput = {
  filter: z
    .string()
    .optional()
    .describe(
      'AIP-160 の部分集合。`field = value` を AND でつなぐ形のみ。' +
        '使えるフィールドは fiscalYear / direction / phase / cofog.division（scope ごとの必須・可否はエンドポイントの説明を参照）',
    ),
  pageSize: z
    .coerce.number().int().min(0).optional()
    .describe('1ページの最大件数。未指定・0 は既定値 1000。上限 1000（超過は丸める）。負数は 400'),
  pageToken: z
    .string()
    .optional()
    .describe('前ページの nextPageToken。発行時と同じ filter でだけ使える（pageSize は変えてよい）。deploy をまたぐと 410'),
}
