/**
 * 団体の同一性。**層に依存しない。**
 *
 * ①予算・②調達・③会議録はすべて全国地方公共団体コードで束ねるので、
 * 名称と識別子はどの層からも参照される。
 *
 * ⚠️ **以前はこれが③会議録のゲート判定ファイルに同居していた。**
 * そのため予算の粒度調査が、母集団を得るためだけに③のファイルを読んでいた。
 * 設計上は分離していたのに、物理構造では③が落ちると①も動かない状態だった。
 */
import { z } from 'zod'

export const Jurisdiction = z.object({
  name: z.string(),
  /** Open Civic Data 形式の識別子。本家未登録の市区町村は同形式で自前定義 */
  ocdId: z.string().regex(/^ocd-division\/country:jp\/prefecture:\d{2}\/city:\d{6}$/),
  /** 東京都カタログでの公開データセット数。母集団の目安であって、粒度の判定には使わない */
  tokyoCatalogDatasets: z.number().int().nonnegative().nullable(),
})

export const Registry = z.object({
  note: z.string(),
  generatedAt: z.iso.date().optional(),
  /** キーは全国地方公共団体コード（6桁） */
  jurisdictions: z.record(z.string().regex(/^\d{6}$/), Jurisdiction),
})

export type Jurisdiction = z.infer<typeof Jurisdiction>
export type Registry = z.infer<typeof Registry>

export const REGISTRY_PATH = new URL('../../data/shared/jurisdictions.json', import.meta.url).pathname

export async function loadJurisdictions(): Promise<Registry> {
  return Registry.parse(JSON.parse(await Bun.file(REGISTRY_PATH).text()))
}
