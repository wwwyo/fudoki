/**
 * contract の実装。判断はすべて build 済みのパーティションに寄せてあり、
 * ここは「該当パーティションを1つ読んで絞る」以外のことをしない。
 */
import { implement } from '@orpc/server'
import {
  type Env,
  type CofogChunkFile,
  type JurisdictionsFile,
  type LinesFile,
  paths,
  readJsonAsset,
} from './assets'
import { contract, type BudgetLine, type CrossJurisdictionLine } from './contract'
import { FilterSyntaxError, filterFingerprint, parseFilter, type ParsedFilter } from './filter'
import { decodePageToken, encodePageToken, type PageToken } from './token'

const PAGE_SIZE_DEFAULT = 1000
const PAGE_SIZE_MAX = 1000

const os = implement(contract).$context<{ env: Env }>()

type Errors = Parameters<Parameters<typeof os.listBudgetLines.handler>[0]>[0]['errors']

function resolvePageSize(pageSize: number | undefined): number {
  if (pageSize === undefined || pageSize === 0) return PAGE_SIZE_DEFAULT
  return Math.min(pageSize, PAGE_SIZE_MAX)
}

function parseFilterOr400(raw: string | undefined, errors: Errors): ParsedFilter {
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

function verifyToken(
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

async function readMeta(env: Env): Promise<JurisdictionsFile> {
  const meta = await readJsonAsset<JurisdictionsFile>(env, paths.jurisdictions)
  if (meta === null) throw new Error('meta/jurisdictions.json is missing from assets')
  return meta
}

/** 走査は最大1 chunk。フィルタで該当が減っても offset は生の行位置で進める */
function scanPage<T>(
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

export const router = os.router({
  listJurisdictions: os.listJurisdictions.handler(async ({ context }) => {
    const meta = await readMeta(context.env)
    return { jurisdictions: meta.jurisdictions, revision: meta.revision }
  }),

  getJurisdiction: os.getJurisdiction.handler(async ({ context, input, errors }) => {
    const meta = await readMeta(context.env)
    const jurisdiction = meta.jurisdictions.find((j) => j.id === input.jurisdiction)
    if (!jurisdiction) throw errors.NOT_FOUND({ message: `unknown jurisdiction: ${input.jurisdiction}` })
    return { jurisdiction, revision: meta.revision }
  }),

  listBudgetLines: os.listBudgetLines.handler(async ({ context, input, errors }) => {
    const pageSize = resolvePageSize(input.pageSize)
    const filter = parseFilterOr400(input.filter, errors)

    if (input.jurisdiction === '-') {
      return listCrossJurisdiction(context.env, filter, pageSize, input.pageToken, errors)
    }
    return listWithinJurisdiction(context.env, input.jurisdiction, filter, pageSize, input.pageToken, errors)
  }),

  getBudgetLine: os.getBudgetLine.handler(async ({ context, input, errors }) => {
    const notFound = () =>
      errors.NOT_FOUND({ message: `unknown budget line: ${input.budgetLine}` })
    // budget_line_id は {団体}:{年度}:{direction}:... なので、id 自身がパーティションを指す
    const [jurisdiction, fiscalYear, direction] = input.budgetLine.split(':')
    if (jurisdiction !== input.jurisdiction) throw notFound()
    if (direction !== 'expenditure' && direction !== 'revenue') throw notFound()
    if (!jurisdiction || !fiscalYear) throw notFound()
    const file = await readJsonAsset<LinesFile>(
      context.env,
      paths.lines(jurisdiction, fiscalYear, direction),
    )
    if (file === null) throw notFound()
    const line = file.lines.find((l) => l.budgetLineId === input.budgetLine)
    if (!line) throw notFound()
    return { budgetLine: line, revision: file.revision }
  }),
})

async function listCrossJurisdiction(
  env: Env,
  filter: ParsedFilter,
  pageSize: number,
  rawToken: string | undefined,
  errors: Errors,
) {
  if (filter.direction !== undefined || filter.phase !== undefined) {
    throw errors.BAD_REQUEST({
      message: 'direction and phase filters are not supported for cross-jurisdiction queries',
      data: { reason: 'unsupported filter field for parent "-"' },
    })
  }
  const division = filter.cofogDivision
  if (division === undefined) {
    throw errors.BAD_REQUEST({
      message: 'cofog.division filter is required for cross-jurisdiction queries',
      data: { reason: 'missing required filter' },
    })
  }
  if (!/^(0[1-9]|10)$/.test(division)) {
    throw errors.BAD_REQUEST({
      message: `cofog.division must be 01..10, got ${division}`,
      data: { reason: 'invalid cofog.division' },
    })
  }

  const meta = await readMeta(env)
  const family = paths.cofogFamily(division, filter.fiscalYear)
  const fingerprint = filterFingerprint(filter)
  const token = rawToken === undefined ? null : verifyToken(rawToken, { revision: meta.revision, family, fingerprint }, errors)
  const chunkIndex = token?.chunk ?? 0
  const offset = token?.off ?? 0

  const chunk = await readJsonAsset<CofogChunkFile>(env, paths.cofogChunk(family, chunkIndex))
  if (chunk === null) {
    // 系列自体が無い（そのフィルタに該当が無い）のは先頭ページだけで正当
    if (token === null) {
      return { scope: 'crossJurisdiction' as const, budgetLines: [], revision: meta.revision }
    }
    throw errors.BAD_REQUEST({ message: 'pageToken points outside the result set', data: { reason: 'invalid pageToken' } })
  }
  if (offset > chunk.lines.length) {
    throw errors.BAD_REQUEST({ message: 'pageToken offset is out of range', data: { reason: 'invalid pageToken' } })
  }

  const { items, nextOffset } = scanPage<CrossJurisdictionLine>(chunk.lines, offset, pageSize, () => true)
  let nextPageToken: string | undefined
  if (nextOffset !== null) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: chunkIndex, off: nextOffset, fh: fingerprint })
  } else if (chunk.hasNext) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: chunkIndex + 1, off: 0, fh: fingerprint })
  }
  return { scope: 'crossJurisdiction' as const, budgetLines: items, revision: chunk.revision, nextPageToken }
}

