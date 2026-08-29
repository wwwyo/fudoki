/**
 * contract の implementer（oRPC の慣習で os と呼ぶ）と、procedure が共有する道具。
 * oRPC の推奨構成（contract → procedure → router）の procedure 層にあたる。
 */
import { implement } from '@orpc/server'
import { type Env, type JurisdictionsFile, paths, readJsonAsset } from '../assets'
import { contract, type Budget, type Jurisdiction } from '../contract'
import { FilterSyntaxError, parseFilter, type ParsedFilter } from '../lib/filter'
import { decodePageToken, type PageToken } from '../lib/token'

export const os = implement(contract).$context<{ env: Env }>()

export type Errors = Parameters<Parameters<typeof os.getStatement.handler>[0]>[0]['errors']

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
