/**
 * # 原典の階層と FDP の ColumnType の対応
 *
 * 出力スキーマそのものなので、変換を書く前にここで固定する。
 *
 * ## 法定の語彙と自治体固有の語彙を分ける
 *
 * 款・項・目・節は地方自治法にもとづく区分で、どの自治体でも同じ語を使う。
 * 目の下の事業階層（三鷹市は「事項」）と、節の下の細分（「細節」「細々節」）は法定ではない。
 * `budget-granularity-profile.ts` と同じ分け方を守り、**固有の語は団体コードごとに宣言する**。
 * 混ぜると、3団体目で新しい呼び名に出会うたびに共有配列へ足すことになり、
 * その語が別団体の無関係な列へ誤ヒットする危険が全団体へ波及する（パーサ設計の原則5）。
 *
 * ## 歳出と歳入で階層の意味が違う
 *
 * 歳出の款・項・目は**目的による区分**、節・細々節は**経済的性質による区分**、事項は事業の候補。
 * 歳入の款・項・目（市税 / 国庫支出金 …）は目的ではなく**財源の区分**なので、
 * `functional-classification` に置くと意味が反転する。FDP の `fin-source` を使う。
 *
 * @see src/schema/budget-granularity-profile.ts 同じ「法定 / 固有」の分け方
 */
import type { Direction } from './source'

/** FDP 1.0.0 の Budget Standard Taxonomy。descriptor の `columnTypes` が指す正準 URL */
export const BUDGET_TAXONOMY_URL = 'https://specs.frictionlessdata.io/taxonomies/fiscal/budgets.json'

/** 地方自治法にもとづく科目区分。全自治体で共通の語 */
export const STATUTORY_LEVELS = ['款', '項', '目', '節'] as const

/**
 * 原典の1階層。原典の1セルが code / label / 原文 の3列へ分かれる。
 */
export type LevelSpec = {
  /** 出力の列名の接頭辞。ASCII に固定する（外部データと join する側が扱えるように） */
  key: string
  /** 原典の列名（連番プレフィックスを除いたもの） */
  sourceColumn: string
  /** 地方自治法にもとづく語か、三鷹市固有の語か */
  vocabulary: 'statutory' | 'jurisdiction-specific'
  /** code 列に与える ColumnType */
  codeType: string
  /** label 列に与える ColumnType。`labelOf` で codeType を指す */
  labelType: string
  /**
   * 同じ親の下でコードが一意か。**実測で埋める。推測しない。**
   *
   * 一意なら「親 + コード」で名称が一意に定まる。一意でないなら定まらないので、
   * その階層ではコードを識別子の構成要素にできない。
   * 検査は宣言と実測を**両方向で**突き合わせる（`false` と宣言したのに実際は一意なら、
   * 宣言が古くなっているか、原典が直された合図なので、どちらも気づきたい）。
   */
  codeUniqueAmongSiblings: boolean
  /**
   * 1セルの先頭に付くコードの桁数。**団体ごとに実測で埋める。**
   *
   * 三鷹市は2桁（`01議会費`）。桁数が違う団体でこの値を直さないと、
   * コードと名称の分離が黙って失敗する（`irregularCells` に積まれるだけで止まらない）。
   */
  codeDigits: number
}

/**
 * 三鷹市の歳出の階層。
 *
 * 事項を `activity:generic:program` に置くのは、事項が事業を表す候補だという判断による。
 * **名称を持つことは、その区分が1つの事業に対応することの証明にならない**（Caveats 1）。
 */
