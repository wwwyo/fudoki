/**
 * budgetLines リソース（予算明細）。
 * 団体単位（団体固有の階層つき）と横断（共通の最小軸のみ）の2つの scope を持ち、
 * どちらも同じコレクション `jurisdictions/{jurisdiction}/budgetLines` の List で表す
 * （横断は AIP-159 のワイルドカード親 `-`）。
 *
 * 各フィールドの `.describe()` は OpenAPI の description にそのまま出る。
 */
import * as z from 'zod'
import { base, pageInput, resourceName } from './shared'

const hierarchyEntry = z.object({
  level: z.string().describe('階層の名前（fund=会計, kan=款, kou=項, moku=目, …。並びと語彙は団体の宣言による）'),
  code: z.string().describe('原典のコード。"0" はその階層を持たない行のプレースホルダ'),
  label: z.string().nullable().describe('原典の名称。名称の列を持たない団体（狛江市の款・項・目など）は null'),
})

const dimensionEntry = z.object({
  name: z.string().describe('軸の名前（org=所属（部課）, budget_class=予算区分 など）'),
  code: z.string().describe('原典のコード'),
  label: z.string().nullable().describe('原典の名称。無ければ null'),
})

const amountEntry = z.object({
  phase: z.string().describe('予算段階の id（approved=当初予算, adjusted=予算現額, executed=執行済額 など）'),
  phaseLabel: z.string().describe('予算段階の原典での呼び名'),
  amount: z.number().describe('円に正規化した金額'),
  sourceAmount: z.number().describe('原典の額面（単位変換前の値）'),
  sourceAmountUnit: z.string().describe('原典の単位（円 / 千円）'),
  sourceRow: z.number().describe('原典 CSV での行番号。応答から原典の行へ戻るための参照'),
})

const cofogJudgment = z.object({
  status: z.string().describe('分類の状態（assigned=割当済み / unclassifiable=分類不能 / out-of-scope=対象外）'),
  division: z.string().nullable().describe('COFOG の大分類コード（01〜10）。割当済み以外は null'),
  consolidation: z.string().describe('連結状態（retained=保持 / eliminated=会計間移転として消去済み）。全会計を合計するとき eliminated を除くと二重計上を避けられる'),
  decidedAtLevel: z.string().nullable().describe('どの階層の単位で分類が決まったか（款 / 項 / 目）'),
  ruleId: z.string().nullable().describe('適用した分類規則の id。配布物の cofog_rules リソースで根拠を引ける'),
})

export const budgetLineSchema = z.object({
  name: resourceName.describe('リソース名（AIP-122）。jurisdictions/{団体}/budgetLines/{budgetLineId}'),
  budgetLineId: z.string().describe('配布物の明細識別子。{団体}:{年度}:{direction}:{資料種別}:{ハッシュ} の形で安定'),
  fiscalYear: z.string().describe('会計年度（西暦）'),
  direction: z.enum(['expenditure', 'revenue']).describe('歳出 / 歳入'),
  hierarchy: z.array(hierarchyEntry).describe('科目の階層（款→項→目→…）。並びと段数は団体ごとに違い、jurisdiction の levels が宣言する'),
  dimensions: z.array(dimensionEntry).describe('階層以外の同一性の軸（狛江市の所属・予算区分）。無い団体は空配列'),
  amounts: z.array(amountEntry).describe('この明細が持つ予算段階ごとの金額。決算資料の明細は複数段階を持つ'),
  judgments: z
    .object({
      cofog: cofogJudgment.nullable().describe('COFOG 分類の判断。歳入は not-applicable'),
      projectName: z.string().nullable().describe('事業名。原典に無い場合に決算資料から fudoki が対応づけたもの（付かない明細は null）'),
    })
    .describe('fudoki の判断。上の正本由来フィールドと違い、自治体が公表した事実ではない'),
})
export type BudgetLine = z.infer<typeof budgetLineSchema>

export const crossJurisdictionLineSchema = z.object({
  name: resourceName.describe('リソース名。そのまま Get に渡すと団体固有の階層を含む元明細が返る'),
  jurisdictionId: z.string().describe('全国地方公共団体コード'),
  budgetLineId: z.string().describe('配布物の明細識別子'),
  fiscalYear: z.string().describe('会計年度（西暦）'),
  amounts: z
    .array(z.object({
      phase: z.string().describe('予算段階の id'),
      amount: z.number().describe('円に正規化した金額'),
    }))
    .describe('予算段階ごとの金額。段階の構成は団体で違うので、比較は同じ段階どうしで行うこと'),
  cofog: z
    .object({
      status: z.string().describe('分類の状態（assigned / unclassifiable / out-of-scope）'),
      division: z.string().nullable().describe('COFOG の大分類コード（01〜10）'),
      consolidation: z.string().describe('連結状態（retained / eliminated）'),
    })
    .describe('COFOG 分類（fudoki の判断）'),
})
export type CrossJurisdictionLine = z.infer<typeof crossJurisdictionLineSchema>

export const listBudgetLinesResponseSchema = z.discriminatedUnion('scope', [
  z.object({
    scope: z.literal('jurisdiction').describe('団体単位の応答。明細は団体固有の形'),
    budgetLines: z.array(budgetLineSchema),
    nextPageToken: z.string().optional().describe('続きがあるときだけ返る。無ければ最後まで返した'),
    revision: z.string().describe('由来する配布物の revision（git commit）'),
  }),
  z.object({
    scope: z.literal('crossJurisdiction').describe('横断の応答。明細は団体に依存しない共通の最小軸のみ'),
    budgetLines: z.array(crossJurisdictionLineSchema),
    nextPageToken: z.string().optional().describe('続きがあるときだけ返る。無ければ最後まで返した'),
    revision: z.string().describe('由来する配布物の revision（git commit）'),
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
  .input(z.object({ jurisdiction: z.string().describe('全国地方公共団体コード、または全団体横断の `-`'), ...pageInput }))
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
  .input(
    z.object({
      jurisdiction: z.string().describe('全国地方公共団体コード'),
      budgetLine: z.string().describe('budget_line_id'),
    }),
  )
  .output(z.object({ budgetLine: budgetLineSchema, revision: z.string().describe('由来する配布物の revision（git commit）') }))
