import { copyFile, readFile, readdir, rm } from 'node:fs/promises'
import { Database } from 'bun:sqlite'
import { join } from 'node:path'
import { REPO, BUILD } from '../paths'
import { verifyCandidate } from '../fdp/manifest'
import { LATEST } from '../paths'
import { sha256 } from '../release'

const revision = Bun.spawnSync(['git', 'rev-parse', 'HEAD'], {
  cwd: REPO,
  stdout: 'pipe',
  stderr: 'inherit',
})
if (revision.exitCode !== 0)
  throw new Error('Unable to resolve Git manifest URL')

if (!LATEST) throw new Error('Run pipeline:build before loading local D1')
const candidate = join(BUILD, 'releases', LATEST.releaseId)
const manifest = await verifyCandidate(candidate)
const manifestBytes = await readFile(join(candidate, 'verification.json'))

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
  const active = db
    .query('SELECT release_id FROM active_release WHERE singleton=1')
    .get() as { release_id: string } | null
  if (active?.release_id !== manifest.releaseId)
    throw new Error(
      'Local database belongs to another candidate; rebuild before loading it'
    )
  db.transaction(() => {
    const insert = db.prepare(
      'INSERT INTO files(release_id,path,object_key,sha256,bytes,content_type) VALUES(?,?,?,?,?,?)'
    )
    for (const file of manifest.files)
      insert.run(
        manifest.releaseId,
        file.path,
        file.objectKey,
        file.sha256,
        file.bytes,
        file.contentType
      )
    db.prepare(
      'UPDATE releases SET manifest_url=?,verification_sha256=?,code_revision=?,input_fingerprint=? WHERE release_id=?'
    ).run(
      `https://raw.githubusercontent.com/wwwyo/fudoki/${revision.stdout.toString().trim()}/pipeline/publish/manifest.json`,
      sha256(manifestBytes),
      manifest.codeRevision,
      manifest.inputFingerprint,
      manifest.releaseId
    )
  })()
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
