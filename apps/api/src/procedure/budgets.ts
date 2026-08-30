/**
 * budgets リソースの procedure。root の一覧（filter で絞る）と Get。
 * 一覧の存在がカバレッジそのもの。
 */
import {
  type AggBudgetsAsset,
  type AggCrossAsset,
  type AggHierarchyAsset,
  type AggHierarchyCofogAsset,
  type AggYearsCofogDivisionAsset,
  type AggYearsTotalAsset,
  type CofogChunkFile,
  type Env,
  type LinesChunkFile,
  type NameIndexChunkFile,
  type NameIndexEntry,
  paths,
  readJsonAsset,
} from '../assets'
import {
  budgetIdOf,
  type BudgetLinesView,
  cofogDepthOf,
  CROSS_JURISDICTION_GROUPINGS,
  hierarchyChildLevel,
  hierarchyParentPathString,
  JURISDICTION_YEARS_GROUPINGS,
  type NameFieldValue,
  parseBudgetId,
  parseBudgetLineId,
  parseHierarchyParent,
  type SearchMatch,
  SINGLE_BUDGET_GROUPINGS,
  type StoredBudgetLine,
  type StoredCrossBudgetLine,
  SUPPORTED_AGGREGATE_DIRECTIONS,
  SUPPORTED_GROUPINGS,
  type Budget,
  type BudgetDirectionScope,
  type BudgetLine,
  type GroupingKey,
  type PhaseId,
} from '../contract'
import { fingerprintOf, type ParsedFilter } from '../lib/filter'
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
  type Meta,
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

// ---- budgetLines（明細の一覧。design doc「明細の一覧」） ----

/**
 * budget の isPrimary な段階を引く。BASIC の `amount` はこの段階1つに絞った軽量な形
 * （design doc「view=BASIC（既定）：…金額…」）。500 で落とすのは、実在する budget の
 * direction スコープに isPrimary が無いのは利用者の誤りではなくデプロイの不整合だから。
 */
function primaryPhaseOf(scope: BudgetDirectionScope, context: string): PhaseId {
  const primary = scope.phases.find((p) => p.isPrimary)
  if (!primary) throw new Error(`no isPrimary phase declared for ${context}`)
  return primary.id
}

/** amounts 配列から特定の段階を取り出す。無ければデプロイの不整合として 500 で落とす */
function pickAmount(amounts: readonly { phase: string; amount: number }[], phase: PhaseId, context: string): { phase: PhaseId; amount: number } {
  const found = amounts.find((a) => a.phase === phase)
  if (!found) throw new Error(`no amount at phase ${phase} for ${context}`)
  return { phase: found.phase as PhaseId, amount: found.amount }
}

/**
 * 保存形式（StoredBudgetLine。団体固有の完全な形）を、view に応じた公開の BudgetLine へ射影する。
 * BASIC はここで全フィールドを削るのではなく、そもそも呼び出し側が hierarchy 等を
 * 詰めないことで表す（optional なので undefined のまま返せば「返らない」と同じ）。
 */
function projectStoredLine(budgetName: string, line: StoredBudgetLine, primaryPhase: PhaseId, view: BudgetLinesView): BudgetLine {
  const cofogFull = line.judgments.cofog
  const base: BudgetLine = {
    name: `${budgetName}/budgetLines/${line.budgetLineId}`,
    budgetLineId: line.budgetLineId,
    budget: budgetName,
    fiscalYear: line.fiscalYear,
    direction: line.direction,
    amount: pickAmount(line.amounts, primaryPhase, `${budgetName}/budgetLines/${line.budgetLineId}`),
    cofog: cofogFull ? { status: cofogFull.status, division: cofogFull.division, consolidation: cofogFull.consolidation } : null,
  }
  if (view === 'BASIC') return base
  return {
    ...base,
    hierarchy: line.hierarchy,
    dimensions: line.dimensions,
    amounts: line.amounts,
    judgments: line.judgments,
  }
}

/**
 * 横断（`-`）の保存形式は元から共通の最小軸しか持たないので、view=BASIC の形へ
 * 直に写せる（FULL はここへ来る前に 400 で弾いている）。
 * 横断の系列は expenditure の COFOG だけが対象（design doc: 歳入は not-applicable）なので direction は固定値。
 */
function projectCrossLine(meta: Meta, line: StoredCrossBudgetLine): BudgetLine {
  const parsed = parseBudgetId(line.budget.slice('budgets/'.length))
  if (!parsed) throw new Error(`cross line has a malformed budget reference: ${line.budget}`)
  const budget = meta.budgetById.get(`${parsed.jurisdiction}:${parsed.fiscalYear}`)
  if (!budget) throw new Error(`cross line references an unknown budget: ${line.budget}`)
  const scope = budget.scopes.expenditure
  if (!scope) throw new Error(`budget ${line.budget} has no expenditure scope but is referenced by a cross line`)
  const primaryPhase = primaryPhaseOf(scope, `${line.budget}/expenditure`)
  return {
    name: `${line.budget}/budgetLines/${line.budgetLineId}`,
    budgetLineId: line.budgetLineId,
    budget: line.budget,
    fiscalYear: line.fiscalYear,
    direction: 'expenditure',
    amount: pickAmount(line.amounts, primaryPhase, `${line.budget}/budgetLines/${line.budgetLineId}`),
    cofog: line.cofog,
  }
}

export const getBudgetLines = os.getBudgetLines.handler(async ({ context, input, errors }) => {
  const pageSize = resolvePageSize(input.pageSize)
  const filter = parseFilterOr400(input.filter, errors)
  if (filter.jurisdiction !== undefined) {
    throw errors.BAD_REQUEST({
      message: 'jurisdiction is not a filter for budgetLines. Specify the parent budget ({jurisdiction}:{year}) instead',
      data: { reason: 'unsupported filter field' },
    })
  }

  if (input.budget === '-') {
    // design doc「FULL は実在する予算を親にしたときだけ許し、`-` では 400 にする」。
    // 団体固有の hierarchy/dimensions は団体を固定しないと意味を持たない。
    if (input.view === 'FULL') {
      throw errors.BAD_REQUEST({
        message: 'view=FULL requires a concrete budget as the parent (jurisdiction-specific fields have no meaning without fixing the jurisdiction). Omit view, or use view=BASIC, for the wildcard parent "-"',
        data: { reason: 'FULL view not supported for wildcard parent' },
      })
    }
    return crossBudgetLines(context.env, filter, pageSize, input.pageToken, input.view, errors)
  }
  return budgetLinesForBudget(context.env, input.budget, filter, pageSize, input.pageToken, input.view, errors)
})

async function crossBudgetLines(
  env: Env,
  filter: ParsedFilter,
  pageSize: number,
  rawToken: string | undefined,
  view: BudgetLinesView,
  errors: Errors,
) {
  if (filter.direction !== undefined || filter.phase !== undefined) {
    throw errors.BAD_REQUEST({
      message: 'direction and phase filters are not supported for cross-budget budgetLines',
      data: { reason: 'unsupported filter field for parent "-"' },
    })
  }
  const division = filter.cofogDivision
  if (division === undefined) {
    throw errors.BAD_REQUEST({
      message: 'cofog.division filter is required for cross-budget budgetLines',
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
  // design doc「ページトークンには問い合わせ全体の指紋を入れる」── view も typed field の
  // 一部なので、フィルタだけでなく view を含めて指紋にする(別 view のトークン流用を防ぐ)。
  const fingerprint = fingerprintOf({ ...filter, view })
  const token =
    rawToken === undefined ? null : verifyToken(rawToken, { revision: meta.revision, family, fingerprint }, errors)
  const chunkIndex = token?.chunk ?? 0
  const offset = token?.off ?? 0

  const chunk = await readJsonAsset<CofogChunkFile>(env, paths.chunk(family, chunkIndex))
  if (chunk === null) {
    // 系列自体が無い（そのフィルタに該当が無い）のは先頭ページだけで正当
    if (token === null) {
      return { lines: [], revision: meta.revision }
    }
    throw errors.BAD_REQUEST({ message: 'pageToken points outside the result set', data: { reason: 'invalid pageToken' } })
  }
  // design doc「実行時は revision の混在を止める」── meta と chunk の revision が
  // 食い違うのは deploy やキャッシュの不整合であって利用者の誤りではないので 500 で落とす
  if (chunk.revision !== meta.revision) {
    throw new Error(`asset revision mismatch (meta=${meta.revision}, asset=${chunk.revision}) for ${paths.chunk(family, chunkIndex)}`)
  }
  checkOffsetInRange(offset, chunk.lines.length, errors)

  const { items, nextOffset } = scanPage<StoredCrossBudgetLine>(chunk.lines, offset, pageSize, () => true)
  let nextPageToken: string | undefined
  if (nextOffset !== null) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: chunkIndex, off: nextOffset, fh: fingerprint })
  } else if (chunk.hasNext) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: chunkIndex + 1, off: 0, fh: fingerprint })
  }
  // design doc「応答の revision は一貫して meta のものにする」（旧実装はチャンク側の revision を返していた）
  return { lines: items.map((l) => projectCrossLine(meta, l)), revision: meta.revision, nextPageToken }
}

