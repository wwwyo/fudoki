import { getPlatformProxy } from 'wrangler'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import clientConfig from './client/cloudflare.config.ts'

// Wrangler's proxy runs under Node; the pipeline caller retains Bun's runtime.
let platform
let directory
let session
const allowed = new Set([
  'candidate',
  'existingFile',
  'file',
  'chunk',
  'api',
  'publicContracts',
  'downloads',
  'download',
  'measure',
])
const ready = (async () => {
  // The proxy library still reads JSON; derive its transient input from cf's declaration.
  const worker = clientConfig.worker
  const binding = worker.env.VERIFICATION
  directory = await mkdtemp(join(tmpdir(), 'fudoki-verification-proxy-'))
  const configPath = join(directory, 'proxy.json')
  await writeFile(
    configPath,
    JSON.stringify({
      name: worker.name,
      compatibility_date: worker.compatibilityDate,
      workers_dev: worker.workersDev,
      preview_urls: worker.previewUrls,
      services: [
        {
          binding: 'VERIFICATION',
          service: binding.worker,
          entrypoint: binding.exportName,
          remote: binding.dev.remote,
        },
      ],
    }),
    { mode: 0o600 }
  )
  platform = await getPlatformProxy({
    configPath,
    remoteBindings: true,
    persist: false,
    envFiles: [],
  })
})()
process.on('message', async (message) => {
  const { id, method, args } = message
  try {
    await ready
    if (method === 'session') {
      if (session || !Array.isArray(args) || args.length !== 1)
        throw new Error('Invalid session initialization')
      session = await platform.env.VERIFICATION.session(args[0])
      process.send({ id, result: null })
      return
    }
    if (method === 'dispose') {
      session?.[Symbol.dispose]()
      await platform.dispose()
      await rm(directory, { recursive: true, force: true })
      process.send({ id, result: null })
      process.disconnect()
      return
    }
    if (!allowed.has(method) || !Array.isArray(args))
      throw new Error('Invalid verification RPC')
    process.send({
      id,
      result: await session[method](...args),
    })
  } catch (error) {
    process.send({
      id,
      error: error instanceof Error ? error.message : 'Verification RPC failed',
    })
  }
})
process.on('disconnect', async () => {
  session?.[Symbol.dispose]()
  await platform?.dispose()
  if (directory) await rm(directory, { recursive: true, force: true })
})
ready.catch(() => {})
