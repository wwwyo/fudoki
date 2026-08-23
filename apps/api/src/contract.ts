/**
 * budget-api の contract。**API の入出力はここが唯一の定義**で、
 * 実装（router.ts）も OpenAPI（spec.ts）もここから導出する。
 * 形は Google AIP に倣う（逸脱は .agent/prd/budget-api/design-doc.md の
 * 「AIP への倣い方と、意図的な逸脱」節が正本）。
 */
import { oc } from '@orpc/contract'
import * as z from 'zod'

/** AIP-122 のリソース名。例: jurisdictions/132195/budgetLines/132195:2018:... */
const resourceName = z.string()

const hierarchyEntry = z.object({
  level: z.string(),
  code: z.string(),
  label: z.string().nullable(),
})

const dimensionEntry = z.object({
  name: z.string(),
  code: z.string(),
  label: z.string().nullable(),
})

const amountEntry = z.object({
  phase: z.string(),
  phaseLabel: z.string(),
  /** 円に正規化した値（配布物の value） */
  amount: z.number(),
  /** 原典の額面と単位。応答から原典の行を復元できるように保つ */
  sourceAmount: z.number(),
  sourceAmountUnit: z.string(),
  sourceRow: z.number(),
})

const cofogJudgment = z.object({
  status: z.string(),
  division: z.string().nullable(),
  consolidation: z.string(),
  decidedAtLevel: z.string().nullable(),
  ruleId: z.string().nullable(),
})

export const budgetLineSchema = z.object({
  name: resourceName,
  budgetLineId: z.string(),
  fiscalYear: z.string(),
  direction: z.enum(['expenditure', 'revenue']),
  hierarchy: z.array(hierarchyEntry),
  /** 階層以外の同一性の軸（狛江市の所属・予算区分）。無い団体は空配列 */
  dimensions: z.array(dimensionEntry),
  amounts: z.array(amountEntry),
  /** fudoki の判断。正本由来の上のフィールドと構造で区別する */
  judgments: z.object({
    cofog: cofogJudgment.nullable(),
    projectName: z.string().nullable(),
  }),
})
export type BudgetLine = z.infer<typeof budgetLineSchema>

export const crossJurisdictionLineSchema = z.object({
  name: resourceName,
  jurisdictionId: z.string(),
  budgetLineId: z.string(),
  fiscalYear: z.string(),
  amounts: z.array(z.object({ phase: z.string(), amount: z.number() })),
  cofog: z.object({
    status: z.string(),
    division: z.string().nullable(),
    consolidation: z.string(),
  }),
})
export type CrossJurisdictionLine = z.infer<typeof crossJurisdictionLineSchema>

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

const pageInput = {
  /**
   * AIP-160 の部分集合。`=` と `AND` のみ。
   * 使えるフィールド: fiscalYear / direction / phase / cofog.division（詳細は説明文）
   */
  filter: z.string().optional(),
  /** 未指定・0 は既定値 1000。上限 1000（超過は丸める）。負数は 400 */
  pageSize: z.coerce.number().int().min(0).optional(),
  pageToken: z.string().optional(),
}

export const listBudgetLinesResponseSchema = z.discriminatedUnion('scope', [
  z.object({
    scope: z.literal('jurisdiction'),
    budgetLines: z.array(budgetLineSchema),
    nextPageToken: z.string().optional(),
    revision: z.string(),
  }),
  z.object({
    scope: z.literal('crossJurisdiction'),
    budgetLines: z.array(crossJurisdictionLineSchema),
    nextPageToken: z.string().optional(),
    revision: z.string(),
  }),
])
export type ListBudgetLinesResponse = z.infer<typeof listBudgetLinesResponseSchema>

const base = oc.errors({
  BAD_REQUEST: {
    data: z.object({ reason: z.string() }).optional(),
  },
  NOT_FOUND: {},
  /** deploy をまたいだ pageToken。入力誤り（400）と区別して 410 で返す */
  STALE_PAGE_TOKEN: {
    status: 410,
    message: 'pageToken was issued for a different revision. Restart from the first page.',
  },
})

export const contract = {
  listJurisdictions: base
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
    ),

  getJurisdiction: base
    .route({
      method: 'GET',
      path: '/jurisdictions/{jurisdiction}',
      summary: 'Get a jurisdiction',
    })
    .input(z.object({ jurisdiction: z.string() }))
    .output(z.object({ jurisdiction: jurisdictionSchema, revision: z.string() })),

  listBudgetLines: base
    .route({
      method: 'GET',
      path: '/jurisdictions/{jurisdiction}/budgetLines',
      summary: 'List budget lines',
      description:
        '予算明細の一覧。`{jurisdiction}` に団体コードを指定すると団体固有の階層を含む明細' +
        '（scope: jurisdiction）を返す。filter には fiscalYear と direction が必須で、' +
        'phase / cofog.division を追加できる。\n\n' +
        '`{jurisdiction}` にワイルドカード `-` を指定すると全団体を横断し（AIP-159）、' +
        '団体に依存しない共通の最小軸だけの明細（scope: crossJurisdiction）を返す。' +
        'filter には cofog.division が必須で、fiscalYear を追加できる（direction / phase は使えない）。\n\n' +
        'filter の文法は AIP-160 の部分集合（`=` と `AND` のみ）。' +
        '例: `cofog.division = "09" AND fiscalYear = 2023`。' +
        'phase は amounts[].phase に対する仮想フィールド（いずれかの段階が一致したら真）で、' +
        '一致した明細の amounts は全段階のまま返る。\n\n' +
        '並び順は name の昇順。結果が複数ページに分かれる場合は nextPageToken が返り、' +
        'nextPageToken が無いことが「最後まで返した」ことを意味する。' +
        'フィルタの該当が薄いページは pageSize 未満の件数（0件を含む）になり得るが、' +
        'nextPageToken がある限り続きがある。',
    })
    .input(z.object({ jurisdiction: z.string(), ...pageInput }))
    .output(listBudgetLinesResponseSchema),

  getBudgetLine: base
    .route({
      method: 'GET',
      path: '/jurisdictions/{jurisdiction}/budgetLines/{budgetLine}',
      summary: 'Get a budget line',
      description:
        '明細1件を配布物の識別子（budget_line_id）で取得する。' +
        '横断応答の name をそのまま辿って団体固有の階層を含む元明細に戻れる。',
    })
    .input(z.object({ jurisdiction: z.string(), budgetLine: z.string() }))
    .output(z.object({ budgetLine: budgetLineSchema, revision: z.string() })),
}

export type Contract = typeof contract
