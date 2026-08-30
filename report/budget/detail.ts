/**
 * 明細（画面用の射影）の列の宣言。**生成側と画面側が同じものを見る。**
 *
 * ## なぜ宣言が要るか
 *
 * 以前は `Record<string, string>` で運んでいたので、**存在しない列を読んでも
 * 型検査が通った**。配布物から `*_source` を落としたとき、画面はその列で
 * 階層を絞り込んだままで、明細タブが黙って空になった。
 * 型が効かない場所は、実装を変えた瞬間に壊れる場所でもある。
 *
 * ここを正本にして、
 * - 生成側は**実行時に**「宣言した列が全部あるか」を確かめ、無ければ落ちる
 * - 画面側は**コンパイル時に**列名を検査される
 *
 * ## 階層は宣言から来る。ここには書かない
 *
 * ⚠️ **階層の並びは団体ごとに違う**（三鷹市の歳出は事項、狛江市は大事業・中事業・小事業）。
 * 正本は `dbt/dbt_project.yml` の `budget_levels` で、dbt のモデルも検査もそこを見る。
 * ここに写すと、団体を足したとき片方だけ直る。だから生成側が YAML から読んで
 * 報告（`ReportData.detailLevels`）に載せ、画面はそれを読む。
 *
 * ここに残すのは**型としての階層名の集合**だけ。どの団体がどれを使うかは実行時のデータで、
 * 「宣言に無い階層名を書いたらコンパイルが落ちる」ことだけを型で守る。
 */

/** 階層名の集合。**全団体の和**で、どれを使うかは団体ごとに違う */
export const ALL_LEVELS = [
  'fund', 'kan', 'kou', 'moku',
  // 事業階層。三鷹市は「事項」の1段、狛江市は「大事業・中事業・小事業」の3段
  'jikou', 'daijigyo', 'chujigyo', 'shojigyo',
  'setsu', 'saisetsu', 'saisaisetsu',
] as const

export type Level = (typeof ALL_LEVELS)[number]

/** 階層の日本語名。**階層名の集合と同じ場所に置く** — 離すと片方だけ直る */
export const LEVEL_JA: Record<Level, string> = {
  fund: '会計', kan: '款', kou: '項', moku: '目',
  jikou: '事項', daijigyo: '大事業', chujigyo: '中事業', shojigyo: '小事業',
  setsu: '節', saisetsu: '細節', saisaisetsu: '細々節',
}

/** COFOG 1999 の大分類。**ここが唯一の定義**で、SQL に埋める値もここから作る */
export const COFOG_DIVISIONS: Record<string, string> = {
  '01': '一般公共サービス', '02': '防衛', '03': '公共の秩序及び安全', '04': '経済業務',
  '05': '環境保護', '06': '住宅及び地域アメニティ', '07': '保健',
  '08': '娯楽、文化及び宗教', '09': '教育', '10': '社会保護',
}

/**
 * COFOG の中分類（`04.5`）と小分類（`04.5.1`）の名称。
 *
 * ⚠️ **規則が使うコードだけを持つ。** COFOG 1999 の全 69 中分類・109 小分類を写すと、
 * 使っていない大半が検証されないまま増える。規則が新しいコードを使ったら
 * `cofogLabel` が落ちるので、黙って名称なしで配られることはない。
 *
 * ⚠️ **小分類を足したらその親の中分類も要る。** `04.1.2` は
 * 04.1（一般経済・商業・労働関係）の下にあり、画面は division → group → class の
 * 連なりで見せるため、途中が欠けると「まだ降りていない」と区別がつかなくなる。
 */
export const COFOG_GROUPS: Record<string, string> = {
  '01.1': '立法機関及び行政機関、財政・財務、対外関係',
  '01.7': '公債取引',
  '03.2': '消防サービス',
  '04.1': '一般経済・商業・労働関係',
  '04.2': '農業、林業、漁業及び狩猟',
  '04.5': '運輸',
  '04.7': 'その他の産業',
  '05.1': '廃棄物管理',
  '05.2': '排水管理',
  '05.4': '生物多様性及び景観の保護',
  '06.1': '住宅開発',
  '06.2': '地域開発',
  '08.1': 'レクリエーション及びスポーツのサービス',
  '08.2': '文化サービス',
  '09.1': '就学前教育及び初等教育',
  '09.2': '中等教育',
  '09.5': '水準が定義できない教育',
  '09.6': '教育に付帯するサービス',
  '09.8': '他に分類されない教育',
  '10.2': '高齢',
}

export const COFOG_CLASSES: Record<string, string> = {
  '04.1.2': '一般労働業務',
  '04.5.1': '道路交通',
}

/** COFOG の深さ。`cofog_code` の段数がそのまま到達した深さになる */
export const COFOG_DEPTHS = ['division', 'group', 'class'] as const
export type CofogDepth = (typeof COFOG_DEPTHS)[number]

/** 深さから名称表を引く。**深さの集合と対で置く** — 離すと片方だけ直る */
export const COFOG_NAMES: Record<CofogDepth, Record<string, string>> = {
  division: COFOG_DIVISIONS, group: COFOG_GROUPS, class: COFOG_CLASSES,
}

export const COFOG_DEPTH_JA: Record<CofogDepth, string> = {
  division: '大分類（2桁）', group: '中分類（04.5）', class: '小分類（04.5.1）',
}

