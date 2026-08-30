/**
 * tool の応答を組み立てる道具。
 *
 * outputSchema を付けた tool は、callback が structuredContent を自分で
 * 詰めた CallToolResult を返す必要がある（SDK は検証するだけで自動生成しない）。
 * 後方互換のため同じ JSON を text content にも入れる（PRD の指示どおり）。
 */
import { ORPCError } from '@orpc/client'
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js'

export function ok(data: Record<string, unknown>): CallToolResult {
  return {
    content: [{ type: 'text', text: JSON.stringify(data, null, 2) }],
    structuredContent: data,
  }
}

function toolError(message: string): CallToolResult {
  return { isError: true, content: [{ type: 'text', text: message }] }
}

/**
 * router が投げる ORPCError（BAD_REQUEST / NOT_FOUND / STALE_PAGE_TOKEN）を
 * 例外にせず isError の結果へ変換する。MCP 仕様は tool 実行エラーを
 * 言語モデルが自己修正するための応答と位置づけており、本文には理由と
 * 代替の問い方（= errors.BAD_REQUEST の message が既に持っている）をそのまま乗せる。
 * ORPCError 以外（サーバのバグ）は握りつぶさず再 throw する。
 */
export function fromApiError(error: unknown): CallToolResult {
  if (error instanceof ORPCError) {
    const data = error.data as
      | { reason?: string; supportedGroupings?: string[][]; allowedValues?: string[] }
      | undefined
    const lines = [`${error.code}: ${error.message}`]
    if (data?.reason) lines.push(`reason: ${data.reason}`)
    // 400 の本文は「次に何を指定すればよいか」を機械可読で持つ（design doc「拒否の表し方」）。
    // reason だけ通すと、言語モデルが自己修正するための情報が本文から欠ける。
    if (data?.supportedGroupings) lines.push(`supportedGroupings: ${JSON.stringify(data.supportedGroupings)}`)
    if (data?.allowedValues) lines.push(`allowedValues: ${JSON.stringify(data.allowedValues)}`)
    return toolError(lines.join('\n'))
  }
  throw error
}
