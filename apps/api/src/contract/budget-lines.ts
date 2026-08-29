/**
 * budgetLines リソース（予算明細）。
 * 団体単位（団体固有の階層つき）と横断（共通の最小軸のみ）の2つの scope を持ち、
 * どちらも同じコレクション `jurisdictions/{jurisdiction}/budgetLines` の List で表す
 * （横断は AIP-159 のワイルドカード親 `-`）。
 */
import * as z from 'zod'
import { base, pageInput, resourceName } from './shared'

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

export const listBudgetLines = base
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
  .output(listBudgetLinesResponseSchema)

export const getBudgetLine = base
  .route({
    method: 'GET',
    path: '/jurisdictions/{jurisdiction}/budgetLines/{budgetLine}',
    summary: 'Get a budget line',
    description:
      '明細1件を配布物の識別子（budget_line_id）で取得する。' +
      '横断応答の name をそのまま辿って団体固有の階層を含む元明細に戻れる。',
  })
  .input(z.object({ jurisdiction: z.string(), budgetLine: z.string() }))
  .output(z.object({ budgetLine: budgetLineSchema, revision: z.string() }))