const MITAKA_EXPENDITURE_LEVELS: LevelSpec[] = [
  { key: 'fund', sourceColumn: '会計', vocabulary: 'jurisdiction-specific', codeType: 'fund:code', labelType: 'fund:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'kan', sourceColumn: '款', vocabulary: 'statutory', codeType: 'functional-classification:generic:level1:code', labelType: 'functional-classification:generic:level1:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'kou', sourceColumn: '項', vocabulary: 'statutory', codeType: 'functional-classification:generic:level2:code', labelType: 'functional-classification:generic:level2:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'moku', sourceColumn: '目', vocabulary: 'statutory', codeType: 'functional-classification:generic:level3:code', labelType: 'functional-classification:generic:level3:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'jikou', sourceColumn: '事項', vocabulary: 'jurisdiction-specific', codeType: 'activity:generic:program:code', labelType: 'activity:generic:program:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'setsu', sourceColumn: '節', vocabulary: 'statutory', codeType: 'economic-classification:generic:level1:code', labelType: 'economic-classification:generic:level1:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'saisaisetsu', sourceColumn: '細々節', vocabulary: 'jurisdiction-specific', codeType: 'economic-classification:generic:level2:code', labelType: 'economic-classification:generic:level2:label', codeUniqueAmongSiblings: false, codeDigits: 2 },
]

/**
 * 三鷹市の歳入の階層。
 *
 * ⚠️ **Design Doc は歳入を6階層（会計/款/項/目/節/細節）としていたが、原典は細々節を持つ。**
 * 実測では 821 行中 18 行が細々節を使い、細々節を落とすと識別子が7組衝突する。
 * 資料の記述ではなく実物の列で判定する（パーサ設計の原則3）。
 *
 * ⚠️ `fin-source:generic` は標準では level1〜3 までしか定義がない。
 * level4〜6 は fudoki が同じ命名規則で拡張したもので、`prior` を繋いで順序を保つ。
 * 標準側が後から level4 を別の意味で定義すると衝突する（Caveats 参照）。
 */
