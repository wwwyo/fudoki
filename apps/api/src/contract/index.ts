import { oc } from '@orpc/contract'
import { z } from 'zod'
import {
  directionSchema,
  documentKindSchema,
  phaseSchema,
  releaseIdSchema,
  sha256Schema,
  cofogStatusSchema,
  nameSourceSchema,
  amountUnitSchema,
} from '@fudoki/data-contracts'

const base = oc.errors({
  BAD_REQUEST: { data: z.object({ reason: z.string() }) },
  NOT_FOUND: {},
  RELEASE_EXPIRED: { status: 410 },
  UNAVAILABLE: { status: 503 },
})
const releaseInput = { releaseId: releaseIdSchema.optional() }
const envelope = { releaseId: releaseIdSchema }
const jurisdictionSchema = z.object({
  code: z.string(),
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
  jurisdictionCode: z.string(),
  fiscalYear: z.number().int(),
  direction: directionSchema,
  documentKind: documentKindSchema,
  originSha256: sha256Schema,
  phases: z.array(phaseSchema),
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
export const lineSchema = z.object({
  id: z.string(),
  datasetId: z.string(),
  sourceRow: z.number().int(),
  fundCode: z.string(),
  fundLabel: z.string(),
  phase: phaseSchema,
  value: z.number().int().safe(),
  sourceAmount: z.number().int().safe(),
  sourceAmountUnit: amountUnitSchema,
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
  cofog: z.object({
    status: cofogStatusSchema,
    division: z.string(),
    group: z.string(),
    class: z.string(),
    consolidation: z.enum(['retained', 'eliminated']),
    decidedAtLevel: z.string(),
    ruleId: z.string(),
    basis: z.string(),
    counterpartFund: z.string(),
  }),
})
export const lineQuerySchema = z
  .object({
    ...releaseInput,
    datasetIds: z.array(z.string().min(1).max(256)).min(1).max(100),
    phase: phaseSchema.optional(),
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
    phase: phaseSchema,
    groupBy: z.array(groupingSchema).min(1).max(4),
  })
export const contract = {
  listJurisdictions: base
    .route({ method: 'GET', path: '/jurisdictions' })
    .input(z.object(releaseInput).strict())
    .output(
      z.object({ ...envelope, jurisdictions: z.array(jurisdictionSchema) })
    ),
  listFiscalDatasets: base
    .route({ method: 'GET', path: '/fiscal-datasets' })
    .input(
      z
        .object({
          ...releaseInput,
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
        .object({ ...releaseInput, datasetId: z.string().min(1).max(256) })
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
            phase: phaseSchema,
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
  listFiles: base
    .route({ method: 'GET', path: '/files' })
    .input(
      z
        .object({
          ...releaseInput,
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
        manifestUrl: z.string().url(),
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
