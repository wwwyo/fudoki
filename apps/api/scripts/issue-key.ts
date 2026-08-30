#!/usr/bin/env bun
/**
 * ベータ用 API キーの発行 CLI。
 *
 * ランダムなキーを生成し、**SHA-256 ハッシュだけ**を KV（API_KEYS binding）へ put する。
 * 生のキーはここでの標準出力にしか出ない ── KV には残らないので、後から同じ値を
 * 再表示する経路は無い（紛失したら revoke して発行し直す）。
 *
 * ⚠️ 既定は local（`wrangler kv key put --local`）。本番へ書くときだけ
 * 明示的に `--remote` を渡す。誤操作の代償が非対称なため:
 *   - local のつもりで remote に書くと、本番に意図しない有効なキーが残る。
 *     生のキーは1度しか表示されないので後から中身を確認する経路も無い
 *   - remote のつもりで local に書いても、単に「効かない」だけで気づける
 * 安全な側（local）を既定にし、危険な側（remote）を明示にする。
 *
 * 実行には Cloudflare への書き込み権限が要る（`--remote` のときのみ）。
 * `wrangler login` 済みか、`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` が
 * 環境にある状態で実行すること
 * （このリポジトリの秘密管理方針に従い、トークンは mise + age で持つ。平文でここに書かない）。
 *
 * 実行:
 *   bun run keys:issue -- <発行先ラベル>           # local（wrangler dev 用）
 *   bun run keys:issue -- <発行先ラベル> --remote  # 本番
 */
import { createHash, randomBytes } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { apiKeyEntrySchema } from '../src/lib/apiKey'

const args = process.argv.slice(2)
const remote = args.includes('--remote')
const [label] = args.filter((a) => a !== '--remote')
if (label === undefined || label.length === 0) {
  console.error('usage: bun run keys:issue -- <label> [--remote]')
  process.exit(1)
}

const rawKey = `fdk_${randomBytes(24).toString('base64url')}`
const hash = createHash('sha256').update(rawKey).digest('hex')
const entry = apiKeyEntrySchema.parse({
  label,
  issuedAt: new Date().toISOString(),
  status: 'active',
})

const cwd = join(dirname(fileURLToPath(import.meta.url)), '..')
const target = remote ? '--remote' : '--local'
const result = spawnSync(
  'bunx',
  ['wrangler', 'kv', 'key', 'put', '--binding=API_KEYS', target, hash, JSON.stringify(entry)],
  { cwd, stdio: 'inherit' },
)
if (result.status !== 0) {
  console.error('failed to write the key to KV')
  process.exit(result.status ?? 1)
}

console.error(`wrote to ${remote ? 'REMOTE (production)' : 'local'} KV, for "${label}".`)
console.error('Store the key below now — it will not be shown again:')
console.log(rawKey)
