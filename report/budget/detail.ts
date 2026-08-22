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
 */

/** 階層。歳出は目と節の間に「事項」、歳入は節と細々節の間に「細節」を持つ */
export const LEVELS = {
  expenditure: ['fund', 'kan', 'kou', 'moku', 'jikou', 'setsu', 'saisaisetsu'],
  revenue: ['fund', 'kan', 'kou', 'moku', 'setsu', 'saisetsu', 'saisaisetsu'],
} as const

/** 階層の日本語名。**階層の定義と同じ場所に置く** — 離すと片方だけ直る */
export const LEVEL_JA: Record<string, string> = {
  fund: '会計', kan: '款', kou: '項', moku: '目',
  jikou: '事項', setsu: '節', saisetsu: '細節', saisaisetsu: '細々節',
}

/** COFOG 1999 のディビジョン。**ここが唯一の定義**で、SQL に埋める値もここから作る */
export const COFOG_DIVISIONS: Record<string, string> = {
  '01': '一般公共サービス', '02': '防衛', '03': '公共の秩序及び安全', '04': '経済業務',
  '05': '環境保護', '06': '住宅及び地域アメニティ', '07': '保健',
  '08': '娯楽、文化及び宗教', '09': '教育', '10': '社会保護',
}

export type Direction = keyof typeof LEVELS
export type Level<D extends Direction = Direction> = (typeof LEVELS)[D][number]

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
  'cofog_status',
  'cofog_division_code',
  'cofog_consolidation',
  'cofog_decided_at_level',
  'cofog_division_label',
  'cofog_rule_id',
  'cofog_basis',
] as const

export type DetailColumn<D extends Direction = Direction> =
  | (typeof DETAIL_BASE_COLUMNS)[number]
  | LevelColumn<Level<D>>

/** 明細の1行。**宣言に無い列を読むとコンパイルが落ちる** */
export type DetailRow<D extends Direction = Direction> = Record<DetailColumn<D>, string>

/** 列指向で運ぶ。行ごとにキーを繰り返すとファイルの大半が列名になる */
export type DetailTable<D extends Direction = Direction> = {
  columns: DetailColumn<D>[]
  rows: string[][]
}

/** その direction で揃っているべき列 */
export function expectedColumns(direction: Direction): string[] {
  return [
    ...DETAIL_BASE_COLUMNS,
    ...LEVELS[direction].flatMap((l) => [`${l}_code`, `${l}_label`, `${l}_source`]),
  ]
}

/**
 * 生成側の実行時検査。**宣言した列が欠けていたら落とす。**
 * 画面が黙って空になるより、生成が止まるほうがよい。
 */
export function assertDetailColumns(direction: Direction, columns: string[]): void {
  const missing = expectedColumns(direction).filter((c) => !columns.includes(c))
  if (missing.length > 0) {
    throw new Error(
      `明細（${direction}）に宣言した列が無い: ${missing.join(', ')}\n` +
        `report/budget/detail.ts の宣言か、配布物・join のどちらかが実装とずれている`,
    )
  }
}

/**
 * 明細の値を読む。
 *
 * `DetailColumn<D>` は `DetailRow<D>` のキーそのものだが、`D` が generic のままだと
 * TypeScript は index 可能だと判断できない。**その1点だけをここで吸収する。**
 * 呼ぶ側は列名を型で検査されるので、宣言に無い列を渡せばコンパイルが落ちる。
 */
export function cell<D extends Direction>(row: DetailRow<D>, column: DetailColumn<D>): string {
  return (row as Record<string, string>)[column] ?? ''
}

/** 階層の値を読む。`level` がその direction に存在しなければコンパイルが落ちる */
export function levelCell<D extends Direction>(
  row: DetailRow<D>,
  level: Level<D>,
  part: 'code' | 'label' | 'source',
): string {
  return (row as Record<string, string>)[`${level}_${part}`] ?? ''
}