async function budgetLinesForBudget(
  env: Env,
  budgetId: string,
  filter: ParsedFilter,
  pageSize: number,
  rawToken: string | undefined,
  view: BudgetLinesView,
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
      message: 'direction filter is required for budgetLines under a budget',
      data: { reason: 'missing required filter' },
    })
  }
  if (!budget.directions.includes(direction)) {
    throw errors.NOT_FOUND({ message: `${direction} is not covered for budget ${budgetId}` })
  }
  const scope = budget.scopes[direction]
  if (!scope) throw new Error(`budget ${budgetId} covers ${direction} but has no scopes.${direction}`)
  const primaryPhase = primaryPhaseOf(scope, `${budgetId}/${direction}`)

  const family = paths.linesFamily(parsed.jurisdiction, parsed.fiscalYear, direction)
  const fingerprint = fingerprintOf({ ...filter, view })
  const token =
    rawToken === undefined ? null : verifyToken(rawToken, { revision: meta.revision, family, fingerprint }, errors)
  const chunkIndex = token?.chunk ?? 0
  const offset = token?.off ?? 0

  const chunk = await readJsonAsset<LinesChunkFile>(env, paths.chunk(family, chunkIndex))
  if (chunk === null) {
    if (token === null) throw new Error(`partition missing for covered budget: ${family}`)
    throw errors.BAD_REQUEST({ message: 'pageToken points outside the result set', data: { reason: 'invalid pageToken' } })
  }
  if (chunk.revision !== meta.revision) {
    throw new Error(`asset revision mismatch (meta=${meta.revision}, asset=${chunk.revision}) for ${paths.chunk(family, chunkIndex)}`)
  }
  checkOffsetInRange(offset, chunk.lines.length, errors)

  const predicate = (line: StoredBudgetLine): boolean => {
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
  const budgetName = `budgets/${budgetId}`
  return {
    lines: items.map((l) => projectStoredLine(budgetName, l, primaryPhase, view)),
    revision: meta.revision,
    nextPageToken,
  }
}

// ---- aggregate（budgets コレクションのカスタムメソッド。design doc「引ける集計の一覧」） ----

/**
 * 集計対象の phase の label を引く。単一 budget の場合は呼び出し側が直接 phaseScope.label を持つので
 * 使わない ── ここは横断（複数団体）で、応答に含める代表 label を選ぶために使う
 * （団体をまたいでも同じ phase id の label は同じはず。異なる場合は最初に見つかったものを使う）。
 */
function findPhaseLabel(meta: Meta, fiscalYear: string, direction: 'expenditure' | 'revenue', phase: string): string {
  for (const b of meta.budgets) {
    if (b.fiscalYear !== fiscalYear) continue
    const found = b.scopes[direction]?.phases.find((p) => p.id === phase)
    if (found) return found.label
  }
  return phase
}

/**
 * budget のリソース名から団体ごとの provenance.sources を組む。実体は団体ごとに1回だけ作る。
 *
 * ⚠️ 以前はここで団体の代表ライセンス（`licenses[0]`）を全出典へ機械的に付け、`kind` も常に
 * `'canonical'` に固定していた。狛江市の事業名は決算資料 PDF（`ingestion/budget/sources.toml`
 * では `redistribute = "review"` / `license_id = "NOASSERTION"`）から起こしており、
 * カタログの CC BY とは権利状態が別なのに canonical と誤表示していた（PR #27 レビュー指摘）。
 * `jurisdiction.provenanceSources`（build.ts が sources.toml から重複排除して組んだもの）を
 * 出典ごとの kind・license のまま使う。
 *
 * `includeJudgment` が false の呼び出し（集計。判断は cofog だけで、事業名の判断は含まない）は
 * canonical だけを結ぶ。true の呼び出し（budgetLines:search で nameField=projectName を含むとき）
 * だけ、事業名の根拠になった judgment 出典も結ぶ ── 実際に応答へ含めた判断に対応する出典だけを
 * 結ぶという設計に合わせ、使っていない判断の出典を混ぜない。
 */
function provenanceSourcesFor(
  meta: Meta,
  jurisdictionIds: readonly string[],
  includeJudgment: boolean,
): {
  sources: { id: string; title: string; path: string | null; license: string; kind: 'canonical' | 'judgment' }[]
  byJurisdiction: Map<string, string[]>
} {
  const sources: { id: string; title: string; path: string | null; license: string; kind: 'canonical' | 'judgment' }[] = []
  const byJurisdiction = new Map<string, string[]>()
  for (const jid of jurisdictionIds) {
    if (byJurisdiction.has(jid)) continue
    const jurisdiction = meta.jurisdictionById.get(jid)
    if (!jurisdiction) throw new Error(`aggregate: unknown jurisdiction referenced by an included budget: ${jid}`)
    const decls = jurisdiction.provenanceSources.filter((s) => s.kind === 'canonical' || includeJudgment)
    const ids: string[] = []
    decls.forEach((s, i) => {
      const id = `${jid}-src-${i}`
      ids.push(id)
      sources.push({ id, title: s.title, path: s.path, license: s.license, kind: s.kind })
    })
    byJurisdiction.set(jid, ids)
  }
  return { sources, byJurisdiction }
}

export const aggregateBudgets = os.aggregateBudgets.handler(async ({ context, input, errors }) => {
  const filter = parseFilterOr400(input.filter, errors)
  if (filter.direction !== undefined || filter.phase !== undefined || filter.cofogDivision !== undefined) {
    throw errors.BAD_REQUEST({
      message:
        'direction, phase, and cofog.division are not filter fields for budgets:aggregate. ' +
        'direction and phase are typed fields; cofog depth is chosen via groupBy',
      data: { reason: 'unsupported filter field' },
    })
  }
  if (input.hierarchyParent !== undefined && !input.groupBy.includes('hierarchy')) {
    throw errors.BAD_REQUEST({
      message: 'hierarchyParent is only usable when groupBy includes "hierarchy"',
      data: { reason: 'hierarchyParent not applicable' },
    })
  }

  const groupByKey = input.groupBy.join(',')
  if (!SUPPORTED_GROUPINGS.some((g) => g.join(',') === groupByKey)) {
    throw errors.BAD_REQUEST({
      message: `unsupported groupBy: [${input.groupBy.join(', ')}]`,
      data: { reason: 'UNSUPPORTED_AGGREGATION', supportedGroupings: mutableGroupings(SUPPORTED_GROUPINGS), supportedDirections: [...SUPPORTED_AGGREGATE_DIRECTIONS] },
    })
  }
  if (input.direction === 'revenue') {
    // ⚠️ 理由は「歳入に COFOG が無い」ではない。hierarchy や fiscalYear の軸は歳入でも意味を持つが、
    // budgets:aggregate 自体が歳入の集計をまだ実装していない（PR #27 レビュー指摘: 以前のメッセージは
    // COFOG が理由であるかのように読め、設計より広く歳入を拒否しているように見えた）。
    throw errors.BAD_REQUEST({
      message: 'budgets:aggregate does not support direction=revenue yet. v1 only implements direction=expenditure ' +
        '(a scope limit of this version, unrelated to whether classification axes apply to revenue)',
      data: {
        reason: 'revenue aggregation not supported in v1',
        supportedGroupings: mutableGroupings(SUPPORTED_GROUPINGS),
        supportedDirections: [...SUPPORTED_AGGREGATE_DIRECTIONS],
      },
    })
  }

  const meta = await readMeta(context.env)

  // design doc「範囲の表し方」: filter だけで範囲を決める。jurisdiction・fiscalYear の
  // 有無の組み合わせが3通りの axis（単一予算 / 同一団体の年度横断 / 団体横断）を分ける。
  if (filter.jurisdiction !== undefined && filter.fiscalYear !== undefined) {
    return singleBudgetAggregate(context.env, meta, filter.jurisdiction, filter.fiscalYear, input, errors)
  }
  if (filter.jurisdiction !== undefined) {
    return jurisdictionYearsAggregate(context.env, meta, filter.jurisdiction, input, errors)
  }
  if (filter.fiscalYear !== undefined) {
    return crossJurisdictionAggregate(context.env, meta, filter.fiscalYear, input, errors)
  }
  throw errors.BAD_REQUEST({
    message: 'filter must specify jurisdiction, fiscalYear, or both for budgets:aggregate',
    data: { reason: 'missing required filter' },
  })
})

