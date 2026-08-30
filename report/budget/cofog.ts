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

export function cofogGranularity(byState: StateRow[]):
  Pick<Transform, 'byCode' | 'byDivision' | 'cofogReach' | 'assigned' | 'total' | 'assignedShare'> {
  const total = byState.reduce(add, ZERO)
  const assignedRows = byState.filter((r) => r.status === 'assigned')
  const assigned = assignedRows.reduce(add, ZERO)
  const byCode = foldBy(
    assignedRows.map(({ status: _s, consolidation: _c, ...code }) => code),
    (r) => [r.division, r.group, r.class].join(''),
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
