import { CONTRACT_VERSION, type D1Database } from '@fudoki/data-contracts'
import {
  aggregateQuerySchema,
  lineQuerySchema,
  type AggregateQuery,
  type Dataset,
  type FiscalLine,
  type LineQuery,
} from '../contract'
import { decodeCursor, encodeCursor, fingerprint } from '../lib/cursor'

export type VersionRef = { jurisdictionCode: string; versionId: string }
export class QueryError extends Error {
  code: 'BAD_REQUEST' | 'NOT_FOUND' | 'VERSION_EXPIRED' | 'UNAVAILABLE'
  constructor(code: QueryError['code'], message: string) {
    super(message)
    this.code = code
  }
}
async function rows<T>(
  db: D1Database,
  sql: string,
  args: unknown[] = []
): Promise<T[]> {
  const result = await db
    .prepare(sql)
    .bind(...args)
    .all<T>()
  if (!result.success) throw new Error('Database query failed')
  return result.results
}
export async function resolveVersions(
  db: D1Database,
  explicit: VersionRef[] = []
): Promise<VersionRef[]> {
  if (new Set(explicit.map((v) => v.jurisdictionCode)).size !== explicit.length)
    throw new QueryError('BAD_REQUEST', 'Choose one version per jurisdiction')
  const json = JSON.stringify(explicit)
  if (explicit.length) {
    const found = await rows(
      db,
      `SELECT v.version_id FROM fiscal_jurisdiction_versions v JOIN json_each(?) e ON v.version_id=json_extract(e.value,'$.versionId') AND v.jurisdiction_code=json_extract(e.value,'$.jurisdictionCode') WHERE v.contract_version=${CONTRACT_VERSION}`,
      [json]
    )
    if (found.length !== explicit.length)
      throw new QueryError(
        'VERSION_EXPIRED',
        'A requested jurisdiction version does not exist'
      )
  }
  return rows<VersionRef>(
    db,
    `SELECT v.jurisdiction_code AS jurisdictionCode,v.version_id AS versionId FROM fiscal_jurisdiction_versions v WHERE v.contract_version=${CONTRACT_VERSION} AND (
    EXISTS(SELECT 1 FROM json_each(?) e WHERE v.version_id=json_extract(e.value,'$.versionId') AND v.jurisdiction_code=json_extract(e.value,'$.jurisdictionCode')) OR (
    NOT EXISTS(SELECT 1 FROM json_each(?) e WHERE v.jurisdiction_code=json_extract(e.value,'$.jurisdictionCode')) AND
    NOT EXISTS(SELECT 1 FROM fiscal_jurisdiction_versions newer WHERE newer.contract_version=${CONTRACT_VERSION} AND newer.jurisdiction_code=v.jurisdiction_code AND (newer.registered_at>v.registered_at OR (newer.registered_at=v.registered_at AND newer.version_id>v.version_id))))) ORDER BY v.jurisdiction_code`,
    [json, json]
  )
}
function dataset(row: Record<string, unknown>): Dataset {
  return {
    id: String(row.dataset_id),
    versionId: String(row.version_id),
    jurisdictionCode: String(row.jurisdiction_code),
    fiscalYear: Number(row.fiscal_year),
    direction: row.direction as Dataset['direction'],
    documentKind: row.document_kind as Dataset['documentKind'],
    originSha256: String(row.origin_sha256),
    source: JSON.parse(String(row.source_json)),
    structure: JSON.parse(String(row.structure_json)),
    coverage: JSON.parse(String(row.coverage_json)),
    lineCount: Number(row.line_count),
    amendmentNumber: row.amendment_number as number | null,
    effectiveAt: row.effective_at as string | null,
    sourceAmountKind: row.source_amount_kind as Dataset['sourceAmountKind'],
  }
}
export async function listDatasets(
  db: D1Database,
  input: {
    versions?: VersionRef[]
    jurisdictionCode?: string
    fiscalYear?: number
    direction?: string
    documentKind?: string
    datasetIds?: string[]
  } = {},
  resolvedVersions?: VersionRef[]
): Promise<Dataset[]> {
  const versions =
      resolvedVersions ?? (await resolveVersions(db, input.versions)),
    clauses = ['version_id IN (SELECT value FROM json_each(?))'],
    args: unknown[] = [JSON.stringify(versions.map((v) => v.versionId))]
  for (const [field, column] of [
    ['jurisdictionCode', 'jurisdiction_code'],
    ['fiscalYear', 'fiscal_year'],
    ['direction', 'direction'],
    ['documentKind', 'document_kind'],
  ] as const) {
    if (input[field] !== undefined) {
      clauses.push(column + '=?')
      args.push(input[field])
    }
  }
  if (input.datasetIds) {
    clauses.push('dataset_id IN (SELECT value FROM json_each(?))')
    args.push(JSON.stringify(input.datasetIds))
  }
  return (
    await rows<Record<string, unknown>>(
      db,
      `SELECT * FROM fiscal_datasets WHERE ${clauses.join(' AND ')} ORDER BY jurisdiction_code,fiscal_year,direction,document_kind,dataset_id`,
      args
    )
  ).map(dataset)
}
export async function selectDatasets(
  db: D1Database,
  input: Pick<LineQuery, 'datasetIds' | 'versions'>,
  aggregation = false
): Promise<Dataset[]> {
  if (new Set(input.datasetIds).size !== input.datasetIds.length)
    throw new QueryError('BAD_REQUEST', 'datasetIds contains duplicates')
  const ids = new Set(input.datasetIds),
    found = await listDatasets(db, input)
  if (found.length !== ids.size)
    throw new QueryError(
      'NOT_FOUND',
      'A dataset does not exist in the selected jurisdiction version'
    )
  if (found.some((d) => !['settlement', 'budget'].includes(d.documentKind)))
    throw new QueryError(
      'BAD_REQUEST',
      'Budget changes are separate records, not settlement or initial amounts'
    )
  if (aggregation) {
    const scopes = found.map(
      (d) => `${d.jurisdictionCode}:${d.fiscalYear}:${d.direction}`
    )
    if (new Set(scopes).size !== scopes.length)
      throw new QueryError(
        'BAD_REQUEST',
        'Choose one document and edition per jurisdiction, year and direction'
      )
    if (
      new Set(found.map((d) => d.direction)).size !== 1 ||
      new Set(found.map((d) => d.documentKind)).size !== 1
    )
      throw new QueryError(
        'BAD_REQUEST',
        'Revenue, expenditure, initial budgets and settlements require separate aggregates'
      )
  }
  return found
}
function versionRefs(datasets: Dataset[]): VersionRef[] {
  return [
    ...new Map(
      datasets.map((d) => [
        d.jurisdictionCode,
        { jurisdictionCode: d.jurisdictionCode, versionId: d.versionId },
      ])
    ).values(),
  ].sort((a, b) => a.jurisdictionCode.localeCompare(b.jurisdictionCode))
}
function relationalJson(
  direction: 'expenditure' | 'revenue',
  suffix: 'hierarchy' | 'dimensions' | 'names'
) {
  const table = `fiscal_settlement_${direction}_line_${suffix}`
  const [order, object] =
    suffix === 'hierarchy'
      ? [
          'ordinal',
          "'level',c.level,'code',c.code,'label',c.label,'nameSource',c.name_source",
        ]
      : suffix === 'dimensions'
        ? ['dimension', "'dimension',c.dimension,'code',c.code,'label',c.label"]
        : [
            'name_kind,level',
            "'kind',c.name_kind,'level',c.level,'value',c.value,'nameSource',c.name_source,'basis',c.basis",
          ]
  return `(SELECT json_group_array(json_object(${object})) FROM (SELECT * FROM ${table} WHERE version_id=l.version_id AND fiscal_line_id=l.fiscal_line_id ORDER BY ${order}) c)`
}
function fiscalRows() {
  const selects = []
  for (const direction of ['expenditure', 'revenue'] as const) {
    const classification =
      direction === 'expenditure'
        ? 'l.cofog_code,l.cofog_status,l.cofog_basis'
        : 'NULL AS cofog_code,NULL AS cofog_status,NULL AS cofog_basis'
    selects.push(
      `SELECT l.version_id,l.fiscal_line_id,l.dataset_id,l.source_row,l.fund_code,l.fund_label,l.amount,l.consolidation,l.counterpart_fund,${classification},${relationalJson(direction, 'hierarchy')} AS hierarchy,${relationalJson(direction, 'dimensions')} AS dimensions,${relationalJson(direction, 'names')} AS names FROM fiscal_settlement_${direction}_lines l`
    )
    selects.push(
      `SELECT l.version_id,l.fiscal_line_id,l.dataset_id,l.source_row,b.fund_code,b.fund_label,l.amount,l.consolidation,l.counterpart_fund,${classification},b.account_path_json AS hierarchy,b.dimensions_json AS dimensions,b.names_json AS names FROM fiscal_initial_${direction}_budget_lines l JOIN fiscal_${direction}_budget_items b USING(version_id,budget_item_id)`
    )
  }
  return 'WITH fiscal_rows AS (' + selects.join(' UNION ALL ') + ') '
}
const joined =
  'FROM fiscal_rows l JOIN fiscal_datasets d ON d.version_id=l.version_id AND d.dataset_id=l.dataset_id'
