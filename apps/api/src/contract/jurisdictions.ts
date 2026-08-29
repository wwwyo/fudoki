/**
 * jurisdictions リソース（収録団体）。
 * 一覧・詳細と、団体ごとのメタデータ（収録年度、注意事項、COFOG 分類率、
 * 配布物への発見経路）の型を持つ。
 *
 * 各フィールドの `.describe()` は OpenAPI の description にそのまま出る。
 */
import * as z from 'zod'
import { base, levelName, phaseId, resourceName } from './shared'

export const classificationRateSchema = z.object({
  fiscalYear: z.string().describe('会計年度（西暦）'),
  amountPhase: phaseId.describe('金額ベースの分類率の計算に使った予算段階'),
  statuses: z
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
    .describe('COFOG 分類の内訳（assigned=割当済み / unclassifiable=分類不能 / outOfScope=対象外）。分母は歳出明細で、3状態の合計が歳出全体に一致する'),
})
export type ClassificationRate = z.infer<typeof classificationRateSchema>

export const caveatSchema = z.object({
  category: z
    .enum(['coverage', 'phaseSemantics', 'classification', 'sourceAndLicense', 'other'])
    .describe('注意事項の分類（coverage=収録範囲と欠損 / phaseSemantics=予算段階の意味 / classification=COFOG 分類の限界 / sourceAndLicense=出典と再配布上の制約 / other=その他）'),
  topic: z.string().describe('注意事項の見出し'),
  body: z.string().describe('本文。数値の主張には実測日を含む'),
})

export const jurisdictionSchema = z.object({
  name: resourceName.describe('リソース名（AIP-122）。jurisdictions/{団体コード}'),
  id: z.string().describe('全国地方公共団体コード（例: 三鷹市 132047、狛江市 132195）'),
  label: z.string().describe('団体名'),
  fiscalYears: z
    .object({
      expenditure: z.array(z.string()).describe('歳出を収録している年度'),
      revenue: z.array(z.string()).describe('歳入を収録している年度'),
    })
    .describe('収録範囲。ここに無い年度への問い合わせは 404'),
  levels: z
    .object({
      expenditure: z.array(levelName).describe('歳出の階層名の並び'),
      revenue: z.array(levelName).describe('歳入の階層名の並び'),
    })
    .describe('団体固有の階層の並び（datapackage の宣言由来）。budgetLines 応答の hierarchy はこの順で並ぶ'),
  datapackagePath: z.string().describe('配布物（datapackage.json）へのパス。出典・ライセンス・改変表示の正本'),
  resources: z.array(z.string()).describe('パススルー（/datapackages/{id}/{file}）で取得できるファイル名'),
  licenses: z
    .array(z.object({
      name: z.string().describe('SPDX 形式のライセンス名（例: CC-BY-4.0）'),
      title: z.string().describe('ライセンスの表示名'),
      path: z.string().describe('ライセンス本文の URL'),
    }))
    .describe('配布物のライセンス'),
  sources: z
    .array(z.object({
      title: z.string().describe('出典の名前'),
      path: z.string().nullable().describe('出典の URL。無ければ null'),
    }))
    .describe('原典の出典。再配布時の帰属表示に使う'),
  consolidationScope: z.string().describe('会計間の繰出・繰入の連結（消去）をどの範囲で行ったか。消去していない団体は全会計合計が二重計上を含む'),
  caveats: z.array(caveatSchema).describe('この団体のデータを使う前に知るべき注意事項'),
  classificationRates: z.array(classificationRateSchema).describe('年度ごとの COFOG 分類率。COFOG で絞った結果に含まれない明細の規模がここで分かる'),
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
      revision: z.string().describe('由来する配布物の revision（git commit）'),
    }),
  )

export const getJurisdiction = base
  .route({
    method: 'GET',
    path: '/jurisdictions/{jurisdiction}',
    summary: 'Get a jurisdiction',
  })
  .input(z.object({ jurisdiction: z.string().describe('全国地方公共団体コード') }))
  .output(
    z.object({
      jurisdiction: jurisdictionSchema,
      revision: z.string().describe('由来する配布物の revision（git commit）'),
    }),
  )
