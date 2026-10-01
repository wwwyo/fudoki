import { fileURLToPath } from 'node:url'
import type { Verifier } from './publish'
import type { ReleaseManifest } from '@fudoki/data-contracts'
import type { Verification } from './verification'

export function remoteVerification(manifest: ReleaseManifest) {
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
  const ready = call('session', manifest)
  async function invoke(method: string, ...args: unknown[]) {
    await ready
    return call(method, ...args)
  }
  const verifier: Verifier & Pick<Verification, 'candidate'> = {
    candidate: (id) => invoke('candidate', id),
    existingFile: (id, path) => invoke('existingFile', id, path),
    file: (id, path) => invoke('file', id, path),
    chunk: (id, table, after) => invoke('chunk', id, table, after),
    api: (id, dataset, phase) => invoke('api', id, dataset, phase),
    publicContracts: (id) => invoke('publicContracts', id),
    downloads: (id) => invoke('downloads', id),
    download: (id, path) => invoke('download', id, path),
    measure: (id) => invoke('measure', id),
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
