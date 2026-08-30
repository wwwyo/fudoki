/**
 * aggregate_budgets tool。`aggregateBudgets` procedure をそのまま呼ぶだけ。
 * MCP 側では集計しない・応答を組み替えない（AGENTS.md「集計は1箇所」）。
 */
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import * as z from 'zod'
import { aggregateBudgetsOutput, direction, groupingKey, phaseId } from '../../contract'
import type { ApiClient } from '../client'
import { fromApiError, ok } from '../result'

const inputSchema = z.object({
  filter: z
    .string()
    .optional()
    .describe(
      'AIP-160 の部分集合（`=` と `AND` のみ）。使えるフィールドは jurisdiction / fiscalYear。' +
        'fiscalYear は必須。jurisdiction も指定すると1つの予算（団体×年度）に閉じた集計になり、' +
        '省略するとその年度の全団体を横断する集計になる（このときは groupBy に jurisdiction が必須）。' +
        '例: `jurisdiction = "132047" AND fiscalYear = "2024"`、`fiscalYear = "2023"`',
    ),
  direction: direction.describe(
    '歳出 / 歳入。必須。COFOG は歳入には無い（cofog_status は常に not-applicable）ので revenue を指定すると 400 になる',
  ),
  phase: phaseId.describe(
    '予算段階。必須で既定値は無い。同じ明細が予算段階ごとに複数の金額（当初予算額・補正後・執行済額など）を' +
      '持つ団体があり、段階を固定しないと同じ明細を複数回合算することになるため。\n\n' +
      '⚠️ 段階は団体で違う（例: 三鷹市・多摩市は approved のみ、狛江市は adjusted 系のみ）。' +
      'このまま推測で指定せず、先に list_budgets を呼び、集計したい団体の scopes[direction].phases に' +
      '実在する id を確認してから指定すること。存在しない phase を指定すると 400（応答に allowedValues が入る）',
  ),
  fund: z
    .string()
    .optional()
    .describe(
      '会計コード。既定は "all"（全会計を合算）。会計コードは団体で揃わない（例: 一般会計は三鷹市 "01" / ' +
        '狛江市 "1" / 多摩市 ""）ので、fund を指定できるのは filter で団体を1つに絞ったときだけ。' +
        '団体を絞らずに指定すると 400。\n\n' +
        '⚠️ groupBy に hierarchy を含めるときは "all" を指定できない（会計を1つに絞ることが必須）。' +
        '款・項のコードは会計の中でしか意味を持たず、例えば三鷹市の款コード "01" は一般会計では議会費、' +
        '国民健康保険事業特別会計では総務費である。COFOG と違って会計をまたぐ正規化が無いので、' +
        '"all" のまま集計すると無関係な科目が黙って合算される。会計コードは団体ごとに違うので、' +
        '先に list_budgets の scopes[direction].funds で対象団体に実在する値を確認してから指定すること',
    ),
  groupBy: z
    .array(groupingKey)
    .min(1)
    .max(2)
    .describe(
      '集計の軸。前計算済みの組み合わせしか引けず、許される組み合わせは応答の supportedGroupings に入る。\n\n' +
        '⚠️ filter が複数団体にまたがる（jurisdiction を指定していない）ときは、groupBy に jurisdiction を' +
        '含めることが必須。含めないと「団体をまたいだ合計」という存在しない数値になるため 400 になる' +
        '（例: `["jurisdiction", "cofog.division"]`）。filter で団体を1つに絞ったときは、逆に jurisdiction を' +
        '軸にできない（すべてのセルが同じ団体になるため）',
    ),
  hierarchyParent: z
    .string()
    .optional()
    .describe(
      'groupBy に hierarchy を含めるときだけ使う。指定した親の直下1段だけを返す（親自身の合計は含まない）。' +
        '省略すると根（款の一覧）を返す。指定できるのは款（例: `kan=10`）と項（例: `kan=10/kou=04`）までで、' +
        '目（moku）を指定すると 400 になる（目より下は事業階層で、集計の軸にはしていない）',
    ),
  pageSize: z
    .coerce
    .number()
    .int()
    .min(0)
    .optional()
    .describe('1ページの最大件数。未指定・0 は既定値 1000。上限 1000（超過は丸める）'),
  pageToken: z
    .string()
    .optional()
    .describe('前ページの nextPageToken。発行時と同じ条件（filter・direction・phase・fund・groupBy）でだけ使える'),
})

export function registerAggregateBudgets(server: McpServer, client: ApiClient): void {
  server.registerTool(
    'aggregate_budgets',
    {
      title: 'Aggregate budgets',
      description:
        '団体・年度で絞った予算を COFOG（大分類・中分類・小分類）別、または科目階層（款・項・目）別に' +
        '集計する。実行時の再集計はせず、前計算済みの組み合わせだけを引く（応答の supportedGroupings が' +
        '引ける組み合わせの全部）。\n\n' +
        '`direction` と `phase` は必須（既定値なし）。同じ明細が複数の予算段階（当初予算額・補正後・' +
        '執行済額など）の金額を持つ団体があり、段階を固定しないと同じ明細を複数回合算することになる。' +
        '段階は団体ごとに違うので、まず list_budgets で対象団体の scopes[direction].phases を見て、' +
        'その団体の direction に実在する phase を選んでから呼ぶこと。\n\n' +
        '複数の団体にまたがる集計（filter に jurisdiction を指定しない）は、groupBy に jurisdiction を' +
        '含めることが必須。含めないと 400（団体をまたいだ合計は存在しない数値になるため）。\n\n' +
        '⚠️ 科目階層の軸（groupBy に hierarchy を含める）を使うときは fund を会計コード1つに絞ることが必須' +
        '（"all" は 400）。款・項のコードは会計の中でしか意味を持たない ── 三鷹市の款コード "01" は' +
        '一般会計では議会費、国民健康保険事業特別会計では総務費である。会計コードは団体で違うので、' +
        '先に list_budgets の scopes[direction].funds で対象団体に実在する値を確認すること。' +
        '`hierarchyParent` で直下1段を辿る（未指定は根＝款の一覧、目より下は 400）。\n\n' +
        '応答の `cells`（グループごとの内訳）と `residual`（unclassifiable / outOfScope / notDescended の' +
        '合計）を足すと、filter が1団体に閉じているときだけ返る `total` に一致する（複数団体にまたがる' +
        'ときは total 自体を返さない）。`residual.notDescended` は割当済み（cofog_status=assigned）だが' +
        '要求した粒度のコードを持たない行の金額 ── 「分類できていない」のではなく「その粒度にまだ降りて' +
        'いない」ことを表す。',
      inputSchema,
      outputSchema: aggregateBudgetsOutput,
    },
    async (input) => {
      try {
        const result = await client.aggregateBudgets({
          filter: input.filter,
          direction: input.direction,
          phase: input.phase,
          fund: input.fund,
          groupBy: input.groupBy,
          hierarchyParent: input.hierarchyParent,
          pageSize: input.pageSize,
          pageToken: input.pageToken,
        })
        return ok(result)
      } catch (error) {
        return fromApiError(error)
      }
    },
  )
}
