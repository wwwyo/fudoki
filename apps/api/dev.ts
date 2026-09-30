import { unstable_dev } from 'wrangler'
import { randomBytes } from 'node:crypto'
import { join } from 'node:path'
import { queryFingerprint } from './scripts/query-fingerprint.ts'

const worker = await unstable_dev(join(import.meta.dirname, 'src/index.ts'), {
  config: join(import.meta.dirname, 'wrangler.jsonc'),
  local: true,
  ip: '127.0.0.1',
  port: Number(process.env.FUDOKI_API_PORT ?? 8787),
  vars: {
    QUERY_FINGERPRINT: await queryFingerprint(),
    CURSOR_SECRET: randomBytes(32).toString('hex'),
    DOWNLOAD_BASE_URL: 'http://127.0.0.1:8788',
  },
  logLevel: 'error',
  experimental: { showInteractiveDevSession: false },
})
console.log(
  JSON.stringify({
    url: `http://127.0.0.1:${worker.port}`,
    mode: 'local',
    cursorKey: 'ephemeral',
  })
)
for (const signal of ['SIGINT', 'SIGTERM'] as const)
  process.on(signal, async () => {
    await worker.stop()
    process.exit(0)
  })
await worker.waitUntilExit()
