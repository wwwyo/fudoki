/**
 * 検証画面（`/pipeline/<団体コード>/`）のローカル・データ口の読み側。
 *
 * 報告（pipeline.json）も行そのもの・PDF の頁画像・語の文字層・
 * 行と頁の対応は dev server の middleware（`vite-plugins/local-data.ts`）だけが
 * 返す — ビルド成果物には載らない。ここで読むエンドポイントはすべて `/local/*`。
 */
import type {
  ColDoc,
  Direction,
  Node,
  Provenance,
  ReportData,
  Stage,
} from '@/lib/pipeline'

/* ---- 段・向き ---- */

export const STAGE_JA: Record<Stage['id'], string> = {
  origin: '原典',
  ingestion: '取り込み',
  staging: '原典別の整形',
  intermediate: '統合・分類',
  marts: '提供用データ',
}

/**
 * 共有リソース（account_map などの規則表・マスタデータ）か。系統図には出さない。
 * 共有の intermediate モデルは jurisdictionCode が null だが `kind === 'model'` なので
 * ここには来ない — それらは「この団体の行数」が `rowsByJurisdiction` で切れる。
 */
export const isRes = (n: Node) => !n.jurisdictionCode && n.kind !== 'model'

/** 系統図で選んだ組（辺の両端のノード id） */
export type Pair = { from: string; to: string }

/**
 * `.origin` ノード id の `.origin` を外したもの。向きの語（expenditure/revenue）を
 * id から拾うためだけに使う — ファイル単位の原典 id（`…doc_<sha>.origin`）は
 * 向きを名乗らないので何も付かず、文書を歳出・歳入が分かち合う場合はそれが正しい
 */
export function srcIdOf(originId: string): string {
  return originId.endsWith('.origin')
    ? originId.slice(0, -'.origin'.length)
    : originId
}

/** ノードの表示名。id が向きを名乗るもの（`…expenditure` など）は末尾に（歳出）を添える。
 * 末尾一致で見るのは、「歳入歳出予算事項別明細書」のように題名の中に両方の字が
 * あっても向きを区別するため（原典ノードは歳出・歳入で同名の文書を指すことがある） */
export function nodeLabel(n: Node): string {
  let l = n.label
  // 補助表のソースは dbt 上の表名が `data` しか名乗らない。親のソース名
  // （raw_<団体>_<種類>）から引き直す — 「data」では図で何のノードか分からない
  if (l === 'data') {
    const m = /\.raw_\d{6}_(.+)\./.exec(n.id)
    if (m) l = m[1]!
  }
  if (/\.(expenditure|revenue)(\.|$)/.test(srcIdOf(n.id))) {
    const d = n.id.includes('expenditure') ? '歳出' : '歳入'
    if (!l.endsWith(`（${d}）`)) l = `${l}（${d}）`
  }
  return l
}

/**
 * そのノードの表で引ける列の意味（`列名 → 説明`）。
 * marts ノードはモデル名でスコープした語彙を使う — 同じ列名でも歳出と歳入で
 * 意味が違う列（`saisetsu_code`）があり、canonical 語彙で一義に説明すると嘘になる。
 * 原典ノードは原典自身の見出しが列名なので語彙は引かない（説明は原典側の責任）。
 */
export function colDocsOf(
  n: Node,
  docs: ReportData['columnDocs']
): Record<string, ColDoc> {
  if (n.stage === 'marts') {
    const res = n.label
    return (res && docs.resources[res]) || {}
  }
  return n.kind === 'origin' ? {} : docs.canonical
}

/**
 * 組（辺）の向き。両端の id から推る — 向きは行の絞り込みと
 * 証跡・金額宣言の選択に使う（向きを持たない系統は null）。
 */
