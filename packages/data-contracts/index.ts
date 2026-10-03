import { z } from 'zod'

export const CONTRACT_VERSION = 4
export const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/)
export const buildIdSchema = z.string().regex(/^r-[a-f0-9]{32}$/)
export const versionIdSchema = z.string().regex(/^v-[a-f0-9]{64}$/)
export const packageIdSchema = z.string().regex(/^p-[a-f0-9]{64}$/)
export const jurisdictionCodeSchema = z.string().regex(/^\d{6}$/)
export const directionSchema = z.enum(['expenditure', 'revenue'])
export const documentKindSchema = z.enum([
  'budget',
  'supplementary',
  'settlement',
  'carryover',
  'reserve-allocation',
  'transfer',
])
export const cofogStatusSchema = z.enum([
  'assigned',
  'unclassifiable',
  'out-of-scope',
])
export const nameSourceSchema = z.enum([
  'canonical',
  'settlement-pdf',
  'judgment',
  '',
])
export const jurisdictionMasterSchema = z
  .object({
    jurisdiction_code: jurisdictionCodeSchema,
    name: z.string().min(1),
    ocd_id: z.string().min(1),
  })
  .strict()
export const lineGranularitySchema = z.enum([
  'expenditure_setsu',
  'origin_line',
])
export const expenditureSetsuMasterSchema = z
  .object({
    expenditure_setsu_id: z.string().min(1),
    code: z.string().min(1),
    label: z.string().min(1),
    valid_from_fiscal_year: z.number().int().nullable(),
    valid_to_fiscal_year: z.number().int().nullable(),
    legal_basis: z.string().min(1),
  })
  .strict()
  .superRefine((row, ctx) => {
    if (
      row.valid_from_fiscal_year !== null &&
      row.valid_to_fiscal_year !== null &&
      row.valid_from_fiscal_year > row.valid_to_fiscal_year
    )
      ctx.addIssue({ code: 'custom', message: 'Setsu period is empty' })
  })
export const cofogMasterSchema = z
  .object({
    code: z.string().regex(/^\d{2}(?:\.\d){0,2}$/),
    label: z.string().min(1),
    level: z.enum(['division', 'group', 'class']),
    parent_code: z.string().nullable(),
  })
  .strict()
  .superRefine((row, ctx) => {
    const depth = row.code.split('.').length
    const parent =
      depth === 1 ? null : row.code.slice(0, row.code.lastIndexOf('.'))
    if (
      row.level !== ['division', 'group', 'class'][depth - 1] ||
      row.parent_code !== parent
    )
      ctx.addIssue({
        code: 'custom',
        message: 'COFOG code, level and parent differ',
      })
  })
export const distributionKeySchema = z
  .string()
  .regex(/^fiscal\/\d{6}\/p-[a-f0-9]{64}\/[a-z_]+\.(?:csv|json)$/)
export const fileSchema = z
  .object({
    path: z.string().regex(/^fiscal\/\d{6}\/[a-z_]+\.(?:csv|json)$/),
    objectKey: distributionKeySchema,
    sha256: sha256Schema,
    bytes: z.number().int().nonnegative(),
    contentType: z.enum([
      'text/csv; charset=utf-8',
      'application/json; charset=utf-8',
    ]),
  })
  .strict()
export const packageSchema = z
  .object({
    jurisdictionCode: jurisdictionCodeSchema,
    packageId: packageIdSchema,
    datasetIds: z.array(z.string().min(1)).min(1),
  })
  .strict()
export const jurisdictionVersionSchema = z
  .object({
    jurisdictionCode: jurisdictionCodeSchema,
    versionId: versionIdSchema,
    packageId: packageIdSchema.nullable(),
    name: z.string().min(1),
    ocdId: z.string().min(1),
    caveats: z.array(z.unknown()),
  })
  .strict()
export const datasetStorageSchema = z
  .object({
    dataset_id: z.string().min(1),
    jurisdiction_code: jurisdictionCodeSchema,
    fiscal_year: z.number().int(),
    direction: directionSchema,
    document_kind: documentKindSchema,
    origin_sha256: sha256Schema,
    source_json: z.string(),
    structure_json: z.string(),
    line_count: z.number().int().nonnegative(),
    amendment_number: z.number().int().nullable(),
    effective_at: z.string().nullable(),
    source_amount_kind: z.string().nullable(),
    coverage_json: z.string(),
  })
  .strict()
