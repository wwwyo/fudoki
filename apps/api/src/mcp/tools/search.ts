/**
 * search_budget_lines tool。`searchBudgetLines` procedure をそのまま呼ぶだけ。
 * MCP 側では検索しない・応答を組み替えない（AGENTS.md「集計は1箇所」と同じ理由で、
 * 名称の解決も判断も apps/api 側に持たせる）。
 *
 * inputSchema/outputSchema は contract の searchBudgetLinesInput/Output をそのまま使う
 * （aggregate.ts と違い、フィールドの説明を書き直す理由が無い ── contract 側の説明が
 * 既に AIP の HTTP 利用者と同じ疑問に答えている）。ただし contract/index.ts のバレルは
 * 型（SearchBudgetLinesOutput）しか再輸出していないので、schema 自体は contract/budgets
 * から直接 import する。
 */
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { searchBudgetLinesInput, searchBudgetLinesOutput } from '../../contract/budgets'
import type { ApiClient } from '../client'
import { fromApiError, ok } from '../result'

export function registerSearchBudgetLines(server: McpServer, client: ApiClient): void {
  server.registerTool(
    'search_budget_lines',
    {
      title: 'Search budget lines by name',
      description:
        '名称の部分一致で予算の明細を横断検索する（get_budget_lines・aggregate_budgets はコードで絞るが、' +
        'こちらは名称の語で発見する）。\n\n' +
        '検索対象は2種類ある。`accountLabel`（原典の科目階層の名称。nameSource は canonical）と ' +
        '`projectName`（fudoki が決算資料等から対応づけた事業名。nameSource は judgment）。nameField を' +
        '省略すると両方を検索する。\n\n' +
        '⚠️ どちらの名称を持つかは団体で違う。ある団体は事業名を fudoki が決算資料等から対応づけている一方、' +
        '別の団体では原典の科目階層の名称自体が事業名を兼ねていることがある（同じ語の検索でも、団体によって' +
        'accountLabel/canonical で当たったり projectName/judgment で当たったりする）。\n\n' +
        '⚠️ 応答の `coverage` を必ず読むこと。0件が「該当なし」なのか「そもそも名称が付いていない」のかは' +
        'これでしか区別できない（`namedCoverage` に NO_NAMES / PARTIAL_NAMES が団体・フィールドごとに入る）。' +
        '原典が名称を一切持たない階層を `level` に指定すると、0件ではなく400になる' +
        '（どの団体のどの階層に名称が無いかは list_jurisdictions / list_budgets の収録状況で確認する）。\n\n' +
        '`direction` と `phase` は任意（集計と違い、名称を引く段階では条件が定まっていないのが普通）。' +
        '絞らずに投げても、返る match 1件ごとに `fiscalYear` / `direction` / `fund` が明示されるので、' +
        '後から個々の match で条件を確認できる。`fund` を指定するには filter に jurisdiction が必須' +
        '（会計コードは団体で揃わない）。',
      inputSchema: searchBudgetLinesInput,
      outputSchema: searchBudgetLinesOutput,
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async (input) => {
      try {
        const result = await client.searchBudgetLines({
          query: input.query,
          filter: input.filter,
          direction: input.direction,
          phase: input.phase,
          fund: input.fund,
          nameField: input.nameField,
          level: input.level,
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