function conditions(
  datasets: Dataset[],
  input: Pick<
    LineQuery,
    'datasetIds' | 'fund' | 'consolidation' | 'hierarchy' | 'cofog' | 'name'
  >
) {
  const where = [
      'l.version_id IN (SELECT value FROM json_each(?))',
      'l.dataset_id IN (SELECT value FROM json_each(?))',
    ],
    args: unknown[] = [
      JSON.stringify(versionRefs(datasets).map((v) => v.versionId)),
      JSON.stringify(input.datasetIds),
    ]
  if (input.fund !== undefined) {
    where.push('l.fund_code=?')
    args.push(input.fund)
  }
  if (input.consolidation !== 'all') {
    where.push('l.consolidation=?')
    args.push(input.consolidation)
  }
  for (const h of input.hierarchy) {
    where.push(
      "EXISTS(SELECT 1 FROM json_each(l.hierarchy) h WHERE json_extract(h.value,'$.level')=? AND json_extract(h.value,'$.code')=?)"
    )
    args.push(h.level, h.code)
  }
  if (input.name) {
    where.push(
      "EXISTS(SELECT 1 FROM json_each(l.names) n WHERE instr(json_extract(n.value,'$.value'),?)>0)"
    )
    args.push(input.name)
  }
  if (input.cofog) {
    if (datasets.some((d) => d.direction === 'revenue'))
      throw new QueryError('BAD_REQUEST', 'COFOG applies only to expenditure')
    for (const [level, length] of [
      ['division', 2],
      ['group', 4],
      ['class', 6],
    ] as const) {
      if (input.cofog[level] !== undefined) {
        where.push('substr(l.cofog_code,1,?)=?')
        args.push(length, input.cofog[level])
      }
    }
    if (input.cofog.status) {
      where.push('l.cofog_status=?')
      args.push(input.cofog.status)
    }
  }
  return { where: where.join(' AND '), args }
}
export async function queryLines(
  db: D1Database,
  datasets: Dataset[],
  input: LineQuery,
  after: [string, string] = ['', '']
): Promise<FiscalLine[]> {
  const scope = conditions(datasets, input)
  const result = await rows<Record<string, unknown>>(
    db,
    `${fiscalRows()}SELECT l.*,d.direction,d.document_kind ${joined} WHERE ${scope.where} AND (l.version_id>? OR (l.version_id=? AND l.fiscal_line_id>?)) ORDER BY l.version_id,l.fiscal_line_id LIMIT ?`,
    [...scope.args, after[0], after[0], after[1], input.pageSize + 1]
  )
  return result.map((r) => {
    const code = String(r.cofog_code ?? '')
    return {
      id: String(r.fiscal_line_id),
      versionId: String(r.version_id),
      datasetId: String(r.dataset_id),
      direction: r.direction,
      documentKind: r.document_kind,
      sourceRow: Number(r.source_row),
      fundCode: String(r.fund_code),
      fundLabel: String(r.fund_label),
      amount: Number(r.amount),
      consolidation: r.consolidation,
      counterpartFund: String(r.counterpart_fund),
      hierarchy: JSON.parse(String(r.hierarchy)),
      dimensions: JSON.parse(String(r.dimensions)),
      names: JSON.parse(String(r.names)),
      ...(r.direction === 'expenditure'
        ? {
            cofog: {
              status: r.cofog_status,
              division: code.slice(0, 2),
              group: code.length >= 4 ? code.slice(0, 4) : '',
              class: code.length === 6 ? code : '',
              basis: r.cofog_basis,
            },
          }
        : {}),
    } as FiscalLine
  })
}
export async function pageLines(
  db: D1Database,
  secret: string,
  input: LineQuery
) {
  input = lineQuerySchema.parse(input)
  const { cursor, pageSize, ...query } = input,
    queryHash = await fingerprint(query)
  let refs = input.versions,
    after: [string, string] = ['', ''],
    expiresAt = Date.now() + 3600000
  if (cursor) {
    try {
      const decoded = await decodeCursor(cursor, secret)
      if (decoded.fingerprint !== queryHash) throw new Error('Query differs')
      refs = decoded.versions
      after = decoded.after
      expiresAt = decoded.expiresAt
    } catch {
      throw new QueryError(
        'BAD_REQUEST',
        'Invalid, expired or mismatched cursor'
      )
    }
  }
  const datasets = await selectDatasets(db, {
    datasetIds: input.datasetIds,
    versions: refs,
  })
  const all = await queryLines(db, datasets, input, after),
    lines = all.slice(0, pageSize),
    versions = versionRefs(datasets)
  const last = lines.at(-1)
  const nextCursor =
    all.length > pageSize && last
      ? await encodeCursor(
          {
            v: 2,
            versions,
            fingerprint: queryHash,
            after: [last.versionId, last.id],
            expiresAt,
          },
          secret
        )
      : undefined
  return { versions, lines, nextCursor }
}
export async function aggregate(db: D1Database, input: AggregateQuery) {
  input = aggregateQuerySchema.parse(input)
  if (new Set(input.groupBy).size !== input.groupBy.length)
    throw new QueryError('BAD_REQUEST', 'groupBy contains duplicates')
  const datasets = await selectDatasets(db, input, true)
  if (
    new Set(datasets.map((d) => d.jurisdictionCode)).size > 1 &&
    !input.groupBy.includes('jurisdiction')
  )
    throw new QueryError(
      'BAD_REQUEST',
      'Comparisons must group by jurisdiction'
    )
  if (
    new Set(datasets.map((d) => d.fiscalYear)).size > 1 &&
    !input.groupBy.includes('year')
  )
    throw new QueryError('BAD_REQUEST', 'Comparisons must group by year')
  if (
    datasets.some((d) => d.direction === 'revenue') &&
    input.groupBy.some((k) => k.startsWith('cofog.'))
  )
    throw new QueryError('BAD_REQUEST', 'COFOG applies only to expenditure')
  const scope = conditions(datasets, input)
  const expressions = input.groupBy.map((key) => {
    if (key === 'jurisdiction') return 'd.jurisdiction_code'
    if (key === 'year') return 'CAST(d.fiscal_year AS TEXT)'
    if (key === 'fund') return 'l.fund_code'
    if (key.startsWith('cofog.')) {
      const n = { division: 2, group: 4, class: 6 }[
        key.slice(6) as 'division' | 'group' | 'class'
      ]
      return `CASE WHEN l.cofog_status!='assigned' THEN l.cofog_status WHEN length(l.cofog_code)<${n} THEN 'not-descended' ELSE substr(l.cofog_code,1,${n}) END`
    }
    return `(SELECT json_group_array(json_array(json_extract(h.value,'$.level'),json_extract(h.value,'$.code'))) FROM json_each(l.hierarchy) h WHERE CAST(h.key AS INTEGER)<=(SELECT CAST(k.key AS INTEGER) FROM json_each(l.hierarchy) k WHERE json_extract(k.value,'$.level')='${key}'))`
  })
  for (const key of input.groupBy.filter(
    (k) =>
      !['jurisdiction', 'year', 'fund'].includes(k) && !k.startsWith('cofog.')
  )) {
    const missing = await rows(
      db,
      `${fiscalRows()}SELECT 1 ${joined} WHERE ${scope.where} AND NOT EXISTS(SELECT 1 FROM json_each(l.hierarchy) h WHERE json_extract(h.value,'$.level')=?) LIMIT 1`,
      [...scope.args, key]
    )
    if (missing.length)
      throw new QueryError(
        'BAD_REQUEST',
        `Hierarchy level ${key} is unavailable`
      )
  }
  const result = await rows<Record<string, unknown>>(
    db,
    `${fiscalRows()}SELECT ${expressions.map((e, i) => `${e} AS k${i}`).join(',')},sum(l.amount) AS amount,count(*) AS lineCount ${joined} WHERE ${scope.where} GROUP BY ${expressions.map((_, i) => 'k' + i).join(',')} ORDER BY ${expressions.map((_, i) => 'k' + i).join(',')} LIMIT 10001`,
    scope.args
  )
  if (result.length > 10000)
    throw new QueryError('BAD_REQUEST', 'Too many aggregate cells')
  const cells = result.map((r) => ({
    keys: expressions.map((_, i) => String(r['k' + i] ?? '')),
    amount: Number(r.amount),
    lineCount: Number(r.lineCount),
  }))
  const totals = await rows<{
    datasetId: string
    amount: number
    lineCount: number
  }>(
    db,
    `${fiscalRows()}SELECT l.dataset_id AS datasetId,sum(l.amount) AS amount,count(*) AS lineCount ${joined} WHERE ${scope.where} GROUP BY l.dataset_id ORDER BY l.dataset_id`,
    scope.args
  )
  if (
    cells.some((c) => !Number.isSafeInteger(c.amount)) ||
    totals.some((t) => !Number.isSafeInteger(t.amount))
  )
    throw new QueryError(
      'BAD_REQUEST',
      'Aggregate exceeds the exact integer range'
    )
  const total =
    totals.length === 1
      ? { amount: totals[0]!.amount, lineCount: totals[0]!.lineCount }
      : undefined
  return {
    versions: versionRefs(datasets),
    datasets,
    groupBy: input.groupBy,
    cells,
    totals,
    total,
  }
}
export async function jurisdictions(
  db: D1Database,
  explicit: VersionRef[] = []
) {
  const versions = await resolveVersions(db, explicit)
  const found = await rows<{
    jurisdiction_code: string
    version_id: string
    name_snapshot: string
    ocd_id_snapshot: string
    caveats_json: string
  }>(
    db,
    'SELECT * FROM fiscal_jurisdiction_versions WHERE version_id IN (SELECT value FROM json_each(?)) ORDER BY jurisdiction_code',
    [JSON.stringify(versions.map((v) => v.versionId))]
  )
  return {
    versions,
    jurisdictions: found.map((r) => ({
      code: r.jurisdiction_code,
      versionId: r.version_id,
      name: r.name_snapshot,
      ocdId: r.ocd_id_snapshot,
      caveats: JSON.parse(r.caveats_json),
    })),
  }
}
export async function files(
  db: D1Database,
  baseUrl: string,
  input: { versions?: VersionRef[]; jurisdictionCode?: string } = {}
) {
  const versions = (await resolveVersions(db, input.versions)).filter(
    (v) =>
      !input.jurisdictionCode || v.jurisdictionCode === input.jurisdictionCode
  )
  const ids = JSON.stringify(versions.map((v) => v.versionId))
  const found = await rows<{
    path: string
    object_key: string
    sha256: string
    bytes: number
    content_type: string
  }>(
    db,
    'SELECT * FROM fiscal_package_files WHERE version_id IN (SELECT value FROM json_each(?)) ORDER BY jurisdiction_code,path',
    [ids]
  )
  const manifests = await rows<{
    jurisdictionCode: string
    versionId: string
    url: string
  }>(
    db,
    'SELECT jurisdiction_code AS jurisdictionCode,version_id AS versionId,manifest_url AS url FROM fiscal_jurisdiction_versions WHERE version_id IN (SELECT value FROM json_each(?)) ORDER BY jurisdiction_code',
    [ids]
  )
  return {
    versions,
    manifests,
    files: found.map((r) => ({
      path: r.path,
      url: baseUrl.replace(/\/$/, '') + '/' + r.object_key,
      sha256: r.sha256,
      bytes: r.bytes,
      contentType: r.content_type,
    })),
  }
}

