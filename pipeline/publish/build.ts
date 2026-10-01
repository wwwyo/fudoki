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
  ['mise', 'exec', '--', 'cf', 'deploy', ...(!deploy ? ['--dry-run'] : [])],
  { cwd: import.meta.dirname, stdout: 'inherit', stderr: 'inherit' }
)
if ((await command.exited) !== 0)
  throw new Error('Worker build or deployment failed')
