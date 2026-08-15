/**
 * # 予算資料の粒度プロファイル
 *
 * 自治体が公開する予算・決算 CSV が、どの粒度まで届いているかを**列構成から**判定する。
 * データセット名では判定しない（パーサ設計の原則3）。
 *
 * ## 法定の語彙と自治体固有の語彙を分ける
 *
 * 款・項・目・節は地方自治法にもとづく区分で、どの自治体でも同じ語を使う。
 * 一方、目の下に置く事業階層の呼び名は法定ではない。
 * 三鷹市は「事項」、狛江市は「大事業 / 中事業 / 小事業」と、団体ごとに違う。
 *
 * **この2つを1つの共有配列に混ぜてはいけない**（パーサ設計の原則5「例外は一般化せず、その対象に閉じる」）。
 * 混ぜると、3団体目で新しい呼び名に出会うたびに共有配列へ足すことになり、
 * その語が別団体の無関係な列（「事業者名」など）へ誤ヒットする危険が全団体へ波及する。
 *
 * そこで事業階層の列名は**団体コードごとに宣言**し、未知の団体にだけ推定を当てる。
 * 判定結果には `basis` を付けて、宣言によるものか推定によるものかを区別する。
 *
 * @see src/schema/tokyo-municipal-bulletin-profile.ts 同じ「列構成で判定する」型の先例
 */

/** 到達した粒度。① が「目まで届いているか」だけが本質的な区別 */
export type Granularity = 'project' | 'account-item' | 'category' | 'indicator' | 'unchecked'

/** 判定の根拠。宣言済みの団体か、未知の団体への推定か */
export type Basis = 'declared' | 'inferred'

/** 深いほど大きい。`unchecked` は順序比較の対象にしない */
export const GRANULARITY_RANK: Record<Exclude<Granularity, 'unchecked'>, number> = {
  project: 4,
  'account-item': 3,
  category: 2,
  indicator: 1,
}

/** 地方自治法にもとづく科目区分。全自治体で共通の語 */
export const STATUTORY_LEVELS = ['款', '項', '目', '節'] as const

/**
 * 事業階層の列名。**団体コードごとに宣言する**。
 * 実測で確認した団体だけをここに書く。推測で足さない。
 */
export const ACTIVITY_COLUMNS: Record<string, readonly string[]> = {
  '132047': ['事項'], // 三鷹市
  '132195': ['大事業', '中事業', '小事業'], // 狛江市
}

/** 未宣言の団体に当てる推定用。確定ではないので判定に `basis: 'inferred'` を付ける */
const ACTIVITY_HINTS = ['事業', '事項', '施策'] as const
/** 事業階層ではないのに上の推定に当たる列 */
const NOT_ACTIVITY = ['事業者', '事業所', '事業年度'] as const

const CATEGORY_AXES = ['目的別', '性質別'] as const
const INDICATORS = ['比率', '指標', '財政力', '経常収支', '将来負担'] as const
const AMOUNTS = ['予算額', '決算額', '金額', '予算計', '執行', '額'] as const

/** 表題に含まれれば予算資料の候補とみなす語。CKAN の全文検索が拾う無関係な資料を落とす */
export const RELEVANT_TITLE_WORDS = ['予算', '決算', '歳出', '財政'] as const

/** 歳出か歳入か。歳出の粒度を測るのが目的なので、歳入を歳出の代表にしない */
export type Direction = 'expenditure' | 'revenue' | 'unknown'

/** 歳入と歳出はデータセット名かリソース名にしか書かれていない */
export function detectDirection(title: string): Direction {
  const rev = title.includes('歳入')
  const exp = title.includes('歳出')
  if (exp && !rev) return 'expenditure'
  if (rev && !exp) return 'revenue'
  return 'unknown'
}

/** 列名の連番プレフィックスと単位の括弧を外す（三鷹は `04目`、狛江は `予算額(円)`） */
export function normalizeColumn(c: string): string {
  return c
    .replace(/^[0-9０-９]+[._\-\s]*/, '')
    .replace(/[（(].*?[）)]/g, '')
    .trim()
}

export type GranularityResult = { granularity: Granularity; basis: Basis; hits: string[] }

/**
 * 列構成から粒度を判定する。
 *
 * 判定は深い順に見て最初に当たったものを返す。
 * 事業階層は団体コードで宣言されていればその列名だけを見て、無ければ推定へ落とす。
 */
export function classifyGranularity(header: readonly string[], jurisdictionCode: string): GranularityResult {
  const cols = header.map(normalizeColumn)
  const joined = cols.join('|')
  const hasAmount = AMOUNTS.some((k) => joined.includes(k))
  const levels = STATUTORY_LEVELS.filter((k) => cols.includes(k))
  const reachesMoku = levels.includes('目')

  const declared = ACTIVITY_COLUMNS[jurisdictionCode]
  const basis: Basis = declared ? 'declared' : 'inferred'
  const activity = declared
    ? cols.filter((c) => declared.includes(c))
    : cols.filter((c) => ACTIVITY_HINTS.some((k) => c.includes(k)) && !NOT_ACTIVITY.some((n) => c.includes(n)))

  const rules: { granularity: Granularity; when: boolean; hits: string[] }[] = [
    { granularity: 'project', when: activity.length > 0 && reachesMoku && hasAmount, hits: [...activity, ...levels] },
    { granularity: 'account-item', when: reachesMoku && hasAmount, hits: [...levels] },
    {
      granularity: 'category',
      when: (levels.length > 0 || CATEGORY_AXES.some((k) => joined.includes(k))) && hasAmount,
      hits: [...levels],
    },
    { granularity: 'indicator', when: INDICATORS.some((k) => joined.includes(k)), hits: INDICATORS.filter((k) => joined.includes(k)) },
  ]

  const hit = rules.find((r) => r.when)
  return hit ? { granularity: hit.granularity, basis, hits: hit.hits } : { granularity: 'unchecked', basis, hits: [] }
}
