/**
 * ①予算の報告の型。**層に依存しない部分は `../common` にある。**
 *
 * ここにあるのは会計年度・COFOG・FDP の ColumnType など、予算固有のもの。
 * ②調達（OCDS）③会議録（Popolo）は別の schema を持つので、
 * 巨大な optional の塊にしない。
 */
import type { Provenance, ReportEnvelope } from '../common'
import type { Direction, Level } from '@fudoki/fiscal/detail'

export type { DocumentKind } from '../common'
export { DOCUMENT_KINDS } from '../common'

export type {
  CanonicalFetch,
  Check,
  CheckAttribution,
  Edge,
  Node,
  ProjectNamesExtract,
  Provenance,
  RevenueAccountsExtract,
  Stage,
  StatementExtract,
  Topology,
} from '../common'
export { extractedKindOf, isCanonicalFetch } from '../common'
// 行数の集計（団体 × 年度へのグルーピング・合算）は lineage.ts の1箇所で終わらせてあり、
// 画面側の nodeRows はその結果から選ぶだけ
export { nodeRows } from '../common'

/**
 * COFOG のコード（`04.5.1`）とその分解。**規則が決めた粒度までしか埋まらない。**
 * ⚠️ **`group` / `class` が空なのは「該当が無い」ではなく「まだ降りていない」。**
 * 款の名称だけで決まる規則（総務費 → 01）は division 止まりが正しく、
 * group を埋めるには項や目まで下げる判断が要る。
 */
export type { CofogCode, CofogReach, Transform } from '@fudoki/fiscal/types'
import type { Transform } from '@fudoki/fiscal/types'

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
    /** `named / inSourceScope`。**出所の無い年度は null**（0% ではない） */ shareInScope:
      number | null
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

/**
 * 原典の金額列の宣言1件。**正本は `dbt/dbt_project.yml` の `fiscal_amounts`**。
 * 「今見ている行の金額が何の単位か」を画面が言えるように、生成側がそのまま運ぶ。
 * 年度で割れる団体（多摩市は年度で単位が変わる）では `years` で範囲を持つ。
 */
export type AmountDecl = {
  /** 原典の列名 */
  name: string
  /** 宣言の出所（dbt_project.yml / 証跡の source_amount_unit / 注意点） */
  source: 'dbt_project' | 'source_amount_unit' | 'caveat'
  /** 原典での単位（「円」「千円」など） */
  unit: string
  /** 円へ換算する倍率 */
  multiplier: number
  phase: string
  phaseLabel: string
  /** 宣言が効く年度。null = 全年度 */
  years: number[] | null
}

/** 列の意味。`title` は短い表題（款コード など）、`description` は読み方の注意を含む説明 */
export type ColDoc = { title?: string; description?: string }

export type ReportData = ReportEnvelope & {
  meta: ReportEnvelope['meta'] & { fiscalYears: number[] }
  /**
   * 明細の階層。**正本は dbt_project.yml の `fiscal_levels`** で、生成側が読んで載せる。
   * 画面は階層名を直書きせず、これを回す（団体ごとに並びが違うため）。
   */
  detailLevels: { direction: Direction; levels: Level[] }[]
  levels: LevelGroup[]
  /** 年度 × direction ごとの収録の状況。**年度で並べ替えて出す** */
  coverage: YearCoverage[]
  transform: Transform
  notYetReconciled: {
    scope: string
    reason: string
    wouldComeFrom: string
    currentEvidence: string
  }
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
   * 列名 → 意味。**正本は配布物の descriptor（datapackage.json）と dbt の列記述**。
   * `resources` はリソース名でスコープする — 同じ列名でも歳出と歳入で意味が違う
   * （`saisetsu_code`）ので、配布物側はリソース単位でしか引けない。
   * `canonical` は dbt manifest の列記述に、配布物語彙のうち全リソースで意味が
   * 一意なものを併せたもの。正規化・判断の表は配布物と同じ列語彙を使うので、
   * こちらで引くと `kan_code` 等の意味が途中段でも出る。
   */
  columnDocs: {
    /** 配布物のリソース名 → 列名 → 説明 */
    resources: Record<string, Record<string, ColDoc>>
    /** リソースに属さない表（取り込み・正規化・判断）での列名 → 説明 */
    canonical: Record<string, ColDoc>
  }
  /**
   * `api` は budget-api の jurisdiction 応答に載せるものだけ true にする。
   * 基準: データ（enum・数値・構造）から見えず、API 利用者の解釈を変えるもの。
   * 構造が既に語っている事実、fudoki 側で吸収済みの経緯、repo の再現性の話は載せない
   * （報告=ダッシュボードには全量を出す）。
   *
   * `body` の書式: 空行で段落を分け、`- ` で始まる段落は1行1項目の箇条書き、
   * `**強調**` と `` `コード` `` が使える（md ではなくこの3つだけ）。
   */
  caveats: {
    topic: string
    body: string
    category: CaveatCategory
    api?: boolean
  }[]
  /**
   * 原典の金額列と単位の宣言（direction ごと）。
   * 「今見ている行の単位」を画面が言うためのもの。年度・予算段階で単位が変わる
   * 団体は宣言が年度で割れている。
   */
  amounts: Record<Direction, AmountDecl[]>
  /**
   * 正本の取り込み以外の証跡（PDF から起こした補助表 — 狛江市の事業名・歳入科目名）。
   * **団体の `raw/jurisdiction=<code>/` の外に置かれる**ので `ingestion` には来ない。
   * 抽出物の原典ノードの詳細を出すために運ぶ。
   */
  supplements: Provenance[]
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
