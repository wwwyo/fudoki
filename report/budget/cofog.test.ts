/**
 * `cofogGranularity` / `foldBy` / `share` / `cmp` の純粋関数テスト。
 * AGENTS.md「集計は1箇所だけで行う」を守る境界（`report/budget/cofog.ts`）に
 * 直接のテストが無かった（`apps/api` の統合テスト経由でしか触れていない）ので、
 * ここでは境界条件を独立に検証する。
 */
import { describe, expect, test } from 'bun:test'
import { buildCofogTree, cmp, cofogGranularity, foldBy, share, unclassifiedOf, type CofogTreeNode, type StateRow } from './cofog'
import type { CofogDepth } from './detail'
import type { CofogCode, CofogReach } from './schema'

/** 深さ指定で `cofogReach` の該当行を取り出す。無ければ即座にテストを落とす */
function reachOf(cofogReach: CofogReach[], depth: CofogDepth): CofogReach {
  const found = cofogReach.find((r) => r.depth === depth)
  if (!found) throw new Error(`cofogReach に ${depth} が無い`)
  return found
}

/** 短く書くための行ビルダ。指定しなかった列は「該当なし・未割当」の既定値で埋める */
function row(overrides: Partial<StateRow> = {}): StateRow {
  return {
    division: '', divisionLabel: '',
    group: '', groupLabel: '',
    class: '', classLabel: '',
    status: 'assigned',
    consolidation: 'none',
    count: 1,
    sum: 100,
    ...overrides,
  }
}