export function edgeDir(from: string, to: string): Direction | null {
  const s = `${from} ${to}`
  if (s.includes('expenditure')) return 'expenditure'
  if (s.includes('revenue')) return 'revenue'
  // 履歴の初回入力は歳出専用。PDF hit と方向を持つ表の鍵を一致させる。
  if (s.includes('_history.') || s.includes('__budget_history') || s.includes('int_fiscal_budget_history')) return 'expenditure'
  return null
}

/* ---- 行データ（/local/rows） ---- */

export type PdfDocMeta = {
  id: string
  code: string
  title: string
  url: string
  sha256: string
  years: number[]
  /** 収録した頁範囲（PDF の頁番号。1 始まり） */
  first: number
  last: number
  /** 文字層が取れたか。OCR だけの原典は false（語の選択・行との対応なし） */
  textLayer: boolean
  /** この文書が原典になっている source ノードの id */
  sources: string[]
}

export type TableRows = {
  kind: 'table'
  columns: string[]
  rows: unknown[][]
  /** 行対応に使う鍵列（source_row / ordinal / pdf_ordinal のうち存在するもの） */
  keyColumn: string | null
  totalRows: number
  /** 行数の上限で打ち切られたか。見えていない行があることを画面が言うための印 */
  truncated?: boolean
  /** 原典ノードだけが持つ、その原典の証跡 */
  provs?: Provenance[]
}

export type PdfRows = {
  kind: 'pdf'
  /** 原典の文書（年度ごとに別ファイルのことがある）。無い = レイヤ未生成 */
  docs: PdfDocMeta[]
  provs: Provenance[]
}

export type NoRows = { kind: 'none'; reason: string }

export type NodeRows = TableRows | PdfRows | NoRows

const rowsCache = new Map<string, Promise<NodeRows>>()

/**
 * fetch + JSON + 恒常キャッシュ。パイプラインを回し直さない限り結果は変わらない。
 * ⚠️ **失敗した promise は残さない** — 一時的な不通をキャッシュに固定すると、
 * 以後そのキーはリロードするまでずっと欠けたままになる。
 */
function cachedJson<T>(
  cache: Map<string, Promise<T>>,
  key: string,
  url: string,
  fallback: (reason: string) => T
): Promise<T> {
  let p = cache.get(key)
  if (!p) {
    p = fetch(url, { cache: 'no-store' })
      .then((r) =>
        r.ok ? (r.json() as Promise<T>) : fallback(`HTTP ${r.status}`)
      )
      .catch((e) => {
        cache.delete(key)
        return fallback(String(e).slice(0, 120))
      })
    cache.set(key, p)
  }
  return p
}

/**
 * ノードの行を取りに行く（団体・年度・向き・ノードで分けてキャッシュ）。
 */
export function loadRows(
  nodeId: string,
  code: string,
  year: number | null,
  dir: Direction | null
): Promise<NodeRows> {
  const q = new URLSearchParams({ node: nodeId, code })
  if (year !== null) q.set('year', String(year))
  if (dir) q.set('dir', dir)
  const key = q.toString()
  return cachedJson(
    rowsCache,
    key,
    `${import.meta.env.BASE_URL}local/rows?${key}`,
    (reason) => ({ kind: 'none', reason })
  )
}

/* ---- 行対応キー ---- */

/**
 * 行対応の鍵空間。鍵は `<空間>|<年度>|<向き>|<値>` — 空間タグを先頭に付けるので
 * 別空間どうし（source_row=5 と ordinal=5 など）が文字列として一致して
 * 誤対応することがない。`<年度>|<向き>` は行が持つ分だけ前置する。
 *
 * 空間:
 * - `sr`   … source_row（原典→取り込み→配布物を貫く行番号。PDF の hit 鍵もこの空間）
 * - `ord`  … ordinal / pdf_ordinal（同じ番号の別名列）
 * - `bli`  … fiscal_line_id（事業行 id。intermediate/marts が共有 — 行番号を持たない
 *            COFOG 割当表などもこれで支出・収入の行と対応が取れる）
 * - `rule` … rule_id / cofog_rule_id（COFOG 規則。ルール側と割当側で列名が
 *            違うだけで同じ値域）
 * - `acct` … fund_code+kan_code+kou_code+moku_code の複合（科目名マスタと
 *            支出・収入の行を「同じ科目の行」として対応させる）
 */
