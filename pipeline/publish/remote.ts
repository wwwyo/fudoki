import { fileURLToPath } from 'node:url'
import type { Verifier } from './publish'
import type { Verification } from './verification'

export function remoteVerification() {
  let nextId = 0
  const pending = new Map<
    number,
    { resolve: (value: any) => void; reject: (error: Error) => void }
  >()
  const child = Bun.spawn(
    ['node', fileURLToPath(new URL('./rpc-bridge.mjs', import.meta.url))],
    {
      stdout: 'pipe',
      stderr: 'inherit',
      serialization: 'json',
      ipc(message: any) {
        const wait = pending.get(message.id)
        if (!wait) return
        pending.delete(message.id)
        if (message.error) wait.reject(new Error(message.error))
        else wait.resolve(message.result)
      },
      onExit() {
        for (const wait of pending.values())
          wait.reject(new Error('Verification RPC connection closed'))
        pending.clear()
      },
    }
  )
  const output = (async () => {
    for await (const chunk of child.stdout) process.stderr.write(chunk)
  })()
  function call(method: string, ...args: unknown[]) {
    return new Promise<any>((resolve, reject) => {
      const id = ++nextId
      pending.set(id, { resolve, reject })
      child.send({ id, method, args })
    })
  }
  const verifier: Verifier & Pick<Verification, 'candidate'> = {
    candidate: (id) => call('candidate', id),
    existingManifest: (id, hash) => call('existingManifest', id, hash),
    existingFile: (id, path) => call('existingFile', id, path),
    file: (id, path) => call('file', id, path),
    chunk: (id, table, after) => call('chunk', id, table, after),
    api: (id, dataset, phase) => call('api', id, dataset, phase),
    publicContracts: (id) => call('publicContracts', id),
    downloads: (id) => call('downloads', id),
    download: (id, path) => call('download', id, path),
    measure: (id) => call('measure', id),
    report: (id, sha256, bytes) => call('report', id, sha256, bytes),
  }
  return {
    verifier,
    async dispose() {
      try {
        await call('dispose')
      } finally {
        child.kill()
        await child.exited
        await output
      }
    },
  }
}
