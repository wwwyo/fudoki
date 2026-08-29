/**
 * budgets リソース（団体 × 年度の予算）。
 * 年度スコープのメタデータ（収録している direction、分類率、金額の段階）の器で、
 * **収録範囲（どの年度があるか）は budgets の List から導出する**
 * （jurisdiction には年度を持たせない。収録が増えても団体の表現が変わらないように）。
 *
 * 明細そのものはここに入れ子にしない。年度は budgetLines にとっては filter の軸
 * （`fiscalYear = 2023`）であり、URL の階層に固定しない。
 */
import * as z from 'zod'
import { base, phaseId, resourceName } from './shared'

export const budgetSchema = z.object({
  name: resourceName.describe('リソース名（AIP-122）。jurisdictions/{団体コード}/budgets/{年度}'),
  jurisdictionId: z.string().describe('全国地方公共団体コード'),
  fiscalYear: z.string().describe('会計年度（西暦）'),
  directions: z
    .array(z.enum(['expenditure', 'revenue']))
    .describe('この年度に収録している歳出・歳入の別'),
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
    path: '/jurisdictions/{jurisdiction}/budgets',
    summary: 'List budgets',
    description:
      '団体が収録している年度の一覧（= この団体のカバレッジ）。' +
      '各年度の分類率と、金額ベースの計算に使った予算段階を返す。' +
      '明細は /jurisdictions/{jurisdiction}/budgetLines を fiscalYear で絞って取得する。',
  })
  .input(z.object({ jurisdiction: z.string().describe('全国地方公共団体コード') }))
  .output(
    z.object({
      budgets: z.array(budgetSchema).describe('fiscalYear の昇順'),
      revision: z.string().describe('由来する配布物の revision（git commit）'),
    }),
  )

export const getBudget = base
  .route({
    method: 'GET',
    path: '/jurisdictions/{jurisdiction}/budgets/{budget}',
    summary: 'Get a budget',
  })
  .input(
    z.object({
      jurisdiction: z.string().describe('全国地方公共団体コード'),
      budget: z.string().describe('会計年度（西暦）'),
    }),
  )
  .output(
    z.object({
      budget: budgetSchema,
      revision: z.string().describe('由来する配布物の revision（git commit）'),
    }),
  )