const MITAKA_REVENUE_LEVELS: LevelSpec[] = [
  { key: 'fund', sourceColumn: '会計', vocabulary: 'jurisdiction-specific', codeType: 'fund:code', labelType: 'fund:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'kan', sourceColumn: '款', vocabulary: 'statutory', codeType: 'fin-source:generic:level1:code', labelType: 'fin-source:generic:level1:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'kou', sourceColumn: '項', vocabulary: 'statutory', codeType: 'fin-source:generic:level2:code', labelType: 'fin-source:generic:level2:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'moku', sourceColumn: '目', vocabulary: 'statutory', codeType: 'fin-source:generic:level3:code', labelType: 'fin-source:generic:level3:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'setsu', sourceColumn: '節', vocabulary: 'statutory', codeType: 'fin-source:generic:level4:code', labelType: 'fin-source:generic:level4:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'saisetsu', sourceColumn: '細節', vocabulary: 'jurisdiction-specific', codeType: 'fin-source:generic:level5:code', labelType: 'fin-source:generic:level5:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
  { key: 'saisaisetsu', sourceColumn: '細々節', vocabulary: 'jurisdiction-specific', codeType: 'fin-source:generic:level6:code', labelType: 'fin-source:generic:level6:label', codeUniqueAmongSiblings: true, codeDigits: 2 },
]

/** 団体コードごとに宣言する。推測で足さない */
const LEVELS_BY_JURISDICTION: Record<string, Record<Direction, LevelSpec[]>> = {
  '132047': { expenditure: MITAKA_EXPENDITURE_LEVELS, revenue: MITAKA_REVENUE_LEVELS },
}

/**
 * 「その階層が無い」ことを表すセル。**団体ごとに宣言する。**
 *
 * 三鷹市の歳入は細々節を持たない行を `0` で埋める（821 行中 803 行）。
 * これを不正なセルとして扱うと報告が 803 件のノイズで埋まり、
 * 本当に想定外のセルが埋もれる。逆に空文字へ潰すと原文へ戻せなくなるので、
 * **原文は残したまま「階層なし」として数える**。
 */
const ABSENT_LEVEL_MARKERS: Record<string, readonly string[]> = {
  '132047': ['0'],
}

export function absentLevelMarkers(jurisdictionCode: string): readonly string[] {
  return ABSENT_LEVEL_MARKERS[jurisdictionCode] ?? []
}

export function levelsFor(jurisdictionCode: string, direction: Direction): LevelSpec[] {
  const byDirection = LEVELS_BY_JURISDICTION[jurisdictionCode]
  if (!byDirection) throw new Error(`団体コード ${jurisdictionCode} の階層が宣言されていない。src/budget/columns.ts へ実測にもとづいて足すこと`)
  return byDirection[direction]
}

/** 原典の金額列。歳出も歳入も末尾1列 */
export const AMOUNT_COLUMN = '予算額'

/**
 * 標準の taxonomy に無く、fudoki が定義した ColumnType。
 * descriptor へインラインで載せ、パイプライン報告にも一覧を出す。
 */
export const CUSTOM_COLUMN_TYPES: { name: string; dataType: string; unique?: boolean; labelOf?: string; prior?: string; why: string }[] = [
  {
    name: 'fund:code',
    dataType: 'string',
    unique: true,
    why: '会計（一般会計・各特別会計）。administrative-classification は資金管理の責任を負う組織単位を指すもので、会計は資金の区分であり別概念。標準に該当する列型が無い',
  },
  { name: 'fund:label', dataType: 'string', labelOf: 'fund:code', why: '会計の表示名' },

  // fin-source の拡張。標準は level3 まで
  { name: 'fin-source:generic:level4:code', dataType: 'string', unique: true, prior: 'fin-source:generic:level3:code', why: '歳入の節。標準の fin-source は level3 までしか定義が無いため同じ命名規則で拡張した' },
  { name: 'fin-source:generic:level4:label', dataType: 'string', labelOf: 'fin-source:generic:level4:code', why: '歳入の節の表示名' },
  { name: 'fin-source:generic:level5:code', dataType: 'string', unique: true, prior: 'fin-source:generic:level4:code', why: '歳入の細節' },
  { name: 'fin-source:generic:level5:label', dataType: 'string', labelOf: 'fin-source:generic:level5:code', why: '歳入の細節の表示名' },
  { name: 'fin-source:generic:level6:code', dataType: 'string', unique: true, prior: 'fin-source:generic:level5:code', why: '歳入の細々節' },
  { name: 'fin-source:generic:level6:label', dataType: 'string', labelOf: 'fin-source:generic:level6:code', why: '歳入の細々節の表示名' },

  {
    name: 'fudoki:jurisdiction:code',
    dataType: 'string',
    unique: true,
    why: '全国地方公共団体コード。外部データとの接続キー。FDP の geo:* は住所や地理コードを指すもので、行政主体の識別子ではない',
  },
  { name: 'fudoki:jurisdiction:label', dataType: 'string', labelOf: 'fudoki:jurisdiction:code', why: '自治体名' },
  {
    name: 'fudoki:source:cell',
    dataType: 'string',
    why: 'code と label へ分ける前の原典のセル。先頭のゼロや全角数字といった表記を保ち、code + label を連結して原文に戻ることを検証に使う',
  },
  { name: 'fudoki:source:amount', dataType: 'number', why: '原典の金額。円へ正規化する前の値' },
  { name: 'fudoki:source:amount-unit', dataType: 'string', why: '原典の金額の単位。FDP に倍率を表す ColumnType が無いため別列に残す' },
  { name: 'fudoki:source:row', dataType: 'integer', why: '原典の物理行番号。特定のスナップショット内でのみ意味を持つ証跡で、外部が参照する識別子ではない' },
  { name: 'fudoki:hierarchy-path', dataType: 'string', why: '階層のコードを連結した可読なパス。コードは兄弟間で一意とは限らないので識別子には使わない' },

  // Transform（派生）だけが持つ列
  { name: 'fudoki:cofog:status', dataType: 'string', why: '分類の軸。assigned / unclassifiable / out-of-scope。分類できなかったものと、そもそも分類の対象でないものを区別する' },
  { name: 'fudoki:cofog:consolidation', dataType: 'string', why: '連結の軸。retained / eliminated。分類の軸とは別の問いなので1つの状態に畳まない' },
  { name: 'fudoki:cofog:counterpart-id', dataType: 'string', why: '消去する行の相手側 budget-line-id' },
  { name: 'fudoki:cofog:basis', dataType: 'string', why: '割り当ての根拠。割当済みと未分類のいずれについても残す' },
  { name: 'fudoki:cofog:decided-at-level', dataType: 'string', why: '款・項・目・事項のどの単位で割り当てが決まったか' },
]
