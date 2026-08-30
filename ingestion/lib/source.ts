/**
 * 取得系スクリプトの共有ユーティリティ。
 *
 * `fetch-robots` / `check-bulletins` / `check-budget-granularity` が同じ処理を
 * 個別に持っていたため切り出した。3本目で同じものを書いた時点が共通化の合図だった。
 */
import { Gates } from '../transcripts/gates'

/** 全スクリプトで同じ UA を名乗る。相手が名指しで拒否できる状態を保つため */
export const UA = 'fudoki/0.1 (+https://github.com/wwwyo/fudoki)'

/** 書き戻すスクリプトが同じパスを参照できるよう公開する */
export const GATES_PATH = new URL('../transcripts/gates.json', import.meta.url).pathname

/** ③会議録のゲート判定。**①予算には掛からない**（根拠が著作権法40条1項と各議会の規約） */
export async function loadGates() {
  return Gates.parse(JSON.parse(await Bun.file(GATES_PATH).text()))
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
