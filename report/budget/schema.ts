/**
 * ①予算の報告の型。**層に依存しない部分は `../common` にある。**
 *
 * ここにあるのは会計年度・COFOG・FDP の ColumnType など、予算固有のもの。
 * ②調達（OCDS）③会議録（Popolo）は別の schema を持つので、
 * 巨大な optional の塊にしない。
 */
import type { ReportEnvelope } from '../common'
import type { CofogDepth, Direction, Level } from './detail'

export type { Check, Edge, Node, Provenance, Stage, Topology } from '../common'

/**
 * COFOG のコード（`04.5.1`）とその分解。**規則が決めた粒度までしか埋まらない。**
 * ⚠️ **`group` / `class` が空なのは「該当が無い」ではなく「まだ降りていない」。**
 * 款の名称だけで決まる規則（総務費 → 01）は division 止まりが正しく、
 * group を埋めるには項や目まで下げる判断が要る。
 */
export type CofogCode = {
  division: string; divisionLabel: string
  group: string; groupLabel: string
  class: string; classLabel: string
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
  byState: (CofogCode & { status: string; consolidation: string; count: number; sum: number })[]
  byKan: (CofogCode & {
    fund: string; kan: string; status: string
    decidedAtLevel: string; ruleId: string | null; sum: number; basis: string | null
  })[]
  /** 割当済みの金額を COFOG のコードごとに。**降りた先そのもの**を見せる */
  byCode: (CofogCode & { count: number; sum: number })[]
  /** 割当済みの金額をディビジョンごとに。帯グラフの構成比はこれで描く */
  byDivision: { division: string; divisionLabel: string; count: number; sum: number }[]
  cofogReach: CofogReach[]
  /** 割当済みの合計。`cofogReach` と帯グラフの母数 */
  assigned: { count: number; sum: number }
  /** 全状態の合計（割当済み + 分類不能 + 対象外）= 原典の合計 */
  total: { count: number; sum: number }
  /** `total` に対する `assigned` の割合（0〜1）。**画面で割り算しない**ため生成側が持つ */
  assignedShare: { count: number; sum: number }
  byLevel: { level: string; count: number; sum: number }[]
  notAssigned: { status: string; fund: string; kan: string; ruleId: string | null; sum: number; basis: string | null }[]
  consolidationPairs: { from: string; to: string; eliminated: number; counterpart: number; counterpartCount: number; ok: boolean }[]
  consolidationScope: string
}

/**
 * 年度 × direction ごとの収録の状況。**団体単位の集計に埋もれる年度差を出す。**
 *
 * ⚠️ **団体で1つに畳んだ数字では、年度ごとに何が取れているかを見られない。**
 * 実際に狛江市は事業名の PDF が 2020〜2023年度にしか無く、2018〜2019年度は
 * 科目の名称も事業名もゼロだが、6年度を合算した割合にはそれが現れない
 * （名称のある4年度が薄めるだけで、無い年度の存在が消える）。
 * 収録範囲の主張は年度ごとにしか正しく書けないので、年度を軸に持つ。
 *
 * ⚠️ **割合は生成側が持つ**（画面で割り算しない）。分母は指標ごとに違う —
 * 名称は行数、COFOG の到達は割当済みの金額で、混ぜると別の数字になる。
 */
export type YearCoverage = {
  fiscalYear: number
  direction: Direction
  /** core の行数（配布物の行数は段階の数だけ展開されるので別） */
  rows: number
  /** primary と宣言した金額の合計（円） */
  sum: number
  /** 科目の名称がある行の割合（0〜1）。**階層ごとに別**（款だけ解決した年度がある） */
  named: { kan: number; kou: number; moku: number }
  /**
   * COFOG の状況。**歳出だけ**（歳入に COFOG の割当は無いので null）。
   * `groupShare` / `classShare` の分母は割当済みの金額
   * （`transform.cofogReach` と同じ取り方で、年度に切ったもの）。
   */
  cofog: {
    assignedShare: { count: number; sum: number }
    /**
     * 割当済みの金額のうち group / class まで降りているもの。
     * ⚠️ **割当済みが 0 円の年度は null**（降りる先が無いので 0% とは言えない）。
     */
    groupShare: number | null
    classShare: number | null
  } | null
  /**
   * 事業名の充足。**大事業の階層を持つ団体だけ**（無い団体は null）。
   * ⚠️ **母集団は全会計の大事業。** 名称の出所（決算書 PDF の事項別明細）は
   * 一般会計しか載せていないので、`inSourceScope` を併記して
   * 「出所が覆っていない」と「出所は覆っているが当たらなかった」を分けられるようにする。
   */
  projectNames: {
    total: number
    named: number
    /**
     * 出所が覆う大事業の数。**出所（`sources.toml` の `[project_names]`）の宣言が
     * 無い年度は 0** — 突合できた行から逆算すると、資料が無い年度と
     * 資料はあるが1件も当たらなかった年度が同じ数字になる。
     */
    inSourceScope: number
    /** `named / total`（0〜1） */ share: number
    /** `named / inSourceScope`。**出所の無い年度は null**（0% ではない） */ shareInScope: number | null
  } | null
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
  /**
   * 明細の階層。**正本は dbt_project.yml の `budget_levels`** で、生成側が読んで載せる。
   * 画面は階層名を直書きせず、これを回す（団体ごとに並びが違うため）。
   */
  detailLevels: { direction: Direction; levels: Level[] }[]
  levels: LevelGroup[]
  /** 年度 × direction ごとの収録の状況。**年度で並べ替えて出す** */
  coverage: YearCoverage[]
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
  /**
   * `api` は budget-api の jurisdiction 応答に載せるものだけ true にする。
   * 基準: データ（enum・数値・構造）から見えず、API 利用者の解釈を変えるもの。
   * 構造が既に語っている事実、fudoki 側で吸収済みの経緯、repo の再現性の話は載せない
   * （報告=ダッシュボードには全量を出す）。
   */
  caveats: { topic: string; body: string; category: CaveatCategory; api?: boolean }[]
}

/**
 * 注意事項の分類。budget-api が団体ごとに必須4カテゴリ
 * （coverage / phaseSemantics / classification / sourceAndLicense）の存在を検査する。
 * どれにも属さない注意事項は `other`。
 */
export type CaveatCategory =
  | 'coverage'
  | 'phaseSemantics'
  | 'classification'
  | 'sourceAndLicense'
  | 'other'

/**
 * ノード1つの中身の先頭数行。**グラフでノードを選んだときに画面が読む。**
 * 報告本体に入れないのは、13ノード分を常に運ぶと報告が明細と同じ太り方をするため
 * （`apps/web/public/preview/<ノードid>.json` に分けて置き、選んだときだけ取りに行く）。
 */
export type NodePreview = {
  id: string
  columns: string[]
  rows: string[][]
  /** 何行で切ったか。全行は totalRows（グラフのノードと同じ数字）を見る */
  limit: number
  totalRows: number | null
  /** 取得元 CSV のプレビュー（`<ノードid>.origin.json`）だけが持つ */
  title?: string
  sourceUrl?: string
  fetchedAt?: string
}