type AggregateTypedInput = {
  filter?: string
  direction: 'expenditure' | 'revenue'
  phase: PhaseId
  fund: string
  groupBy: GroupingKey[]
  hierarchyParent?: string
  pageSize?: number
  pageToken?: string
}

const ZERO_STAT = { amount: 0, lineCount: 0 } as const
const ZERO_RESIDUAL = { unclassifiable: ZERO_STAT, outOfScope: ZERO_STAT, notDescended: ZERO_STAT } as const

async function singleBudgetAggregate(
  env: Env,
  meta: Meta,
  jurisdictionId: string,
  fiscalYear: string,
  input: AggregateTypedInput,
  errors: Errors,
) {
  if (!SINGLE_BUDGET_GROUPINGS.some((g) => g.join(',') === input.groupBy.join(','))) {
    throw errors.BAD_REQUEST({
      message:
        `groupBy [${input.groupBy.join(', ')}] is not supported when filter narrows to a single jurisdiction ` +
        '("jurisdiction" cannot be an axis here — every cell would already be that one jurisdiction)',
      data: { reason: 'UNSUPPORTED_AGGREGATION', supportedGroupings: mutableGroupings(SINGLE_BUDGET_GROUPINGS), supportedDirections: [...SUPPORTED_AGGREGATE_DIRECTIONS] },
    })
  }
  if (!meta.jurisdictionById.has(jurisdictionId)) {
    throw errors.NOT_FOUND({ message: `unknown jurisdiction: ${jurisdictionId}` })
  }
  const budgetId = budgetIdOf(jurisdictionId, fiscalYear)
  const budget = meta.budgetById.get(budgetId)
  if (!budget) throw errors.NOT_FOUND({ message: `unknown budget: ${budgetId}` })
  if (input.direction !== 'expenditure') throw new Error('unreachable: revenue is rejected before reaching here')
  if (!budget.directions.includes(input.direction)) {
    throw errors.NOT_FOUND({ message: `${input.direction} is not covered for budget ${budgetId}` })
  }
  const scope = budget.scopes[input.direction]
  if (!scope) throw new Error(`budget ${budgetId} covers ${input.direction} but has no scopes.${input.direction}`)

  const phaseScope = scope.phases.find((p) => p.id === input.phase)
  if (!phaseScope) {
    throw errors.BAD_REQUEST({
      message: `phase "${input.phase}" is not available for ${budgetId}/${input.direction}`,
      data: { reason: 'invalid phase', allowedValues: scope.phases.map((p) => p.id) },
    })
  }
  if (input.fund !== 'all' && !scope.funds.some((f) => f.code === input.fund)) {
    throw errors.BAD_REQUEST({
      message: `fund "${input.fund}" is not available for ${budgetId}/${input.direction}`,
      data: { reason: 'invalid fund', allowedValues: scope.funds.map((f) => f.code) },
    })
  }

  if (input.groupBy[0] === 'hierarchy') {
    return hierarchyAggregate(env, meta, jurisdictionId, fiscalYear, budget, scope, phaseScope, input, errors)
  }

  const depth = cofogDepthOf(input.groupBy)
  const assetPath = paths.aggBudget(jurisdictionId, fiscalYear, input.direction, input.phase, input.fund, depth)
  const asset = await readJsonAsset<AggBudgetsAsset>(env, assetPath)
  if (asset === null) {
    // 契約が許した組み合わせ（SINGLE_BUDGET_GROUPINGS）なのにアセットが無いのは
    // 利用者の誤りではなくデプロイの不整合（design doc: 404 にしない。500 のまま落とす）
    throw new Error(`aggregate asset missing for an allowed combination: ${assetPath}`)
  }
  if (asset.revision !== meta.revision) {
    throw new Error(`aggregate asset revision mismatch (meta=${meta.revision}, asset=${asset.revision}) for ${assetPath}`)
  }

  const pageSize = resolvePageSize(input.pageSize)
  const fingerprint = fingerprintOf({
    filter: input.filter,
    direction: input.direction,
    phase: input.phase,
    fund: input.fund,
    groupBy: groupByFingerprintValue(input.groupBy),
  })
  const family = assetPath
  const token = input.pageToken === undefined ? null : verifyToken(input.pageToken, { revision: meta.revision, family, fingerprint }, errors)
  const offset = token?.off ?? 0
  checkOffsetInRange(offset, asset.cells.length, errors)
  const { items, nextOffset } = scanPage(asset.cells, offset, pageSize, () => true)
  let nextPageToken: string | undefined
  if (nextOffset !== null) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: 0, off: nextOffset, fh: fingerprint })
  }

  const cofogDimension = input.groupBy[0]!
  const cells = items.map((c) => ({
    dimensions: [{ dimension: cofogDimension, code: c.code, label: c.label }],
    amount: c.amount,
    lineCount: c.lineCount,
  }))

  const warnings: { code: 'UNCONSOLIDATED_INTERFUND_TRANSFERS'; message: string }[] = []
  if (input.fund === 'all' && asset.consolidation.eliminated.lineCount > 0) {
    warnings.push({
      code: 'UNCONSOLIDATED_INTERFUND_TRANSFERS',
      message: '会計間の繰出を消去していないため、全会計の合計は移転を二重に含む',
    })
  }

  const jurisdiction = meta.jurisdictionById.get(jurisdictionId)!
  const { sources, byJurisdiction } = provenanceSourcesFor(meta, [jurisdictionId], false)

  return {
    cells,
    residual: asset.residual,
    total: asset.total,
    currency: 'JPY' as const,
    amountUnit: '1' as const,
    query: {
      filter: input.filter ?? '',
      direction: input.direction,
      phase: { id: phaseScope.id, label: phaseScope.label },
      fund: input.fund,
      groupBy: input.groupBy,
      hierarchyParent: null,
      budgets: [budget.name],
      fundScope: {
        funds: input.fund === 'all' ? scope.funds : scope.funds.filter((f) => f.code === input.fund),
        consolidation: asset.consolidation,
      },
    },
    warnings,
    omitted: [],
    supportedGroupings: mutableGroupings(SINGLE_BUDGET_GROUPINGS),
    supportedDirections: [...SUPPORTED_AGGREGATE_DIRECTIONS],
    judgment: ['cofog' as const],
    provenance: {
      sources,
      byBudget: { [budget.name]: byJurisdiction.get(jurisdictionId) ?? [] },
      attribution: `${jurisdiction.label}の予算（${jurisdiction.sources.map((s) => s.title).join('; ')}）を出典とする`,
      modifications: 'COFOG（Classification of the Functions of Government）別の分類は fudoki が行った判断で、原典（自治体の公表資料）には無い',
    },
    revision: meta.revision,
    nextPageToken,
  }
}

