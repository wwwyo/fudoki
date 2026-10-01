import { oc } from '@orpc/contract'
import { z } from 'zod'
import {
  jurisdictionCodeSchema,
  directionSchema,
  documentKindSchema,
  versionIdSchema,
  sha256Schema,
  cofogStatusSchema,
  nameSourceSchema,
} from '@fudoki/data-contracts'

const base = oc.errors({
  BAD_REQUEST: { data: z.object({ reason: z.string() }) },
  NOT_FOUND: {},
  VERSION_EXPIRED: { status: 410 },
  UNAVAILABLE: { status: 503 },
})
export const versionRefSchema = z
  .object({
    jurisdictionCode: jurisdictionCodeSchema,
    versionId: versionIdSchema,
  })
  .strict()
const versionInput = {
  versions: z.array(versionRefSchema).max(100).default([]),
}
const envelope = { versions: z.array(versionRefSchema) }
const jurisdictionSchema = z.object({
  code: z.string(),
  versionId: versionIdSchema,
  name: z.string(),
  ocdId: z.string(),
  caveats: z.array(
    z.object({
      category: z.string(),
      topic: z.string(),
      body: z.string(),
      api: z.boolean().optional(),
    })
  ),
})
export const datasetSchema = z.object({
  id: z.string(),
  versionId: versionIdSchema,
  jurisdictionCode: z.string(),
  fiscalYear: z.number().int(),
  direction: directionSchema,
  documentKind: documentKindSchema,
  originSha256: sha256Schema,
  coverage: z.record(z.string(), z.unknown()),
  source: z.object({
    documentLabel: z.string(),
    landingPage: z.string(),
    licenseId: z.string(),
    attribution: z.string(),
    rawForm: z.string(),
  }),
  structure: z.object({
    hierarchy: z.array(z.string()),
    dimensions: z.array(z.string()),
    funds: z
      .array(z.object({ code: z.string(), label: z.string() }))
      .default([]),
  }),
  lineCount: z.number().int(),
  amendmentNumber: z.number().int().nullable().default(null),
  effectiveAt: z.string().nullable().default(null),
  sourceAmountKind: z
    .enum(['initial', 'delta', 'before', 'after', 'executed'])
    .nullable()
    .default(null),
})
const levelSchema = z.enum([
  'fund',
  'kan',
  'kou',
  'moku',
  'jikou',
  'daijigyo',
  'chujigyo',
  'shojigyo',
  'saimoku',
  'jigyo',
  'setsu',
  'saisetsu',
  'saisaisetsu',
])
const groupingSchema = z.enum([
  'jurisdiction',
  'year',
  'fund',
  'cofog.division',
  'cofog.group',
  'cofog.class',
  'kan',
  'kou',
  'moku',
  'jigyo',
  'daijigyo',
  'chujigyo',
  'shojigyo',
  'setsu',
])
export const lineSchema = z
  .object({
    id: z.string(),
    versionId: versionIdSchema,
    direction: directionSchema,
    documentKind: z.enum(['budget', 'settlement']),
    datasetId: z.string(),
    sourceRow: z.number().int(),
    fundCode: z.string(),
    fundLabel: z.string(),
    amount: z.number().int().safe(),
    consolidation: z.enum(['retained', 'eliminated']),
    counterpartFund: z.string(),
    hierarchy: z.array(
      z.object({
        level: levelSchema,
        code: z.string(),
        label: z.string(),
        nameSource: nameSourceSchema,
      })
    ),
    dimensions: z.array(
      z.object({ dimension: z.string(), code: z.string(), label: z.string() })
    ),
    names: z.array(
      z.object({
        kind: z.enum(['hierarchy', 'dimension', 'project']),
        level: z.string(),
        value: z.string(),
        nameSource: nameSourceSchema,
        basis: z.string(),
      })
    ),
    cofog: z
      .object({
        status: cofogStatusSchema,
        division: z.string(),
        group: z.string(),
        class: z.string(),
        basis: z.string(),
      })
      .optional(),
  })
  .superRefine((line, ctx) => {
    if ((line.direction === 'expenditure') !== !!line.cofog)
      ctx.addIssue({
        code: 'custom',
        message: 'COFOG belongs only to expenditure',
      })
  })
