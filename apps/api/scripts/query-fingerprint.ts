import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

export async function queryFingerprint(): Promise<string> {
  const repo = resolve(import.meta.dirname, '../../..')
  const hash = createHash('sha256')
  for (const path of [
    'apps/api/src/contract/index.ts',
    'apps/api/src/data/queries.ts',
    'apps/api/src/lib/cursor.ts',
    'packages/data-contracts/index.ts',
    'packages/data-contracts/schema.sql',
  ]) {
    hash
      .update(path + '\0')
      .update(await readFile(resolve(repo, path)))
      .update('\0')
  }
  return hash.digest('hex')
}
