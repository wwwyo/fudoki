/**
 * 報告の型。**画面が読む契約はここが正本**で、`report/build.py` がこの形で出す。
 *
 * 以前はパイプライン本体（TypeScript）から型を取っていたが、パイプラインが
 * Python + dbt へ移ったので契約を画面側に置く。
 * 生成側と食い違うと画面が黙って壊れるので、`report/build.py` は
 * ここに書かれたキーを満たすことを検査で確かめる（`report/test_shape.py`）。
 */

/** 段。**dbt のモデルの置き場がそのまま段になる**（report/build.py の STAGES） */
export type Stage = {
  id: 'ingestion' | 'staging' | 'core' | 'package'
  label: string
  responsibility: string
  excludes: string
  /** fudoki の判断が入る段か。境界はここにある */
  introducesJudgment: boolean
}

/** ノード = dbt のモデル・ソース・seed。手で並べていない */
export type Node = {
  id: string
  label: string
  kind: 'model' | 'source' | 'seed'
  stage: Stage['id']
  rows: number | null
  description: string
  introducesJudgment: boolean
  /** 配布物として書き出されるファイル。package 段のノードだけ持つ */
  artifact: string | null
}

export type Edge = { from: string; to: string; kind: string }

export type Topology = {
  stages: Stage[]
  nodes: Node[]
  edges: Edge[]
  /** 系統の出所。手書きでないことを画面にも出す */
  source: string
}

/** 検査。**紐づけ（binds）も dbt が知っている**（test の depends_on） */
export type Check = {
  name: string
  description: string
  binds: string[]
  ok: boolean
  severity: 'error' | 'warn'
  status: string
  failures: number | null
  detail: string
}

/** 取得の証跡。原典1リソースにつき1件 */
export type Provenance = {
  jurisdiction_code: string
  fiscal_year: number
  direction: string
  resource_name: string
  fiscal_year_basis: string
  request_url: string
  status: number
  bytes: number
  sha256: string
  fetched_at: string
  encoding: string
  header: string[]
  rows: number
  roundtrip_verified: boolean
}

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

export type ReportData = {
  meta: {
    jurisdictionCode: string
    jurisdictionName: string
    fiscalYears: number[]
    phase: { id: string; label: string }
    license: { id: string; url: string }
    attribution: string
    landingPage: string
    generatedAt: string
  }
  summary: { total: number; passed: number; failed: number; warned: number }
  topology: Topology
  ingestion: Provenance[]
  levels: LevelGroup[]
  transform: Transform
  checks: Check[]
  notYetReconciled: { scope: string; reason: string; wouldComeFrom: string; currentEvidence: string }
  /** FDP に無い概念のために自作した ColumnType。**自作は最小限に留めた根拠を出す** */
  customColumnTypes: { name: string; dataType: string; unique: boolean; why: string }[]
  /** 2団体目で壊れうる箇所と、次に何を実測すれば確かめられるか */
  portability: { element: string; kind: string; verifyNext: string }[]
  caveats: { topic: string; body: string }[]
  yearSurvey: {
    note: string
    generatedBy: string
    baseline: Record<string, unknown>
    caveat: string
    observations: {
      year: number; label: string; direction: string; resourceName: string; url: string
      coverageNote: string | null; rows: number | null; columns: string[]
      /** 収録されている会計。年度で範囲が変わる（平成28〜令和元は下水道事業特別会計を含む6会計） */
      funds: string[] | null
      quotedRows: number; compatible: boolean | null; basis: string
    }[]
  }
}
