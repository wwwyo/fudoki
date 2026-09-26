/**
 * 検証画面（`/pipeline/<団体コード>/`）のローカル・データ口の読み側。
 *
 * 報告（pipeline.json）は公開配信物だが、行そのもの・PDF の頁画像・語の文字層・
 * 行と頁の対応は dev server の middleware（`vite-plugins/local-data.ts`）だけが
 * 返す — ビルド成果物には載らない。ここで読むエンドポイントはすべて `/local/*`。
 */
import type { Direction, Node, Provenance, Stage } from '@/lib/pipeline'

/* ---- 段・向き ---- */

export const STAGE_JA: Record<Stage['id'], string> = {
  origin: '原典', ingestion: '取り込み', staging: '正規化', core: '判断', package: '配布物',
}

/**
 * 共有リソース（判断の規則表）か。系統図では段の列ではなく下の別レーンに並べる。
 * 共有の core モデルは jurisdictionCode が null だが `kind === 'model'` なので
 * ここには来ない — それらは「この団体の行数」が `rowsByJurisdiction` で切れる。
 */
export const isRes = (n: Node) => !n.jurisdictionCode && n.kind !== 'model'

/** 系統図で選んだ組（辺の両端のノード id） */
export type Pair = { from: string; to: string }

/** `.origin` ノードから、ぶら下がっている source ノードの id を引く */
export function srcIdOf(originId: string): string {
  return originId.endsWith('.origin') ? originId.slice(0, -'.origin'.length) : originId
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
 * 組（辺）の向き。両端の id から推る — 向きは行の絞り込みと
 * 証跡・金額宣言の選択に使う（向きを持たない系統は null）。
 */
export function edgeDir(from: string, to: string): Direction | null {
  const s = `${from} ${to}`
  if (s.includes('expenditure')) return 'expenditure'
  if (s.includes('revenue')) return 'revenue'
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
function cachedJson<T>(cache: Map<string, Promise<T>>, key: string, url: string, fallback: (reason: string) => T): Promise<T> {
  let p = cache.get(key)
  if (!p) {
    p = fetch(url, { cache: 'no-store' })
      .then((r) => (r.ok ? (r.json() as Promise<T>) : fallback(`HTTP ${r.status}`)))
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
export function loadRows(nodeId: string, code: string, year: number | null, dir: Direction | null): Promise<NodeRows> {
  const q = new URLSearchParams({ node: nodeId, code })
  if (year !== null) q.set('year', String(year))
  if (dir) q.set('dir', dir)
  const key = q.toString()
  return cachedJson(rowsCache, key, `${import.meta.env.BASE_URL}local/rows?${key}`,
    (reason) => ({ kind: 'none', reason }))
}

/* ---- 行対応キー ---- */

/**
 * 行対応の鍵空間。`source_row` と `ordinal`/`pdf_ordinal` は別の番号体系 —
 * `pdf_ordinal` は core が `ordinal` を改名して運んでいるもので、同じ番号を指す。
 * 違う空間どうしで番号が一致しても対応ではないので、空間ごとに分ける。
 */
const KEY_SPACE: Record<string, 'sr' | 'ord'> = { source_row: 'sr', ordinal: 'ord', pdf_ordinal: 'ord' }

export function keySpaceOf(t: TableRows): 'sr' | 'ord' | null {
  return t.keyColumn ? KEY_SPACE[t.keyColumn] : null
}

/** 鍵列・年度列の位置。行ごとに indexOf を引き直さないよう表ごとに1回だけ引く */
const colCache = new WeakMap<TableRows, { ki: number; yi: number }>()
function colInfo(t: TableRows): { ki: number; yi: number } {
  let c = colCache.get(t)
  if (!c) {
    c = {
      ki: t.keyColumn ? t.columns.indexOf(t.keyColumn) : -1,
      yi: t.columns.includes('fiscal_year')
        ? t.columns.indexOf('fiscal_year')
        : t.columns.indexOf('year'),
    }
    colCache.set(t, c)
  }
  return c
}

/** 行の対応キー（鍵列の値そのもの。表示はこれを使う） */
function rowKey(t: TableRows, row: unknown[]): string | null {
  const { ki } = colInfo(t)
  if (ki < 0) return null
  const v = row[ki]
  return v == null ? null : String(v)
}

/** その行の年度。`fiscal_year`（stg/core/配布物）か `year`（raw の hive 列） */
function rowYear(t: TableRows, row: unknown[]): number | null {
  const { yi } = colInfo(t)
  if (yi < 0) return null
  const y = Number(row[yi])
  return Number.isFinite(y) ? y : null
}

/**
 * 対応判定に使う修飾キー = `<年度>|<鍵>`。
 *
 * ⚠️ **年度を入れないと年度をまたいで誤対応する。** 鍵番号は年度ごとに振り直される
 * （PDF の行番号・CSV の物理行番号）ので、「全年度」の表示で 2020年の ordinal=5 が
 * 2021年の ordinal=5 と一致したことになってしまう。年度列を持たない表（規則表）は
 * 裸の鍵のまま — 反対側も年度を持たないときだけ一致する。
 */
function linkKey(t: TableRows, row: unknown[]): string | null {
  const k = rowKey(t, row)
  if (k === null) return null
  const y = rowYear(t, row)
  return y === null ? k : `${y}|${k}`
}

/** 各行の修飾キー（行数分の配列）。表ごとに1回だけ計算して使い回す */
const linkKeysCache = new WeakMap<TableRows, (string | null)[]>()
export function linkKeys(t: TableRows): (string | null)[] {
  let ks = linkKeysCache.get(t)
  if (!ks) {
    ks = t.rows.map((r) => linkKey(t, r))
    linkKeysCache.set(t, ks)
  }
  return ks
}

/** 修飾キーから表示用の鍵番号を取り出す */
export const bareKey = (k: string) => (k.includes('|') ? k.slice(k.indexOf('|') + 1) : k)

/** 対応がある行の修飾キー集合（反対側のバッジ・PDF 側のフラッグに使う） */
export function linkSetOf(t: TableRows): Set<string> {
  const s = new Set<string>()
  for (const k of linkKeys(t)) if (k !== null) s.add(k)
  return s
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

const hitsCache = new Map<string, Promise<Record<string, Record<string, PdfHit>>>>()
const pageCache = new Map<string, Promise<PdfPageData | null>>()

function loadPdfHits(docId: string): Promise<Record<string, Record<string, PdfHit>>> {
  return cachedJson(hitsCache, docId, `${import.meta.env.BASE_URL}local/pdf/${docId}/hits.json`, () => ({}))
}

export function loadPdfPage(docId: string, page: number): Promise<PdfPageData | null> {
  const key = `${docId}/${page}`
  return cachedJson(pageCache, key, `${import.meta.env.BASE_URL}local/pdf/${docId}/p${page}.json`, () => null)
}

export const pdfPagePng = (docId: string, page: number) =>
  `${import.meta.env.BASE_URL}local/pdf/${docId}/p${page}.png`

/** 修飾キー → 文書と頁内位置。表の行キーと同じく `<年度>|<鍵>` に修飾して衝突を防ぐ */
export type PdfHitLoc = { docId: string; page: number; box: [number, number, number, number] }

/**
 * 原典ノードの全文書の hit を1つの対応表へ畳む。
 * ⚠️ **文書は年度ごとに別れうる**ので、hit の鍵は `doc.years[0]` で年度修飾する。
 * 複数年度をまたぐ文書（years が2つ以上）では修飾できないので裸の鍵のままになる
 * — その文書の hit は年度を持つ表の行とは一致しない（誤対応より対応なしのほうがまだ正しい）。
 */
export async function loadHitMap(
  docs: PdfDocMeta[],
  srcId: string,
): Promise<Map<string, PdfHitLoc>> {
  const perDoc = await Promise.all(docs.map((d) => loadPdfHits(d.id)))
  const map = new Map<string, PdfHitLoc>()
  docs.forEach((d, i) => {
    const hits = perDoc[i]?.[srcId]
    if (!hits) return
    const y = d.years.length === 1 ? d.years[0] : null
    for (const [k, h] of Object.entries(hits)) {
      if (!h?.box) continue
      map.set(y === null ? k : `${y}|${k}`, { docId: d.id, page: h.page, box: h.box })
    }
  })
  return map
}
