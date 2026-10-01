import { afterEach, expect, test } from 'bun:test'
import { mkdtemp, mkdir, rm, writeFile, readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { TABLES, manifestSchema } from '@fudoki/data-contracts'
import { finalizeCandidate, verifyCandidate, pinManifest } from './manifest'
import { sha256 } from '../release'

const directories: string[] = []
afterEach(async () => {
  for (const path of directories.splice(0))
    await rm(path, { recursive: true, force: true })
})
async function candidate(releaseId: string, changed = false) {
  const directory = await mkdtemp(join(tmpdir(), 'fudoki-package-test-'))
  directories.push(directory)
  await mkdir(join(directory, 'api'))
  const datasets = [
    ['000001', 2024, 'budget', 'a'],
    ['000001', 2025, 'budget', 'b'],
    ['000001', 2025, 'supplementary', 'c'],
    ['000001', 2025, 'supplementary', 'd'],
    ['000002', 2025, 'budget', 'e'],
  ].map(([code, year, kind, edition]) => ({
    dataset_id: `${code}:${year}:expenditure:${kind}:${String(edition).repeat(64)}`,
    jurisdiction_code: code,
    fiscal_year: year,
    direction: 'expenditure',
    document_kind: kind,
    origin_sha256: String(edition).repeat(64),
    phases_json: '["approved"]',
    source_json: '{}',
    structure_json: '{}',
    line_count: 1,
  }))
  const validation: {
    tables: Record<string, { rows: number; sha256: string }>
    scopeTotals: unknown[]
  } = { tables: {}, scopeTotals: [] }
  for (const table of TABLES) {
    const rows = table === 'fiscal_datasets' ? datasets : []
    const body = rows.map((row) => JSON.stringify(row) + '\n').join('')
    await writeFile(join(directory, 'api', table + '.jsonl'), body)
    validation.tables[table] = { rows: rows.length, sha256: sha256(body) }
  }
  for (const code of ['000001', '000002']) {
    await mkdir(join(directory, 'fiscal', code), { recursive: true })
    await writeFile(
      join(directory, 'fiscal', code, 'expenditure.csv'),
      'dataset_id,value\n' +
        datasets
          .filter((d) => d.jurisdiction_code === code)
          .map(
            (d) =>
              `${d.dataset_id},${changed && code === '000001' ? 200 : 100}\n`
          )
          .join('')
    )
    await writeFile(
      join(directory, 'fiscal', code, 'datapackage.json'),
      JSON.stringify({
        resources: [{ name: 'expenditure', path: 'expenditure.csv' }],
      })
    )
  }
  const manifest = await finalizeCandidate(
    directory,
    {
      releaseId,
      codeRevision: 'a'.repeat(40),
      codeFingerprint: 'b'.repeat(64),
      inputFingerprint: 'c'.repeat(64),
      judgmentFingerprint: 'd'.repeat(64),
      queryFingerprint: 'e'.repeat(64),
    },
    validation
  )
  await verifyCandidate(directory)
  return { directory, manifest }
}
test('new global releases share every unchanged jurisdiction package and keep years and supplementary editions distinct', async () => {
  const first = await candidate('r-' + '1'.repeat(32))
  const next = await candidate('r-' + '2'.repeat(32))
  expect(next.manifest.packages).toEqual(first.manifest.packages)
  expect(
    next.manifest.files.filter((f) => f.path.startsWith('fiscal/'))
  ).toEqual(first.manifest.files.filter((f) => f.path.startsWith('fiscal/')))
  expect(
    next.manifest.packages.find((p) => p.jurisdictionCode === '000001')
      ?.datasetIds
  ).toHaveLength(4)
})
test('a change in one jurisdiction preserves the other package and relative FDP resource paths', async () => {
  const first = await candidate('r-' + '1'.repeat(32))
  const next = await candidate('r-' + '2'.repeat(32), true)
  expect(next.manifest.packages[0]?.packageId).not.toBe(
    first.manifest.packages[0]?.packageId
  )
  expect(next.manifest.packages[1]).toEqual(first.manifest.packages[1])
  const csv = next.manifest.files.find(
    (f) => f.path === 'fiscal/000001/expenditure.csv'
  )!
  const descriptor = next.manifest.files.find(
    (f) => f.path === 'fiscal/000001/datapackage.json'
  )!
  const resource = JSON.parse(
    await readFile(join(next.directory, descriptor.path), 'utf8')
  ).resources[0].path
  expect(
    new URL(resource, `https://download.example.org/${descriptor.objectKey}`)
      .pathname
  ).toBe('/' + csv.objectKey)
})
test('a file cannot point at another jurisdiction or package version', async () => {
  const { manifest } = await candidate('r-' + '1'.repeat(32))
  for (const key of [
    manifest.files[2]!.objectKey,
    'fiscal/000001/p-' + 'f'.repeat(64) + '/datapackage.json',
  ]) {
    const altered = structuredClone(manifest)
    altered.files[0]!.objectKey = key
    expect(manifestSchema.safeParse(altered).success).toBe(false)
  }
})

test('the Git manifest contains scope and references without catalog or internal verification data', async () => {
  const { directory, manifest } = await candidate('r-' + '1'.repeat(32))
  const target = join(directory, 'git-manifest.json')
  await pinManifest(directory, target)
  const publicManifest = JSON.parse(await readFile(target, 'utf8'))
  expect(publicManifest.datasets).toHaveLength(5)
  expect(publicManifest.packages).toEqual(manifest.packages)
  expect(
    publicManifest.files.every((file: any) => file.path.startsWith('fiscal/'))
  ).toBe(true)
  expect(publicManifest.tables).toBeUndefined()
  expect(publicManifest.queryFingerprint).toBeUndefined()
  expect(Bun.file(join(directory, 'catalog.json')).size).toBe(0)
  await writeFile(
    join(directory, 'manifest.json'),
    JSON.stringify({ ...publicManifest, selection: 'changed' })
  )
  await expect(pinManifest(directory, target)).rejects.toThrow(
    'manifest differs'
  )
  expect(JSON.parse(await readFile(target, 'utf8'))).toEqual(publicManifest)
})
