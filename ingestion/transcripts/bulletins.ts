/**
 * 議会だより CSV の所在と、観測プロファイルへの適合判定。
 *
 * 適合は `bun run check:bulletins` が実測して書き戻す。**手で書かない。**
 */
import { z } from 'zod'

export const SchemaCheck = z.object({
  standard: z.enum(['fudoki/tokyo-municipal-bulletin-profile/0.1', 'unknown']),
  conformance: z.enum(['conformant', 'variant', 'broken', 'unchecked']),
  columns: z.number().int().nullable().optional(),
  /** 標準に無い追加列。variant の内訳を残す */
  extraColumns: z.array(z.string()).nullable().optional(),
  checkedAt: z.iso.date().optional(),
  note: z.string().nullable().optional(),
})

/** 東京都オープンデータカタログ（CKAN）で見つかった1データセット */
export const OpenDataset = z.object({
  title: z.string(),
  formats: z.array(z.string()),
  /** CKAN のリソース URL。スキームなしが混ざるため取り込み時に正規化する */
  url: z.url().nullable(),
  license: z.string().nullable(),
  /** 同カテゴリで見つかったデータセット数 */
  count: z.number().int().positive(),
  schemaCheck: SchemaCheck.optional(),
})

export const Bulletins = z.object({
  note: z.string(),
  datasets: z.record(z.string().regex(/^\d{6}$/), OpenDataset),
})

export type OpenDataset = z.infer<typeof OpenDataset>
export type Bulletins = z.infer<typeof Bulletins>

export const BULLETINS_PATH = new URL('./bulletins.json', import.meta.url).pathname

export async function loadBulletins(): Promise<Bulletins> {
  return Bulletins.parse(JSON.parse(await Bun.file(BULLETINS_PATH).text()))
}
