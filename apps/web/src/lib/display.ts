import type { Direction } from '@fudoki/fiscal/detail'
export type { Direction }
export type { CofogCode } from '@fudoki/fiscal/types'

export const yen = (v: number | string) => Number(v).toLocaleString('ja-JP')

/** 歳出・歳入の表示名。画面で2箇所以上から参照されるのでここが正本 */
export const DIR_JA: Record<Direction, string> = {
  expenditure: '歳出',
  revenue: '歳入',
}

/**
 * 件数の桁区切り。`yen` と実装は同じだが、**金額でないものに `yen` を使わない**
 * （読んだ者が単位を取り違える。実際に件数へ `yen` を当てていた箇所があった）。
 */
export const count = (v: number | string) => Number(v).toLocaleString('ja-JP')

/**
 * 千円表示。合計カードと COFOG ツリーで使う（明細は桁の小さい行があるため円のまま
 * — cofog-statement.tsx 参照）。呼び出し側で必ず「千円」を明示すること（円と混在する画面なので、
 * 単位を数字に付けずに置くと読み違える）。
 *
 * ⚠️ 円が1000で割り切れない値がある（狛江市の歳出は決算書 PDF から起こした真の円単位で、
 * 千円未満の端数を持つ）。表示専用の丸めなので四捨五入する
 * （切り捨てだと構造的に実額より小さく見せることになり、合計が明細より系統的にずれる）。
 * 正確な値は常に明細（円）に残るので、丸めによる情報の欠落は起きない。
 */
export const senYen = (v: number | string) =>
  Math.round(Number(v) / 1000).toLocaleString('ja-JP')

/** 割合（0〜1）の書式。**割り算は生成側が済ませてある** — ここでは桁の揃え方だけを1箇所で決める */
export const pct = (v: number) => `${(v * 100).toFixed(1)}%`

/** 円は桁が多い。俯瞰する場所では丸め、厳密な値は必ず併記する */
export function yenShort(v: number | string): string {
  const x = Number(v)
  if (Math.abs(x) >= 1e8) return `${(x / 1e8).toFixed(x >= 1e10 ? 0 : 1)}億円`
  if (Math.abs(x) >= 1e4)
    return `${Math.round(x / 1e4).toLocaleString('ja-JP')}万円`
  return `${yen(x)}円`
}

/** COFOG 1999 の大分類。色は識別の補助で、コードは必ず文字でも出す */
export const DIVISION_COLOR: Record<string, string> = {
  '01': 'oklch(62% 0.06 260)',
  '02': 'oklch(58% 0.06 300)',
  '03': 'oklch(58% 0.07 40)',
  '04': 'oklch(69% 0.10 80)',
  '05': 'oklch(64% 0.08 145)',
  '06': 'oklch(60% 0.06 65)',
  '07': 'oklch(63% 0.09 20)',
  '08': 'oklch(63% 0.07 295)',
  '09': 'oklch(60% 0.06 230)',
  '10': 'oklch(64% 0.05 355)',
}

export const STATUS_JA: Record<string, string> = {
  assigned: '割当済み',
  unclassifiable: '分類不能',
  'out-of-scope': '対象外',
  // 歳入。COFOG は支出の機能別分類なので分類の軸そのものが無い。
  // 「分類できなかった」と混ぜないために別の状態にしてある。
  'not-applicable': '分類の軸なし',
}
