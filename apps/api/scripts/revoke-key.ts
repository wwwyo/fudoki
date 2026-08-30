#!/usr/bin/env bun
/**
 * ベータ用 API キーの失効 CLI。
 *
 * 生のキー（issue-key.ts が発行時に一度だけ出力したもの）を受け取り、
 * KV 上の対応するエントリの status を revoked に書き換える。
 * エントリごと消してもよいが、いつ・誰のキーを止めたかを label ごと残すため
 * status の書き換えを既定にする。
 *
 * ⚠️ ハッシュは access-control.ts / issue-key.ts と同じ `sha256Hex`
 * （lib/apiKey.ts）を使う。ハッシュの作り方が発行側・検証側・失効側で
 * 食い違うと、正しいキーを渡しても KV 上のエントリを引けなくなる。
 *
 * ⚠️ `bunx wrangler` は使わない。issue-key.ts と同じ理由（高権限操作での
 * 意図しないパッケージ取得を避ける）で、ピン留めされた wrangler を直接呼ぶ。
 *
 * ⚠️ `--local` / `--remote` の指定を必須にする（既定を持たない）。
 * issue は既定 local でよい（開発中に何度も試すだけなので、代償の非対称性
 * ── local のつもりで remote に書くと本番に有効なキーが残る ── が効く）。
 * revoke は逆に**本番のキーを止めたい場面こそが本番運用そのもの**なので、
 * 「デフォルトで local に倒して安全」という理屈が成立しない。既定 local の
 * まま `--remote` を付け忘れると、ローカルだけ失効して本番では有効なままなのに
 * 「revoked」という成功メッセージが出てしまう ── 実行後の表示は事故が
 * 起きた後なので防止にならない。だから未指定はエラーにして usage を出す。
 *
 * ⚠️ KV の書き込み反映は最大60秒。実行直後の数十秒は access-control.ts が
 * まだ古い active を読み、失効前のキーを一時的に通すことがある（即時には止まらない）。
 *
 * 実行:
 *   bun run keys:revoke -- <生のキー> --local   # wrangler dev 用
 *   bun run keys:revoke -- <生のキー> --remote  # 本番
 */
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { apiKeyEntrySchema, sha256Hex } from '../src/lib/apiKey'

const args = process.argv.slice(2)
const remote = args.includes('--remote')
const local = args.includes('--local')
const [rawKey] = args.filter((a) => a !== '--remote' && a !== '--local')

if (rawKey === undefined || rawKey.length === 0 || (!remote && !local) || (remote && local)) {
  console.error('usage: bun run keys:revoke -- <raw key> (--local | --remote)')
  console.error('  --local and --remote are both explicit; there is no default.')
  process.exit(1)
}

const hash = await sha256Hex(rawKey)
const cwd = join(dirname(fileURLToPath(import.meta.url)), '..')
const wrangler = join(cwd, 'node_modules/.bin/wrangler')
const target = remote ? '--remote' : '--local'
const targetLabel = remote ? 'REMOTE (production)' : 'local'

const got = spawnSync(wrangler, ['kv', 'key', 'get', '--binding=API_KEYS', target, hash], {
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
  wrangler,
  ['kv', 'key', 'put', '--binding=API_KEYS', target, hash, JSON.stringify(entry)],
  { cwd, stdio: 'inherit' },
)
if (put.status !== 0) {
  console.error(`failed to write the revocation to ${targetLabel} KV`)
  process.exit(put.status ?? 1)
}

console.error(`revoked in ${targetLabel} KV: key issued for "${entry.label}" (propagation takes up to 60s)`)