/**
 * COFOG コードの名称。**空のコードは空の名称**（「まだ降りていない」を潰さない）。
 * 名称の無いコードは落とす — 規則が新しいコードを使ったら宣言を足すまで気づける。
 */
export function cofogLabel(depth: CofogDepth, code: string): string {
  if (!code) return ''
  const label = COFOG_NAMES[depth][code]
  if (label === undefined) {
    throw new Error(
      `COFOG ${depth} ${code} の名称が report/budget/detail.ts に無い。` +
        `規則（dbt/seeds/budget/cofog_rules.csv）が使うコードは宣言が要る`,
    )
  }
  return label
}

export const DIRECTIONS = ['expenditure', 'revenue'] as const
export type Direction = (typeof DIRECTIONS)[number]

/** 階層ごとに3列。`_source` は配布物には無く、code‖label から復元したもの */
type LevelColumn<L extends string> = `${L}_code` | `${L}_label` | `${L}_source`

/** 階層以外の列。正本・派生・規則表を join した結果 */
export const DETAIL_BASE_COLUMNS = [
  'budget_line_id',
  'fiscal_year',
  'source_row',
  'value',
  'source_amount',
  'source_amount_unit',
  'phase_id',
  'phase_label',
  'cofog_status',
  'cofog_division_code',
  'cofog_consolidation',
  'cofog_decided_at_level',
  'cofog_rule_id',
  // ⚠️ **原典に無い列。** 決算資料 PDF から起こして大事業コードへ対応づけた事業名で、
  // 対応づかない事業では空になる（金額 0 の事業と、PDF が無い年度）。
  'project_name',
] as const

export type DetailColumn = (typeof DETAIL_BASE_COLUMNS)[number] | LevelColumn<Level>

/**
 * 明細の1行。**宣言に無い列を読むとコンパイルが落ちる。**
 *
 * ⚠️ **「その団体・その direction に実在する階層か」までは型で守れない。**
 * 階層の並びが実行時のデータ（`ReportData.detailLevels`）から来るので、
 * `daijigyo_code` を三鷹市の行に対して書いてもコンパイルは通る。
 * 実在するかは生成側の `assertDetailColumns` と画面側の読み込み時検査が見る。
 * 画面は階層名を直書きせず、報告が渡した並びだけを回す。
 */
export type DetailRow = Record<DetailColumn, string>

/**
 * 列指向で運ぶ。行ごとにキーを繰り返すとファイルの大半が列名になる。
 *
 * ⚠️ **異なり数の少ない列を行に複製しない。**
 * 割当の根拠（`cofog_basis`）を行へ入れていたとき、狛江市の歳出の明細 23.7 MB のうち
 * **7.0 MB がこの1列**だった（異なり値は19個で、`cofog_rule_id` が全行にあるので情報量はゼロ）。
 * 規則表として1回だけ運び、`cofog_rule_id` で引く。配布物の派生パッケージと同じ形。
 * 大分類名も同じ理由で運ばない（画面が `COFOG_DIVISIONS` を持っている）。
 */
export type DetailTable = {
  columns: DetailColumn[]
  rows: string[][]
  /** 割当の根拠。`cofog_rule_id` → 根拠。行に複製せず1回だけ運ぶ */
  ruleBasis: Record<string, string>
}

/** その (団体, direction) で揃っているべき列。階層は報告が渡した並びから作る */
export function expectedColumns(levels: readonly Level[]): string[] {
  return [
    ...DETAIL_BASE_COLUMNS,
    ...levels.flatMap((l) => [`${l}_code`, `${l}_label`, `${l}_source`]),
  ]
}

/**
 * 生成側の実行時検査。**宣言した列が欠けていたら落とす。**
 * 画面が黙って空になるより、生成が止まるほうがよい。
 */
export function assertDetailColumns(
  code: string, direction: Direction, levels: readonly Level[], columns: string[],
): void {
  const missing = expectedColumns(levels).filter((c) => !columns.includes(c))
  if (missing.length > 0) {
    throw new Error(
      `明細（${code} / ${direction}）に宣言した列が無い: ${missing.join(', ')}\n` +
        `dbt_project.yml の budget_levels か、配布物・join のどちらかが実装とずれている`,
    )
  }
}

/**
 * 明細の値を読む。呼ぶ側は列名を型で検査されるので、宣言に無い列を渡せばコンパイルが落ちる。
 */
export function cell(row: DetailRow, column: DetailColumn): string {
  return row[column] ?? ''
}

/** 割当の根拠を引く。行には入っておらず、規則表から引く */
export function basisOf(table: DetailTable, row: DetailRow): string {
  return table.ruleBasis[cell(row, 'cofog_rule_id')] ?? ''
}

/** COFOG 大分類の表示名。行には入っておらず、宣言から引く */
export function divisionLabelOf(row: DetailRow): string {
  return COFOG_DIVISIONS[cell(row, 'cofog_division_code')] ?? ''
}

/** 階層の値を読む。`level` が階層名の集合に無ければコンパイルが落ちる */
export function levelCell(row: DetailRow, level: Level, part: 'code' | 'label' | 'source'): string {
  return (row as Record<string, string>)[`${level}_${part}`] ?? ''
}