const KEY_COLS: Record<string, 'sr' | 'ord' | 'bli' | 'rule'> = {
  source_row: 'sr',
  ordinal: 'ord',
  pdf_ordinal: 'ord',
  fiscal_line_id: 'bli',
  rule_id: 'rule',
  cofog_rule_id: 'rule',
}
const ACCT_COLS = ['fund_code', 'kan_code', 'kou_code', 'moku_code']

/** 鍵列・年度列・向き列・鍵空間列の位置。行ごとに indexOf を引き直さないよう表ごとに1回だけ引く */
const colCache = new WeakMap<
  TableRows,
  {
    yi: number
    di: number
    /** 鍵空間 → 列 index（その表が持つ分だけ） */
    sp: [string, number][]
    /** acct 複合の列 index（全列あるときだけ） */
    acct: number[] | null
  }
>()
function colInfo(t: TableRows) {
  let c = colCache.get(t)
  if (!c) {
    const sp: [string, number][] = []
    t.columns.forEach((name, i) => {
      const s = KEY_COLS[name]
      if (s) sp.push([s, i])
    })
    const acctIdx = ACCT_COLS.map((n) => t.columns.indexOf(n))
    c = {
      yi: t.columns.includes('fiscal_year')
        ? t.columns.indexOf('fiscal_year')
        : t.columns.indexOf('year'),
      di: t.columns.indexOf('direction'),
      sp,
      acct: acctIdx.every((i) => i >= 0) ? acctIdx : null,
    }
    colCache.set(t, c)
  }
  return c
}

/** その行の年度。`fiscal_year`（staging/intermediate/marts）か `year`（raw の hive 列） */
function rowYear(t: TableRows, row: unknown[]): number | null {
  const { yi } = colInfo(t)
  if (yi < 0) return null
  const y = Number(row[yi])
  return Number.isFinite(y) ? y : null
}

/** その行の向き（`direction` 列を持つ表だけ）。値は expenditure / revenue */
function rowDir(t: TableRows, row: unknown[]): string | null {
  const { di } = colInfo(t)
  if (di < 0) return null
  const v = row[di]
  return v == null ? null : String(v)
}

/**
 * 行が持つ対応キー全て（存在する鍵空間ごとに1つずつ）。鍵が1つも無ければ null。
 * 1行が複数の空間に同時に居られる（例: intermediate の行は `sr` と `bli` を両方持つ）—
 * どれか1つの鍵が一致すれば対応と見なすので、行番号を経由しない対応も拾える。
 *
 * ⚠️ **年度を入れないと年度をまたいで誤対応する。** 鍵番号は年度ごとに振り直される
 * （PDF の行番号・CSV の物理行番号）ので、「全年度」の表示で 2020年の ordinal=5 が
 * 2021年の ordinal=5 と一致したことになってしまう。年度列を持たない表（規則表）は
 * 裸の鍵のまま — 反対側も年度を持たないときだけ一致する。
 *
 * 向きも同じ理屈: 歳出と歳入は別の行番号体系なので、両方向を同時に見せる表示
 * （overview）は `dir` を渡して向き修飾する。`'row'` は行自身の direction 列の
 * 値で修飾する（併合原典の表など、表の中で向きが混ざるもの用）。省略したときは
 * 向き修飾なし — hit 側も同じく無修飾なので一致する。
 */