async function crossJurisdictionAggregate(
  env: Env,
  meta: Meta,
  fiscalYear: string,
  input: AggregateTypedInput,
  errors: Errors,
) {
  if (input.fund !== 'all') {
    throw errors.BAD_REQUEST({
      message:
        'fund cannot be specified without narrowing filter to a single jurisdiction (fund codes are not aligned across jurisdictions; ' +
        'e.g. the general account is "01" in Mitaka, "1" in Komae, "" in Tama)',
      data: { reason: 'fund requires a single jurisdiction' },
    })
  }
  if (!CROSS_JURISDICTION_GROUPINGS.some((g) => g.join(',') === input.groupBy.join(','))) {
    throw errors.BAD_REQUEST({
      message:
        `groupBy [${input.groupBy.join(', ')}] is missing "jurisdiction". filter has no jurisdiction, so this query spans multiple ` +
        'jurisdictions; summing without a jurisdiction axis would produce a cross-jurisdiction total that does not exist ' +
        '(add "jurisdiction" to groupBy, or narrow filter to a single jurisdiction)',
      data: { reason: 'UNSUPPORTED_AGGREGATION', supportedGroupings: mutableGroupings(CROSS_JURISDICTION_GROUPINGS), supportedDirections: [...SUPPORTED_AGGREGATE_DIRECTIONS] },
    })
  }
  if (input.direction !== 'expenditure') throw new Error('unreachable: revenue is rejected before reaching here')
  const budgetsThisYear = meta.budgets.filter((b) => b.fiscalYear === fiscalYear && b.directions.includes(input.direction))
  if (budgetsThisYear.length === 0) throw errors.NOT_FOUND({ message: `no ${input.direction} budgets for fiscalYear ${fiscalYear}` })
  // ⚠️ phase を検証しないままアセットパスを組むと、契約が許さない (fiscalYear, phase) の組み合わせ
  // （どの団体もその phase を持たない年度）が「アセットが無い」500 になっていた
  // （PR #27 レビュー指摘。利用者の入力誤りは 400 で返す。500 はデプロイの不整合のときだけ）
  const allowedPhases = [...new Set(budgetsThisYear.flatMap((b) => b.scopes[input.direction]?.phases.map((p) => p.id) ?? []))]
  if (!allowedPhases.includes(input.phase)) {
    throw errors.BAD_REQUEST({
      message: `phase "${input.phase}" is not available for any ${input.direction} budget in fiscalYear ${fiscalYear}`,
      data: { reason: 'invalid phase', allowedValues: allowedPhases },
    })
  }

  const depth = cofogDepthOf(input.groupBy)
  const assetPath = paths.aggCross(fiscalYear, input.direction, input.phase, depth)
  const asset = await readJsonAsset<AggCrossAsset>(env, assetPath)
  if (asset === null) {
    throw new Error(`aggregate asset missing for an allowed combination: ${assetPath}`)
  }
  if (asset.revision !== meta.revision) {
    throw new Error(`aggregate asset revision mismatch (meta=${meta.revision}, asset=${asset.revision}) for ${assetPath}`)
  }

  const pageSize = resolvePageSize(input.pageSize)
  const fingerprint = fingerprintOf({
    filter: input.filter,
    direction: input.direction,
    phase: input.phase,
    fund: input.fund,
    groupBy: groupByFingerprintValue(input.groupBy),
  })
  const family = assetPath
  const token = input.pageToken === undefined ? null : verifyToken(input.pageToken, { revision: meta.revision, family, fingerprint }, errors)
  const offset = token?.off ?? 0
  checkOffsetInRange(offset, asset.cells.length, errors)
  const { items, nextOffset } = scanPage(asset.cells, offset, pageSize, () => true)
  let nextPageToken: string | undefined
  if (nextOffset !== null) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: 0, off: nextOffset, fh: fingerprint })
  }

  const cofogDimension = input.groupBy.find((g) => g !== 'jurisdiction')!
  const cells = items.map((c) => ({
    dimensions: [
      { dimension: 'jurisdiction' as const, code: c.jurisdiction, label: c.jurisdictionLabel },
      { dimension: cofogDimension, code: c.code, label: c.label },
    ],
    amount: c.amount,
    lineCount: c.lineCount,
  }))

  const warnings: { code: 'UNCONSOLIDATED_INTERFUND_TRANSFERS'; message: string }[] = []
  if (asset.consolidation.eliminated.lineCount > 0) {
    warnings.push({
      code: 'UNCONSOLIDATED_INTERFUND_TRANSFERS',
      message: '会計間の繰出を消去していないため、全会計の合計は移転を二重に含む',
    })
  }

  const includedJurisdictionIds = asset.includedBudgets.map((b) => parseBudgetId(b.split('/')[1]!)?.jurisdiction ?? fail())
  const { sources, byJurisdiction } = provenanceSourcesFor(meta, includedJurisdictionIds, false)
  const byBudget: Record<string, string[]> = {}
  for (const budgetName of asset.includedBudgets) {
    const parsed = parseBudgetId(budgetName.split('/')[1]!)
    if (!parsed) throw new Error(`aggregate: malformed budget id in includedBudgets: ${budgetName}`)
    byBudget[budgetName] = byJurisdiction.get(parsed.jurisdiction) ?? []
  }
  const attributionParts = [...new Set(includedJurisdictionIds)].map((jid) => meta.jurisdictionById.get(jid)?.label ?? jid)

  return {
    cells,
    // design doc「団体をまたいで足さない」── total と同じ理由で、団体をまたいだ単一の residual も
    // 存在しない。cells が jurisdiction を軸に必須なので、残余も団体ごとに返す
    // （PR #27 レビュー指摘。以前は全団体を1つの residual に合算しており、団体ごとに
    // cells + residual を復元できなかった）
    residualByJurisdiction: asset.residualByJurisdiction,
    // total は返さない（filter が複数団体にまたがるため。design doc「団体をまたいで足さない」）
    currency: 'JPY' as const,
    amountUnit: '1' as const,
    query: {
      filter: input.filter ?? '',
      direction: input.direction,
      phase: { id: input.phase, label: findPhaseLabel(meta, fiscalYear, input.direction, input.phase) },
      fund: input.fund,
      groupBy: input.groupBy,
      hierarchyParent: null,
      budgets: asset.includedBudgets,
      // 会計コードは団体で揃わないため、横断では個々の会計を列挙しない（design doc Caveats 3）
      fundScope: { funds: [], consolidation: asset.consolidation },
    },
    warnings,
    omitted: asset.omittedBudgets,
    supportedGroupings: mutableGroupings(CROSS_JURISDICTION_GROUPINGS),
    supportedDirections: [...SUPPORTED_AGGREGATE_DIRECTIONS],
    judgment: ['cofog' as const],
    provenance: {
      sources,
      byBudget,
      attribution: `${attributionParts.join('、')}の予算を出典とする`,
      modifications: 'COFOG（Classification of the Functions of Government）別の分類は fudoki が行った判断で、原典（各自治体の公表資料）には無い',
    },
    revision: meta.revision,
    nextPageToken,
  }
}

// ---- hierarchy 軸（design doc Tasks 5）。単一 budget の科目階層集計 ----

/**
 * hierarchy / hierarchy,cofog.division を集計する。呼び出し元（singleBudgetAggregate）が
 * jurisdiction・budget・direction・phase・fund の存在をすでに検証済み。
 */
