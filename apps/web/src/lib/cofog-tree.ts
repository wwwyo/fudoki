/**
 * 分析画面の COFOG ツリーの型と組み立て。
 *
 * ⚠️ **集計はしない。並べ替えるだけ。** 木の各ノードの金額・件数・構成比は
 * `budgets:aggregate`（`groupBy: ['cofog.class']`）が返した値をそのまま使う。
 * ここでやるのは、小分類コード（`04.5.1` のような階層プレフィックス表記）の
 * 前方一致で division → group → class へネストし直すことだけ（AGENTS.md「集計は1箇所」）。
 * 以前は `getCofogBreakdown` が組んだ木（`report/budget/cofog.ts` の `buildCofogTree()`）を
 * そのまま描いていたが、その口を `budgets:aggregate` に一本化したので、
 * 「並べ替え」の実装がここへ移った。
 *
 * ⚠️ **division / group の名称は API から来ない。** `budgets:aggregate` が
 * `groupBy: ['cofog.class']` で返すセルは小分類の名称（`classLabel`）しか持たない
 * （中分類・大分類は集計の軸にしていないため）。COFOG の名称は
 * COFOG 1999 という固定の分類表であり、`report/budget/detail.ts` の `cofogLabel` が
 * 唯一の宣言なので、判断を計算し直すのではなくそこから引く
 * （`DIVISION_COLOR` を画面側の定数として持つのと同じ扱い。`report/` は変更していない）。
 */
import type { RouterClient } from "@orpc/server"
import type { Router } from "@fudoki/api/router"
import { cofogLabel } from "@fudoki/report/budget/detail"

/** `aggregateBudgets` の応答。画面はここから導出した型だけを使い、別経路で導出し直さない */
export type AggregateBudgetsResponse = Awaited<ReturnType<RouterClient<Router>["aggregateBudgets"]>>

/** ツリーのノードに紐づく statement filter。選択可能なノードだけが持つ */
export type CofogNodeFilter = { division: string; group?: string; class?: string }

export type CofogTreeNode = {
  /** React key かつ展開状態の管理キー */
  key: string
  code: string
  label: string
  depth: "division" | "group" | "class"
  count: number
  sum: number
  /** `total`（budget の合計）に対する構成比。画面で割り算しない */
  share: number
  filter: CofogNodeFilter | null
  children?: CofogTreeNode[]
}

/** class コード（`04.5.1`）から division（`04`）を取り出す */
function divisionOf(classCode: string): string {
  return classCode.slice(0, 2)
}

/** class コード（`04.5.1`）から group（`04.5`）を取り出す。最後のドットまでが group */
function groupOf(classCode: string): string {
  const i = classCode.lastIndexOf(".")
  if (i === -1) throw new Error(`cofog class code has no group prefix: ${classCode}`)
  return classCode.slice(0, i)
}

/**
 * `budgets:aggregate`（`groupBy: ['cofog.class']`、単一 budget）の応答から
 * division → group → class の木を組む。
 *
 * ⚠️ **単一 budget の応答（`residual.notDescendedByDivision` を持つ応答）専用。**
 * 団体横断の応答はこの内訳をまだ持たない（design doc の制約。procedure/budgets.ts 参照）。
 *
 * ⚠️ **「止まった分」は大分類単位でしか出せない。** 旧 `getCofogBreakdown` は
 * 「大分類までで止まった分」と「中分類までで止まった分」を別ノードとして分けていたが、
 * `budgets:aggregate` の `residual.notDescendedByDivision` は division 単位の合計しか
 * 持たない（`cofog.class` で集計した depth の残余なので、途中で止まった深さを区別しない）。
 * ここでは division 直下に「（分類が完全でない分）」という1本のノードにまとめる
 * ── 情報を捨てているわけではない（合計は一致する）が、旧実装より粒度が粗い。
 */
export function buildCofogTree(response: AggregateBudgetsResponse): CofogTreeNode[] {
  type Leaf = { classCode: string; label: string; amount: number; lineCount: number; share: number }
  const leaves: Leaf[] = response.cells.map((c) => {
    const dim = c.dimensions[0]
    if (!dim || c.dimensions.length !== 1 || dim.dimension !== "cofog.class") {
      throw new Error(`buildCofogTree expects cells grouped by cofog.class only, got: ${JSON.stringify(c.dimensions)}`)
    }
    return {
      classCode: dim.code,
      label: dim.label ?? cofogLabel("class", dim.code),
      amount: c.amount,
      lineCount: c.lineCount,
      share: c.share ?? 0,
    }
  })

  const notDescendedByDivision = new Map((response.residual?.notDescendedByDivision ?? []).map((d) => [d.division, d]))

  const leavesByDivision = new Map<string, Leaf[]>()
  for (const leaf of leaves) {
    const div = divisionOf(leaf.classCode)
    const arr = leavesByDivision.get(div) ?? []
    arr.push(leaf)
    leavesByDivision.set(div, arr)
  }

  const divisionCodes = new Set([...leavesByDivision.keys(), ...notDescendedByDivision.keys()])

  const divisionNodes: CofogTreeNode[] = [...divisionCodes].sort().map((divCode) => {
    const divLeaves = leavesByDivision.get(divCode) ?? []
    const leavesByGroup = new Map<string, Leaf[]>()
    for (const leaf of divLeaves) {
      const g = groupOf(leaf.classCode)
      const arr = leavesByGroup.get(g) ?? []
      arr.push(leaf)
      leavesByGroup.set(g, arr)
    }

    const groupNodes: CofogTreeNode[] = [...leavesByGroup.entries()]
      .map(([groupCode, groupLeaves]) => {
        const classNodes: CofogTreeNode[] = groupLeaves
          .map((leaf) => ({
            key: leaf.classCode,
            code: leaf.classCode,
            label: leaf.label,
            depth: "class" as const,
            sum: leaf.amount,
            count: leaf.lineCount,
            share: leaf.share,
            filter: { division: divCode, group: groupCode, class: leaf.classCode },
          }))
          .sort((a, b) => b.sum - a.sum)
        return {
          key: groupCode,
          code: groupCode,
          label: cofogLabel("group", groupCode),
          depth: "group" as const,
          sum: classNodes.reduce((s, n) => s + n.sum, 0),
          count: classNodes.reduce((s, n) => s + n.count, 0),
          share: classNodes.reduce((s, n) => s + n.share, 0),
          filter: { division: divCode, group: groupCode },
          children: classNodes,
        }
      })
      .sort((a, b) => b.sum - a.sum)

    const notDescended = notDescendedByDivision.get(divCode)
    const children: CofogTreeNode[] =
      notDescended && notDescended.amount > 0 && groupNodes.length > 0
        ? [
            {
              key: `${divCode}/_own`,
              code: "",
              label: "（分類が完全でない分）",
              depth: "group" as const,
              sum: notDescended.amount,
              count: notDescended.lineCount,
              share: notDescended.share ?? 0,
              filter: null,
            },
            ...groupNodes,
          ]
        : groupNodes

    return {
      key: divCode,
      code: divCode,
      label: notDescended?.divisionLabel ?? cofogLabel("division", divCode),
      depth: "division" as const,
      sum: groupNodes.reduce((s, n) => s + n.sum, 0) + (notDescended?.amount ?? 0),
      count: groupNodes.reduce((s, n) => s + n.count, 0) + (notDescended?.lineCount ?? 0),
      share: groupNodes.reduce((s, n) => s + n.share, 0) + (notDescended?.share ?? 0),
      filter: { division: divCode },
      children: children.length > 0 ? children : undefined,
    }
  })

  return divisionNodes
}