function rowKeySet(
  t: TableRows,
  row: unknown[],
  ri: number,
  dir?: Direction | 'row'
): Set<string> | null {
  const { sp, acct, yi } = colInfo(t)
  const dataset = String(row[t.columns.indexOf('dataset_id')] ?? '').split(':')
  const d = dir === 'row' ? rowDir(t, row) ?? (dataset.length >= 5 ? dataset[2] : null) : dir
  const y = (yi >= 0 ? rowYear(t, row) : null) ?? (dataset.length >= 5 ? Number(dataset[1]) : null)
  // 修飾は鍵空間ごとに要否が違う:
  // - sr/ord … 行番号は年度・向きで振り直されるので両方修飾する
  // - acct   … 科目複合は年度を持つ表同士で一致させたいので年度だけ
  // - bli/rule … bli は値自体が年度・向きを含み、rule id は共通名 — 修飾すると
  //   年度・向きを持たない表（規則表・COFOG 割当）と永遠に一致しないので付けない
  const value = (name: string) => row[t.columns.indexOf(name)]
  const table = value('table_id') ?? value('resource') ?? (dataset.length === 6 ? dataset[5] : null)
  const edition = value('origin_sha256') ?? value('edition') ?? (table ? dataset[4] : null)
  const scope = table && edition ? `${edition}|${table}` : null
  const q = (space: string, v: unknown) =>
    [
      space,
      space === 'bli' || space === 'rule' ? null : y,
      space === 'sr' || space === 'ord' ? d : null,
      space === 'sr' ? scope : null,
      String(v),
    ]
      .filter((x) => x !== null && x !== undefined)
      .join('|')
  let out: Set<string> | null = null
  let hasSr = false
  for (const [space, i] of sp) {
    const v = row[i]
    if (v == null) continue
    ;(out ??= new Set()).add(q(space, v))
    if (space === 'sr') hasSr = true
  }
  // 科目複合: kan+moku が揃っていないと行の識別子にならない（fund/kou は欠けてよい）
  if (!scope && acct && row[acct[1]!] != null && row[acct[3]!] != null)
    (out ??= new Set()).add(q('acct', acct.map((i) => row[i] ?? '').join(':')))
  // 原典 CSV の行には source_row 列が無い — 物理行番号（ヘッダ=1行目、データは2行目から）を
  // sr 空間の鍵として持つ（stg 側の source_row はこの番号）。provs を持つのは原典だけ。
  // acct 等の別空間の鍵があっても sr が無ければ付ける — それらは行番号の代わりにならない
  if (!hasSr && t.provs) (out ??= new Set()).add(q('sr', ri + 2))
  return out
}

/** 各行の鍵集合（行数分の配列）。表×向き修飾ごとに1回だけ計算して使い回す */
const keySetsCache = new WeakMap<
  TableRows,
  Map<string, (Set<string> | null)[]>
>()
export function rowKeySets(
  t: TableRows,
  dir?: Direction | 'row'
): (Set<string> | null)[] {
  let m = keySetsCache.get(t)
  if (!m) {
    m = new Map()
    keySetsCache.set(t, m)
  }
  const cacheKey = dir ?? ''
  let ks = m.get(cacheKey)
  if (!ks) {
    ks = t.rows.map((r, ri) => rowKeySet(t, r, ri, dir))
    m.set(cacheKey, ks)
  }
  return ks
}

/** 鍵集合どうしに共通の鍵があるか */
export function keysIntersect(
  a: Set<string> | null,
  b: Set<string> | null
): boolean {
  if (!a || !b) return false
  for (const k of a) if (b.has(k)) return true
  return false
}

/** 鍵集合が同じ行を指すか（同じ行の再選択は解除にするトグルの判定用）。
 * 部分集合も「同じ行の再クリック」と見なす — PDF の語・フラッグは行の sr 鍵
 * 1つだけを持つので、それが選ばれた行の集合に含まれていれば解除になる */
export function keysEqual(
  a: Set<string> | null,
  b: Set<string> | null
): boolean {
  if (a === b) return true
  if (!a || !b) return false
  for (const k of b) if (!a.has(k)) return false
  return true
}

/** 修飾キーから表示用の鍵番号を取り出す */
export const bareKey = (k: string) => k.slice(k.lastIndexOf('|') + 1)

