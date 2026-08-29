/**
 * budgets リソース（団体 × 年度の予算）。**root のコレクション**で、
 * 一覧の絞り込み（団体・年度）は filter で表現する。
 * budget は年度スコープのメタ（収録 direction、分類率、金額の段階）を持ち、
 * 明細（statement）をサブリソースとして持つ（statement.ts）。
 *
 * budget の id は `{団体コード}:{年度}`（例: 132195:2023）。
 * budget_line_id の先頭2セグメントと一致し、明細から親 budget が機械的に決まる。
 */
import * as z from 'zod'
import { base, phaseId, resourceName } from './shared'

export const budgetSchema = z.object({
  name: resourceName.describe('リソース名（AIP-122）。budgets/{id}'),
  id: z.string().describe('budget の識別子。{団体コード}:{年度}（budget_line_id の先頭2セグメントと一致）'),
  jurisdictionId: z.string().describe('全国地方公共団体コード'),
  fiscalYear: z.string().describe('会計年度（西暦）'),
  directions: z
    .array(z.enum(['expenditure', 'revenue']))
    .describe('この予算で収録している歳出・歳入の別'),
  amountPhase: phaseId.describe('分類率の金額ベースの計算に使った予算段階'),
  classificationRate: z
    .object({
      assigned: z.object({
        lines: z.number().describe('明細数（一意な budget_line_id の件数）'),
        amount: z.number().describe('amountPhase 時点の金額合計（円）'),
      }),
      unclassifiable: z.object({
        lines: z.number().describe('明細数'),
        amount: z.number().describe('金額合計（円）'),
      }),
      outOfScope: z.object({
        lines: z.number().describe('明細数'),
        amount: z.number().describe('金額合計（円）'),
      }),
    })
    .describe('歳出の COFOG 分類の内訳。3状態の合計が歳出全体に一致する。COFOG で絞った結果に含まれない明細の規模がここで分かる'),
})
export type Budget = z.infer<typeof budgetSchema>

export const listBudgets = base
  .route({
    method: 'GET',
    path: '/budgets',
    summary: 'List budgets',
    description:
      '収録している予算（団体 × 年度）の一覧。これがカバレッジの正体で、' +
      'どの団体のどの年度が収録済みかは budgets の存在から導出する。' +
      'filter で `jurisdiction` と `fiscalYear` を絞れる（例: `jurisdiction = "132195"`）。' +
      '件数が少ないためページングは持たない。明細は /budgets/{id}/statement から取得する。',
  })
  .input(
    z.object({
      filter: z
        .string()
        .optional()
        .describe('AIP-160 の部分集合（`=` と `AND`）。使えるフィールドは jurisdiction / fiscalYear'),
    }),
  )
  .output(
    z.object({
      budgets: z.array(budgetSchema).describe('id の昇順'),
      revision: z.string().describe('由来する配布物の revision（git commit）'),
    }),
  )

export const getBudget = base
  .route({
    method: 'GET',
    path: '/budgets/{budget}',
    summary: 'Get a budget',
  })
  .input(z.object({ budget: z.string().describe('budget の識別子（{団体コード}:{年度}）') }))
  .output(
    z.object({
      budget: budgetSchema,
      revision: z.string().describe('由来する配布物の revision（git commit）'),
    }),
  )
