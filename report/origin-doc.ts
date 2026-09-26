import { createHash } from 'node:crypto'
import type { Provenance } from './common'

/**
 * 原典ノードの文書同一性キー。証跡が指す文書（sha256）の集合のハッシュ。
 * 同じ文書から起こした取り込み（歳入と歳出を同じ PDF から起こす団体など）は
 * 系統図で1つの原典ノードにまとめるので、報告側とローカル・データ口が同じ鍵を
 * 使って対応する取り込みを引き直せるようにする。
 *
 * ブラウザバンドルに乗る `common.ts` には置けない（node:crypto のため）。
 */
export function originDocKey(ps: Provenance[]): string {
  return createHash('sha256')
    .update(ps.map((p) => p.sha256).sort().join('\n'))
    .digest('hex')
    .slice(0, 12)
}
