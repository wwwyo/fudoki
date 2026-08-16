/**
 * # Extract：原典を無加工で取得する
 *
 * CKAN からリソースを解決し、レスポンスをバイト列のまま作業領域へ置く。
 * 解釈・整形・結合はしない。
 *
 * **冪等にする。** 既に同じバイト列が作業領域にあれば取得しない。
 * ここが冪等でないと、表記ルールを1つ直すたびに全自治体を再クロールすることになる。
 *
 * 取得物はリポジトリのツリーへ置かない。残すのは URL・status・SHA-256・取得時刻の証跡だけで、
 * これにより再現性の意味が「原典から再生成できること」から「成果物の版が残ること」へ変わる。
 */
import { UA, decodeText, fetchCapped, sha256, sniffContent } from '../../scripts/lib/source'
import { CKAN_ENDPOINT, type BudgetSource, type Direction } from './source'

/** 原典は最大でも 1MB 程度。桁が違うものが返ったら取得元の異常なので落とす */
const MAX_BYTES = 20 * 1024 * 1024
/** 作業領域。ツリー外（.gitignore 済み） */
export const WORK_DIR = new URL('../../.cache/budget/', import.meta.url).pathname

/** 1リソースの取得証跡。要約ではなく観測を残す */
export type Provenance = {
  direction: Direction
  datasetTitle: string
  /** 年度の唯一の出所。どのリソース名からどの年度を導いたかを残す */
  resourceName: string
  fiscalYear: number
  fiscalYearBasis: string
  requestUrl: string
  status: number
  bytes: number
  sha256: string
  fetchedAt: string
  /** 先頭バイトで見た種別。HTML が返るのは「取得できたが中身が無い」典型 */
  detectedFormat: string
  encoding: 'utf-8' | 'shift_jis'
  header: string[]
  rows: number
}

export type Extracted = { provenance: Provenance; text: string }

type CkanResource = { format?: string; name?: string; url?: string }
type CkanPackage = { title: string; organization?: { name?: string }; resources?: CkanResource[] }

/**
 * データセットを CKAN から引く。
 * `q` は説明文まで全文一致するので、団体（organization = `t` + 団体コード）と
 * タイトルの完全一致まで絞ってから返す。
 */
async function findDataset(source: BudgetSource): Promise<CkanPackage> {
  const url = `${CKAN_ENDPOINT}?q=${encodeURIComponent(source.datasetTitle)}&rows=300`
  const res = await fetch(url, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(40_000) })
  if (!res.ok) throw new Error(`CKAN が ${res.status} を返した: ${url}`)
  const body = (await res.json()) as { result?: { results?: CkanPackage[] } }
  const hit = (body.result?.results ?? []).find(
    (p) => p.organization?.name === `t${source.jurisdictionCode}` && p.title === source.datasetTitle,
  )
  if (!hit) throw new Error(`データセット「${source.datasetTitle}」が ${source.jurisdictionName}（t${source.jurisdictionCode}）に見つからない`)
  return hit
}

/**
 * 年度をリソース名から解決する。
 *
 * 原典に年度の列が無く、カタログのリソース名にしか現れない。
 * **Load より後ろでこれをやると、中間表現が年度を持たないまま複数年度を扱うことになり、
 * 取り違えても検出できない。** そこで Extract で解決し、由来を証跡へ残す。
 */
function resolveFiscalYear(resourceName: string, source: BudgetSource): { year: number; basis: string } {
  if (!resourceName.includes(source.fiscalYearLabel)) {
    throw new Error(`リソース名「${resourceName}」に年度表記「${source.fiscalYearLabel}」が無い。年度を解決できないので収録しない`)
  }
  return { year: source.fiscalYear, basis: `CKAN のリソース名「${resourceName}」に含まれる「${source.fiscalYearLabel}」から解決（西暦 ${source.fiscalYear}）` }
}

/** CRLF・BOM・空行を落として行に割る。原典は引用符を使っていないが、使われたら検出したい */
export function splitRows(text: string): string[][] {
  const lines = text.replace(/^﻿/, '').split(/\r?\n/).filter((l) => l.trim() !== '')
  return lines.map((l) => l.split(',').map((c) => c.trim()))
}

async function readCached(path: string): Promise<Uint8Array | null> {
  const f = Bun.file(path)
  return (await f.exists()) ? new Uint8Array(await f.arrayBuffer()) : null
}

/**
 * 1リソースを取得する。作業領域に同じ内容があれば取得しない。
 *
 * `refetch` を立てると必ず取り直し、前回とハッシュが違えば呼び出し側へ知らせる
 * （自治体側の差し替えを無言で上書きしないため）。
 */
export async function extractResource(
  source: BudgetSource,
  spec: BudgetSource['resources'][number],
  opts: { refetch?: boolean } = {},
): Promise<Extracted & { changedFrom: string | null }> {
  const pkg = await findDataset(source)
  const resource = (pkg.resources ?? []).find((r) => r.name === spec.resourceName)
  if (!resource?.url) throw new Error(`リソース「${spec.resourceName}」が見つからない`)

  const { year, basis } = resolveFiscalYear(spec.resourceName, source)
  const cachePath = `${WORK_DIR}${source.jurisdictionCode}-${year}-${spec.slug}.csv`
  const metaPath = `${cachePath}.meta.json`
  const previous = await readCached(cachePath)
  const previousHash = previous ? sha256(previous) : null

  // 取得時刻は「いつ取ったか」の事実なので、キャッシュを使ったときに now で上書きしない。
  // 上書きすると、証跡の日時と実際に手元にあるバイト列の取得時点がずれる。
  let bytes = previous
  let meta = previous && (await Bun.file(metaPath).exists()) ? ((await Bun.file(metaPath).json()) as { status: number; fetchedAt: string }) : null
  if (!bytes || !meta || opts.refetch) {
    const got = await fetchCapped(resource.url, MAX_BYTES)
    if (!got.ok) throw new Error(`原典を取得できない（${spec.resourceName}）: ${got.reason}。Extract を失敗として扱い、正本を更新しない`)
    bytes = got.bytes
    meta = { status: got.status, fetchedAt: new Date().toISOString() }
    await Bun.write(cachePath, bytes)
    await Bun.write(metaPath, JSON.stringify(meta) + '\n')
  }

  const detectedFormat = sniffContent(bytes)
  if (detectedFormat !== 'text') throw new Error(`原典が ${detectedFormat} で返った（${spec.resourceName}）。HTTP 200 でも中身が無い`)

  const text = decodeText(bytes)
  const encoding = new TextDecoder('utf-8', { fatal: false }).decode(bytes).includes('�') ? 'shift_jis' : 'utf-8'
  const rows = splitRows(text)
  const header = rows[0]
  if (!header) throw new Error(`原典が空（${spec.resourceName}）`)

  const hash = sha256(bytes)
  return {
    changedFrom: previousHash && previousHash !== hash ? previousHash : null,
    text,
    provenance: {
      direction: spec.direction,
      datasetTitle: source.datasetTitle,
      resourceName: spec.resourceName,
      fiscalYear: year,
      fiscalYearBasis: basis,
      requestUrl: resource.url,
      status: meta.status,
      bytes: bytes.length,
      sha256: hash,
      fetchedAt: meta.fetchedAt,
      detectedFormat,
      encoding,
      header,
      rows: rows.length - 1,
    },
  }
}
