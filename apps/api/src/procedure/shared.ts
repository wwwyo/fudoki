/**
 * contract の implementer（oRPC の慣習で os と呼ぶ）と、procedure が共有する道具。
 * oRPC の推奨構成（contract → procedure → router）の procedure 層にあたる。
 */
import { implement } from '@orpc/server'
import { type Env, type JurisdictionsFile, paths, readJsonAsset } from '../assets'
import { contract, type Budget, type Jurisdiction } from '../contract'
import { FilterSyntaxError, fingerprintOf, parseFilter, type ParsedFilter } from '../lib/filter'
import { decodePageToken, encodePageToken, type PageToken } from '../lib/token'

// 出力検証の無効化（decision.log 10 の対処順の2番目）は oRPC v1 に口が無く、
// v2 の implement(contract, { disableOutputValidation: true }) を待つ。
export const os = implement(contract).$context<{ env: Env }>()

export type Errors = Parameters<Parameters<typeof os.getBudgetLines.handler>[0]>[0]['errors']

export const PAGE_SIZE_DEFAULT = 1000
export const PAGE_SIZE_MAX = 1000

export function resolvePageSize(pageSize: number | undefined): number {
  if (pageSize === undefined || pageSize === 0) return PAGE_SIZE_DEFAULT
  return Math.min(pageSize, PAGE_SIZE_MAX)
}

export function parseFilterOr400(raw: string | undefined, errors: Errors): ParsedFilter {
  if (raw === undefined || raw.trim() === '') return {}
  try {
    return parseFilter(raw)
  } catch (e) {
    if (e instanceof FilterSyntaxError) {
      throw errors.BAD_REQUEST({ message: e.message, data: { reason: 'invalid filter' } })
    }
    throw e
  }
}

export function verifyToken(
  raw: string,
  expected: { revision: string; family: string; fingerprint: string },
  errors: Errors,
): PageToken {
  const token = decodePageToken(raw)
  if (token === null) {
    throw errors.BAD_REQUEST({ message: 'malformed pageToken', data: { reason: 'invalid pageToken' } })
  }
  if (token.rev !== expected.revision) throw errors.STALE_PAGE_TOKEN()
  if (token.family !== expected.family || token.fh !== expected.fingerprint) {
    throw errors.BAD_REQUEST({
      message: 'pageToken was issued for a different query',
      data: { reason: 'pageToken/query mismatch' },
    })
  }
  return token
}

export type Meta = JurisdictionsFile & {
  jurisdictionById: Map<string, Jurisdiction>
  budgetById: Map<string, Budget>
}

/**
 * meta はデプロイに焼き込まれた不変データなので、isolate の生存中は
 * モジュールスコープに1回だけ読む（毎リクエストの fetch + JSON.parse を避ける。
 * デプロイのたびに isolate ごと入れ替わるため無効化は不要）。
 */
let metaCache: Meta | null = null

export async function readMeta(env: Env): Promise<Meta> {
  if (metaCache !== null) return metaCache
  const meta = await readJsonAsset<JurisdictionsFile>(env, paths.jurisdictions)
  if (meta === null) throw new Error('meta/jurisdictions.json is missing from assets')
  metaCache = {
    ...meta,
    jurisdictionById: new Map(meta.jurisdictions.map((j) => [j.id, j])),
    budgetById: new Map(meta.budgets.map((b) => [b.id, b])),
  }
  return metaCache
}

/** pageToken の offset が走査対象の範囲内であることの検査（budget / crossBudget で共通） */
export function checkOffsetInRange(offset: number, length: number, errors: Errors): void {
  if (offset > length) {
    throw errors.BAD_REQUEST({ message: 'pageToken offset is out of range', data: { reason: 'invalid pageToken' } })
  }
}

/** 走査は最大1 chunk。フィルタで該当が減っても offset は生の行位置で進める */
export function scanPage<T>(
  rows: T[],
  startOffset: number,
  pageSize: number,
  predicate: (row: T) => boolean,
): { items: T[]; nextOffset: number | null } {
  const items: T[] = []
  for (let i = startOffset; i < rows.length; i++) {
    const row = rows[i]!
    if (!predicate(row)) continue
    items.push(row)
    if (items.length === pageSize) {
      return { items, nextOffset: i + 1 < rows.length ? i + 1 : null }
    }
  }
  return { items, nextOffset: null }
}

/**
 * 単一 chunk の集計アセット（budget / cross / hierarchy / years）から1ページを切り出す。
 * resolvePageSize → fingerprint → verifyToken → checkOffsetInRange → scanPage → encodePageToken
 * の並びは4箇所（procedure/budgets.ts の各 *Aggregate 関数）で同一だったので、ここへまとめる。
 * fingerprint に含める項目は呼び出し元ごとに違う（hierarchy は hierarchyParent を足す）ので、
 * 組み立て済みの Record を受け取る。
 */
export function pageAggregateCells<T>(
  meta: Meta,
  assetPath: string,
  cells: T[],
  pageSize: number | undefined,
  pageToken: string | undefined,
  fingerprintFields: Record<string, unknown>,
  errors: Errors,
): { items: T[]; nextPageToken: string | undefined } {
  const resolvedPageSize = resolvePageSize(pageSize)
  const fingerprint = fingerprintOf(fingerprintFields)
  const family = assetPath
  const token = pageToken === undefined ? null : verifyToken(pageToken, { revision: meta.revision, family, fingerprint }, errors)
  const offset = token?.off ?? 0
  checkOffsetInRange(offset, cells.length, errors)
  const { items, nextOffset } = scanPage(cells, offset, resolvedPageSize, () => true)
  let nextPageToken: string | undefined
  if (nextOffset !== null) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: 0, off: nextOffset, fh: fingerprint })
  }
  return { items, nextPageToken }
}