describe('cofogGranularity', () => {
  test('大分類止まりの行と、中分類・小分類まで降りた行が混在する場合、深さごとに正しく振り分ける', () => {
    const byState: StateRow[] = [
      row({ division: '01', divisionLabel: '一般行政', count: 1, sum: 100 }),
      row({ division: '04', divisionLabel: '経済業務', group: '04.5', groupLabel: '運輸', count: 1, sum: 200 }),
      row({
        division: '04', divisionLabel: '経済業務', group: '04.5', groupLabel: '運輸',
        class: '04.5.1', classLabel: '道路交通', count: 1, sum: 300,
      }),
    ]
    const result = cofogGranularity(byState)

    // division 止まりの行は division の deepest にだけ現れる
    expect(reachOf(result.cofogReach, 'division').deepest).toEqual({ count: 1, sum: 100 })
    // group 止まりの行は group の deepest にだけ現れる
    expect(reachOf(result.cofogReach, 'group').deepest).toEqual({ count: 1, sum: 200 })
    // class まで降りた行は class の deepest にだけ現れる
    expect(reachOf(result.cofogReach, 'class').deepest).toEqual({ count: 1, sum: 300 })
    // reached は「その深さ以上」の累積。division の reached は全割当済みを含む
    expect(reachOf(result.cofogReach, 'division').reached).toEqual({ count: 3, sum: 600 })
    expect(reachOf(result.cofogReach, 'group').reached).toEqual({ count: 2, sum: 500 })
    expect(reachOf(result.cofogReach, 'class').reached).toEqual({ count: 1, sum: 300 })
  })

  test('group や class が空文字の行は「まだ降りていない」として division / group 止まりに数える', () => {
    const byState: StateRow[] = [
      row({ division: '01', divisionLabel: '一般行政', group: '', class: '' }),
      row({ division: '02', divisionLabel: '国防', group: '02.1', groupLabel: '軍事', class: '' }),
    ]
    const result = cofogGranularity(byState)
    expect(reachOf(result.cofogReach, 'division').deepest.count).toBe(1)
    expect(reachOf(result.cofogReach, 'group').deepest.count).toBe(1)
    expect(reachOf(result.cofogReach, 'class').deepest.count).toBe(0)
  })

  test('全行が not-applicable（歳入の形）のとき、assigned は 0 で total だけが積み上がる', () => {
    const byState: StateRow[] = [
      row({ status: 'not-applicable', division: '', divisionLabel: '', count: 1, sum: 1000 }),
      row({ status: 'not-applicable', division: '', divisionLabel: '', count: 1, sum: 2000 }),
    ]
    const result = cofogGranularity(byState)
    expect(result.assigned).toEqual({ count: 0, sum: 0 })
    expect(result.total).toEqual({ count: 2, sum: 3000 })
    expect(result.byCode).toEqual([])
    expect(result.byDivision).toEqual([])
    expect(result.assignedShare).toEqual({ count: 0, sum: 0 })
    // 割当済みが無いので、どの深さの reached/deepest も 0
    for (const r of result.cofogReach) {
      expect(r.deepest).toEqual({ count: 0, sum: 0 })
      expect(r.reached).toEqual({ count: 0, sum: 0 })
      expect(r.share).toEqual({ count: 0, sum: 0 })
    }
  })

  test('金額が 0 の行も件数としては数える（金額の大小と行の有無を混同しない）', () => {
    const byState: StateRow[] = [
      row({ division: '01', divisionLabel: '一般行政', count: 1, sum: 0 }),
    ]
    const result = cofogGranularity(byState)
    expect(result.assigned).toEqual({ count: 1, sum: 0 })
    expect(result.total).toEqual({ count: 1, sum: 0 })
    expect(result.byDivision).toEqual([{ division: '01', divisionLabel: '一般行政', count: 1, sum: 0 }])
  })

  test('同じコードの行は fold されて1行にまとまる（byCode・byDivision の両方）', () => {
    const byState: StateRow[] = [
      row({ division: '01', divisionLabel: '一般行政', count: 1, sum: 100 }),
      row({ division: '01', divisionLabel: '一般行政', count: 2, sum: 300 }),
    ]
    const result = cofogGranularity(byState)
    expect(result.byCode).toEqual([
      { division: '01', divisionLabel: '一般行政', group: '', groupLabel: '', class: '', classLabel: '', count: 3, sum: 400 },
    ])
    expect(result.byDivision).toEqual([{ division: '01', divisionLabel: '一般行政', count: 3, sum: 400 }])
  })

  test('total と assigned の差は、分類不能・対象外として残り、byCode/byDivision には現れない', () => {
    const byState: StateRow[] = [
      row({ status: 'assigned', division: '01', divisionLabel: '一般行政', count: 1, sum: 100 }),
      row({ status: 'unclassified', division: '', divisionLabel: '', count: 1, sum: 50 }),
      row({ status: 'not-applicable', division: '', divisionLabel: '', count: 1, sum: 30 }),
    ]
    const result = cofogGranularity(byState)
    expect(result.assigned).toEqual({ count: 1, sum: 100 })
    expect(result.total).toEqual({ count: 3, sum: 180 })
    // 落ちた分（分類不能＋対象外）が失われず total - assigned に残っている
    expect(result.total.count - result.assigned.count).toBe(2)
    expect(result.total.sum - result.assigned.sum).toBe(80)
    expect(result.byCode).toEqual([
      { division: '01', divisionLabel: '一般行政', group: '', groupLabel: '', class: '', classLabel: '', count: 1, sum: 100 },
    ])
  })

  test('byCode は金額の降順で並ぶ', () => {
    const byState: StateRow[] = [
      row({ division: '01', divisionLabel: '一般行政', count: 1, sum: 100 }),
      row({ division: '04', divisionLabel: '経済業務', count: 1, sum: 500 }),
      row({ division: '02', divisionLabel: '国防', count: 1, sum: 300 }),
    ]
    const result = cofogGranularity(byState)
    expect(result.byCode.map((r) => r.division)).toEqual(['04', '02', '01'])
  })
})

describe('foldBy', () => {
  test('同じ鍵の行を count/sum で合算し、鍵に含めない列は先頭行の値を残す', () => {
    const rows = [
      { id: 'a', label: 'first', count: 1, sum: 10 },
      { id: 'a', label: 'second', count: 2, sum: 20 },
      { id: 'b', label: 'third', count: 3, sum: 30 },
    ]
    const result = foldBy(rows, (r) => r.id)
    expect(result).toEqual([
      { id: 'a', label: 'first', count: 3, sum: 30 },
      { id: 'b', label: 'third', count: 3, sum: 30 },
    ])
  })

  test('空配列を渡すと空配列を返す', () => {
    expect(foldBy([] as { count: number; sum: number }[], () => 'k')).toEqual([])
  })
})

describe('share', () => {
  test('分母が 0 のときは 0 を返す（NaN・Infinity にしない）', () => {
    expect(share(10, 0)).toBe(0)
  })

  test('通常の割合を計算する', () => {
    expect(share(1, 4)).toBe(0.25)
  })

  test('分子が 0 のときは 0', () => {
    expect(share(0, 100)).toBe(0)
  })
})

