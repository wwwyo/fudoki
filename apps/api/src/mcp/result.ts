/**
 * tool の応答を組み立てる道具。
 *
 * outputSchema を付けた tool は、callback が structuredContent を自分で
 * 詰めた CallToolResult を返す必要がある（SDK は検証するだけで自動生成しない）。
 * 後方互換のため同じ JSON を text content にも入れる（PRD の指示どおり）。
 */
import { ORPCError } from '@orpc/client'
import type { CallToolResult } from '@modelcontextprotocol/server'

export function ok(data: Record<string, unknown>): CallToolResult {
  return {
    content: [{ type: 'text', text: JSON.stringify(data, null, 2) }],
    structuredContent: data,
  }
}

function toolError(message: string): CallToolResult {
  return { isError: true, content: [{ type: 'text', text: message }] }
}

/** Convert public API errors into a tool error while preserving the reason. */
export async function runTool(
  fn: () => Promise<Record<string, unknown>>
): Promise<CallToolResult> {
  try {
    return ok(await fn())
  } catch (error) {
    return fromApiError(error)
  }
}

export function fromApiError(error: unknown): CallToolResult {
  if (error instanceof ORPCError) {
    const data = error.data as { reason?: string } | undefined
    const lines = [`${error.code}: ${error.message}`]
    if (data?.reason) lines.push(`reason: ${data.reason}`)
    return toolError(lines.join('\n'))
  }
  throw error
}