async function listWithinJurisdiction(
  env: Env,
  jurisdictionId: string,
  filter: ParsedFilter,
  pageSize: number,
  rawToken: string | undefined,
  errors: Errors,
) {
  const meta = await readMeta(env)
  const jurisdiction = meta.jurisdictions.find((j) => j.id === jurisdictionId)
  if (!jurisdiction) throw errors.NOT_FOUND({ message: `unknown jurisdiction: ${jurisdictionId}` })

  const { fiscalYear, direction } = filter
  if (fiscalYear === undefined || direction === undefined) {
    throw errors.BAD_REQUEST({
      message: 'fiscalYear and direction filters are required when listing within a jurisdiction',
      data: { reason: 'missing required filter' },
    })
  }
  if (!jurisdiction.fiscalYears[direction].includes(fiscalYear)) {
    throw errors.NOT_FOUND({
      message: `fiscal year ${fiscalYear} (${direction}) is not covered for ${jurisdictionId}`,
    })
  }

  const family = paths.lines(jurisdictionId, fiscalYear, direction).replace(/\.json$/, '')
  const fingerprint = filterFingerprint(filter)
  const token = rawToken === undefined ? null : verifyToken(rawToken, { revision: meta.revision, family, fingerprint }, errors)
  const offset = token?.off ?? 0

  const file = await readJsonAsset<LinesFile>(env, paths.lines(jurisdictionId, fiscalYear, direction))
  if (file === null) throw new Error(`partition missing for covered year: ${family}`)
  if (offset > file.lines.length) {
    throw errors.BAD_REQUEST({ message: 'pageToken offset is out of range', data: { reason: 'invalid pageToken' } })
  }

  const predicate = (line: BudgetLine): boolean => {
    if (filter.phase !== undefined && !line.amounts.some((a) => a.phase === filter.phase)) return false
    if (filter.cofogDivision !== undefined && line.judgments.cofog?.division !== filter.cofogDivision) return false
    return true
  }
  const { items, nextOffset } = scanPage(file.lines, offset, pageSize, predicate)
  const nextPageToken =
    nextOffset === null
      ? undefined
      : encodePageToken({ v: 1, rev: meta.revision, family, chunk: 0, off: nextOffset, fh: fingerprint })
  return { scope: 'jurisdiction' as const, budgetLines: items, revision: file.revision, nextPageToken }
}