describe('cmp', () => {
  test('文字列の昇順比較として振る舞う', () => {
    expect(cmp('a', 'b')).toBe(-1)
    expect(cmp('b', 'a')).toBe(1)
    expect(cmp('a', 'a')).toBe(0)
  })

  test('Array.prototype.sort に渡して昇順に並べられる', () => {
    expect(['c', 'a', 'b'].sort(cmp)).toEqual(['a', 'b', 'c'])
  })
})

describe('unclassifiedOf', () => {
  test('total と assigned の差を返し、total に対する share を持つ', () => {
    const result = unclassifiedOf({ count: 1, sum: 100 }, { count: 3, sum: 180 })
    expect(result).toEqual({ count: 2, sum: 80, share: 80 / 180 })
  })

  test('total が 0 のときは share も 0（NaN にしない）', () => {
    expect(unclassifiedOf({ count: 0, sum: 0 }, { count: 0, sum: 0 })).toEqual({ count: 0, sum: 0, share: 0 })
  })
})

/**
 * `buildCofogTree` の invariant テスト。以前は `apps/web/src/lib/cofog-tree.ts` に
 * 実装があり、そこにテストもあったが、実装を境界（report/budget/cofog.ts）へ移したので
 * テストも一緒に移す（AGENTS.md「集計は1箇所」の境界に直接のテストを持たせる）。
 *
 * ここは API の `byCode`（すでに fold 済みの最終値）をネストし直すだけで新しい集計をしない
 * ので、テストは「組み替えても値の合計が保たれるか」と「share が total に対する割合になっているか」を測る。
 */
function code(overrides: Partial<CofogCode & { count: number; sum: number }>): CofogCode & { count: number; sum: number } {
  return {
    division: '01', divisionLabel: '一般行政',
    group: '', groupLabel: '',
    class: '', classLabel: '',
    count: 1, sum: 100,
    ...overrides,
  }
}

function division(
  overrides: Partial<Pick<CofogCode, 'division' | 'divisionLabel'> & { count: number; sum: number }>,
): Pick<CofogCode, 'division' | 'divisionLabel'> & { count: number; sum: number } {
  return { division: '01', divisionLabel: '一般行政', count: 0, sum: 0, ...overrides }
}

const sumOf = (nodes: readonly CofogTreeNode[]) => nodes.reduce((s, n) => s + n.sum, 0)
const countOf = (nodes: readonly CofogTreeNode[]) => nodes.reduce((s, n) => s + n.count, 0)

