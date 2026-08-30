#!/usr/bin/env bun
/**
 * ベータ用 API キーの失効 CLI。
 *
 * 生のキー（issue-key.ts が発行時に一度だけ出力したもの）を受け取り、
 * KV 上の対応するエントリの status を revoked に書き換える。
 * エントリごと消してもよいが、いつ・誰のキーを止めたかを label ごと残すため
 * status の書き換えを既定にする。
 *
 * ⚠️ 既定は local（`wrangler kv key get/put --local`）。本番のキーを止めるときだけ
 * 明示的に `--remote` を渡す。issue-key.ts と同じ非対称性が理由:
 * local のつもりで remote に書くと本番に意図しない変更が残り、
 * remote のつもりで local に書いても「効かない」だけで気づける。
 * ⚠️ ただし revoke は「本番のキーを止めたい」が実行動機のほぼ全てなので、
 * 既定 local のまま気づかずに実行して「止めたつもりが止まっていない」を
 * 起こさないよう、実行後に必ずどちらを操作したかを標準エラーへ出す。
 *
 * ⚠️ KV の書き込み反映は最大60秒。実行直後の数十秒は access-control.ts が
 * まだ古い active を読み、失効前のキーを一時的に通すことがある（即時には止まらない）。
 *
 * 実行:
 *   bun run keys:revoke -- <生のキー>           # local（wrangler dev 用）
 *   bun run keys:revoke -- <生のキー> --remote  # 本番
 */
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { apiKeyEntrySchema } from '../src/lib/apiKey'

const args = process.argv.slice(2)
const remote = args.includes('--remote')
const [rawKey] = args.filter((a) => a !== '--remote')
if (rawKey === undefined || rawKey.length === 0) {
  console.error('usage: bun run keys:revoke -- <raw key> [--remote]')
  process.exit(1)
}

const hash = createHash('sha256').update(rawKey).digest('hex')
const cwd = join(dirname(fileURLToPath(import.meta.url)), '..')
const target = remote ? '--remote' : '--local'
const targetLabel = remote ? 'REMOTE (production)' : 'local'

const got = spawnSync('bunx', ['wrangler', 'kv', 'key', 'get', '--binding=API_KEYS', target, hash], {
  cwd,
  encoding: 'utf8',
})
if (got.status !== 0 || got.stdout.trim().length === 0) {
  console.error(`no such key in ${targetLabel} KV (already revoked/deleted, or never issued there)`)
  process.exit(1)
}

const entry = apiKeyEntrySchema.parse(JSON.parse(got.stdout))
if (entry.status === 'revoked') {
  console.error(`already revoked in ${targetLabel} KV: ${entry.label}`)
  process.exit(0)
}
entry.status = 'revoked'

const put = spawnSync(
  'bunx',
  ['wrangler', 'kv', 'key', 'put', '--binding=API_KEYS', target, hash, JSON.stringify(entry)],
  { cwd, stdio: 'inherit' },
)
if (put.status !== 0) {
  console.error(`failed to write the revocation to ${targetLabel} KV`)
  process.exit(put.status ?? 1)
}

console.error(`revoked in ${targetLabel} KV: key issued for "${entry.label}" (propagation takes up to 60s)`)
