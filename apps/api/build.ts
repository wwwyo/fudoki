const deploy = process.argv.includes('--deploy')
if (deploy) {
  const status = Bun.spawnSync(['git', 'status', '--porcelain'], {
    cwd: import.meta.dirname,
  })
  if (status.exitCode !== 0 || status.stdout.toString().trim())
    throw new Error('Commit the verified changes before deploying API code')
}
const workerBuild = Bun.spawn(
  ['mise', 'exec', '--', 'cf', 'deploy', ...(!deploy ? ['--dry-run'] : [])],
  { cwd: import.meta.dirname, stdout: 'inherit', stderr: 'inherit' }
)
if ((await workerBuild.exited) !== 0)
  throw new Error('Worker build or deployment failed')
