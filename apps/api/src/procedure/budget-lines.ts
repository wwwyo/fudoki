/**
 * budgetLines リソースの procedure。
 * 判断はすべて build 済みのパーティションに寄せてあり、
 * ここは「該当パーティションを1つ読んで絞る」以外のことをしない。
 */
import {
  type Env,
  type CofogChunkFile,
  type LinesFile,
  paths,
  readJsonAsset,
} from '../assets'
import type { BudgetLine, CrossJurisdictionLine } from '../contract'
import { filterFingerprint, type ParsedFilter } from '../lib/filter'
import { encodePageToken } from '../lib/token'
import { os, parseFilterOr400, readMeta, resolvePageSize, scanPage, verifyToken, type Errors } from './os'

export const listBudgetLines = os.listBudgetLines.handler(async ({ context, input, errors }) => {
  const pageSize = resolvePageSize(input.pageSize)
  const filter = parseFilterOr400(input.filter, errors)

  if (input.jurisdiction === '-') {
    return listCrossJurisdiction(context.env, filter, pageSize, input.pageToken, errors)
  }
  return listWithinJurisdiction(context.env, input.jurisdiction, filter, pageSize, input.pageToken, errors)
})

export const getBudgetLine = os.getBudgetLine.handler(async ({ context, input, errors }) => {
  const notFound = () => errors.NOT_FOUND({ message: `unknown budget line: ${input.budgetLine}` })
  // budget_line_id は {団体}:{年度}:{direction}:... なので、id 自身がパーティションを指す
  const [jurisdiction, fiscalYear, direction] = input.budgetLine.split(':')
  if (jurisdiction !== input.jurisdiction) throw notFound()
  if (direction !== 'expenditure' && direction !== 'revenue') throw notFound()
  if (!jurisdiction || !fiscalYear) throw notFound()
  const file = await readJsonAsset<LinesFile>(context.env, paths.lines(jurisdiction, fiscalYear, direction))
  if (file === null) throw notFound()
  const line = file.lines.find((l) => l.budgetLineId === input.budgetLine)
  if (!line) throw notFound()
  return { budgetLine: line, revision: file.revision }
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
  const token =
    rawToken === undefined ? null : verifyToken(rawToken, { revision: meta.revision, family, fingerprint }, errors)
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
  const budget = meta.budgets[jurisdictionId]?.find((b) => b.fiscalYear === fiscalYear)
  if (!budget || !budget.directions.includes(direction)) {
    throw errors.NOT_FOUND({
      message: `fiscal year ${fiscalYear} (${direction}) is not covered for ${jurisdictionId}`,
    })
  }

  const family = paths.lines(jurisdictionId, fiscalYear, direction).replace(/\.json$/, '')
  const fingerprint = filterFingerprint(filter)
  const token =
    rawToken === undefined ? null : verifyToken(rawToken, { revision: meta.revision, family, fingerprint }, errors)
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