export const distributionManifestSchema = z
  .object({
    schemaVersion: z.literal(CONTRACT_VERSION),
    jurisdictions: z.array(jurisdictionVersionSchema),
    datasets: z.array(datasetStorageSchema),
    packages: z.array(packageSchema),
    files: z.array(fileSchema),
    amountUnit: z.literal('JPY'),
    selection: z.string(),
  })
  .strict()
  .superRefine((m, ctx) => {
    const fail = (message: string) => ctx.addIssue({ code: 'custom', message })
    const versions = new Map(
      m.jurisdictions.map((j) => [j.jurisdictionCode, j])
    )
    const packages = new Map(m.packages.map((p) => [p.jurisdictionCode, p]))
    if (
      versions.size !== m.jurisdictions.length ||
      packages.size !== m.packages.length
    )
      fail('Duplicate jurisdiction')
    if (new Set(m.datasets.map((d) => d.dataset_id)).size !== m.datasets.length)
      fail('Duplicate dataset')
    if (new Set(m.files.map((f) => f.path)).size !== m.files.length)
      fail('Duplicate file')
    for (const j of m.jurisdictions)
      if (j.packageId !== (packages.get(j.jurisdictionCode)?.packageId ?? null))
        fail('Version package differs')
    for (const pkg of m.packages) {
      if (!versions.has(pkg.jurisdictionCode))
        fail('Package has no jurisdiction version')
      const ids = m.datasets
        .filter((d) => d.jurisdiction_code === pkg.jurisdictionCode)
        .map((d) => d.dataset_id)
        .sort()
      if (JSON.stringify(ids) !== JSON.stringify([...pkg.datasetIds].sort()))
        fail('Package dataset coverage differs')
      if (
        !m.files.some((f) =>
          f.path.startsWith(`fiscal/${pkg.jurisdictionCode}/`)
        )
      )
        fail('Package has no files')
    }
    for (const d of m.datasets)
      if (!packages.get(d.jurisdiction_code)?.datasetIds.includes(d.dataset_id))
        fail('Dataset has no package')
    for (const f of m.files) {
      const [, code, name] = f.path.split('/')
      const pkg = packages.get(code!)
      if (!pkg || f.objectKey !== `fiscal/${code}/${pkg.packageId}/${name}`)
        fail('File belongs to another jurisdiction package')
    }
  })
