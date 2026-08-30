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
        '⚠️ どちらの名称を持つかは団体で違う。事業名の対応づけ（project_names.csv）があるのは狛江市だけで、' +
        '三鷹市の事業名は原典の事項（jikou）の名称にそのまま載っている。例えば「いじめ」で検索すると、' +
        '三鷹市の「いじめ問題対策協議会関係費」は accountLabel/canonical、狛江市の「いじめ問題等対策推進」は ' +
        'projectName/judgment として返る。\n\n' +
        '⚠️ 応答の `coverage` を必ず読むこと。0件が「該当なし」なのか「そもそも名称が付いていない」のかは' +
        'これでしか区別できない（`namedCoverage` に NO_NAMES / PARTIAL_NAMES が団体・フィールドごとに入る）。' +
        '原典が名称を一切持たない階層（例: 狛江市の款・項・目）を `level` に指定すると、0件ではなく400になる。\n\n' +
        '`direction` と `phase` は任意（集計と違い、名称を引く段階では条件が定まっていないのが普通）。' +
        '絞らずに投げても、返る match 1件ごとに `fiscalYear` / `direction` / `fund` が明示されるので、' +
        '後から個々の match で条件を確認できる。`fund` を指定するには filter に jurisdiction が必須' +
        '（会計コードは団体で揃わない）。',
      inputSchema: searchBudgetLinesInput,
      outputSchema: searchBudgetLinesOutput,
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
