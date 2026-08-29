/**
 * budgets リソースの procedure。root の一覧（filter で絞る）と Get。
 * 一覧の存在がカバレッジそのもの。
 */
import {
  type Env,
  type CofogChunkFile,
  type LinesChunkFile,
  paths,
  readJsonAsset,
} from '../assets'
import { parseBudgetId, type BudgetLine, type CrossBudgetLine } from '../contract'
import { filterFingerprint, type ParsedFilter } from '../lib/filter'
import { encodePageToken } from '../lib/token'
import {
  checkOffsetInRange,
  os,
  parseFilterOr400,
  readMeta,
  resolvePageSize,
  scanPage,
  verifyToken,
  type Errors,
} from './shared'

export const listBudgets = os.listBudgets.handler(async ({ context, input, errors }) => {
  const filter = parseFilterOr400(input.filter, errors)
  if (filter.direction !== undefined || filter.phase !== undefined || filter.cofogDivision !== undefined) {
    throw errors.BAD_REQUEST({
      message: 'only jurisdiction and fiscalYear filters are supported for budgets',
      data: { reason: 'unsupported filter field' },
    })
  }
  const meta = await readMeta(context.env)
  const budgets = meta.budgets.filter(
    (b) =>
      (filter.jurisdiction === undefined || b.jurisdictionId === filter.jurisdiction) &&
      (filter.fiscalYear === undefined || b.fiscalYear === filter.fiscalYear),
  )
  return { budgets, revision: meta.revision }
})

export const getBudget = os.getBudget.handler(async ({ context, input, errors }) => {
  const meta = await readMeta(context.env)
  const budget = meta.budgetById.get(input.budget)
  if (!budget) throw errors.NOT_FOUND({ message: `unknown budget: ${input.budget}` })
  return { budget, revision: meta.revision }
})

// ---- statement（予算の明細。budget 集約の内部） ----

export const getStatement = os.getStatement.handler(async ({ context, input, errors }) => {
  const pageSize = resolvePageSize(input.pageSize)
  const filter = parseFilterOr400(input.filter, errors)
  if (filter.jurisdiction !== undefined) {
    throw errors.BAD_REQUEST({
      message: 'jurisdiction is not a filter for statements. Specify the parent budget ({jurisdiction}:{year}) instead',
      data: { reason: 'unsupported filter field' },
    })
  }

  if (input.budget === '-') {
    return crossBudgetStatement(context.env, filter, pageSize, input.pageToken, errors)
  }
  return budgetStatement(context.env, input.budget, filter, pageSize, input.pageToken, errors)
})

async function crossBudgetStatement(
  env: Env,
  filter: ParsedFilter,
  pageSize: number,
  rawToken: string | undefined,
  errors: Errors,
) {
  if (filter.direction !== undefined || filter.phase !== undefined) {
    throw errors.BAD_REQUEST({
      message: 'direction and phase filters are not supported for cross-budget statements',
      data: { reason: 'unsupported filter field for parent "-"' },
    })
  }
  const division = filter.cofogDivision
  if (division === undefined) {
    throw errors.BAD_REQUEST({
      message: 'cofog.division filter is required for cross-budget statements',
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

  const chunk = await readJsonAsset<CofogChunkFile>(env, paths.chunk(family, chunkIndex))
  if (chunk === null) {
    // 系列自体が無い（そのフィルタに該当が無い）のは先頭ページだけで正当
    if (token === null) {
      return { scope: 'crossBudget' as const, lines: [], revision: meta.revision }
    }
    throw errors.BAD_REQUEST({ message: 'pageToken points outside the result set', data: { reason: 'invalid pageToken' } })
  }
  checkOffsetInRange(offset, chunk.lines.length, errors)

  const { items, nextOffset } = scanPage<CrossBudgetLine>(chunk.lines, offset, pageSize, () => true)
  let nextPageToken: string | undefined
  if (nextOffset !== null) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: chunkIndex, off: nextOffset, fh: fingerprint })
  } else if (chunk.hasNext) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: chunkIndex + 1, off: 0, fh: fingerprint })
  }
  return { scope: 'crossBudget' as const, lines: items, revision: chunk.revision, nextPageToken }
}

async function budgetStatement(
  env: Env,
  budgetId: string,
  filter: ParsedFilter,
  pageSize: number,
  rawToken: string | undefined,
  errors: Errors,
) {
  const parsed = parseBudgetId(budgetId)
  if (parsed === null) {
    throw errors.BAD_REQUEST({
      message: `malformed budget id: ${budgetId} (expected {jurisdiction}:{year})`,
      data: { reason: 'invalid budget id' },
    })
  }
  const meta = await readMeta(env)
  const budget = meta.budgetById.get(budgetId)
  if (!budget) throw errors.NOT_FOUND({ message: `unknown budget: ${budgetId}` })

  if (filter.fiscalYear !== undefined) {
    throw errors.BAD_REQUEST({
      message: 'fiscalYear filter is redundant within a budget (the parent budget fixes the year)',
      data: { reason: 'unsupported filter field' },
    })
  }
  const { direction } = filter
  if (direction === undefined) {
    throw errors.BAD_REQUEST({
      message: 'direction filter is required for a budget statement',
      data: { reason: 'missing required filter' },
    })
  }
  if (!budget.directions.includes(direction)) {
    throw errors.NOT_FOUND({ message: `${direction} is not covered for budget ${budgetId}` })
  }

  const family = paths.linesFamily(parsed.jurisdiction, parsed.fiscalYear, direction)
  const fingerprint = filterFingerprint(filter)
  const token =
    rawToken === undefined ? null : verifyToken(rawToken, { revision: meta.revision, family, fingerprint }, errors)
  const chunkIndex = token?.chunk ?? 0
  const offset = token?.off ?? 0

  const chunk = await readJsonAsset<LinesChunkFile>(env, paths.chunk(family, chunkIndex))
  if (chunk === null) {
    if (token === null) throw new Error(`partition missing for covered budget: ${family}`)
    throw errors.BAD_REQUEST({ message: 'pageToken points outside the result set', data: { reason: 'invalid pageToken' } })
  }
  checkOffsetInRange(offset, chunk.lines.length, errors)

  const predicate = (line: BudgetLine): boolean => {
    if (filter.phase !== undefined && !line.amounts.some((a) => a.phase === filter.phase)) return false
    if (filter.cofogDivision !== undefined && line.judgments.cofog?.division !== filter.cofogDivision) return false
    return true
  }
  const { items, nextOffset } = scanPage(chunk.lines, offset, pageSize, predicate)
  let nextPageToken: string | undefined
  if (nextOffset !== null) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: chunkIndex, off: nextOffset, fh: fingerprint })
  } else if (chunk.hasNext) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: chunkIndex + 1, off: 0, fh: fingerprint })
  }
  return { scope: 'budget' as const, lines: items, revision: chunk.revision, nextPageToken }
}
