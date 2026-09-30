import { queryFingerprint } from './scripts/query-fingerprint'
const deploy = process.argv.includes('--deploy')
if (deploy) {
  const status = Bun.spawnSync(['git', 'status', '--porcelain'], {
    cwd: import.meta.dirname,
  })
  if (status.exitCode !== 0 || status.stdout.toString().trim())
    throw new Error('Commit the verified changes before deploying API code')
}
const version = await queryFingerprint()
const workerBuild = Bun.spawn(
  [
    'bun',
    'run',
    'wrangler',
    'deploy',
    ...(!deploy ? ['--dry-run', '--outdir', 'dist'] : []),
    '--var',
    `QUERY_FINGERPRINT:${version}`,
  ],
  { cwd: import.meta.dirname, stdout: 'inherit', stderr: 'inherit' }
)
if ((await workerBuild.exited) !== 0)
  throw new Error('API code build or deployment failed')