async function hierarchyAggregate(
  env: Env,
  meta: Meta,
  jurisdictionId: string,
  fiscalYear: string,
  budget: Budget,
  scope: BudgetDirectionScope,
  phaseScope: { id: PhaseId; label: string },
  input: AggregateTypedInput,
  errors: Errors,
) {
  // 款・項のコードは会計内でしか一意でない（COFOG と違い fudoki の判断による正規化を経ていない）。
  // "all" のまま kan/kou コードだけで合算すると、会計をまたいで別カテゴリを1つのセルへ混ぜてしまう
  // （実測: 三鷹市の kan_code "01" は一般会計で議会費、国保特別会計で総務費）。
  // design doc は fund と hierarchy の相互作用を明記していないため、これはこの実装での判断。
  if (input.fund === 'all') {
    throw errors.BAD_REQUEST({
      message:
        'hierarchy aggregation requires a specific fund. kan/kou codes are meaningful only within one fund ' +
        '(unlike COFOG codes, which are a fudoki judgment normalized across funds), so summing across funds by ' +
        'code would merge unrelated categories',
      data: { reason: 'fund required for hierarchy aggregation', allowedValues: scope.funds.map((f) => f.code) },
    })
  }

  const parsed = input.hierarchyParent === undefined ? [] : parseHierarchyParent(input.hierarchyParent)
  if (!Array.isArray(parsed)) {
    throw errors.BAD_REQUEST({ message: parsed.error, data: { reason: 'invalid hierarchyParent' } })
  }
  const childLevel = hierarchyChildLevel(parsed)
  const parentPath = hierarchyParentPathString(parsed)
  const includesCofog = input.groupBy.length === 2

  const assetPath = includesCofog
    ? paths.aggHierarchyCofog(jurisdictionId, fiscalYear, input.direction, input.phase, input.fund, parentPath)
    : paths.aggHierarchy(jurisdictionId, fiscalYear, input.direction, input.phase, input.fund, parentPath)
  const asset = includesCofog
    ? await readJsonAsset<AggHierarchyCofogAsset>(env, assetPath)
    : await readJsonAsset<AggHierarchyAsset>(env, assetPath)
  if (asset === null) {
    // hierarchyParent は自由入力なので、根拠のない親（存在しない款・項）を指した場合もここに来る。
    // 契約は "kan=XX" の形式までしか縛れず中身までは検証していないので、これは利用者の誤りでもありうる
    // ── ただし build はデータに実在する親のパスをすべて生成しているので、実在する親なら必ずアセットがある。
    throw errors.NOT_FOUND({ message: `no data at hierarchyParent "${parentPath}" for ${budget.id}/${input.direction}` })
  }
  if (asset.revision !== meta.revision) {
    throw new Error(`aggregate asset revision mismatch (meta=${meta.revision}, asset=${asset.revision}) for ${assetPath}`)
  }

  const pageSize = resolvePageSize(input.pageSize)
  const fingerprint = fingerprintOf({
    filter: input.filter,
    direction: input.direction,
    phase: input.phase,
    fund: input.fund,
    groupBy: groupByFingerprintValue(input.groupBy),
    hierarchyParent: input.hierarchyParent ?? '',
  })
  const family = assetPath
  const token = input.pageToken === undefined ? null : verifyToken(input.pageToken, { revision: meta.revision, family, fingerprint }, errors)
  const offset = token?.off ?? 0
  checkOffsetInRange(offset, asset.cells.length, errors)
  const { items, nextOffset } = scanPage(asset.cells, offset, pageSize, () => true)
  let nextPageToken: string | undefined
  if (nextOffset !== null) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: 0, off: nextOffset, fh: fingerprint })
  }

  const cells = includesCofog
    ? (items as AggHierarchyCofogAsset['cells']).map((c) => ({
        dimensions: [
          { dimension: 'hierarchy' as const, code: c.code, label: c.label },
          { dimension: 'cofog.division' as const, code: c.cofogDivision, label: c.cofogLabel },
        ],
        amount: c.amount,
        lineCount: c.lineCount,
      }))
    : (items as AggHierarchyAsset['cells']).map((c) => ({
        dimensions: [{ dimension: 'hierarchy' as const, code: c.code, label: c.label }],
        amount: c.amount,
        lineCount: c.lineCount,
      }))

  // fund は特定の会計コードなので会計間の繰出という概念自体が無く、UNCONSOLIDATED_INTERFUND_TRANSFERS は起きない
  const residual = includesCofog ? (asset as AggHierarchyCofogAsset).residual : ZERO_RESIDUAL

  const jurisdiction = meta.jurisdictionById.get(jurisdictionId)!
  const { sources, byJurisdiction } = provenanceSourcesFor(meta, [jurisdictionId], false)

  return {
    cells,
    residual,
    total: asset.total,
    currency: 'JPY' as const,
    amountUnit: '1' as const,
    query: {
      filter: input.filter ?? '',
      direction: input.direction,
      phase: { id: phaseScope.id, label: phaseScope.label },
      fund: input.fund,
      groupBy: input.groupBy,
      hierarchyParent: input.hierarchyParent ?? null,
      budgets: [budget.name],
      fundScope: { funds: scope.funds.filter((f) => f.code === input.fund), consolidation: scope.consolidation },
    },
    warnings: [],
    omitted: [],
    supportedGroupings: mutableGroupings(SINGLE_BUDGET_GROUPINGS),
    supportedDirections: [...SUPPORTED_AGGREGATE_DIRECTIONS],
    judgment: includesCofog ? ['cofog' as const] : [],
    provenance: {
      sources,
      byBudget: { [budget.name]: byJurisdiction.get(jurisdictionId) ?? [] },
      attribution: `${jurisdiction.label}の予算（${jurisdiction.sources.map((s) => s.title).join('; ')}）を出典とする`,
      modifications: includesCofog
        ? 'COFOG（Classification of the Functions of Government）別の分類は fudoki が行った判断で、原典（自治体の公表資料）には無い'
        : '款・項・目の階層は原典のとおりで、fudoki の判断は加えていない',
    },
    revision: meta.revision,
    nextPageToken,
  }
}

// ---- fiscalYear 軸（design doc Tasks 6）。同一団体の年度横断 ----

function findPhaseLabelForJurisdiction(meta: Meta, jurisdictionId: string, direction: 'expenditure' | 'revenue', phase: string): string {
  for (const b of meta.budgets) {
    if (b.jurisdictionId !== jurisdictionId) continue
    const found = b.scopes[direction]?.phases.find((p) => p.id === phase)
    if (found) return found.label
  }
  return phase
}

