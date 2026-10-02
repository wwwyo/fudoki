import { getPlatformProxy } from 'wrangler'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import config from '../cloudflare.config.ts'

const [action, key, value] = process.argv.slice(2)
if (!['init-d1', 'kv-get', 'kv-put'].includes(action))
  throw new Error('Expected init-d1, kv-get, or kv-put')
if (action !== 'init-d1' && !/^[a-f0-9]{64}$/.test(key ?? ''))
  throw new Error('Expected a SHA-256 key')
if (action === 'kv-put') JSON.parse(value)
const { worker } = await config({ mode: 'development', isPreview: false })
const directory = await mkdtemp(join(tmpdir(), 'fudoki-local-bindings-'))
let platform
try {
  const configPath = join(directory, 'proxy.json')
  // cf's local D1 endpoint is incomplete; the builder's proxy uses the same persistence.
  await writeFile(
    configPath,
    JSON.stringify({
      name: worker.name,
      compatibility_date: worker.compatibilityDate,
      d1_databases: [
        {
          binding: 'DB',
          database_name: worker.env.DB.name,
          database_id: worker.env.DB.id,
        },
      ],
      kv_namespaces: [{ binding: 'API_KEYS', id: worker.env.API_KEYS.id }],
    }),
    { mode: 0o600 }
  )
  platform = await getPlatformProxy({
    configPath,
    remoteBindings: false,
    envFiles: [],
    persist: {
      path: fileURLToPath(new URL('../.wrangler/state/v3', import.meta.url)),
    },
  })
  if (action === 'init-d1') await platform.env.DB.prepare('SELECT 1').all()
  else if (action === 'kv-put') await platform.env.API_KEYS.put(key, value)
  else {
    const stored = await platform.env.API_KEYS.get(key)
    if (stored === null) process.exitCode = 1
    else process.stdout.write(stored)
  }
} finally {
  await platform?.dispose()
  await rm(directory, { recursive: true, force: true })
}