export const lineQuerySchema = z
  .object({
    ...versionInput,
    datasetIds: z.array(z.string().min(1).max(256)).min(1).max(100),
    fund: z.string().max(128).optional(),
    consolidation: z.enum(['all', 'retained', 'eliminated']).default('all'),
    hierarchy: z
      .array(
        z.object({ level: levelSchema, code: z.string().max(128) }).strict()
      )
      .max(14)
      .default([]),
    cofog: z
      .object({
        division: z.string().max(8).optional(),
        group: z.string().max(8).optional(),
        class: z.string().max(8).optional(),
        status: cofogStatusSchema.optional(),
      })
      .strict()
      .optional(),
    name: z.string().min(1).max(128).optional(),
    pageSize: z.number().int().min(1).max(500).default(100),
    cursor: z.string().max(8192).optional(),
  })
  .strict()
export const aggregateQuerySchema = lineQuerySchema
  .omit({ pageSize: true, cursor: true, name: true })
  .extend({
    groupBy: z.array(groupingSchema).min(1).max(4),
  })
export const budgetHistoryQuerySchema = z
  .object({
    ...versionInput,
    jurisdictionCode: jurisdictionCodeSchema,
    fiscalYear: z.number().int(),
    direction: directionSchema,
    asOf: z.iso.date(),
    fundCode: z.string().min(1).max(128).optional(),
  })
  .strict()
