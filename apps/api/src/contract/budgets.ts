/**
 * budgets リソース（団体 × 年度の予算）。**root のコレクション**で、
 * 一覧の絞り込み（団体・年度）は filter で表現する。
 * budget は年度スコープのメタ（収録 direction、分類率、金額の段階）を持ち、
 * 明細（statement）をサブリソースとして持つ。statement は集約の内部なので
 * 独立したファイルにせず、このファイル（budget 集約）に同居させる。
 *
 * budget の id は `{団体コード}:{年度}`（例: 132195:2023）。
 * budget_line_id の先頭2セグメントと一致し、明細から親 budget が機械的に決まる。
 */
import * as z from 'zod'
import {
  base,
  cofogConsolidation,
  cofogDecidedAtLevel,
  cofogStatus,
  dimensionName,
  direction,
  levelName,
  pageInput,
  phaseId,
  resourceName,
} from './shared'

/**
 * budget id のコーデック。**形式（{6桁の団体コード}:{4桁の年度}）を知るのはここだけ**。
 * 作る側（build）は budgetIdOf、読む側（procedure）は parseBudgetId を使い、
 * 独立に文字列連結・正規表現を書かない。
 */
export const BUDGET_ID_PATTERN = /^(\d{6}):(\d{4})$/

export function budgetIdOf(jurisdiction: string, fiscalYear: string): string {
  const id = `${jurisdiction}:${fiscalYear}`
  if (!BUDGET_ID_PATTERN.test(id)) throw new Error(`malformed budget id would be produced: ${id}`)
  return id
}

/** 形式が違えば null（呼び出し側が 400 にする） */
export function parseBudgetId(id: string): { jurisdiction: string; fiscalYear: string } | null {
  const m = id.match(BUDGET_ID_PATTERN)
  if (!m) return null
  return { jurisdiction: m[1]!, fiscalYear: m[2]! }
}

export const budgetSchema = z.object({
  name: resourceName.describe('リソース名（AIP-122）。budgets/{id}'),
  id: z
    .string()
    .regex(BUDGET_ID_PATTERN)
    .describe('budget の識別子。{団体コード}:{年度}（budget_line_id の先頭2セグメントと一致）'),
  jurisdictionId: z.string().describe('全国地方公共団体コード'),
  fiscalYear: z.string().describe('会計年度（西暦）'),
  directions: z.array(direction).describe('この予算で収録している歳出・歳入の別'),
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

// ---- statement（予算の明細。budget 集約の内部） ----

const hierarchyEntry = z.object({
  level: levelName,
  code: z.string().describe('原典のコード。"0" はその階層を持たない行のプレースホルダ'),
  label: z.string().nullable().describe('原典の名称。名称の列を持たない団体（狛江市の款・項・目など）は null'),
})

const dimensionEntry = z.object({
  name: dimensionName,
  code: z.string().describe('原典のコード'),
  label: z.string().nullable().describe('原典の名称。無ければ null'),
})

const amountEntry = z.object({
  phase: phaseId,
  phaseLabel: z.string().describe('予算段階の原典での呼び名'),
  amount: z.number().describe('円に正規化した金額'),
  sourceAmount: z.number().describe('原典の額面（単位変換前の値）'),
  sourceAmountUnit: z.string().describe('原典の単位（円 / 千円）'),
  sourceRow: z.number().describe('原典 CSV での行番号。応答から原典の行へ戻るための参照'),
})

const cofogJudgment = z.object({
  status: cofogStatus,
  division: z.string().nullable().describe('COFOG の大分類コード（01〜10）。割当済み以外は null'),
  consolidation: cofogConsolidation,
  decidedAtLevel: cofogDecidedAtLevel.nullable(),
  ruleId: z.string().nullable().describe('適用した分類規則の id。配布物の cofog_rules リソースで根拠を引ける'),
})

export const budgetLineSchema = z.object({
  budgetLineId: z.string().describe('配布物の明細識別子。{団体}:{年度}:{direction}:{資料種別}:{ハッシュ} の形で安定。先頭2セグメントが親 budget の id'),
  fiscalYear: z.string().describe('会計年度（西暦）'),
  direction,
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

export const crossBudgetLineSchema = z.object({
  budget: z.string().describe('親 budget のリソース名（budgets/{団体コード}:{年度}）。団体固有の階層を含む行は GET /budgets/{id}/statement で読む'),
  budgetLineId: z.string().describe('配布物の明細識別子'),
  fiscalYear: z.string().describe('会計年度（西暦）'),
  amounts: z
    .array(z.object({
      phase: phaseId,
      amount: z.number().describe('円に正規化した金額'),
    }))
    .describe('予算段階ごとの金額。段階の構成は団体で違うので、比較は同じ段階どうしで行うこと'),
  // 団体単位の行の cofogJudgment から共通の最小軸ぶんだけ導出する（二重定義しない）
  cofog: cofogJudgment
    .pick({ status: true, division: true, consolidation: true })
    .describe('COFOG 分類（fudoki の判断）'),
})
export type CrossBudgetLine = z.infer<typeof crossBudgetLineSchema>

export const statementSchema = z.discriminatedUnion('scope', [
  z.object({
    scope: z.literal('budget').describe('親 budget を指定した応答。行は団体固有の形'),
    lines: z.array(budgetLineSchema),
    nextPageToken: z.string().optional().describe('続きがあるときだけ返る。無ければ最後まで返した'),
    revision: z.string().describe('由来する配布物の revision（git commit）'),
  }),
  z.object({
    scope: z.literal('crossBudget').describe('横断の応答。行は団体に依存しない共通の最小軸のみ'),
    lines: z.array(crossBudgetLineSchema),
    nextPageToken: z.string().optional().describe('続きがあるときだけ返る。無ければ最後まで返した'),
    revision: z.string().describe('由来する配布物の revision（git commit）'),
  }),
])
export type Statement = z.infer<typeof statementSchema>

export const getStatement = base
  .route({
    method: 'GET',
    path: '/budgets/{budget}/statement',
    summary: 'Get budget statement',
    description:
      '予算の明細。`{budget}` に budget の id（{団体コード}:{年度}）を指定すると、' +
      'その予算の明細行を団体固有の階層を含む形で返す（scope: budget）。' +
      'filter には direction が必須で、phase / cofog.division を追加できる。\n\n' +
      '`{budget}` にワイルドカード `-` を指定すると全予算を横断し（AIP-159）、' +
      '団体に依存しない共通の最小軸だけの行（scope: crossBudget）を返す。' +
      'filter には cofog.division が必須で、fiscalYear を追加できる（direction / phase は使えない）。' +
      '各行の budget フィールドから親予算へ辿れる。\n\n' +
      'filter の文法は AIP-160 の部分集合（`=` と `AND` のみ）。' +
      '例: `cofog.division = "09" AND fiscalYear = 2023`。' +
      'phase は amounts[].phase に対する仮想フィールド（いずれかの段階が一致したら真）で、' +
      '一致した行の amounts は全段階のまま返る。\n\n' +
      '並び順は budgetLineId の昇順。結果が複数ページに分かれる場合は nextPageToken が返り、' +
      'nextPageToken が無いことが「最後まで返した」ことを意味する。' +
      'フィルタの該当が薄いページは pageSize 未満の件数（0件を含む）になり得るが、' +
      'nextPageToken がある限り続きがある。',
  })
  .input(z.object({ budget: z.string().describe('budget の識別子（{団体コード}:{年度}）、または全予算横断の `-`'), ...pageInput }))
  .output(statementSchema)