async function jurisdictionYearsAggregate(
  env: Env,
  meta: Meta,
  jurisdictionId: string,
  input: AggregateTypedInput,
  errors: Errors,
) {
  if (!meta.jurisdictionById.has(jurisdictionId)) {
    throw errors.NOT_FOUND({ message: `unknown jurisdiction: ${jurisdictionId}` })
  }
  if (!JURISDICTION_YEARS_GROUPINGS.some((g) => g.join(',') === input.groupBy.join(','))) {
    throw errors.BAD_REQUEST({
      message:
        `groupBy [${input.groupBy.join(', ')}] is not supported when filter narrows to a jurisdiction without a fiscalYear ` +
        '(expected "fiscalYear" or "fiscalYear,cofog.division" — aggregating across years of one jurisdiction)',
      data: { reason: 'UNSUPPORTED_AGGREGATION', supportedGroupings: mutableGroupings(JURISDICTION_YEARS_GROUPINGS), supportedDirections: [...SUPPORTED_AGGREGATE_DIRECTIONS] },
    })
  }
  if (input.hierarchyParent !== undefined) {
    throw errors.BAD_REQUEST({
      message: 'hierarchyParent is not usable with the fiscalYear axis',
      data: { reason: 'hierarchyParent not applicable' },
    })
  }
  if (input.direction !== 'expenditure') throw new Error('unreachable: revenue is rejected before reaching here')

  const budgetsForJ = meta.budgets.filter((b) => b.jurisdictionId === jurisdictionId && b.directions.includes('expenditure'))
  if (budgetsForJ.length === 0) throw errors.NOT_FOUND({ message: `no expenditure budgets for jurisdiction ${jurisdictionId}` })

  // ⚠️ phase・fund を検証しないままアセットパスを組むと、この団体のどの年度も持たない組み合わせ
  // （例: 狛江市に存在しない phase=approved）が「アセットが無い」500 になっていた
  // （PR #27 レビュー指摘。build はこの団体のどこかの年度に実在する (phase, fund) の組しか
  // アセットを作らないので、実在しない組を利用者の入力誤りとして 400 で返す）
  const allowedPhases = [...new Set(budgetsForJ.flatMap((b) => b.scopes.expenditure?.phases.map((p) => p.id) ?? []))]
  if (!allowedPhases.includes(input.phase)) {
    throw errors.BAD_REQUEST({
      message: `phase "${input.phase}" is not available for any expenditure budget of jurisdiction ${jurisdictionId}`,
      data: { reason: 'invalid phase', allowedValues: allowedPhases },
    })
  }
  if (input.fund !== 'all') {
    const allowedFunds = [...new Set(budgetsForJ.flatMap((b) => b.scopes.expenditure?.funds.map((f) => f.code) ?? []))]
    if (!allowedFunds.includes(input.fund)) {
      throw errors.BAD_REQUEST({
        message: `fund "${input.fund}" is not available for any expenditure budget of jurisdiction ${jurisdictionId}`,
        data: { reason: 'invalid fund', allowedValues: allowedFunds },
      })
    }
  }

  const includesCofog = input.groupBy.length === 2
  const assetPath = includesCofog
    ? paths.aggYearsCofogDivision(jurisdictionId, input.direction, input.phase, input.fund)
    : paths.aggYearsTotal(jurisdictionId, input.direction, input.phase, input.fund)
  const asset = includesCofog
    ? await readJsonAsset<AggYearsCofogDivisionAsset>(env, assetPath)
    : await readJsonAsset<AggYearsTotalAsset>(env, assetPath)
  if (asset === null) {
    throw new Error(`aggregate asset missing for an allowed combination: ${assetPath}`)
  }
  if (asset.revision !== meta.revision) {
    throw new Error(`aggregate asset revision mismatch (meta=${meta.revision}, asset=${asset.revision}) for ${assetPath}`)
  }

  const pageSize = resolvePageSize(input.pageSize)
  const fingerprint = fingerprintOf({
    filter: input.filter,
    direction: input.direction,
    phase: input.phase,
    fund: input.fund,
    groupBy: groupByFingerprintValue(input.groupBy),
  })
  const family = assetPath
  const token = input.pageToken === undefined ? null : verifyToken(input.pageToken, { revision: meta.revision, family, fingerprint }, errors)
  const offset = token?.off ?? 0
  checkOffsetInRange(offset, asset.cells.length, errors)
  const { items, nextOffset } = scanPage(asset.cells, offset, pageSize, () => true)
  let nextPageToken: string | undefined
  if (nextOffset !== null) {
    nextPageToken = encodePageToken({ v: 1, rev: meta.revision, family, chunk: 0, off: nextOffset, fh: fingerprint })
  }

  const cells = includesCofog
    ? (items as AggYearsCofogDivisionAsset['cells']).map((c) => ({
        dimensions: [
          { dimension: 'fiscalYear' as const, code: c.fiscalYear, label: null },
          { dimension: 'cofog.division' as const, code: c.cofogDivision, label: c.cofogLabel },
        ],
        amount: c.amount,
        lineCount: c.lineCount,
        fundScope: c.fundScope,
      }))
    : (items as AggYearsTotalAsset['cells']).map((c) => ({
        dimensions: [{ dimension: 'fiscalYear' as const, code: c.fiscalYear, label: null }],
        amount: c.amount,
        lineCount: c.lineCount,
        fundScope: c.fundScope,
      }))

  const residual = includesCofog
    ? Object.values((asset as AggYearsCofogDivisionAsset).residualByYear).reduce(
        (s, r) => ({
          unclassifiable: { amount: s.unclassifiable.amount + r.unclassifiable.amount, lineCount: s.unclassifiable.lineCount + r.unclassifiable.lineCount },
          outOfScope: { amount: s.outOfScope.amount + r.outOfScope.amount, lineCount: s.outOfScope.lineCount + r.outOfScope.lineCount },
          notDescended: { amount: s.notDescended.amount + r.notDescended.amount, lineCount: s.notDescended.lineCount + r.notDescended.lineCount },
        }),
        { unclassifiable: { amount: 0, lineCount: 0 }, outOfScope: { amount: 0, lineCount: 0 }, notDescended: { amount: 0, lineCount: 0 } },
      )
    : ZERO_RESIDUAL

  // design doc「total は範囲が1つの団体に閉じているときだけ返す」「範囲全体の要約は
  // アセットに一度だけ持つ」── total と query.fundScope はアセットが範囲全体（全年度）に
  // ついて一度だけ計算した値を使う。ページ後の cells から作り直すと pageSize で値が変わる
  // （PR #27 レビュー指摘: 全件 total と pageSize=1 の total が食い違っていた）
  const total = asset.total

  const omitted = asset.omittedYears.map((o) => ({ budget: `budgets/${jurisdictionId}:${o.fiscalYear}`, code: o.code }))

  const jurisdiction = meta.jurisdictionById.get(jurisdictionId)!
  const { sources, byJurisdiction } = provenanceSourcesFor(meta, [jurisdictionId], false)
  const budgetsIncluded = budgetsForJ
    .filter((b) => !asset.omittedYears.some((o) => o.fiscalYear === b.fiscalYear))
    .map((b) => b.name)
    .sort()

  return {
    cells,
    residual,
    total,
    currency: 'JPY' as const,
    amountUnit: '1' as const,
    query: {
      filter: input.filter ?? '',
      direction: input.direction,
      phase: { id: input.phase, label: findPhaseLabelForJurisdiction(meta, jurisdictionId, input.direction, input.phase) },
      fund: input.fund,
      groupBy: input.groupBy,
      hierarchyParent: null,
      budgets: budgetsIncluded,
      // 年度をまたぐ union（design doc: セルごとの fundScope が正）。アセットが範囲全体について
      // 一度だけ計算した値を使う（cells から作り直すと、cofog 軸で年度内の division 数だけ
      // consolidation を二重に数えてしまう。PR #27 レビュー指摘）
      fundScope: asset.fundScope,
    },
    warnings: [],
    omitted,
    supportedGroupings: mutableGroupings(JURISDICTION_YEARS_GROUPINGS),
    supportedDirections: [...SUPPORTED_AGGREGATE_DIRECTIONS],
    judgment: includesCofog ? ['cofog' as const] : [],
    provenance: {
      sources,
      byBudget: Object.fromEntries(budgetsIncluded.map((name) => [name, byJurisdiction.get(jurisdictionId) ?? []])),
      attribution: `${jurisdiction.label}の予算（${jurisdiction.sources.map((s) => s.title).join('; ')}）を出典とする`,
      modifications: includesCofog
        ? 'COFOG（Classification of the Functions of Government）別の分類は fudoki が行った判断で、原典（自治体の公表資料）には無い'
        : '',
    },
    revision: meta.revision,
    nextPageToken,
  }
}

/** readonly な groupBy allowlist を、エラー応答の data（mutable な string[][]）へ変換する */
function mutableGroupings(groupings: readonly (readonly GroupingKey[])[]): GroupingKey[][] {
  return groupings.map((g) => [...g])
}

/** pageToken の指紋に groupBy を含めるための正規化（配列の要素順は仕様上意味を持つのでそのまま結合する） */
function groupByFingerprintValue(groupBy: readonly GroupingKey[]): string {
  return groupBy.join(',')
}

function fail(): never {
  throw new Error('aggregate: malformed budget id encountered while building provenance')
}

// ---- budgetLines:search（design doc「名称の検索」） ----

const ALL_NAME_FIELDS: readonly NameFieldValue[] = ['accountLabel', 'projectName']
/** 原典に名称が無いことが scopes.names.hierarchy から判定できる階層（design doc: 狛江市の款・項・目） */
const NAME_SCOPED_LEVELS = new Set(['kan', 'kou', 'moku'])

type SearchTypedInput = {
  query: string
  filter?: string
  direction?: 'expenditure' | 'revenue'
  phase?: PhaseId
  fund?: string
  nameField?: NameFieldValue[]
  level?: string
  pageSize?: number
  pageToken?: string
}

/**
 * level（kan/kou/moku）が budgetsInScope のどの (budget, direction) にも
 * canonical な名称を持たないかどうか。design doc「原典が名称を持たない階層を level に
 * 指定した検索は、0件ではなく400を返す」の判定に使う。
 */
