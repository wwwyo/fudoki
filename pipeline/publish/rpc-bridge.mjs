import { getPlatformProxy } from 'wrangler'
import { fileURLToPath } from 'node:url'

// Wrangler's proxy runs under Node; the pipeline caller retains Bun's runtime.
let platform
const allowed = new Set([
  'candidate',
  'existingManifest',
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
  platform = await getPlatformProxy({
    configPath: fileURLToPath(
      new URL('./client-wrangler.jsonc', import.meta.url)
    ),
    remoteBindings: true,
    persist: false,
    envFiles: [],
  })
})()
process.on('message', async (message) => {
  const { id, method, args } = message
  try {
    await ready
    if (method === 'dispose') {
      await platform.dispose()
      process.send({ id, result: null })
      process.disconnect()
      return
    }
    if (!allowed.has(method) || !Array.isArray(args))
      throw new Error('Invalid verification RPC')
    process.send({
      id,
      result: await platform.env.VERIFICATION[method](...args),
    })
  } catch (error) {
    process.send({
      id,
      error: error instanceof Error ? error.message : 'Verification RPC failed',
    })
  }
})
process.on('disconnect', async () => {
  await platform?.dispose()
})
ready.catch(() => {})
