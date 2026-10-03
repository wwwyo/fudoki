import { createHash } from 'node:crypto'
import { readFile, readdir } from 'node:fs/promises'
import { join, relative } from 'node:path'

export async function artifactHashes(directory: string) {
  const hashes: Record<string, string> = {}
  async function visit(path: string) {
    for (const entry of (await readdir(path, { withFileTypes: true })).sort(
      (a, b) => a.name.localeCompare(b.name)
    )) {
      const file = join(path, entry.name)
      if (entry.isDirectory()) await visit(file)
      else if (entry.isFile() && entry.name.endsWith('.csv'))
        hashes[relative(directory, file)] = createHash('sha256')
          .update(await readFile(file))
          .digest('hex')
    }
  }
  await visit(directory)
  return hashes
}

export async function verifyArtifacts(
  directory: string,
  expected: Record<string, string>
) {
  const actual = await artifactHashes(directory)
  if (JSON.stringify(actual) !== JSON.stringify(expected))
    throw new Error('Built CSV files differ from their verification record')
}
