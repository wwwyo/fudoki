import type { CofogDepth } from './detail'

export type CofogCode = {
  division: string
  divisionLabel: string
  group: string
  groupLabel: string
  class: string
  classLabel: string
}

/**
 * どの深さまで降りているか。**割当済みの行だけ**を母数にする
 * （分類不能・対象外に深さは無い）。
 */
export type CofogReach = {
  depth: CofogDepth
  label: string
  /** その深さが**最も深い**到達点である行。深さごとに排他 */
  deepest: { count: number; sum: number }
  /** その深さ**以上**に降りている行（累積）。division は割当済みの全部 */
  reached: { count: number; sum: number }
  /** 割当済みに対する `reached` の割合（0〜1）。**画面で割り算しない**ため生成側が持つ */
  share: { count: number; sum: number }
}

export type Transform = {
  cofogVersion: string
  cofogSource: { name: string; url: string }
  ruleCount: number
  ruleScope: { shared: number; jurisdictionSpecific: number }
  byState: (CofogCode & {
    status: string
    consolidation: string
    count: number
    sum: number
  })[]
  byKan: (CofogCode & {
    fund: string
    kan: string
    status: string
    decidedAtLevel: string
    ruleId: string | null
    sum: number
    basis: string | null
  })[]
  /** 割当済みの金額を COFOG のコードごとに。**降りた先そのもの**を見せる */
  byCode: (CofogCode & { count: number; sum: number })[]
  /** 割当済みの金額を大分類ごとに。帯グラフの構成比はこれで描く */
  byDivision: {
    division: string
    divisionLabel: string
    count: number
    sum: number
  }[]
  cofogReach: CofogReach[]
  /** 割当済みの合計。`cofogReach` と帯グラフの母数 */
  assigned: { count: number; sum: number }
  /** 全状態の合計（割当済み + 分類不能 + 対象外）= 原典の合計 */
  total: { count: number; sum: number }
  /** `total` に対する `assigned` の割合（0〜1）。**画面で割り算しない**ため生成側が持つ */
  assignedShare: { count: number; sum: number }
  byLevel: { level: string; count: number; sum: number }[]
  notAssigned: {
    status: string
    fund: string
    kan: string
    ruleId: string | null
    sum: number
    basis: string | null
  }[]
  consolidationPairs: {
    from: string
    to: string
    eliminated: number
    counterpart: number
    counterpartCount: number
    ok: boolean
  }[]
  consolidationScope: string
}
