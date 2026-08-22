/**
 * 取得系スクリプトの共有ユーティリティ。
 *
 * `fetch-robots` / `check-bulletins` / `check-budget-granularity` が同じ処理を
 * 個別に持っていたため切り出した。3本目で同じものを書いた時点が共通化の合図だった。
 */
import { Manifest } from './gates'

/** 全スクリプトで同じ UA を名乗る。相手が名指しで拒否できる状態を保つため */
export const UA = 'fudoki/0.1 (+https://github.com/wwwyo/fudoki)'

/** 書き戻すスクリプトが同じパスを参照できるよう公開する */
export const MANIFEST_PATH = new URL('../../ingestion/transcript-gates.json', import.meta.url).pathname

export async function loadManifest() {
  return Manifest.parse(JSON.parse(await Bun.file(MANIFEST_PATH).text()))
}

/** CSV は cp932 で配られることがある。置換文字が出たら読み直す */
export function decodeText(bytes: Uint8Array): string {
  const utf8 = new TextDecoder('utf-8', { fatal: false }).decode(bytes)
  return utf8.includes('�') ? new TextDecoder('shift_jis').decode(bytes) : utf8
}

/** ヘッダ1行を取れれば足りるので、引用符内の改行は想定しない */
export function splitCsvLine(line: string): string[] {
  const out: string[] = []
  let cur = '',
    quoted = false
  for (const ch of line) {
    if (ch === '"') quoted = !quoted
    else if (ch === ',' && !quoted) (out.push(cur), (cur = ''))
    else cur += ch
  }
  out.push(cur)
  return out.map((s) => s.replace(/^﻿/, '').trim())
}

export type ContentKind = 'zip' | 'pdf' | 'xls' | 'html' | 'text'

/**
 * 先頭バイトで種別を見る。拡張子も Content-Type も当てにならない。
 * HTML が返るのは「取得できたが中身が無い」典型なので、text と区別する。
 */
export function sniffContent(bytes: Uint8Array): ContentKind {
  const b = bytes
  if (b[0] === 0x50 && b[1] === 0x4b) return 'zip' // xlsx / docx も zip
  if (b[0] === 0x25 && b[1] === 0x50 && b[2] === 0x44 && b[3] === 0x46) return 'pdf'
  if (b[0] === 0xd0 && b[1] === 0xcf) return 'xls' // 旧 OLE2
  const head = new TextDecoder('utf-8', { fatal: false }).decode(b.slice(0, 200)).trimStart()
  return /^<(!DOCTYPE|html)/i.test(head) ? 'html' : 'text'
}

export const sha256 = (bytes: Uint8Array) => new Bun.CryptoHasher('sha256').update(bytes).digest('hex')

export type Fetched =
  | { ok: true; status: number; bytes: Uint8Array }
  | { ok: false; status: number | null; reason: string }

/**
 * 上限を超えたら読むのをやめる。
 * `content-length` は欠落することがあるので、ヘッダではなく実際の累積バイト数で打ち切る。
 */
export async function fetchCapped(url: string, maxBytes: number, timeoutMs = 30_000): Promise<Fetched> {
  let res: Response
  try {
    res = await fetch(url, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(timeoutMs) })
  } catch (e) {
    return { ok: false, status: null, reason: `取得できない: ${e instanceof Error ? e.message : e}` }
  }
  const reader = res.body?.getReader()
  if (!reader) return { ok: false, status: res.status, reason: '本文が無い' }

  const chunks: Uint8Array[] = []
  let total = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    total += value.length
    if (total > maxBytes) {
      await reader.cancel()
      return { ok: false, status: res.status, reason: `${(maxBytes / 1024 / 1024).toFixed(0)}MB の上限を超えた` }
    }
    chunks.push(value)
  }
  const bytes = new Uint8Array(total)
  let at = 0
  for (const c of chunks) (bytes.set(c, at), (at += c.length))
  return { ok: true, status: res.status, bytes }
}

/** 空行を除いたデータ行数。全行を配列化せずに数える */
export function countDataRows(text: string): number {
  let rows = 0
  let start = 0
  for (;;) {
    const nl = text.indexOf('\n', start)
    const line = (nl < 0 ? text.slice(start) : text.slice(start, nl)).trim()
    if (line) rows++
    if (nl < 0) break
    start = nl + 1
  }
  return Math.max(0, rows - 1) // ヘッダを除く
}

/** 相手は自治体のサーバなので、同時実行数を絞って回す */
export async function mapWithConcurrency<T, R>(items: readonly T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length)
  let next = 0
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, async () => {
      for (;;) {
        const i = next++
        if (i >= items.length) return
        out[i] = await fn(items[i]!)
      }
    }),
  )
  return out
}
