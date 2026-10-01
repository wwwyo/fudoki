import { expect, test } from 'bun:test'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { distributionManifestSchema } from '@fudoki/data-contracts'
import { fixture } from '../verify/fixture'
import { verifyCandidate } from './manifest'

test('code-only rebuilds retain municipality and package identities, while amounts or metadata change the appropriate identity', async () => {
  const root = await mkdtemp(join(tmpdir(), 'fudoki-identity-'))
  try {
    const a = await fixture(join(root, 'a'), 'r-' + '1'.repeat(32), 100, 3)
    const b = await fixture(join(root, 'b'), 'r-' + '2'.repeat(32), 100, 3)
    const c = await fixture(join(root, 'c'), 'r-' + '3'.repeat(32), 101, 3)
    const d = await fixture(
      join(root, 'd'),
      'r-' + '4'.repeat(32),
      100,
      3,
      '名称変更'
    )
    expect(a.versions).toEqual(b.versions)
    expect(a.versions[0]!.versionId).not.toBe(c.versions[0]!.versionId)
    expect(a.versions[0]!.packageId).not.toBe(c.versions[0]!.packageId)
    expect(a.versions[0]!.versionId).not.toBe(d.versions[0]!.versionId)
    expect(a.versions[0]!.packageId).toBe(d.versions[0]!.packageId)
    const publicManifest = JSON.parse(
      await readFile(join(root, 'a/manifest.json'), 'utf8')
    )
    expect(publicManifest.buildId).toBeUndefined()
    expect(publicManifest.publicationId).toBeUndefined()
    expect(publicManifest.codeRevision).toBeUndefined()
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
test('manifest ownership rejects another municipality prefix', async () => {
  const root = await mkdtemp(join(tmpdir(), 'fudoki-ownership-'))
  try {
    await fixture(root, 'r-' + '1'.repeat(32), 100, 3)
    const manifest = JSON.parse(
      await readFile(join(root, 'manifest.json'), 'utf8')
    )
    manifest.files[0].objectKey = manifest.files[0].objectKey.replace(
      '/000001/',
      '/000002/'
    )
    expect(() => distributionManifestSchema.parse(manifest)).toThrow(
      'another jurisdiction'
    )
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
test('changed immutable bytes fail candidate verification', async () => {
  const root = await mkdtemp(join(tmpdir(), 'fudoki-tamper-'))
  try {
    await fixture(root, 'r-' + '1'.repeat(32), 100, 3)
    await writeFile(
      join(root, 'fiscal/000001/settlement_expenditure.csv'),
      'changed'
    )
    await expect(verifyCandidate(root)).rejects.toThrow(
      'Candidate file differs'
    )
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
