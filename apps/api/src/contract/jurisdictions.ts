/**
 * jurisdictions リソース（収録団体）。
 * 一覧・詳細と、団体ごとのメタデータ（収録年度、注意事項、COFOG 分類率、
 * 配布物への発見経路）の型を持つ。
 *
 * 各フィールドの `.describe()` は OpenAPI の description にそのまま出る。
 */
import * as z from 'zod'
import { base, resourceName } from './shared'

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
  datapackagePath: z.string().describe('配布物（datapackage.json）へのパス。出典・ライセンス・改変表示の正本'),
  resources: z.array(z.string()).describe('パススルー（/datapackages/{id}/{file}）で取得できるファイル名'),
  licenses: z
    .array(z.object({
      name: z.string().describe('SPDX 形式のライセンス名（例: CC-BY-4.0）'),
      title: z.string().describe('ライセンスの表示名'),
      path: z.string().describe('ライセンス本文の URL'),
    }))
    .describe(
      '配布物のライセンス。⚠️ **空配列は「利用条件が未確定」を意味する**'
      + '（原典の許諾を fudoki が判断できておらず、fudoki 自身のライセンスも貼っていない）。'
      + 'そのときは caveats の sourceAndLicense と、sources の原典を確認すること',
    ),
  sources: z
    .array(z.object({
      title: z.string().describe('出典の名前'),
      path: z.string().nullable().describe('出典の URL。無ければ null'),
    }))
    .describe('原典の出典。再配布時の帰属表示に使う'),
  consolidationScope: z.string().describe('会計間の繰出・繰入の連結（消去）をどの範囲で行ったか。消去していない団体は全会計合計が二重計上を含む'),
  caveats: z.array(caveatSchema).describe('この団体のデータを使う前に知るべき注意事項。データ（enum・数値・構造）から見えず解釈を変えるものに絞ってある。調査・検証の全記録はダッシュボード（https://fudoki.dev/）にある'),
})
export type Jurisdiction = z.infer<typeof jurisdictionSchema>

export const listJurisdictions = base
  .route({
    method: 'GET',
    path: '/jurisdictions',
    summary: 'List jurisdictions',
    description:
      '収録団体の一覧。団体の同一性・注意事項（caveats）と、' +
      '配布物（datapackage.json）への参照を返す。' +
      '収録している予算（年度）と分類率は /budgets?filter=jurisdiction%20=%20"{id}" から取得する（カバレッジは budgets の List から導出する）。',
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
