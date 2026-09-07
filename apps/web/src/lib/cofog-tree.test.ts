/**
 * `buildCofogTree` のテスト。**並べ替えであって集計ではない**ことを検査する
 * ── 各ノードの sum/count/share が、入力（`budgets:aggregate` の応答）の値の
 * 単純な再配分（足し戻し）になっていて、画面側で新しい金額を作っていないことを確かめる。
 */
import { describe, expect, test } from "bun:test"
import { buildCofogTree, type AggregateBudgetsResponse } from "./cofog-tree"

/** テストに必要な最小限のフィールドだけを持つ応答を組み立てる */
// group・division の share は total から作り直す（cofog-tree.ts）ので、テストの入力側も
// class の share（0.1 = 1000/10000 など）と辻褄が合う total を明示する。
const FAKE_TOTAL = 10000

function fakeResponse(
  cells: { code: string; label: string; amount: number; lineCount: number; share: number }[],
  notDescendedByDivision: { division: string; divisionLabel: string; stoppedAt: "division" | "group"; amount: number; lineCount: number; share: number }[] = [],
): AggregateBudgetsResponse {
  return {
    cells: cells.map((c) => ({
      dimensions: [{ dimension: "cofog.class" as const, code: c.code, label: c.label }],
      amount: c.amount,
      lineCount: c.lineCount,
      share: c.share,
    })),
    total: { amount: FAKE_TOTAL, lineCount: 0 },
    residual: {
      unclassifiable: { amount: 0, lineCount: 0, share: 0 },
      outOfScope: { amount: 0, lineCount: 0, share: 0 },
      notDescended: {
        amount: notDescendedByDivision.reduce((s, d) => s + d.amount, 0),
        lineCount: notDescendedByDivision.reduce((s, d) => s + d.lineCount, 0),
        share: notDescendedByDivision.reduce((s, d) => s + d.share, 0),
      },
      notDescendedByDivision,
    },
  } as unknown as AggregateBudgetsResponse
}