export type DistributionManifest = z.infer<typeof distributionManifestSchema>
export const tableDigestSchema = z.object({
  rows: z.number().int().nonnegative(),
  sha256: sha256Schema,
  canonicalSha256: sha256Schema,
  chunks: z.array(sha256Schema),
})
export const TABLES = [
  'fiscal_datasets',
  'fiscal_expenditure_budget_items',
  'fiscal_revenue_budget_items',
  'fiscal_settlement_expenditure_lines',
  'fiscal_settlement_expenditure_line_hierarchy',
  'fiscal_settlement_expenditure_line_dimensions',
  'fiscal_settlement_expenditure_line_names',
  'fiscal_initial_expenditure_budget_lines',
  'fiscal_expenditure_budget_changes',
  'fiscal_expenditure_settlement_links',
  'fiscal_settlement_revenue_lines',
  'fiscal_settlement_revenue_line_hierarchy',
  'fiscal_settlement_revenue_line_dimensions',
  'fiscal_settlement_revenue_line_names',
  'fiscal_initial_revenue_budget_lines',
  'fiscal_revenue_budget_changes',
  'fiscal_revenue_settlement_links',
] as const
export const TABLE_COLUMNS = {
  fiscal_datasets: [
    'dataset_id',
    'jurisdiction_code',
    'fiscal_year',
    'direction',
    'document_kind',
    'origin_sha256',
    'source_json',
    'structure_json',
    'line_count',
    'amendment_number',
    'effective_at',
    'source_amount_kind',
    'coverage_json',
  ],
  fiscal_expenditure_budget_items: [
    'budget_item_id',
    'jurisdiction_code',
    'fiscal_year',
    'fund_code',
    'fund_label',
    'expenditure_setsu_id',
    'line_granularity',
    'account_path_json',
    'dimensions_json',
    'names_json',
    'initial_state',
  ],
  fiscal_revenue_budget_items: [
    'budget_item_id',
    'jurisdiction_code',
    'fiscal_year',
    'fund_code',
    'fund_label',
    'account_path_json',
    'dimensions_json',
    'names_json',
    'initial_state',
  ],
  fiscal_settlement_expenditure_lines: [
    'fiscal_line_id',
    'dataset_id',
    'source_row',
    'fund_code',
    'fund_label',
    'amount',
    'consolidation',
    'counterpart_fund',
    'cofog_code',
    'cofog_status',
    'cofog_basis',
  ],
  fiscal_settlement_expenditure_line_hierarchy: [
    'fiscal_line_id',
    'ordinal',
    'level',
    'code',
    'label',
    'name_source',
  ],
  fiscal_settlement_expenditure_line_dimensions: [
    'fiscal_line_id',
    'dimension',
    'code',
    'label',
  ],
  fiscal_settlement_expenditure_line_names: [
    'fiscal_line_id',
    'name_kind',
    'level',
    'value',
    'name_source',
    'basis',
  ],
  fiscal_initial_expenditure_budget_lines: [
    'fiscal_line_id',
    'dataset_id',
    'budget_item_id',
    'source_row',
    'amount',
    'details_json',
    'consolidation',
    'counterpart_fund',
    'cofog_code',
    'cofog_status',
    'cofog_basis',
  ],
  fiscal_expenditure_budget_changes: [
    'change_id',
    'dataset_id',
    'budget_item_id',
    'amount_delta',
    'details_json',
    'change_kind',
    'effective_at',
    'sequence',
    'source_row',
    'counterpart_budget_item_id',
    'carryover_from_year',
    'carryover_to_year',
    'cofog_code',
    'cofog_status',
    'cofog_basis',
  ],
  fiscal_expenditure_settlement_links: [
    'budget_item_id',
    'settlement_line_id',
    'match_status',
    'match_group_id',
    'basis',
  ],
  fiscal_settlement_revenue_lines: [
    'fiscal_line_id',
    'dataset_id',
    'source_row',
    'fund_code',
    'fund_label',
    'amount',
    'consolidation',
    'counterpart_fund',
  ],
  fiscal_settlement_revenue_line_hierarchy: [
    'fiscal_line_id',
    'ordinal',
    'level',
    'code',
    'label',
    'name_source',
  ],
  fiscal_settlement_revenue_line_dimensions: [
    'fiscal_line_id',
    'dimension',
    'code',
    'label',
  ],
  fiscal_settlement_revenue_line_names: [
    'fiscal_line_id',
    'name_kind',
    'level',
    'value',
    'name_source',
    'basis',
  ],
  fiscal_initial_revenue_budget_lines: [
    'fiscal_line_id',
    'dataset_id',
    'budget_item_id',
    'source_row',
    'amount',
    'consolidation',
    'counterpart_fund',
  ],
  fiscal_revenue_budget_changes: [
    'change_id',
    'dataset_id',
    'budget_item_id',
    'amount_delta',
    'change_kind',
    'effective_at',
    'sequence',
    'source_row',
    'counterpart_budget_item_id',
    'carryover_from_year',
    'carryover_to_year',
  ],
  fiscal_revenue_settlement_links: [
    'budget_item_id',
    'settlement_line_id',
    'match_status',
    'match_group_id',
    'basis',
  ],
  jurisdiction_master: ['jurisdiction_code', 'name', 'ocd_id'],
  cofog_master: ['code', 'label', 'level', 'parent_code'],
  fiscal_expenditure_setsu_master: [
    'expenditure_setsu_id',
    'code',
    'label',
    'valid_from_fiscal_year',
    'valid_to_fiscal_year',
    'legal_basis',
  ],
  jurisdiction_metadata: [
    'jurisdiction_code',
    'name_snapshot',
    'ocd_id_snapshot',
    'caveats_json',
  ],
} as const
export const TABLE_KEYS = {
  fiscal_datasets: ['dataset_id'],
  fiscal_expenditure_budget_items: ['budget_item_id'],
  fiscal_revenue_budget_items: ['budget_item_id'],
  fiscal_settlement_expenditure_lines: ['fiscal_line_id'],
  fiscal_settlement_expenditure_line_hierarchy: ['fiscal_line_id', 'ordinal'],
  fiscal_settlement_expenditure_line_dimensions: [
    'fiscal_line_id',
    'dimension',
  ],
  fiscal_settlement_expenditure_line_names: [
    'fiscal_line_id',
    'name_kind',
    'level',
  ],
  fiscal_initial_expenditure_budget_lines: ['fiscal_line_id'],
  fiscal_expenditure_budget_changes: ['change_id'],
  fiscal_expenditure_settlement_links: ['budget_item_id', 'settlement_line_id'],
  fiscal_settlement_revenue_lines: ['fiscal_line_id'],
  fiscal_settlement_revenue_line_hierarchy: ['fiscal_line_id', 'ordinal'],
  fiscal_settlement_revenue_line_dimensions: ['fiscal_line_id', 'dimension'],
  fiscal_settlement_revenue_line_names: [
    'fiscal_line_id',
    'name_kind',
    'level',
  ],
  fiscal_initial_revenue_budget_lines: ['fiscal_line_id'],
  fiscal_revenue_budget_changes: ['change_id'],
  fiscal_revenue_settlement_links: ['budget_item_id', 'settlement_line_id'],
  jurisdiction_master: ['jurisdiction_code'],
  cofog_master: ['code'],
  fiscal_expenditure_setsu_master: ['expenditure_setsu_id'],
  jurisdiction_metadata: ['jurisdiction_code'],
} as const
export const candidateManifestSchema = z
  .object({
    schemaVersion: z.literal(CONTRACT_VERSION),
    buildId: buildIdSchema,
    codeRevision: z.string().regex(/^[a-f0-9]{40}$/),
    inputFingerprint: sha256Schema,
    judgmentFingerprint: sha256Schema,
    queryFingerprint: sha256Schema,
    manifestSha256: sha256Schema,
    jurisdictionMasterSha256: sha256Schema,
    cofogMasterSha256: sha256Schema,
    expenditureSetsuMasterSha256: sha256Schema,
    tables: z.record(z.enum(TABLES), tableDigestSchema),
    versions: z.array(
      jurisdictionVersionSchema.extend({
        tables: z.record(z.enum(TABLES), tableDigestSchema),
      })
    ),
    totals: z.array(
      z.object({
        datasetId: z.string(),
        jurisdictionCode: jurisdictionCodeSchema,
        resource: z.string(),
        rows: z.number().int().nonnegative(),
        amount: z.number().int().safe(),
      })
    ),
  })
  .strict()
