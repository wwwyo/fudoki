/**
 * `sameFilter` の一致判定テスト。ツリーの選択ハイライトと、選択中の行に明細を挟むかどうかは
 * この関数だけで決まる（cofog-tree.tsx）。集計はここには無い（画面側の残りは並べ替えと比較だけ）。
 */
import { describe, expect, test } from 'bun:test'
import { sameFilter } from './cofog-tree'

describe('sameFilter', () => {
  test('division だけの filter どうしは division が一致すれば真', () => {
    expect(sameFilter({ division: '01' }, { division: '01' })).toBe(true)
    expect(sameFilter({ division: '01' }, { division: '02' })).toBe(false)
  })

  test('group・class まで一致して初めて真になる', () => {
    const a = { division: '04', group: '04.5', class: '04.5.1' }
    expect(sameFilter(a, { division: '04', group: '04.5', class: '04.5.1' })).toBe(true)
    expect(sameFilter(a, { division: '04', group: '04.5' })).toBe(false)
  })

  test('片方が null なら常に偽（「止まった分」ノードは選択できない）', () => {
    expect(sameFilter(null, { division: '01' })).toBe(false)
    expect(sameFilter({ division: '01' }, null)).toBe(false)
    expect(sameFilter(null, null)).toBe(false)
  })
})