describe('buildCofogTree', () => {
  test('大分類ノードの合計は byDivision と一致する', () => {
    const byDivision = [
      division({ division: '01', divisionLabel: '一般行政', count: 3, sum: 300 }),
      division({ division: '04', divisionLabel: '経済業務', count: 2, sum: 200 }),
    ]
    const byCode = [
      code({ division: '01', divisionLabel: '一般行政', count: 3, sum: 300 }),
      code({ division: '04', divisionLabel: '経済業務', group: '04.5', groupLabel: '運輸', count: 2, sum: 200 }),
    ]
    const tree = buildCofogTree(byDivision, byCode, 500)
    expect(tree).toHaveLength(2)
    for (const node of tree) {
      const source = byDivision.find((d) => d.division === node.code)
      expect(source).toBeDefined()
      expect(node.sum).toBe(source ? source.sum : Number.NaN)
      expect(node.count).toBe(source ? source.count : Number.NaN)
    }
  })

  test('ノードの share は total に対する割合になる', () => {
    const byDivision = [division({ division: '01', divisionLabel: '一般行政', count: 1, sum: 250 })]
    const byCode = [code({ division: '01', divisionLabel: '一般行政', count: 1, sum: 250 })]
    const tree = buildCofogTree(byDivision, byCode, 1000)
    expect(tree[0]?.share).toBe(0.25)
  })

  test('total が 0 のときの share は 0（NaN にしない）', () => {
    const byDivision = [division({ division: '01', divisionLabel: '一般行政', count: 0, sum: 0 })]
    const byCode = [code({ division: '01', divisionLabel: '一般行政', count: 0, sum: 0 })]
    const tree = buildCofogTree(byDivision, byCode, 0)
    expect(tree[0]?.share).toBe(0)
  })

  test('中分類ノードの子（小分類＋中分類止まり）の合計は、その中分類自身と一致する', () => {
    const byDivision = [division({ division: '04', divisionLabel: '経済業務', count: 3, sum: 300 })]
    const byCode = [
      // group まで（class 止まり）
      code({ division: '04', divisionLabel: '経済業務', group: '04.5', groupLabel: '運輸', class: '', count: 1, sum: 100 }),
      // class まで降りた行
      code({
        division: '04', divisionLabel: '経済業務', group: '04.5', groupLabel: '運輸',
        class: '04.5.1', classLabel: '道路交通', count: 2, sum: 200,
      }),
    ]
    const tree = buildCofogTree(byDivision, byCode, 300)
    const groupNode = tree[0]?.children?.find((n) => n.depth === 'group')
    expect(groupNode).toBeDefined()
    if (!groupNode) throw new Error('unreachable')
    expect(groupNode.sum).toBe(300)
    expect(groupNode.count).toBe(3)
    const children = groupNode.children ?? []
    expect(sumOf(children)).toBe(groupNode.sum)
    expect(countOf(children)).toBe(groupNode.count)
  })

  test('大分類の子の合計は大分類自身と一致する', () => {
    const byDivision = [division({ division: '04', divisionLabel: '経済業務', count: 5, sum: 500 })]
    const byCode = [
      // division 直下で止まった分
      code({ division: '04', divisionLabel: '経済業務', group: '', class: '', count: 1, sum: 100 }),
      // group まで降りた分
      code({ division: '04', divisionLabel: '経済業務', group: '04.5', groupLabel: '運輸', count: 4, sum: 400 }),
    ]
    const tree = buildCofogTree(byDivision, byCode, 500)
    const root = tree[0]
    expect(root).toBeDefined()
    if (!root) throw new Error('unreachable')
    const children = root.children ?? []
    expect(sumOf(children)).toBe(root.sum)
    expect(countOf(children)).toBe(root.count)
  })

  test('「〜までで止まった分」ノードは、実際に降りた兄弟がいるときだけ出る', () => {
    // group 直下で止まった分だけがあり、class まで降りた兄弟がいない場合 → 「止まった分」ノードは出ない
    const byDivisionSoleStop = [division({ division: '04', divisionLabel: '経済業務', count: 1, sum: 100 })]
    const byCodeSoleStop = [
      code({ division: '04', divisionLabel: '経済業務', group: '04.5', groupLabel: '運輸', class: '', count: 1, sum: 100 }),
    ]
    const treeSoleStop = buildCofogTree(byDivisionSoleStop, byCodeSoleStop, 100)
    const groupNodeSoleStop = treeSoleStop[0]?.children?.find((n) => n.depth === 'group')
    expect(groupNodeSoleStop?.children).toBeUndefined()

    // class まで降りた兄弟が併存する場合 → 「止まった分」ノードが出る
    const byDivisionWithSibling = [division({ division: '04', divisionLabel: '経済業務', count: 2, sum: 200 })]
    const byCodeWithSibling = [
      code({ division: '04', divisionLabel: '経済業務', group: '04.5', groupLabel: '運輸', class: '', count: 1, sum: 100 }),
      code({
        division: '04', divisionLabel: '経済業務', group: '04.5', groupLabel: '運輸',
        class: '04.5.1', classLabel: '道路交通', count: 1, sum: 100,
      }),
    ]
    const treeWithSibling = buildCofogTree(byDivisionWithSibling, byCodeWithSibling, 200)
    const groupNodeWithSibling = treeWithSibling[0]?.children?.find((n) => n.depth === 'group')
    const stopNode = groupNodeWithSibling?.children?.find((n) => n.filter === null)
    expect(stopNode).toBeDefined()
    expect(stopNode?.label).toBe('（中分類までで止まった分）')
    expect(stopNode?.sum).toBe(100)

    // 同じロジックが division 直下でも成り立つ（division 止まりのみ → 出ない）
    const byDivisionOnly = [division({ division: '01', divisionLabel: '一般行政', count: 1, sum: 50 })]
    const byCodeOnly = [code({ division: '01', divisionLabel: '一般行政', group: '', class: '', count: 1, sum: 50 })]
    const treeDivisionOnly = buildCofogTree(byDivisionOnly, byCodeOnly, 50)
    expect(treeDivisionOnly[0]?.children).toBeUndefined()
  })
})