/** Compare verified correspondence groups, counting each item and actual line once. */
export async function budgetHistory(
  db: D1Database,
  input: import('../contract').BudgetHistoryQuery
): Promise<import('../contract').BudgetHistory> {
  const versions = await resolveVersions(db, input.versions)
  const datasets = await listDatasets(db, input, versions)
  const version = versions.find(
    (v) => v.jurisdictionCode === input.jurisdictionCode
  )
  if (!version)
    throw new QueryError(
      'NOT_FOUND',
      'Jurisdiction does not have a fiscal version'
    )
  const args: (string | number)[] = [version.versionId, input.jurisdictionCode, input.fiscalYear]
  if (input.fundCode) args.push(input.fundCode)
  const direction = input.direction
  const items = await rows<Record<string, unknown>>(
    db,
    `SELECT * FROM fiscal_${direction}_budget_items WHERE version_id=? AND jurisdiction_code=? AND fiscal_year=?${input.fundCode ? " AND fund_code=?" : ""} ORDER BY budget_item_id LIMIT 10001`,
    args
  )
  if (items.length > 10000)
    throw new QueryError(
      'BAD_REQUEST',
      'Too many budget items; select a smaller scope'
    )
  const ids = JSON.stringify(items.map((row) => row.budget_item_id))
  const scoped = `version_id=? AND budget_item_id IN (SELECT value FROM json_each(?))`
  const initial = await rows<Record<string, unknown>>(
    db,
    `SELECT * FROM fiscal_initial_${direction}_budget_lines WHERE ${scoped} ORDER BY fiscal_line_id`,
    [version.versionId, ids]
  )
  const changes = await rows<Record<string, unknown>>(
    db,
    `SELECT * FROM fiscal_${direction}_budget_changes WHERE ${scoped} AND substr(effective_at,1,10)<=? ORDER BY effective_at,sequence,change_id LIMIT 10001`,
    [version.versionId, ids, input.asOf]
  )
  const links = await rows<Record<string, unknown>>(
    db,
    `SELECT * FROM fiscal_${direction}_settlement_links WHERE ${scoped} ORDER BY match_group_id,budget_item_id,settlement_line_id LIMIT 10001`,
    [version.versionId, ids]
  )
  if (changes.length > 10000 || links.length > 10000)
    throw new QueryError(
      'BAD_REQUEST',
      'Budget history is too large for one request'
    )
  const actuals = await rows<Record<string, unknown>>(
    db,
    `SELECT * FROM fiscal_settlement_${direction}_lines WHERE version_id=? AND fiscal_line_id IN (SELECT value FROM json_each(?)) ORDER BY fiscal_line_id`,
    [
      version.versionId,
      JSON.stringify([
        ...new Set(links.map((link) => link.settlement_line_id)),
      ]),
    ]
  )
  const initialByItem = new Map(
    initial.map((row) => [row.budget_item_id, Number(row.amount)])
  )
  const itemById = new Map(items.map((row) => [row.budget_item_id, row]))
  const actualById = new Map(
    actuals.map((row) => [row.fiscal_line_id, Number(row.amount)])
  )
  const groups = new Map<string, { items: Set<string>; lines: Set<string> }>()
  const memberGroup = new Map<string, string>()
  for (const link of links.filter((row) => row.match_status === 'verified')) {
    const groupId = String(link.match_group_id)
    if (!groupId)
      throw new QueryError(
        'UNAVAILABLE',
        'Verified correspondence lacks a group'
      )
    for (const member of [
      'item:' + link.budget_item_id,
      'line:' + link.settlement_line_id,
    ]) {
      const prior = memberGroup.get(member)
      if (prior && prior !== groupId)
        throw new QueryError(
          'UNAVAILABLE',
          'Correspondence spans multiple comparison groups'
        )
      memberGroup.set(member, groupId)
    }
    const group = groups.get(groupId) ?? {
      items: new Set<string>(),
      lines: new Set<string>(),
    }
    group.items.add(String(link.budget_item_id))
    group.lines.add(String(link.settlement_line_id))
    groups.set(groupId, group)
  }
  const comparisons: import('../contract').BudgetHistory['comparisons'] = []
  // Uncollected changes are never inferred to be zero from an empty table.
  const completeCoverage =
    datasets.some((d) => d.documentKind === 'budget') &&
    datasets
      .filter((d) => d.documentKind !== 'settlement')
      .every(
        (d) =>
          d.coverage.budgetHistory === 'complete' &&
          typeof d.coverage.verifiedThrough === 'string' &&
          d.coverage.verifiedThrough >= input.asOf
      )
  for (const [groupId, group] of groups) {
    let base = 0,
      complete = completeCoverage
    for (const id of group.items) {
      const row = itemById.get(id)!
      if (row.initial_state === 'recorded' && initialByItem.has(id))
        base += initialByItem.get(id)!
      else if (row.initial_state !== 'verified-zero') complete = false
    }
    const subtotal = changes
      .filter((row) => group.items.has(String(row.budget_item_id)))
      .reduce((sum, row) => sum + Number(row.amount_delta), 0)
    const actual = [...group.lines].reduce(
      (sum, id) => sum + actualById.get(id)!,
      0
    )
    for (const value of [base, subtotal, actual, base + subtotal])
      if (!Number.isSafeInteger(value))
        throw new QueryError(
          'BAD_REQUEST',
          'Budget total exceeds the exact integer range'
        )
    comparisons.push({
      groupId,
      budgetItemIds: [...group.items].sort(),
      settlementLineIds: [...group.lines].sort(),
      budgetAmount: complete ? base + subtotal : null,
      recordedChangeSubtotal: subtotal,
      actualAmount: actual,
      status: complete ? 'complete' : 'unconfirmed',
    })
  }
  return {
    versions: [version],
    asOf: input.asOf,
    datasets,
    items: items.map((row) => ({
      id: String(row.budget_item_id),
      versionId: version.versionId,
      jurisdictionCode: String(row.jurisdiction_code),
      fiscalYear: Number(row.fiscal_year),
      fundCode: String(row.fund_code),
      fundLabel: String(row.fund_label),
      initialState: row.initial_state as
        'recorded' | 'verified-zero' | 'unknown',
      hierarchy: JSON.parse(String(row.account_path_json)),
      dimensions: JSON.parse(String(row.dimensions_json)),
      names: JSON.parse(String(row.names_json)),
    })),
    initialLines: initial.map((row) => ({
      id: String(row.fiscal_line_id),
      budgetItemId: String(row.budget_item_id),
      datasetId: String(row.dataset_id),
      sourceRow: Number(row.source_row),
      amount: Number(row.amount),
    })),
    changes: changes.map((row) => ({
      id: String(row.change_id),
      budgetItemId: String(row.budget_item_id),
      datasetId: String(row.dataset_id),
      amountDelta: Number(row.amount_delta),
      kind: row.change_kind as
        'supplementary' | 'carryover' | 'reserve-allocation' | 'transfer',
      effectiveAt: String(row.effective_at),
      sequence: Number(row.sequence),
      sourceRow: Number(row.source_row),
      counterpartBudgetItemId: row.counterpart_budget_item_id as string | null,
      carryoverFromYear: row.carryover_from_year as number | null,
      carryoverToYear: row.carryover_to_year as number | null,
      ...(direction === 'expenditure'
        ? {
            cofog: {
              division: String(row.cofog_code ?? '').slice(0, 2),
              group:
                String(row.cofog_code ?? '').length >= 4
                  ? String(row.cofog_code).slice(0, 4)
                  : '',
              class:
                String(row.cofog_code ?? '').length == 6
                  ? String(row.cofog_code)
                  : '',
              status: row.cofog_status as
                'assigned' | 'unclassifiable' | 'out-of-scope',
              basis: String(row.cofog_basis),
            },
          }
        : {}),
    })),
    links: links.map((row) => ({
      budgetItemId: String(row.budget_item_id),
      settlementLineId: String(row.settlement_line_id),
      status: row.match_status as 'verified' | 'unconfirmed',
      groupId: String(row.match_group_id),
      basis: String(row.basis),
    })),
    settlementLines: actuals.map((row) => ({
      id: String(row.fiscal_line_id),
      datasetId: String(row.dataset_id),
      amount: Number(row.amount),
    })),
    comparisons,
  }
}
