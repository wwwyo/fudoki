/**
 * 分析画面の COFOG ツリー用に、API の `byCode`（規則が到達した division/group/class
 * ごとの集計）を division → group → class の木へ組み替える。
 *
 * ⚠️ **新しい集計はしない。** ここでやっているのは `byCode`（すでに fold 済みの最終値）を
 * 表示のためにネストし直すことだけで、`count`/`sum` の値そのものは API から来た値の再配分
 * （同じ値を group・class の親へ積み上げる）に留める。行レベルまで戻って独自に足し直すと
 * AGENTS.md が禁じる「画面側の二重集計」になる。
 *
 * group / class が空文字なのは cofogGranularity と同じ理由（規則がそこまで下げていない）で、
 * ここでは「その分類の直下で止まった分」として独立した葉ノードにする
 * （クリックしても division/group までの filter しか API に無いので、選択は不可）。
 */
import type { RouterClient } from "@orpc/server"
import type { Router } from "@fudoki/api/router"

type CofogBreakdown = Awaited<ReturnType<RouterClient<Router>["getCofogBreakdown"]>>["cofog"]
export type CofogCodeRow = CofogBreakdown["byCode"][number]
export type CofogDivisionRow = CofogBreakdown["byDivision"][number]

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
  /** 「ここで止まった分」の情報ノードは選択できない（API に「該当なし」を絞る術が無い） */
  filter: CofogNodeFilter | null
  children?: CofogTreeNode[]
}

const byDesc = (a: { sum: number }, b: { sum: number }) => b.sum - a.sum

export function buildCofogTree(byDivision: readonly CofogDivisionRow[], byCode: readonly CofogCodeRow[]): CofogTreeNode[] {
  return byDivision.map((d) => {
    const rows = byCode.filter((r) => r.division === d.division)
    const groups = new Map<string, { label: string; count: number; sum: number; rows: CofogCodeRow[] }>()
    const ownAtDivision = { count: 0, sum: 0 }
    for (const r of rows) {
      if (r.group === "") {
        ownAtDivision.count += r.count
        ownAtDivision.sum += r.sum
        continue
      }
      const g = groups.get(r.group) ?? { label: r.groupLabel, count: 0, sum: 0, rows: [] }
      g.count += r.count
      g.sum += r.sum
      g.rows.push(r)
      groups.set(r.group, g)
    }

    const groupNodes: CofogTreeNode[] = [...groups.entries()]
      .sort(([, a], [, b]) => byDesc(a, b))
      .map(([group, g]) => {
        const ownAtGroup = { count: 0, sum: 0 }
        const classNodes: CofogTreeNode[] = []
        for (const r of g.rows) {
          if (r.class === "") {
            ownAtGroup.count += r.count
            ownAtGroup.sum += r.sum
            continue
          }
          classNodes.push({
            key: `${d.division}/${group}/${r.class}`,
            code: r.class,
            label: r.classLabel,
            depth: "class",
            count: r.count,
            sum: r.sum,
            filter: { division: d.division, group, class: r.class },
          })
        }
        classNodes.sort(byDesc)
        // 「止まった分」は、同じ階層に実際に降りた兄弟（classNodes）がいるときだけ出す。
        // 兄弟が無ければ、子が無いこと自体が「ここで止まった」を意味するので冗長になる
        // （合計は group 自身の count/sum にそのまま残るので、ここで削っても値は変わらない）。
        const children: CofogTreeNode[] = ownAtGroup.count > 0 && classNodes.length > 0
          ? [
              {
                key: `${d.division}/${group}/_own`,
                code: "",
                label: "（中分類までで止まった分）",
                depth: "class",
                count: ownAtGroup.count,
                sum: ownAtGroup.sum,
                filter: null,
              },
              ...classNodes,
            ]
          : classNodes
        return {
          key: `${d.division}/${group}`,
          code: group,
          label: g.label,
          depth: "group",
          count: g.count,
          sum: g.sum,
          filter: { division: d.division, group },
          children: children.length > 0 ? children : undefined,
        }
      })

    // 同様に、division 直下の「止まった分」も group が実在するときだけ出す。
    const children: CofogTreeNode[] = ownAtDivision.count > 0 && groupNodes.length > 0
      ? [
          {
            key: `${d.division}/_own`,
            code: "",
            label: "（大分類までで止まった分）",
            depth: "group",
            count: ownAtDivision.count,
            sum: ownAtDivision.sum,
            filter: null,
          },
          ...groupNodes,
        ]
      : groupNodes

    return {
      key: d.division,
      code: d.division,
      label: d.divisionLabel,
      depth: "division",
      count: d.count,
      sum: d.sum,
      filter: { division: d.division },
      children: children.length > 0 ? children : undefined,
    }
  })
}
