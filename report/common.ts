/**
 * 層に依存しない報告の型。①予算・②調達・③会議録で共通。
 *
 * **画面が読む契約はここが正本**で、生成側（各層の build.ts）がこの形で出す。
 *
 * 生成側と画面が同じ型を見るので、食い違いはコンパイラが捕まえる。
 */

/** 段。**dbt のモデルの置き場がそのまま段になる**（report/build.py の STAGES） */
export type Stage = {
  id: 'origin' | 'ingestion' | 'staging' | 'core' | 'package'
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
  kind: 'model' | 'source' | 'seed' | 'origin'
  /**
   * どの団体のノードか。null は団体をまたぐ共有ノード（規則表・core）。
   * **生成側が1箇所で付ける** — 画面が id の命名規則を正規表現で推定すると、
   * id の形式を変えたとき絞り込みが黙って壊れる
   */
  jurisdictionCode: string | null
  stage: Stage['id']
  rows: number | null
  description: string
  /** このノード自身が判断を持ち込むか（規則を適用する core のモデルと、判断を宣言した seed） */
  introducesJudgment: boolean
  /**
   * このノードのデータが判断を含むか。**上流から伝播する。**
   *
   * 2つを分けないと、COFOG を含む派生の配布物が「判断なし」と表示され、
   * 公表資料の書き写しが「判断あり」と表示される（実際にそうなっていた）。
   * 画面が説明している不変条件そのものを、画面が誤って伝えることになる。
   */
  containsJudgment: boolean
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

/** 事業名の抽出器（`extract_projects.py`）の要約 */
export type ProjectNamesExtract = {
  kind: 'project-names'
  projects: number
  moku: number
  totalThousandYen: number
}

/** 事項別明細書の抽出器（`extract_statement.py`）の要約 */
export type StatementExtract = {
  kind: 'statement'
  leaves: number
  moku: number
  total: number
}

/**
 * どちらの抽出器の要約かを、証跡が名乗る抽出器のパスから決める。
 * ⚠️ **形（どのキーがあるか）で判定しない。** 項目が増えたときに黙って別の枝へ落ちる。
 */
export function extractedKindOf(p: Provenance): 'project-names' | 'statement' | null {
  if (!p.extracted) return null
  if (p.extractor?.includes('extract_statement')) return 'statement'
  return 'project-names'
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
  /** ⚠️ **PDF を原典とする取得元は持たない**（テキストの文字コードという概念が無い） */
  encoding?: string
  header: string[]
  rows: number
  roundtrip_verified: boolean
  /** 抽出した取得元だけが持つ。`ingestion/budget/extract_*.py@<版>` */
  extractor?: string
  /**
   * PDF から起こした取得元だけが持つ、抽出の要約（原典と1対1ではない）。
   *
   * ⚠️ **抽出器ごとに項目が違うので、全部を任意にして1つの形へ潰さない。**
   * 潰すと「どの抽出器由来か」を型が何も言わなくなり、事項別明細書の証跡を
   * 事業名の証跡として読むコードがコンパイルを通ってしまう（`projects` が
   * 常に undefined になり、黙って 0 になる）。読む側は `kind` で分岐すること。
   * ⚠️ **判別子は証跡に無い。** 抽出器が書いた `extractor` のパスから読む側が導く
   * （`extractedKindOf`）。証跡に持たせると、既に commit 済みの取得物を作り直す必要が出る。
   */
  extracted?: ProjectNamesExtract | StatementExtract
}


/** どの層の報告でも共通の外枠 */
export type ReportEnvelope = {
  meta: {
    jurisdictionCode: string
    jurisdictionName: string
    phase: { id: string; label: string }
    license: { id: string; url: string }
    attribution: string
    landingPage: string
    /** 実行時刻ではなく原典の取得時刻。回すたびに差分が出ないようにする */
    generatedAt: string
  }
  summary: {
    total: number; passed: number; failed: number; warned: number
    /**
     * staging → 配布物で行が失われていないか。**判定は生成側で行う** —
     * 配布物は1行に複数の金額（狛江市は予算現額・執行済額など3つ）を展開するので、
     * stg と pkg の行数の単純比較は多金額の団体で必ず「不一致」と嘘をつく。
     * 期待値（stg 行数 × 金額の数）は dbt_project.yml の宣言を知る生成側にしか計算できない
     */
    rowsPreserved: boolean
  }
  topology: Topology
  ingestion: Provenance[]
  checks: Check[]
}
