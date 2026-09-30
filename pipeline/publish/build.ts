import { queryFingerprint } from '../../apps/api/scripts/query-fingerprint'
import { PIPELINE } from '../paths'
const deploy = process.argv.includes('--deploy')
if (process.argv.slice(2).some((arg) => arg !== '--deploy'))
  throw new Error('Expected only --deploy')
if (deploy) {
  const status = Bun.spawnSync(['git', 'status', '--porcelain'], {
    cwd: import.meta.dirname,
  })
  if (status.exitCode !== 0 || status.stdout.toString().trim())
    throw new Error(
      'Commit verified changes before deploying verification code'
    )
}
const command = Bun.spawn(
  [
    'bun',
    'run',
    'wrangler',
    'deploy',
    '--config',
    'publish/wrangler.jsonc',
    ...(!deploy ? ['--dry-run', '--outdir', 'build/verification-worker'] : []),
    '--var',
    `QUERY_FINGERPRINT:${await queryFingerprint()}`,
  ],
  { cwd: PIPELINE, stdout: 'inherit', stderr: 'inherit' }
)
if ((await command.exited) !== 0)
  throw new Error('Verification Worker build or deployment failed')
