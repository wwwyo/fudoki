/**
 * jurisdictions リソース（収録団体）。
 * 一覧・詳細と、団体ごとのメタデータ（収録年度、注意事項、COFOG 分類率、
 * 配布物への発見経路）の型を持つ。
 */
import * as z from 'zod'
import { base, resourceName } from './shared'

export const classificationRateSchema = z.object({
  fiscalYear: z.string(),
  /** 金額ベースの計算に使った予算段階 */
  amountPhase: z.string(),
  statuses: z.object({
    assigned: z.object({ lines: z.number(), amount: z.number() }),
    unclassifiable: z.object({ lines: z.number(), amount: z.number() }),
    outOfScope: z.object({ lines: z.number(), amount: z.number() }),
  }),
})
export type ClassificationRate = z.infer<typeof classificationRateSchema>

export const caveatSchema = z.object({
  /** PRD の必須4カテゴリ + other。団体ごとに4カテゴリ全ての存在を build が検査する */
  category: z.enum(['coverage', 'phaseSemantics', 'classification', 'sourceAndLicense', 'other']),
  topic: z.string(),
  body: z.string(),
})

export const jurisdictionSchema = z.object({
  name: resourceName,
  id: z.string(),
  label: z.string(),
  fiscalYears: z.object({
    expenditure: z.array(z.string()),
    revenue: z.array(z.string()),
  }),
  /** 団体固有の階層の並び（datapackage の宣言由来）。応答の hierarchy はこの順で並ぶ */
  levels: z.object({
    expenditure: z.array(z.string()),
    revenue: z.array(z.string()),
  }),
  /** 配布物（datapackage.json）へのパス。出典・ライセンス・改変表示の正本 */
  datapackagePath: z.string(),
  /** パススルーで取得できるファイル名 */
  resources: z.array(z.string()),
  licenses: z.array(z.object({ name: z.string(), title: z.string(), path: z.string() })),
  sources: z.array(z.object({ title: z.string(), path: z.string().nullable() })),
  consolidationScope: z.string(),
  caveats: z.array(caveatSchema),
  classificationRates: z.array(classificationRateSchema),
})
export type Jurisdiction = z.infer<typeof jurisdictionSchema>

export const listJurisdictions = base
  .route({
    method: 'GET',
    path: '/jurisdictions',
    summary: 'List jurisdictions',
    description:
      '収録団体の一覧。各団体の収録年度・注意事項（caveats）・COFOG 分類率と、' +
      '配布物（datapackage.json）への参照を返す。',
  })
  .output(
    z.object({
      jurisdictions: z.array(jurisdictionSchema),
      revision: z.string(),
    }),
  )

export const getJurisdiction = base
  .route({
    method: 'GET',
    path: '/jurisdictions/{jurisdiction}',
    summary: 'Get a jurisdiction',
  })
  .input(z.object({ jurisdiction: z.string() }))
  .output(z.object({ jurisdiction: jurisdictionSchema, revision: z.string() }))
