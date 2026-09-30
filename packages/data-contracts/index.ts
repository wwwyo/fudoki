import { z } from 'zod'

export const CONTRACT_VERSION = 1
export const TABLES = [
  'jurisdictions',
  'fiscal_datasets',
  'fiscal_lines',
  'amounts',
  'cofog',
  'line_hierarchy',
  'line_dimensions',
  'names',
] as const
export const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/)
export const releaseIdSchema = z.string().regex(/^r-[a-f0-9]{32}$/)
export const directionSchema = z.enum(['expenditure', 'revenue'])
export const documentKindSchema = z.enum([
  'budget',
  'supplementary',
  'settlement',
])
export const phaseSchema = z.enum([
  'approved',
  'adjusted',
  'adjusted-before-transfer',
  'executed',
])
export const cofogStatusSchema = z.enum([
  'assigned',
  'unclassifiable',
  'out-of-scope',
  'not-applicable',
])
export const nameSourceSchema = z.enum([
  'canonical',
  'settlement-pdf',
  'judgment',
  '',
])
export const amountUnitSchema = z.enum(['円', '千円'])
export const fileSchema = z.object({
  path: z
    .string()
    .regex(/^(?:fiscal\/\d{6}\/[a-z_]+\.(?:csv|json)|catalog\.json)$/),
  sha256: sha256Schema,
  bytes: z.number().int().nonnegative(),
  contentType: z.enum([
    'text/csv; charset=utf-8',
    'application/json; charset=utf-8',
  ]),
})
export const manifestSchema = z
  .object({
    schemaVersion: z.literal(CONTRACT_VERSION),
    releaseId: releaseIdSchema,
    codeRevision: z.string().regex(/^[a-f0-9]{40}$/),
    inputFingerprint: sha256Schema,
    judgmentFingerprint: sha256Schema,
    queryFingerprint: sha256Schema,
    files: z.array(fileSchema).min(1),
    totals: z
      .array(
        z.object({
          datasetId: z.string(),
          phase: phaseSchema,
          rows: z.number().int().nonnegative(),
          amount: z.number().int().safe(),
        })
      )
      .default([]),
    tables: z.record(
      z.enum(TABLES),
      z.object({
        rows: z.number().int().nonnegative(),
        sha256: sha256Schema,
        canonicalSha256: sha256Schema,
        chunks: z.array(sha256Schema),
      })
    ),
  })
  .superRefine((manifest, context) => {
    if (
      new Set(manifest.files.map((file) => file.path)).size !==
      manifest.files.length
    )
      context.addIssue({ code: 'custom', message: 'Duplicate release file' })
    if (
      new Set(
        manifest.totals.map((total) => `${total.datasetId}:${total.phase}`)
      ).size !== manifest.totals.length
    )
      context.addIssue({
        code: 'custom',
        message: 'Duplicate dataset phase total',
      })
    for (const table of TABLES)
      if (
        manifest.tables[table].chunks.length !==
        Math.ceil(manifest.tables[table].rows / 500)
      )
        context.addIssue({
          code: 'custom',
          message: `Chunk count differs: ${table}`,
        })
  })
export type ReleaseManifest = z.infer<typeof manifestSchema>

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
    cursor?: string
    limit?: number
  }): Promise<{
    objects: { key: string }[]
    truncated: boolean
    cursor?: string
  }>
}

export const TABLE_COLUMNS = {
  jurisdictions: ['jurisdiction_code', 'name', 'ocd_id', 'caveats_json'],
  fiscal_datasets: [
    'dataset_id',
    'jurisdiction_code',
    'fiscal_year',
    'direction',
    'document_kind',
    'origin_sha256',
    'phases_json',
    'source_json',
    'structure_json',
    'line_count',
  ],
  fiscal_lines: [
    'fiscal_line_id',
    'dataset_id',
    'source_row',
    'fund_code',
    'fund_label',
  ],
  amounts: [
    'fiscal_line_id',
    'phase',
    'value',
    'source_amount',
    'source_amount_unit',
    'is_primary',
  ],
  cofog: [
    'fiscal_line_id',
    'status',
    'division',
    'group',
    'class',
    'consolidation',
    'decided_at_level',
    'rule_id',
    'basis',
    'counterpart_fund',
  ],
  line_hierarchy: [
    'fiscal_line_id',
    'ordinal',
    'level',
    'code',
    'label',
    'name_source',
  ],
  line_dimensions: ['fiscal_line_id', 'dimension', 'code', 'label'],
  names: [
    'fiscal_line_id',
    'name_kind',
    'level',
    'value',
    'name_source',
    'basis',
  ],
} as const
export const TABLE_KEYS = {
  jurisdictions: ['jurisdiction_code'],
  fiscal_datasets: ['dataset_id'],
  fiscal_lines: ['fiscal_line_id'],
  amounts: ['fiscal_line_id', 'phase'],
  cofog: ['fiscal_line_id'],
  line_hierarchy: ['fiscal_line_id', 'ordinal'],
  line_dimensions: ['fiscal_line_id', 'dimension'],
  names: ['fiscal_line_id', 'name_kind', 'level'],
} as const
export function canonicalRow(
  table: (typeof TABLES)[number],
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
