/**
 * ベータ用 API キーの KV エントリのスキーマ。
 *
 * 書き手（scripts/issue-key.ts・scripts/revoke-key.ts）と読み手
 * （access-control.ts の middleware）は別プロセス・別タイミングで動くので、
 * TypeScript の型だけでは両者の食い違いを検出できない。ここで zod スキーマを
 * 1つ定義し、両方から import することで、JSON の境界でも壊れたら気づける形にする
 * （AGENTS.md「型が効かない場所は、実装を変えた瞬間に壊れる場所である」）。
 *
 * KV のキー側は生のキーの SHA-256 ハッシュ（生のキーは保存しない）。
 */
import * as z from 'zod'

export const apiKeyEntrySchema = z.object({
  /** 発行先ラベル（誰に配ったキーか。人間可読） */
  label: z.string(),
  issuedAt: z.string(),
  status: z.enum(['active', 'revoked']),
})

export type ApiKeyEntry = z.infer<typeof apiKeyEntrySchema>

/** SHA-256 の hex 文字列。Web Crypto は Workers 実行時にも bun test にも両方ある */
export async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input))
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}
