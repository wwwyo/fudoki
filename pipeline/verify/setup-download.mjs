import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { getPlatformProxy } from 'wrangler'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import config from '../../apps/download/cloudflare.config.ts'

const build = new URL('../build/', import.meta.url)
const latest = JSON.parse(await readFile(new URL('latest.json', build), 'utf8'))
if (!/^r-[a-f0-9]{32}$/.test(latest.releaseId))
  throw new Error('A verified local release is required')
const directory = new URL(`releases/${latest.releaseId}/`, build)
const manifest = JSON.parse(
  await readFile(new URL('manifest.json', directory), 'utf8')
)
const temporary = await mkdtemp(join(tmpdir(), 'fudoki-local-downloads-'))
let platform
try {
  const { worker } = config
  const configPath = join(temporary, 'proxy.json')
  await writeFile(
    configPath,
    JSON.stringify({
      name: worker.name,
      compatibility_date: worker.compatibilityDate,
      r2_buckets: [
        { binding: 'RELEASES', bucket_name: worker.env.RELEASES.name },
      ],
    }),
    { mode: 0o600 }
  )
  platform = await getPlatformProxy({
    configPath,
    remoteBindings: false,
    envFiles: [],
    persist: {
      path: fileURLToPath(
        new URL('../../apps/download/.wrangler/state/v3', import.meta.url)
      ),
    },
  })
  for (const file of manifest.files) {
    if (
      !/^(?:catalog\.json|fiscal\/\d{6}\/[a-z_]+\.(?:csv|json))$/.test(
        file.path
      )
    )
      throw new Error('Unexpected distribution file')
    await platform.env.RELEASES.put(
      file.objectKey,
      await readFile(new URL(file.path, directory)),
      { httpMetadata: { contentType: file.contentType } }
    )
  }
  await platform.env.RELEASES.put(
    `releases/${latest.releaseId}/manifest.json`,
    await readFile(new URL('manifest.json', directory)),
    { httpMetadata: { contentType: 'application/json; charset=utf-8' } }
  )
  console.log(
    JSON.stringify({
      mode: 'local',
      releaseId: latest.releaseId,
      files: manifest.files.length,
    })
  )
} finally {
  await platform?.dispose()
  await rm(temporary, { recursive: true, force: true })
}
