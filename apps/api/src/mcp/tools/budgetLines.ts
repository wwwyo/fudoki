/**
 * get_budget_lines tool。`getBudgetLines` procedure をそのまま呼ぶだけ。
 * 団体によっては明細の件数が多いので、ページングをそのまま露出する。
 *
 * contract の `getBudgetLinesOutput` は判別可能な union をやめて view にした
 * 単一の object schema なので（design doc「明細の一覧」）、MCP SDK 1.30.0 の
 * `registerTool` がトップレベル union の outputSchema を扱えない問題（旧 statement.ts が
 * 抱えていた制約）はそもそも起きない。outputSchema・inputSchema とも contract をそのまま使う。
 */
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { getBudgetLinesInput, getBudgetLinesOutput } from '../../contract'
import type { ApiClient } from '../client'
import { runTool } from '../result'

export function registerGetBudgetLines(server: McpServer, client: ApiClient): void {
  server.registerTool(
    'get_budget_lines',
    {
      title: 'Get budget lines',
      description:
        '予算の明細（budgetLines）を取得する。budget に budget の id を指定すると、その予算の明細を返す。' +
        'budget に `-` を指定すると全予算を横断し、団体に依存しない共通の最小軸だけの行を返す' +
        '（cofog.division の指定が必須）。\n\n' +
        '`view` で応答の充足度を選ぶ（既定 BASIC）。BASIC は name・budget・direction・金額（isPrimary の' +
        '1段階）・共通の COFOG 項目だけの軽量な形。FULL は団体固有の科目階層（hierarchy）・階層以外の軸' +
        '（dimensions）・全段階の金額（amounts）・fudoki の判断の全体（judgments）を追加する。' +
        'FULL は実在する budget を親にしたときだけ指定できる（`-` では 400）。\n\n' +
        '⚠️ filter は省略できない。budget に実在する id を指定したときは direction が必須' +
        '（省略すると 400）。budget に `-` を指定したときは cofog.division が必須（省略すると 400）。' +
        'いずれの場合も団体によっては該当行数が多いので、phase も添えて絞ってから呼ぶこと。' +
        '続きがあるときだけ nextPageToken が返る（無ければ最後まで返した）。\n\n' +
        '⚠️ view=FULL の amounts は予算段階（phase）ごとの金額を持つ。同じ団体でも決算資料の行は複数段階' +
        '（当初予算額・補正後・執行済額など）を持つことがあるので、集計するときは phase を' +
        '固定してから合算すること。団体をまたぐ合算は list_budgets の amountPhase が違う団体どうしでは行わないこと。',
      inputSchema: getBudgetLinesInput,
      outputSchema: getBudgetLinesOutput,
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async (input) =>
      runTool(() =>
        client.getBudgetLines({
          budget: input.budget,
          view: input.view,
          filter: input.filter,
          pageSize: input.pageSize,
          pageToken: input.pageToken,
        }),
      ),
  )
}