function levelHasNoNamesAnywhere(
  budgetsInScope: readonly Budget[],
  level: string,
  directionsToCheck: readonly ('expenditure' | 'revenue')[],
): boolean {
  for (const b of budgetsInScope) {
    for (const dir of directionsToCheck) {
      const scope = b.scopes[dir]
      if (!scope) continue
      const h = scope.names.hierarchy.find((h) => h.level === level)
      if (h?.hasName) return false
    }
  }
  return true
}

function canUseProjectNameInstead(budgetsInScope: readonly Budget[], directionsToCheck: readonly ('expenditure' | 'revenue')[]): boolean {
  return budgetsInScope.some((b) => directionsToCheck.some((dir) => b.scopes[dir]?.names.projectName != null))
}

type NamedCoverageEntry = {
  budget: string
  field: NameFieldValue
  funds: { code: string; label: string | null }[]
  code: 'NO_NAMES' | 'PARTIAL_NAMES'
  message: string
}

/**
 * 完全でない (budget, field) の組だけを列挙する（design doc「coverage は固定値にせず、
 * filter で絞られた範囲について計算する」）。フルカバレッジの組は列挙しない。
 */
function computeNamedCoverage(
  budgetsInScope: readonly Budget[],
  nameFields: readonly NameFieldValue[],
  level: string | undefined,
  directionsToCheck: readonly ('expenditure' | 'revenue')[],
): NamedCoverageEntry[] {
  const out: NamedCoverageEntry[] = []
  for (const b of budgetsInScope) {
    for (const dir of directionsToCheck) {
      const scope = b.scopes[dir]
      if (!scope) continue
      if (nameFields.includes('accountLabel') && level !== undefined && NAME_SCOPED_LEVELS.has(level)) {
        const h = scope.names.hierarchy.find((h) => h.level === level)
        if (h && !h.hasName) {
          out.push({
            budget: b.name,
            field: 'accountLabel',
            funds: scope.funds,
            code: 'NO_NAMES',
            message: `${level} has no canonical name in the raw data for ${b.id}/${dir}`,
          })
        }
      }
      if (nameFields.includes('projectName')) {
        const pn = scope.names.projectName
        if (pn === null) {
          out.push({
            budget: b.name,
            field: 'projectName',
            funds: scope.funds,
            code: 'NO_NAMES',
            message: `no project_names mapping exists for ${b.id}/${dir}`,
          })
        } else if (!pn.fiscalYears.includes(b.fiscalYear)) {
          out.push({
            budget: b.name,
            field: 'projectName',
            funds: scope.funds.filter((f) => pn.funds.includes(f.code)),
            code: 'PARTIAL_NAMES',
            message: `project names only cover fiscal years ${pn.fiscalYears.join(', ')} for ${b.jurisdictionId}/${dir} (this budget is ${b.fiscalYear})`,
          })
        } else if (pn.funds.length < scope.funds.length) {
          out.push({
            budget: b.name,
            field: 'projectName',
            funds: scope.funds.filter((f) => pn.funds.includes(f.code)),
            code: 'PARTIAL_NAMES',
            message: `project names only cover fund(s) ${pn.funds.join(', ')} (out of ${scope.funds.map((f) => f.code).join(', ')}) for ${b.id}/${dir}`,
          })
        }
      }
    }
  }
  return out
}

/**
 * 名称索引の1件（NameIndexEntry）×1 ref を、応答を組む前の中間形へ展開したもの。
 * jurisdiction/fiscalYear/direction は ref の budgetLineId から機械的に決まる
 * （parseBudgetLineId）ので、この段階まで運んでおく。hierarchy・amounts はまだ持たない
 * （resolveLine で取りに行く。ページに乗る分だけ解決すれば足りるため、ここでは持たせない）。
 */
type SearchCandidate = {
  matched: { field: NameFieldValue; level: string; value: string }
  nameSource: 'canonical' | 'judgment'
  budgetLineId: string
  jurisdiction: string
  fiscalYear: string
  direction: 'expenditure' | 'revenue'
  fund: { code: string; label: string | null }
}

/** budgetLineId 昇順（同一 id 内は field, level, value の順）。design doc「並び順は明細識別子の昇順に固定する」 */
function compareCandidates(a: SearchCandidate, b: SearchCandidate): number {
  if (a.budgetLineId !== b.budgetLineId) return a.budgetLineId < b.budgetLineId ? -1 : 1
  if (a.matched.field !== b.matched.field) return a.matched.field < b.matched.field ? -1 : 1
  if (a.matched.level !== b.matched.level) return a.matched.level < b.matched.level ? -1 : 1
  return a.matched.value < b.matched.value ? -1 : a.matched.value > b.matched.value ? 1 : 0
}

/**
 * 名称索引を全チャンク走査し（design doc「1回のリクエストで全チャンクを走査して該当を集める」）、
 * query・nameField・level・direction・fund・jurisdiction/fiscalYear で絞った候補を集めて返す。
 * field/level/value による絞り込みは NameIndexEntry 単位（索引の単位）でできるので、
 * refs へ降りるのは実際にマッチしたエントリだけ ── コースな階層（款など）で無い限り、
 * 実際に展開する ref の数は索引の全件数よりずっと小さい。
 */
async function gatherSearchCandidates(
  env: Env,
  meta: Meta,
  family: string,
  typedInput: SearchTypedInput,
  nameFields: readonly NameFieldValue[],
  budgetIdSet: ReadonlySet<string>,
): Promise<SearchCandidate[]> {
  const entryMatches = (entry: NameIndexEntry): boolean => {
    if (!nameFields.includes(entry.field)) return false
    if (typedInput.level !== undefined) {
      if (entry.field === 'accountLabel' && entry.level !== typedInput.level) return false
      if (entry.field === 'projectName' && typedInput.level !== 'daijigyo') return false
    }
    return entry.value.includes(typedInput.query)
  }

  const candidates: SearchCandidate[] = []
  for (let chunkIndex = 0; ; chunkIndex++) {
    const chunk = await readJsonAsset<NameIndexChunkFile>(env, paths.chunk(family, chunkIndex))
    if (chunk === null) break
    if (chunk.revision !== meta.revision) {
      throw new Error(`asset revision mismatch (meta=${meta.revision}, asset=${chunk.revision}) for ${paths.chunk(family, chunkIndex)}`)
    }
    for (const entry of chunk.lines) {
      if (!entryMatches(entry)) continue
      for (const ref of entry.refs) {
        const parsed = parseBudgetLineId(ref.budgetLineId)
        if (parsed === null) throw new Error(`name index ref has a malformed budgetLineId: ${ref.budgetLineId}`)
        if (!budgetIdSet.has(`${parsed.jurisdiction}:${parsed.fiscalYear}`)) continue
        if (typedInput.direction !== undefined && parsed.direction !== typedInput.direction) continue
        if (typedInput.fund !== undefined && ref.fund.code !== typedInput.fund) continue
        candidates.push({
          matched: { field: entry.field, level: entry.level, value: entry.value },
          nameSource: entry.nameSource,
          budgetLineId: ref.budgetLineId,
          jurisdiction: parsed.jurisdiction,
          fiscalYear: parsed.fiscalYear,
          direction: parsed.direction,
          fund: ref.fund,
        })
      }
    }
    if (!chunk.hasNext) break
  }
  candidates.sort(compareCandidates)
  return candidates
}

/**
 * budgetLineId から明細本体（hierarchy・amounts）を引く。名称索引は明細を丸ごと持たない
 * （NameIndexEntry のコメント参照）ので、応答を組むときに `lines/{jurisdiction}/{fiscalYear}-{direction}`
 * チャンクへ戻る。family 単位でメモ化し、同じ (jurisdiction, fiscalYear, direction) を指す
 * 複数の候補が1回のアセット読み込みで済むようにする。
 */
