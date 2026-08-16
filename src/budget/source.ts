/**
 * # 予算レイヤの取得元定義
 *
 * 「どの自治体の、どの年度の、どのリソースを取るか」だけをここに置く。
 * 変換規則は持たない（それは columns.ts / cofog.ts の役割）。
 *
 * ## なぜ URL を直書きせず CKAN から解決するか
 *
 * リソース URL（`attach_74103_8.csv`）は自治体側の CMS が振る内部番号で、
 * 資料の差し替えで動く。一方 CKAN のデータセット名とリソース名は安定している。
 * **年度の唯一の出所がリソース名**（`令和６年度予算データ（歳出）`）でもあるので、
 * URL だけを持つと年度を解決する術がなくなる。
 *
 * @see src/budget/columns.ts 原典の列と ColumnType の対応
 */

/** 東京都オープンデータカタログ（CKAN）の package_search */
export const CKAN_ENDPOINT = 'https://catalog.data.metro.tokyo.lg.jp/api/3/action/package_search'

/** 歳出か歳入か。FDP の `direction` にそのまま入る値 */
export type Direction = 'expenditure' | 'revenue'

/**
 * 予算段階。FDP の `phase:id` に入る。
 *
 * 三鷹市の当該データは当初予算のみで、補正後の値を持たない。
 * 確認できない年度は収録しない（Design Doc「異常時の扱い」）。
 */
export type PhaseId = 'approved'

export type ResourceSpec = {
  direction: Direction
  /** CKAN のリソース名。年度の唯一の出所でもある */
  resourceName: string
  /** 出力ファイル名の基底。リソース名から導かず固定する（名称が変わっても出力パスを動かさないため） */
  slug: string
}

export type BudgetSource = {
  /** 全国地方公共団体コード */
  jurisdictionCode: string
  jurisdictionName: string
  /** 西暦。令和6年度 = 2024 */
  fiscalYear: number
  /** 原典に現れる和暦表記。リソース名の照合に使う */
  fiscalYearLabel: string
  phase: { id: PhaseId; label: string }
  /** CKAN のデータセット名（`package_search` の `title` と一致） */
  datasetTitle: string
  resources: ResourceSpec[]
  /**
   * 原典の金額の単位。`value` へ入れるときに掛ける倍率。
   * FDP には倍率を表す ColumnType が無いため、円へ正規化したうえで原典の値と単位を別列に残す。
   */
  amountUnit: { label: string; multiplier: number }
  currency: string
  license: { id: string; name: string; url: string }
  /** CC BY が要求する帰属表示 */
  attribution: string
  /** 原典のページ（リソース URL ではなく人が辿れる入口） */
  landingPage: string
  /**
   * 歳出と歳入の合計一致を検算に使ってよいか。
   *
   * **一般の不変条件ではない。** 三鷹市の令和6年度当初予算について、
   * 同一の会計・年度・予算段階・収録範囲で成立することを実測で確認した条件付き検算。
   * 決算・企業会計・補正差分・会計範囲の異なる抽出では成立しない。
   */
  crossCheckExpenditureEqualsRevenue: boolean
  /** リソース名に現れる収録範囲の注記。年度で変わるため記録する */
  coverageNote: string | null
}

/**
 * 三鷹市 令和6年度。
 *
 * 令和2年度以降のリソースには「下水道事業会計除く」の注記があり、
 * 平成28年度から令和元年度には無い。**年度を増やすときは注記も年度ごとに持つ**
 * （会計範囲が違うものを同じ収録範囲として並べると経年比較が壊れる）。
 */
export const MITAKA_FY2024: BudgetSource = {
  jurisdictionCode: '132047',
  jurisdictionName: '三鷹市',
  fiscalYear: 2024,
  fiscalYearLabel: '令和６年度',
  phase: { id: 'approved', label: '当初予算' },
  datasetTitle: '【予算・決算】予算情報',
  resources: [
    { direction: 'expenditure', resourceName: '令和６年度予算データ（歳出）※下水道事業会計除く', slug: 'expenditure' },
    { direction: 'revenue', resourceName: '令和６年度予算データ（歳入）※下水道事業会計除く', slug: 'revenue' },
  ],
  amountUnit: { label: '千円', multiplier: 1000 },
  currency: 'JPY',
  license: { id: 'CC-BY-4.0', name: 'Creative Commons Attribution 4.0', url: 'https://creativecommons.org/licenses/by/4.0/' },
  attribution: '三鷹市「令和6年度予算データ」（東京都オープンデータカタログサイト）',
  landingPage: 'https://www.city.mitaka.lg.jp/c_service/074/',
  crossCheckExpenditureEqualsRevenue: true,
  coverageNote: '下水道事業会計除く',
}

// 突合に使う公表値は src/budget/published/mitaka-2024.ts にある（資料そのものと1対1で対応させるため、
// 取得元の設定とは分けて置く）。
