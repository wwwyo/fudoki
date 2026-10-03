import { expect, test } from 'bun:test'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { artifactHashes, verifyArtifacts } from './artifacts'

test('build verification detects modified, missing and added CSV files', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'fudoki-artifacts-'))
  try {
    await mkdir(join(directory, 'fiscal/132195'), { recursive: true })
    const file = join(directory, 'fiscal/132195/settlement.csv')
    await writeFile(file, 'id,amount\n1,10\n')
    const hashes = await artifactHashes(directory)
    await verifyArtifacts(directory, hashes)
    await writeFile(file, 'id,amount\n1,20\n')
    await expect(verifyArtifacts(directory, hashes)).rejects.toThrow('differ')
    await rm(file)
    await expect(verifyArtifacts(directory, hashes)).rejects.toThrow('differ')
    await writeFile(file, 'id,amount\n1,10\n')
    await writeFile(join(directory, 'extra.csv'), 'id\n2\n')
    await expect(verifyArtifacts(directory, hashes)).rejects.toThrow('differ')
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})
