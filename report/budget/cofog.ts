/**
 * COFOG の**到達粒度**の集計。**API 側にも要るので、生成側（`build.ts`）専用にしない。**
 *
 * `report/budget/build.ts` の `cofogGranularity()` をここへ切り出した。
 * AGENTS.md が「集計は report/budget/build.ts の1箇所だけで行う」と定めているのは
 * 画面と生成側の二重計算を防ぐためで、API 側にも集計が要る以上、
 * 実装を1つにしてダッシュボードの報告生成と API の両方がここを呼ぶ形にする
 * （API へ書き下ろすと、規範が防ごうとしている状態そのものになる）。
 *
 * ⚠️ **`byState` から導出する。問い合わせを増やさない。**
 * どれも同じ join の同じ事実を別の切り方で数えているだけなので、
 * 独立に4本のクエリを投げると、後から片方の絞り込みだけ変えたときに
 * 画面の節どうしが黙って食い違う（合計が一致するのは偶然になる）。
 * 導出なら一致は構造で保たれ、DuckDB CLI の起動も団体あたり4回減る。
 *
 * ⚠️ **`group` / `class` が空なのは「該当が無い」ではなく「まだ降りていない」。**
 * 款の名称だけで決まる規則（総務費 → 01、民生費 → 10）は division 止まりが正しく、
 * group を埋めるには項や目まで下げる判断が要る。したがってここは
 * **達成率ではなく現在地**で、割合の高さを合否に使わない（分類不能の割合と同じ扱い）。
 *
 * ⚠️ **母数は割当済みだけ。** 分類不能・対象外には割当先が無いので深さも無い。
 * 全行を母数にすると「降りていない」と「そもそも割り当てていない」が混ざる。
 *
 * 累積（`reached`）と排他（`deepest`）の両方を持つのは、**画面で足し算させないため**。
 * 集計を画面へ漏らすと、同じ数字が2通りに計算されていずれ食い違う。
 */
import { COFOG_DEPTHS, COFOG_DEPTH_JA, type CofogDepth } from './detail'
import type { CofogCode, CofogReach, Transform } from './schema'

/** ツリーのノードに紐づく statement filter。選択可能なノードだけが持つ */
export type CofogTreeFilter = { division: string; group?: string; class?: string }

export type CofogTreeNode = {
  /** React key かつ展開状態の管理キー */
  key: string
  code: string
  label: string
  depth: CofogDepth
  count: number
  sum: number
  /** 全体（`total`）に対する構成比。画面が割り算しなくて済むよう、ここで持たせる */
  share: number
  /** 「ここで止まった分」の情報ノードは選択できない（API に「該当なし」を絞る術が無い） */
  filter: CofogTreeFilter | null
  children?: CofogTreeNode[]
}

export type StateRow = CofogCode & { status: string; consolidation: string; count: number; sum: number }

/** 順序を SQL と揃える（報告は commit するので、非決定的だと中身が同じでも差分が出る） */
/** 文字列の昇順比較。集計の並びを決めるのに使う（build.ts の並べ替えからも呼ぶ） */
export const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)
const ZERO = { count: 0, sum: 0 }
const add = (a: { count: number; sum: number }, b: { count: number; sum: number }) =>
  ({ count: a.count + b.count, sum: a.sum + b.sum })

/** 鍵ごとに畳む。**鍵に含めない列は先頭行のもの**（同じ鍵なら同じ値である列しか残さない） */
export function foldBy<T extends { count: number; sum: number }>(rows: T[], key: (r: T) => string): T[] {
  const m = new Map<string, T>()
  for (const r of rows) {
    const hit = m.get(key(r))
    if (hit) { hit.count += r.count; hit.sum += r.sum } else m.set(key(r), { ...r })
  }
  return [...m.values()]
}

/** その行がどこまで降りているか。**空は「まだ降りていない」** */
const depthOf = (r: CofogCode): CofogDepth => (r.class ? 'class' : r.group ? 'group' : 'division')

/** 割合。分母が 0 のときは 0（COFOG 以外の充足率でも使う） */
export const share = (v: number, whole: number) => (whole === 0 ? 0 : v / whole)

/**
 * `total` と `assigned` の差（分類不能・対象外・歳入は分類の軸なし）。
 * 画面（旧 analysis.tsx）が `total.sum - assigned.sum` を自分で引いていたのをここへ移す。
 * ⚠️ 分母は `total`（未分類込み）── 割当済みだけを分母にすると、実際には
 * 使途が見えていない分まで「見えている」ことになる。
 */
export function unclassifiedOf(
  assigned: { count: number; sum: number },
  total: { count: number; sum: number },
): { count: number; sum: number; share: number } {
  const count = total.count - assigned.count
  const sum = total.sum - assigned.sum
  return { count, sum, share: share(sum, total.sum) }
}