function makeLineResolver(env: Env, meta: Meta): (c: SearchCandidate) => Promise<StoredBudgetLine> {
  const familyCache = new Map<string, Promise<Map<string, StoredBudgetLine>>>()
  return async (c) => {
    const family = paths.linesFamily(c.jurisdiction, c.fiscalYear, c.direction)
    let loading = familyCache.get(family)
    if (loading === undefined) {
      loading = loadLinesFamily(env, meta, family)
      familyCache.set(family, loading)
    }
    const lines = await loading
    const line = lines.get(c.budgetLineId)
    if (line === undefined) throw new Error(`name index references a budget line missing from ${family}: ${c.budgetLineId}`)
    return line
  }
}

async function loadLinesFamily(env: Env, meta: Meta, family: string): Promise<Map<string, StoredBudgetLine>> {
  const out = new Map<string, StoredBudgetLine>()
  for (let chunkIndex = 0; ; chunkIndex++) {
    const chunk = await readJsonAsset<LinesChunkFile>(env, paths.chunk(family, chunkIndex))
    if (chunk === null) break
    if (chunk.revision !== meta.revision) {
      throw new Error(`asset revision mismatch (meta=${meta.revision}, asset=${chunk.revision}) for ${paths.chunk(family, chunkIndex)}`)
    }
    for (const line of chunk.lines) out.set(line.budgetLineId, line)
    if (!chunk.hasNext) break
  }
  return out
}

export const searchBudgetLines = os.searchBudgetLines.handler(async ({ context, input, errors }) => {
  const typedInput = input as SearchTypedInput
  const filter = parseFilterOr400(typedInput.filter, errors)
  if (filter.direction !== undefined || filter.phase !== undefined || filter.cofogDivision !== undefined) {
    throw errors.BAD_REQUEST({
      message: 'only jurisdiction and fiscalYear filters are supported for budgetLines:search; direction/phase/fund are typed fields',
      data: { reason: 'unsupported filter field' },
    })
  }
  if (typedInput.fund !== undefined && filter.jurisdiction === undefined) {
    throw errors.BAD_REQUEST({
      message:
        'fund cannot be specified without narrowing filter to a single jurisdiction (fund codes are not aligned across jurisdictions; ' +
        'e.g. the general account is "01" in Mitaka, "1" in Komae, "" in Tama)',
      data: { reason: 'fund requires a single jurisdiction' },
    })
  }

  const meta = await readMeta(context.env)
  if (filter.jurisdiction !== undefined && !meta.jurisdictionById.has(filter.jurisdiction)) {
    throw errors.NOT_FOUND({ message: `unknown jurisdiction: ${filter.jurisdiction}` })
  }
  const budgetsInScope = meta.budgets.filter(
    (b) =>
      (filter.jurisdiction === undefined || b.jurisdictionId === filter.jurisdiction) &&
      (filter.fiscalYear === undefined || b.fiscalYear === filter.fiscalYear) &&
      (typedInput.direction === undefined || b.directions.includes(typedInput.direction)),
  )
  if (budgetsInScope.length === 0) {
    throw errors.NOT_FOUND({ message: 'no budgets match the given filter/direction for budgetLines:search' })
  }

  const nameFields = typedInput.nameField ?? ALL_NAME_FIELDS
  const directionsToCheck: readonly ('expenditure' | 'revenue')[] =
    typedInput.direction !== undefined ? [typedInput.direction] : (['expenditure', 'revenue'] as const)

  // design doc: 原典が名称を持たない階層（狛江市の款・項・目）を level に指定した検索は 400
  if (
    typedInput.level !== undefined &&
    NAME_SCOPED_LEVELS.has(typedInput.level) &&
    nameFields.includes('accountLabel') &&
    levelHasNoNamesAnywhere(budgetsInScope, typedInput.level, directionsToCheck)
  ) {
    const alt = canUseProjectNameInstead(budgetsInScope, directionsToCheck)
    throw errors.BAD_REQUEST({
      message:
        `level "${typedInput.level}" has no canonical name in the raw data for the given scope. ` +
        (alt
          ? 'Try nameField=["projectName"] instead (fudoki\'s judgment-based mapping), or search a different level.'
          : 'No projectName mapping is available for this scope either.'),
      data: { reason: 'level has no canonical names' },
    })
  }

  const fingerprint = fingerprintOf({
    filter: typedInput.filter,
    direction: typedInput.direction,
    phase: typedInput.phase,
    fund: typedInput.fund,
    nameField: [...nameFields].sort().join(','),
    level: typedInput.level ?? '',
    query: typedInput.query,
  })
  const family = paths.searchAll
  const pageSize = resolvePageSize(typedInput.pageSize)
  const token = typedInput.pageToken === undefined ? null : verifyToken(typedInput.pageToken, { revision: meta.revision, family, fingerprint }, errors)
  const offset = token?.off ?? 0

  const budgetIdSet = new Set(budgetsInScope.map((b) => b.id))

  const namedCoverage = computeNamedCoverage(budgetsInScope, nameFields, typedInput.level, directionsToCheck)
  const jurisdictionIds = [...new Set(budgetsInScope.map((b) => b.jurisdictionId))].sort()
  const { sources, byJurisdiction } = provenanceSourcesFor(meta, jurisdictionIds, nameFields.includes('projectName'))
  const byBudget: Record<string, string[]> = {}
  for (const b of budgetsInScope) byBudget[b.name] = byJurisdiction.get(b.jurisdictionId) ?? []
  const attribution = `${jurisdictionIds.map((jid) => meta.jurisdictionById.get(jid)?.label ?? jid).join('、')}の予算を出典とする`
  const modifications = nameFields.includes('projectName')
    ? '事業名（projectName）は fudoki が決算資料等から対応づけた判断で、原典（自治体の公表資料）には無い'
    : ''
  const judgment = nameFields.includes('projectName') ? (['projectName'] as const) : []

  const emptyOutput = () => ({
    matches: [] as SearchMatch[],
    coverage: { searchedNameFields: [...nameFields], namedCoverage },
    judgment: [...judgment],
    provenance: { sources, byBudget, attribution, modifications },
    revision: meta.revision,
  })

  // design doc「1回のリクエストで索引全体を走査できる大きさにする」「チャンクに割る場合も、
  // 1回のリクエストで全チャンクを走査して該当を集める（1チャンクで打ち切らない）」。
  // 索引は名称の単位で小さいので、フィルタに合う候補（budgetLineId 昇順）を毎回このまま作り直す
  // ── 同じ revision・同じ入力なら決定的に同じ列になるので、offset をその列への位置として使い回せる。
  const candidates = await gatherSearchCandidates(context.env, meta, family, typedInput, nameFields, budgetIdSet)
  checkOffsetInRange(offset, candidates.length, errors)

  // design doc「ページングは「該当」に対して行う」「該当が0件のページを返さない」。
  // phase フィルタは明細の amounts を解決しないと判定できないので、offset から候補を1件ずつ
  // 解決しながら pageSize 件集まるか候補が尽きるまで進める（1リクエスト内で完結させる。
  // scanPage と同じ「フィルタで落ちても offset は生の位置で進める」考え方の非同期版）。
  const resolveLine = makeLineResolver(context.env, meta)
  const matches: SearchMatch[] = []
  let i = offset
  for (; i < candidates.length && matches.length < pageSize; i++) {
    const c = candidates[i]!
    const line = await resolveLine(c)
    const amounts = typedInput.phase !== undefined ? line.amounts.filter((a) => a.phase === typedInput.phase) : line.amounts
    if (typedInput.phase !== undefined && amounts.length === 0) continue
    matches.push({
      name: `budgets/${budgetIdOf(c.jurisdiction, c.fiscalYear)}/budgetLines/${c.budgetLineId}`,
      budget: `budgets/${budgetIdOf(c.jurisdiction, c.fiscalYear)}`,
      fiscalYear: c.fiscalYear,
      direction: c.direction,
      fund: c.fund,
      matched: c.matched as SearchMatch['matched'],
      nameSource: c.nameSource,
      hierarchy: line.hierarchy as SearchMatch['hierarchy'],
      amounts: amounts as SearchMatch['amounts'],
    })
  }
  const nextPageToken = i < candidates.length ? encodePageToken({ v: 1, rev: meta.revision, family, chunk: 0, off: i, fh: fingerprint }) : undefined

  return { ...emptyOutput(), matches, nextPageToken }
})