const budgetItemSchema = z.object({
  id: z.string(),
  versionId: versionIdSchema,
  jurisdictionCode: z.string(),
  fiscalYear: z.number().int(),
  fundCode: z.string(),
  fundLabel: z.string(),
  initialState: z.enum(['recorded', 'verified-zero', 'unknown']),
  hierarchy: lineSchema.shape.hierarchy,
  dimensions: lineSchema.shape.dimensions,
  names: lineSchema.shape.names,
})
const budgetChangeSchema = z.object({
  id: z.string(),
  budgetItemId: z.string(),
  datasetId: z.string(),
  amountDelta: z.number().int().safe(),
  kind: z.enum([
    'supplementary',
    'carryover',
    'reserve-allocation',
    'transfer',
  ]),
  effectiveAt: z.string(),
  sequence: z.number().int(),
  sourceRow: z.number().int(),
  counterpartBudgetItemId: z.string().nullable(),
  carryoverFromYear: z.number().int().nullable(),
  carryoverToYear: z.number().int().nullable(),
  cofog: lineSchema.shape.cofog,
})
export const budgetHistorySchema = z.object({
  ...envelope,
  asOf: z.string(),
  datasets: z.array(datasetSchema),
  items: z.array(budgetItemSchema),
  initialLines: z.array(
    z.object({
      id: z.string(),
      budgetItemId: z.string(),
      datasetId: z.string(),
      sourceRow: z.number().int(),
      amount: z.number().int().safe(),
    })
  ),
  changes: z.array(budgetChangeSchema),
  links: z.array(
    z.object({
      budgetItemId: z.string(),
      settlementLineId: z.string(),
      status: z.enum(['verified', 'unconfirmed']),
      groupId: z.string(),
      basis: z.string(),
    })
  ),
  settlementLines: z.array(
    z.object({
      id: z.string(),
      datasetId: z.string(),
      amount: z.number().int().safe(),
    })
  ),
  comparisons: z.array(
    z.object({
      groupId: z.string(),
      budgetItemIds: z.array(z.string()),
      settlementLineIds: z.array(z.string()),
      budgetAmount: z.number().int().safe().nullable(),
      recordedChangeSubtotal: z.number().int().safe(),
      actualAmount: z.number().int().safe(),
      status: z.enum(['complete', 'unconfirmed']),
    })
  ),
})
export type BudgetHistoryQuery = z.infer<typeof budgetHistoryQuerySchema>
export type BudgetHistory = z.infer<typeof budgetHistorySchema>
export const contract = {
  listJurisdictions: base
    .route({ method: 'GET', path: '/jurisdictions' })
    .input(z.object(versionInput).strict())
    .output(
      z.object({ ...envelope, jurisdictions: z.array(jurisdictionSchema) })
    ),
  listFiscalDatasets: base
    .route({ method: 'GET', path: '/fiscal-datasets' })
    .input(
      z
        .object({
          ...versionInput,
          jurisdictionCode: z
            .string()
            .regex(/^\d{6}$/)
            .optional(),
          fiscalYear: z.number().int().optional(),
          direction: directionSchema.optional(),
          documentKind: documentKindSchema.optional(),
        })
        .strict()
    )
    .output(z.object({ ...envelope, datasets: z.array(datasetSchema) })),
  getFiscalDataset: base
    .route({ method: 'GET', path: '/fiscal-datasets/{datasetId}' })
    .input(
      z
        .object({ ...versionInput, datasetId: z.string().min(1).max(256) })
        .strict()
    )
    .output(z.object({ ...envelope, dataset: datasetSchema })),
  getFiscalLines: base
    .route({ method: 'POST', path: '/fiscal-lines/query' })
    .input(lineQuerySchema.omit({ name: true }))
    .output(
      z.object({
        ...envelope,
        lines: z.array(lineSchema),
        nextCursor: z.string().optional(),
      })
    ),
  searchFiscalLines: base
    .route({ method: 'POST', path: '/fiscal-lines/search' })
    .input(lineQuerySchema.extend({ name: z.string().min(1).max(128) }))
    .output(
      z.object({
        ...envelope,
        lines: z.array(lineSchema),
        nextCursor: z.string().optional(),
      })
    ),
  aggregateFiscalDatasets: base
    .route({ method: 'POST', path: '/fiscal-datasets/aggregate' })
    .input(aggregateQuerySchema)
    .output(
      z.object({
        ...envelope,
        datasets: z.array(datasetSchema),
        groupBy: z.array(groupingSchema),
        cells: z.array(
          z.object({
            keys: z.array(z.string()),
            amount: z.number().int().safe(),
            lineCount: z.number().int(),
          })
        ),
        totals: z.array(
          z.object({
            datasetId: z.string(),
            amount: z.number().int().safe(),
            lineCount: z.number().int(),
          })
        ),
        total: z
          .object({
            amount: z.number().int().safe(),
            lineCount: z.number().int(),
          })
          .optional(),
      })
    ),
  getFiscalBudgetHistory: base
    .route({ method: 'POST', path: '/fiscal-budget-history/query' })
    .input(budgetHistoryQuerySchema)
    .output(budgetHistorySchema),
  listFiles: base
    .route({ method: 'GET', path: '/files' })
    .input(
      z
        .object({
          ...versionInput,
          jurisdictionCode: z
            .string()
            .regex(/^\d{6}$/)
            .optional(),
        })
        .strict()
    )
    .output(
      z.object({
        ...envelope,
        manifests: z.array(versionRefSchema.extend({ url: z.string().url() })),
        files: z.array(
          z.object({
            path: z.string(),
            url: z.string().url(),
            sha256: z.string(),
            bytes: z.number().int(),
            contentType: z.string(),
          })
        ),
      })
    ),
}
export type Dataset = z.infer<typeof datasetSchema>
export type FiscalLine = z.infer<typeof lineSchema>
export type LineQuery = z.infer<typeof lineQuerySchema>
export type AggregateQuery = z.infer<typeof aggregateQuerySchema>