export function cofogGranularity(byState: StateRow[]):
  Pick<Transform, 'byCode' | 'byDivision' | 'cofogReach' | 'assigned' | 'total' | 'assignedShare'> {
  const total = byState.reduce(add, ZERO)
  const assignedRows = byState.filter((r) => r.status === 'assigned')
  const assigned = assignedRows.reduce(add, ZERO)
  const byCode = foldBy(
    assignedRows.map(({ status: _s, consolidation: _c, ...code }) => code),
    // \x1F（Unit Separator）で繋ぐ。COFOG のコードに現れない文字なので、
    // '01' + '1' と '011' + '' のような別の組が同じキーに潰れない
    (r) => [r.division, r.group, r.class].join('\x1f'),
  ).sort((a, b) => b.sum - a.sum || cmp(a.division, b.division)
    || cmp(a.group, b.group) || cmp(a.class, b.class))
  const byDivision = foldBy(
    byCode.map(({ division, divisionLabel, count, sum }) => ({ division, divisionLabel, count, sum })),
    (r) => r.division,
  ).sort((a, b) => cmp(a.division, b.division))

  const at = (d: CofogDepth) => byCode.filter((r) => depthOf(r) === d).reduce(add, ZERO)
  const cofogReach: CofogReach[] = COFOG_DEPTHS.map((depth, i) => {
    // その深さ「以上」= 自分より深い段も数える（04.5.1 は group にも届いている）
    const reached = COFOG_DEPTHS.slice(i).map(at).reduce(add, ZERO)
    return {
      depth, label: COFOG_DEPTH_JA[depth],
      deepest: at(depth),
      reached,
      share: { count: share(reached.count, assigned.count), sum: share(reached.sum, assigned.sum) },
    }
  })
  return {
    byCode, byDivision, cofogReach, assigned, total,
    assignedShare: { count: share(assigned.count, total.count), sum: share(assigned.sum, total.sum) },
  }
}

/**
 * `byCode`（division/group/class ごとに fold 済みの葉）を division → group → class の
 * 木へ組み替える。ここも `cofogGranularity` と同じ「集計は1箇所」の境界に置く。
 * 画面（旧 `apps/web/src/lib/cofog-tree.ts`）が `+=` で足していたのをここへ移した。
 *
 * ⚠️ **新しい集計はしない。** `byCode` の `count`/`sum`（すでに fold 済みの最終値）を
 * 表示のためにネストし直すだけで、値そのものは API から来た値の再配分（同じ値を
 * group・class の親へ積み上げる）に留める。行レベルまで戻って独自に足し直すと
 * AGENTS.md が禁じる「画面側の二重集計」に戻ってしまう。
 *
 * `total` は構成比（`share`）の分母。呼び出し側は `cofogGranularity` の `total.sum`
 * （未分類込みの全体）を渡す — 割当済みだけを分母にすると、実際には使途が
 * 見えていない分まで「見えている」ことになる（analysis.tsx が説明している理由と同じ）。
 */
export function buildCofogTree(
  byDivision: readonly (Pick<CofogCode, 'division' | 'divisionLabel'> & { count: number; sum: number })[],
  byCode: readonly (CofogCode & { count: number; sum: number })[],
  total: number,
): CofogTreeNode[] {
  const shareOf = (v: number) => share(v, total)
  return byDivision.map((d) => {
    const rows = byCode.filter((r) => r.division === d.division)
    const groups = new Map<string, { label: string; count: number; sum: number; rows: (CofogCode & { count: number; sum: number })[] }>()
    const ownAtDivision = { count: 0, sum: 0 }
    for (const r of rows) {
      if (r.group === '') {
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
      .sort(([, a], [, b]) => b.sum - a.sum)
      .map(([group, g]) => {
        const ownAtGroup = { count: 0, sum: 0 }
        const classNodes: CofogTreeNode[] = []
        for (const r of g.rows) {
          if (r.class === '') {
            ownAtGroup.count += r.count
            ownAtGroup.sum += r.sum
            continue
          }
          classNodes.push({
            key: `${d.division}/${group}/${r.class}`,
            code: r.class,
            label: r.classLabel,
            depth: 'class',
            count: r.count,
            sum: r.sum,
            share: shareOf(r.sum),
            filter: { division: d.division, group, class: r.class },
          })
        }
        classNodes.sort((a, b) => b.sum - a.sum)
        // 「止まった分」は、同じ階層に実際に降りた兄弟（classNodes）がいるときだけ出す。
        // 兄弟が無ければ、子が無いこと自体が「ここで止まった」を意味するので冗長になる
        // （合計は group 自身の count/sum にそのまま残るので、ここで削っても値は変わらない）。
        const children: CofogTreeNode[] = ownAtGroup.count > 0 && classNodes.length > 0
          ? [
              {
                key: `${d.division}/${group}/_own`,
                code: '',
                label: '（中分類までで止まった分）',
                depth: 'class',
                count: ownAtGroup.count,
                sum: ownAtGroup.sum,
                share: shareOf(ownAtGroup.sum),
                filter: null,
              },
              ...classNodes,
            ]
          : classNodes
        return {
          key: `${d.division}/${group}`,
          code: group,
          label: g.label,
          depth: 'group' as const,
          count: g.count,
          sum: g.sum,
          share: shareOf(g.sum),
          filter: { division: d.division, group },
          children: children.length > 0 ? children : undefined,
        }
      })

    // 同様に、division 直下の「止まった分」も group が実在するときだけ出す。
    const children: CofogTreeNode[] = ownAtDivision.count > 0 && groupNodes.length > 0
      ? [
          {
            key: `${d.division}/_own`,
            code: '',
            label: '（大分類までで止まった分）',
            depth: 'group' as const,
            count: ownAtDivision.count,
            sum: ownAtDivision.sum,
            share: shareOf(ownAtDivision.sum),
            filter: null,
          },
          ...groupNodes,
        ]
      : groupNodes

    return {
      key: d.division,
      code: d.division,
      label: d.divisionLabel,
      depth: 'division' as const,
      count: d.count,
      sum: d.sum,
      share: shareOf(d.sum),
      filter: { division: d.division },
      children: children.length > 0 ? children : undefined,
    }
  })
}
