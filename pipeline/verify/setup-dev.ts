import { copyFile, readdir, rm } from 'node:fs/promises'
import { Database } from 'bun:sqlite'
import { join } from 'node:path'
import { REPO, BUILD } from '../paths'
import { verifyCandidate } from '../fdp/manifest'
import { LATEST } from '../paths'

const revision = Bun.spawnSync(['git', 'rev-parse', 'HEAD'], {
  cwd: REPO,
  stdout: 'pipe',
  stderr: 'inherit',
})
if (revision.exitCode !== 0)
  throw new Error('Unable to resolve Git manifest URL')

if (!LATEST) throw new Error('Run pipeline:build before loading local D1')
const candidate = join(BUILD, 'builds', LATEST.releaseId)
const manifest = await verifyCandidate(candidate)

const api = join(REPO, 'apps/api')
const init = Bun.spawn(['node', 'scripts/local-bindings.mjs', 'init-d1'], {
  cwd: api,
  stdout: 'ignore',
  stderr: 'inherit',
})
if ((await init.exited) !== 0) throw new Error('Unable to initialize local D1')
const directory = join(api, '.wrangler/state/v3/d1/miniflare-D1DatabaseObject')
const files = (await readdir(directory)).filter((name) =>
  /^[a-f0-9]{64}\.sqlite$/.test(name)
)
if (files.length !== 1)
  throw new Error(
    'Expected exactly one local D1 database. Stop dev servers and check the local state directory.'
  )
const target = join(directory, files[0]!)
const opened = Bun.spawnSync(['lsof', '-t', target], {
  stdout: 'pipe',
  stderr: 'ignore',
})
if (opened.exitCode !== 1 || opened.stdout.toString().trim())
  throw new Error(
    'Stop the API dev Worker before replacing its local D1 database; lsof must confirm that it is closed'
  )
for (const suffix of ['-wal', '-shm'])
  await rm(target + suffix, { force: true })
await copyFile(join(BUILD, 'candidate.sqlite'), target)
const db = new Database(target)
try {
  const versions = db
    .query(
      'SELECT version_id FROM fiscal_jurisdiction_versions ORDER BY jurisdiction_code'
    )
    .all() as { version_id: string }[]
  if (
    JSON.stringify(versions.map((row) => row.version_id)) !==
    JSON.stringify(manifest.versions.map((row) => row.versionId))
  )
    throw new Error('Local database belongs to another candidate')
  db.prepare(
    'UPDATE fiscal_jurisdiction_versions SET manifest_url=?,manifest_sha256=?'
  ).run(
    `https://raw.githubusercontent.com/wwwyo/fudoki/${revision.stdout.toString().trim()}/pipeline/publish/manifest.json`,
    manifest.manifestSha256
  )
} finally {
  db.close()
}
console.log(
  JSON.stringify({
    database: 'fudoki',
    mode: 'local',
    source: 'verified candidate',
  })
)