/** 対応がある行の修飾キー集合（反対側のバッジ・PDF 側のフラッグに使う） */
export function linkSetOf(t: TableRows, dir?: Direction | 'row'): Set<string> {
  const s = new Set<string>()
  for (const ks of rowKeySets(t, dir)) if (ks) for (const k of ks) s.add(k)
  return s
}

/**
 * 修飾キーを行の direction ごとに分けた集合（向きが混ざる表用 — 併合原典の表）。
 * 向き列を持たない表は `''` にまとまる。
 */
export function linkSetsByDir(t: TableRows): Map<string, Set<string>> {
  const m = new Map<string, Set<string>>()
  const sets = rowKeySets(t, 'row')
  t.rows.forEach((r, ri) => {
    const ks = sets[ri]
    if (!ks) return
    const d = rowDir(t, r) ?? ''
    let s = m.get(d)
    if (!s) m.set(d, (s = new Set()))
    for (const k of ks) s.add(k)
  })
  return m
}

/* ---- PDF レイヤ（/local/pdf/*） ---- */

/** 行キー → 頁内位置。`hits.json` は `{sourceId: {rowKey: {page, box}}}` */
export type PdfHit = { page: number; box: [number, number, number, number] }
export type PdfPageData = {
  w: number
  h: number
  /** [x0, y0, x1, y1, テキスト] */
  words: [number, number, number, number, string][]
}

const hitsCache = new Map<
  string,
  Promise<Record<string, Record<string, PdfHit>>>
>()
const pageCache = new Map<string, Promise<PdfPageData | null>>()

function loadPdfHits(
  docId: string
): Promise<Record<string, Record<string, PdfHit>>> {
  return cachedJson(
    hitsCache,
    docId,
    `${import.meta.env.BASE_URL}local/pdf/${docId}/hits.json`,
    () => ({})
  )
}

export function loadPdfPage(
  docId: string,
  page: number
): Promise<PdfPageData | null> {
  const key = `${docId}/${page}`
  return cachedJson(
    pageCache,
    key,
    `${import.meta.env.BASE_URL}local/pdf/${docId}/p${page}.json`,
    () => null
  )
}

export const pdfPagePng = (docId: string, page: number) =>
  `${import.meta.env.BASE_URL}local/pdf/${docId}/p${page}.png`

/** 修飾キー → 文書と頁内位置。表の行キーと同じく `<年度>|<鍵>` に修飾して衝突を防ぐ */
export type PdfHitLoc = {
  docId: string
  page: number
  box: [number, number, number, number]
}

/**
 * 原典ノードの全文書の hit を1つの対応表へ畳む。
 * ⚠️ **文書は年度ごとに別れうる**ので、hit の鍵は `doc.years[0]` で年度修飾する。
 * 複数年度をまたぐ文書（years が2つ以上）では修飾できないので裸の鍵のままになる
 * — その文書の hit は年度を持つ表の行とは一致しない（誤対応より対応なしのほうがまだ正しい）。
 * `dir` は行の修飾キーと同じ向き修飾 — 歳出・歳入を併せて見せる表示で渡す。
 */
export async function loadHitMap(
  docs: PdfDocMeta[],
  srcId: string,
  dir?: Direction
): Promise<Map<string, PdfHitLoc>> {
  const perDoc = await Promise.all(docs.map((d) => loadPdfHits(d.id)))
  const map = new Map<string, PdfHitLoc>()
  docs.forEach((d, i) => {
    const hits = perDoc[i]?.[srcId]
    if (!hits) return
    const y = d.years.length === 1 ? d.years[0] : null
    for (const [k, h] of Object.entries(hits)) {
      if (!h?.box) continue
      // hit は行番号（source_row 空間）の位置 — 行キーと同じ `sr|` タグを付ける
      map.set(
        ['sr', y, dir, k]
          .filter((v) => v !== null && v !== undefined)
          .join('|'),
        { docId: d.id, page: h.page, box: h.box }
      )
    }
  })
  return map
}
