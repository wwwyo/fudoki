/**
 * ①予算の報告の型。**層に依存しない部分は `../common` にある。**
 *
 * ここにあるのは会計年度・COFOG・FDP の ColumnType など、予算固有のもの。
 * ②調達（OCDS）③会議録（Popolo）は別の schema を持つので、
 * 巨大な optional の塊にしない。
 */
import type { ReportEnvelope } from '../common'

export type { Check, Edge, Node, Provenance, Stage, Topology } from '../common'

export type Transform = {
  cofogVersion: string
  cofogSource: { name: string; url: string }
  ruleCount: number
  ruleScope: { shared: number; jurisdictionSpecific: number }
  byState: { status: string; division: string; divisionLabel: string; consolidation: string; count: number; sum: number }[]
  byKan: {
    fund: string; kan: string; division: string; status: string
    divisionLabel: string; decidedAtLevel: string; ruleId: string | null; sum: number; basis: string | null
  }[]
  byLevel: { level: string; count: number; sum: number }[]
  notAssigned: { status: string; fund: string; kan: string; ruleId: string | null; sum: number; basis: string | null }[]
  consolidationPairs: { from: string; to: string; eliminated: number; counterpart: number; counterpartCount: number; ok: boolean }[]
  consolidationScope: string
}

export type LevelGroup = {
  direction: string
  items: {
    sourceColumn: string
    distinctCodes: number
    distinctPaths: number
    /** 完全修飾の異なり数がコードより多い = 同じコードが別の親の下で再利用されている */
    codeReusedUnderDifferentParents: boolean
  }[]
}

export type ReportData = ReportEnvelope & {
  meta: ReportEnvelope['meta'] & { fiscalYears: number[] }
  levels: LevelGroup[]
  transform: Transform
  notYetReconciled: { scope: string; reason: string; wouldComeFrom: string; currentEvidence: string }
  /** FDP に無い概念のために自作した ColumnType。**自作は最小限に留めた根拠を出す** */
  customColumnTypes: {
    name: string
    dataType: string
    unique?: boolean
    /** FDP の語彙。コード列に対する名称列であることを示す */
    labelOf?: string
    /** FDP の語彙。階層の親を指す */
    prior?: string
    why: string
  }[]
  /** 2団体目で壊れうる箇所と、次に何を実測すれば確かめられるか */
  portability: { element: string; kind: string; verifyNext: string }[]
  caveats: { topic: string; body: string }[]
  yearSurvey: {
    note: string
    generatedBy: string
    baseline: Record<string, unknown>
    caveat: string
    observations: {
      year: number; label: string; direction: string
      resourceName?: string; url?: string; coverageNote?: string | null
      fetchedAt?: string; status?: number; bytes?: number; sha256?: string
      rows?: number; columns?: string[]
      /** 収録されている会計。年度で範囲が変わる（平成28〜令和元は下水道事業特別会計を含む6会計） */
      funds?: string[]
      amountAllIntegers?: boolean; quotedRows?: number; totalRaw?: number | null
      compatible: boolean | null; basis: string
    }[]
  }
}