export type CandidateManifest = z.infer<typeof candidateManifestSchema>
export function canonicalRow(
  table: keyof typeof TABLE_COLUMNS,
  row: Record<string, unknown>
): string {
  return (
    JSON.stringify(
      Object.fromEntries(
        TABLE_COLUMNS[table].map((column) => [column, row[column]])
      )
    ) + '\n'
  )
}
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value))
    return '[' + value.map(canonicalJson).join(',') + ']'
  if (value !== null && typeof value === 'object')
    return (
      '{' +
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, val]) => JSON.stringify(key) + ':' + canonicalJson(val))
        .join(',') +
      '}'
    )
  return JSON.stringify(value)
}
export async function contentId(
  prefix: 'p' | 'v',
  value: unknown
): Promise<string> {
  const bytes = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(canonicalJson(value))
  )
  return (
    prefix +
    '-' +
    [...new Uint8Array(bytes)]
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('')
  )
}
export async function derivePackageId(
  files: Pick<
    z.infer<typeof fileSchema>,
    'path' | 'sha256' | 'bytes' | 'contentType'
  >[]
): Promise<string> {
  return contentId(
    'p',
    [...files]
      .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0))
      .map(({ path, sha256, bytes, contentType }) => ({
        path,
        sha256,
        bytes,
        contentType,
      }))
  )
}
export interface D1Statement {
  bind(...values: unknown[]): D1Statement
  all<T = Record<string, unknown>>(): Promise<{
    results: T[]
    success: boolean
    meta?: { changes?: number; rows_read?: number }
  }>
  first<T = Record<string, unknown>>(): Promise<T | null>
  run(): Promise<{ success: boolean; meta: { changes: number } }>
}
export interface D1Database {
  prepare(sql: string): D1Statement
  batch<T = Record<string, unknown>>(
    statements: D1Statement[]
  ): Promise<{ results: T[]; success: boolean; meta: { changes: number } }[]>
}
export interface R2Object {
  key: string
  size: number
  httpEtag: string
  body: ReadableStream<Uint8Array>
  json<T>(): Promise<T>
  arrayBuffer(): Promise<ArrayBuffer>
  writeHttpMetadata(headers: Headers): void
}
export interface R2Bucket {
  get(key: string): Promise<R2Object | null>
  head(key: string): Promise<{ size: number; httpEtag: string } | null>
  list(options: {
    prefix: string
    delimiter?: string
    cursor?: string
    limit?: number
  }): Promise<{
    objects: { key: string }[]
    delimitedPrefixes: string[]
    truncated: boolean
    cursor?: string
  }>
}