describe("buildCofogTree", () => {
  test("class ノードの金額は入力のセルそのもの（足し直さない）", () => {
    const res = fakeResponse([
      { code: "04.5.1", label: "道路交通", amount: 1000, lineCount: 3, share: 0.1 },
    ])
    const tree = buildCofogTree(res)
    const division = tree.find((n) => n.code === "04")!
    const group = division.children!.find((n) => n.code === "04.5")!
    const cls = group.children!.find((n) => n.code === "04.5.1")!
    expect(cls.sum).toBe(1000)
    expect(cls.count).toBe(3)
    expect(cls.share).toBe(0.1)
    expect(cls.filter).toEqual({ division: "04", group: "04.5", class: "04.5.1" })
  })

  test("group・division の金額は配下の class 金額の合計に一致する（二重集計しない）", () => {
    const res = fakeResponse([
      { code: "04.5.1", label: "道路交通", amount: 1000, lineCount: 3, share: 0.1 },
      { code: "04.1.2", label: "一般労働業務", amount: 500, lineCount: 1, share: 0.05 },
    ])
    const tree = buildCofogTree(res)
    const division = tree.find((n) => n.code === "04")!
    expect(division.sum).toBe(1500)
    expect(division.count).toBe(4)
    expect(division.share).toBeCloseTo(0.15)

    const group45 = division.children!.find((n) => n.code === "04.5")!
    expect(group45.sum).toBe(1000)
    const group41 = division.children!.find((n) => n.code === "04.1")!
    expect(group41.sum).toBe(500)
  })

  test("複数 division にまたがる場合は前方一致で別ノードへ分かれる", () => {
    const res = fakeResponse([
      { code: "04.5.1", label: "道路交通", amount: 1000, lineCount: 1, share: 0.5 },
      // group "01.1" は COFOG_GROUPS に実在するコード。class 自体の名称はセルの label をそのまま使う
      { code: "01.1.9", label: "テスト用の小分類", amount: 2000, lineCount: 4, share: 0.3 },
    ])
    const tree = buildCofogTree(res)
    expect(tree.map((n) => n.code)).toEqual(["01", "04"])
  })

  test("cofog.class 以外の軸で集計したセルを渡すと止める（この関数の前提が壊れているのを検出）", () => {
    const res: AggregateBudgetsResponse = {
      cells: [{ dimensions: [{ dimension: "cofog.division", code: "04", label: "経済業務" }], amount: 100, lineCount: 1, share: 1 }],
    } as unknown as AggregateBudgetsResponse
    expect(() => buildCofogTree(res)).toThrow()
  })

  test("止まった分（notDescendedByDivision, stoppedAt=division）は、その division に既に降りた行があるときだけ子ノードとして現れる", () => {
    const res = fakeResponse(
      [{ code: "04.5.1", label: "道路交通", amount: 1000, lineCount: 1, share: 0.4 }],
      [{ division: "04", divisionLabel: "経済業務", stoppedAt: "division", amount: 300, lineCount: 2, share: 0.12 }],
    )
    const tree = buildCofogTree(res)
    const division = tree.find((n) => n.code === "04")!
    const own = division.children!.find((n) => n.label === "（大分類までで止まった分）")!
    expect(own.sum).toBe(300)
    expect(own.count).toBe(2)
    expect(own.filter).toBeNull()
    // division の合計は「降りた分」+「止まった分」（新しい数字を作っていない）
    expect(division.sum).toBe(1300)
    expect(division.count).toBe(3)
  })

  test("stoppedAt=division と stoppedAt=group は別ノードになる（旧 getCofogBreakdown と同じ区別を復元）", () => {
    const res = fakeResponse(
      [{ code: "04.5.1", label: "道路交通", amount: 1000, lineCount: 1, share: 0.4 }],
      [
        { division: "04", divisionLabel: "経済業務", stoppedAt: "division", amount: 300, lineCount: 2, share: 0.12 },
        { division: "04", divisionLabel: "経済業務", stoppedAt: "group", amount: 150, lineCount: 1, share: 0.06 },
      ],
    )
    const tree = buildCofogTree(res)
    const division = tree.find((n) => n.code === "04")!
    const stoppedAtDivision = division.children!.find((n) => n.label === "（大分類までで止まった分）")!
    const stoppedAtGroup = division.children!.find((n) => n.label === "（中分類までで止まった分）")!
    expect(stoppedAtDivision.sum).toBe(300)
    expect(stoppedAtGroup.sum).toBe(150)
    expect(stoppedAtGroup.filter).toBeNull()
    // division の合計は class + stoppedAt=division + stoppedAt=group の3つの和（分けても合計は変わらない）
    expect(division.sum).toBe(1450)
    expect(division.count).toBe(4)
  })

  test("そのdivisionに降りた行が1つも無ければ、止まった分だけの division ノードになる（子ノードは無い）", () => {
    const res = fakeResponse(
      [],
      [{ division: "09", divisionLabel: "教育", stoppedAt: "division", amount: 700, lineCount: 5, share: 0.3 }],
    )
    const tree = buildCofogTree(res)
    const division = tree.find((n) => n.code === "09")!
    expect(division.sum).toBe(700)
    expect(division.count).toBe(5)
    // 兄弟（groupNodes）が無いので「止まった分」ノードは冗長 ── children を持たせない
    expect(division.children).toBeUndefined()
  })

  test("division の label は常に COFOG 標準名を使う（cofogLabel が唯一の宣言）", () => {
    const res = fakeResponse(
      [{ code: "04.5.1", label: "道路交通", amount: 1000, lineCount: 1, share: 1 }],
      [],
    )
    const tree = buildCofogTree(res)
    const division = tree.find((n) => n.code === "04")!
    expect(division.label).toBe("経済業務")
  })
})
