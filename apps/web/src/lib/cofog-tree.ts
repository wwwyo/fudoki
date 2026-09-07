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
import { share } from "@fudoki/report/budget/cofog"

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
 * `residual.notDescendedByDivision` の各項目は `stoppedAt`（`division` / `group`）を持つ
 * （apps/api/build.ts の `notDescendedByDivisionOf`）ので、旧 `getCofogBreakdown` と同じく
 * 「大分類までで止まった分」と「中分類までで止まった分」を別ノードとして division 直下に並べる。
 * ⚠️ **止まった深さの区別はできるが、group で止まった分の実際の group コードまでは復元しない。**
 * 前計算アセットが group ごとではなく division ごとに畳んで持つため、「どの group で止まったか」は
 * 失われている（合計は一致するので情報の欠落ではなく、旧実装より粒度が粗いだけ）。
 */
export function buildCofogTree(response: AggregateBudgetsResponse): CofogTreeNode[] {
  // group / division の share は子の share を足して作らない（浮動小数の和で誤差が積み上がり、
  // share の定義を変えたときに追随しない）。`total` から `report/budget/cofog.ts` の share() で
  // 都度作り直す。single-budget 応答専用というこの関数の前提（上のコメント）どおり total は必ず来る。
  if (!response.total) throw new Error("buildCofogTree expects a single-budget response with `total`")
  const total = response.total.amount

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

  // stoppedAt ごとに division → エントリの map を分けて持つ（1 division に stoppedAt 違いで
  // 最大2エントリあるので、単純な division キーの Map にはできない）
  const notDescendedByDivisionAt = { division: new Map<string, { amount: number; lineCount: number; share?: number }>(), group: new Map<string, { amount: number; lineCount: number; share?: number }>() }
  for (const d of response.residual?.notDescendedByDivision ?? []) {
    notDescendedByDivisionAt[d.stoppedAt].set(d.division, { amount: d.amount, lineCount: d.lineCount, share: d.share })
  }

  const leavesByDivision = new Map<string, Leaf[]>()
  for (const leaf of leaves) {
    const div = divisionOf(leaf.classCode)
    const arr = leavesByDivision.get(div) ?? []
    arr.push(leaf)
    leavesByDivision.set(div, arr)
  }

  const divisionCodes = new Set([
    ...leavesByDivision.keys(),
    ...notDescendedByDivisionAt.division.keys(),
    ...notDescendedByDivisionAt.group.keys(),
  ])

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
        const groupSum = classNodes.reduce((s, n) => s + n.sum, 0)
        return {
          key: groupCode,
          code: groupCode,
          label: cofogLabel("group", groupCode),
          depth: "group" as const,
          sum: groupSum,
          count: classNodes.reduce((s, n) => s + n.count, 0),
          share: share(groupSum, total),
          filter: { division: divCode, group: groupCode },
          children: classNodes,
        }
      })
      .sort((a, b) => b.sum - a.sum)

    // 「大分類までで止まった分」（stoppedAt='division'）と「中分類までで止まった分」
    // （stoppedAt='group'）を別ノードにする（旧 getCofogBreakdown と同じ区別。AGENTS.md 参照）。
    // 「止まった分」は、同じ階層に実際に降りた兄弟（groupNodes）がいるときだけ出す ──
    // 兄弟が無ければ子が無いこと自体が「ここで止まった」を意味し、出すと冗長になる
    // （合計は division 自身の sum/count にそのまま残るので、ここで削っても値は変わらない）。
    const stoppedAtDivision = notDescendedByDivisionAt.division.get(divCode)
    const stoppedAtGroup = notDescendedByDivisionAt.group.get(divCode)
    const stoppedNode = (
      key: string,
      label: string,
      entry: { amount: number; lineCount: number; share?: number } | undefined,
    ): CofogTreeNode | null =>
      entry && entry.amount > 0
        ? { key, code: "", label, depth: "group", sum: entry.amount, count: entry.lineCount, share: entry.share ?? 0, filter: null }
        : null
    const stoppedNodes: CofogTreeNode[] =
      groupNodes.length === 0
        ? []
        : [
            stoppedNode(`${divCode}/_own-division`, "（大分類までで止まった分）", stoppedAtDivision),
            stoppedNode(`${divCode}/_own-group`, "（中分類までで止まった分）", stoppedAtGroup),
          ].filter((n): n is CofogTreeNode => n !== null)
    const children: CofogTreeNode[] = [...stoppedNodes, ...groupNodes]

    const notDescendedAmount = (stoppedAtDivision?.amount ?? 0) + (stoppedAtGroup?.amount ?? 0)
    const notDescendedCount = (stoppedAtDivision?.lineCount ?? 0) + (stoppedAtGroup?.lineCount ?? 0)
    const divisionSum = groupNodes.reduce((s, n) => s + n.sum, 0) + notDescendedAmount

    return {
      key: divCode,
      code: divCode,
      label: cofogLabel("division", divCode),
      depth: "division" as const,
      sum: divisionSum,
      count: groupNodes.reduce((s, n) => s + n.count, 0) + notDescendedCount,
      share: share(divisionSum, total),
      filter: { division: divCode },
      children: children.length > 0 ? children : undefined,
    }
  })

  return divisionNodes
}
