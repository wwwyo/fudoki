import { readFile, writeFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { createReadStream } from 'node:fs'
import { createInterface } from 'node:readline'
import { createHash } from 'node:crypto'
import {
  manifestSchema,
  distributionManifestSchema,
  TABLES,
  canonicalRow,
  derivePackageId,
  type ReleaseManifest,
} from '@fudoki/data-contracts'
import { sha256, type releaseIdentity } from '../release'
import { PUBLICATION_MANIFEST } from '../paths'

async function jsonLines(path: string): Promise<Record<string, unknown>[]> {
  return (await readFile(path, 'utf8'))
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line))
}
export async function tableDigest(path: string, name: (typeof TABLES)[number]) {
  const raw = createHash('sha256'),
    canonical = createHash('sha256'),
    chunks: string[] = []
  let count = 0,
    chunk = createHash('sha256')
  const stream = createReadStream(path)
  stream.on('data', (body) => raw.update(body))
  for await (const line of createInterface({
    input: stream,
    crlfDelay: Infinity,
  })) {
    if (!line) continue
    const value = canonicalRow(name, JSON.parse(line))
    canonical.update(value)
    chunk.update(value)
    count++
    if (count % 500 === 0) {
      chunks.push(chunk.digest('hex'))
      chunk = createHash('sha256')
    }
  }
  if (count % 500) chunks.push(chunk.digest('hex'))
  return {
    rows: count,
    sha256: raw.digest('hex'),
    canonicalSha256: canonical.digest('hex'),
    chunks,
  }
}
export async function finalizeCandidate(
  directory: string,
  identity: Awaited<ReturnType<typeof releaseIdentity>>,
  validation: Record<string, any>
): Promise<ReleaseManifest> {
  const jurisdictions = (
    await jsonLines(join(directory, 'api/release_jurisdictions.jsonl'))
  ).map((row) => ({
    jurisdiction_code: row.jurisdiction_code,
    name: row.name_snapshot,
    ocd_id: row.ocd_id_snapshot,
    caveats: JSON.parse(row.caveats_json as string),
    caveats_json: undefined,
  }))
  const datasets: Record<string, unknown>[] = (
    await jsonLines(join(directory, 'api/fiscal_datasets.jsonl'))
  ).map((row) => ({
    ...row,
    phases: JSON.parse(row.phases_json as string),
    source: JSON.parse(row.source_json as string),
    structure: JSON.parse(row.structure_json as string),
    phases_json: undefined,
    source_json: undefined,
    structure_json: undefined,
  }))
  const packages: ReleaseManifest['packages'] = []
  const files: ReleaseManifest['files'] = []
  for (const code of (await readdir(join(directory, 'fiscal'))).sort()) {
    if (!/^\d{6}$/.test(code))
      throw new Error('Unexpected distribution directory')
    const contents = []
    for (const name of (
      await readdir(join(directory, 'fiscal', code))
    ).sort()) {
      const path = `fiscal/${code}/${name}`
      const body = await readFile(join(directory, path))
      contents.push({
        path,
        sha256: sha256(body),
        bytes: body.length,
        contentType: name.endsWith('.csv')
          ? ('text/csv; charset=utf-8' as const)
          : ('application/json; charset=utf-8' as const),
      })
    }
    const packageId = await derivePackageId(contents)
    packages.push({
      jurisdictionCode: code,
      packageId,
      datasetIds: datasets
        .filter((dataset) => dataset.jurisdiction_code === code)
        .map((dataset) => String(dataset.dataset_id))
        .sort(),
    })
    files.push(
      ...contents.map((file) => ({
        ...file,
        objectKey: `fiscal/${code}/${packageId}/${file.path.split('/')[2]}`,
      }))
    )
  }
  const distribution = distributionManifestSchema.parse({
    schemaVersion: 1,
    buildId: identity.releaseId,
    codeRevision: identity.codeRevision,
    inputFingerprint: identity.inputFingerprint,
    judgmentFingerprint: identity.judgmentFingerprint,
    jurisdictions,
    datasets,
    packages,
    files,
    amountUnit: 'JPY',
    documents: ['budget', 'supplementary', 'settlement'],
    phases: ['approved', 'adjusted', 'adjusted-before-transfer', 'executed'],
    selection:
      'Choose one document and edition per jurisdiction, year and direction. Comparisons keep jurisdictions and years separate.',
  })
  const distributionText = JSON.stringify(distribution, null, 2) + '\n'
  await writeFile(join(directory, 'manifest.json'), distributionText)
  const tables = {} as ReleaseManifest['tables']
  for (const name of TABLES) {
    const digest = await tableDigest(
      join(directory, 'api', `${name}.jsonl`),
      name
    )
    if (
      digest.rows !== validation.tables[name].rows ||
      digest.sha256 !== validation.tables[name].sha256
    )
      throw new Error(`Table changed after validation: ${name}`)
    tables[name] = digest
  }
  const manifest = manifestSchema.parse({
    schemaVersion: 1,
    ...identity,
    manifestSha256: sha256(distributionText),
    jurisdictionMasterSha256: sha256(
      await readFile(join(directory, 'api/jurisdictions.jsonl'))
    ),
    files,
    packages,
    tables,
    totals: validation.scopeTotals.map(
      ([datasetId, phase, rows, amount]: [string, string, number, number]) => ({
        datasetId,
        phase,
        rows,
        amount,
      })
    ),
  })
  const text = JSON.stringify(manifest, null, 2) + '\n'
  await writeFile(join(directory, 'verification.json'), text)
  await writeFile(
    join(directory, 'validation.json'),
    JSON.stringify(validation, null, 2) + '\n'
  )
  await writeFile(
    join(directory, 'complete.json'),
    JSON.stringify({ ...identity, verificationSha256: sha256(text) }, null, 2) +
      '\n'
  )
  return manifest
}
export async function verifyCandidate(
  directory: string
): Promise<ReleaseManifest> {
  const raw = await readFile(join(directory, 'verification.json'))
  const manifest = manifestSchema.parse(JSON.parse(raw.toString()))
  if (
    sha256(await readFile(join(directory, 'api/jurisdictions.jsonl'))) !==
    manifest.jurisdictionMasterSha256
  )
    throw new Error('Jurisdiction master differs from verification record')
  const complete = JSON.parse(
    await readFile(join(directory, 'complete.json'), 'utf8')
  )
  if (
    complete.verificationSha256 !== sha256(raw) ||
    complete.releaseId !== manifest.releaseId
  )
    throw new Error('Candidate completion marker differs from manifest')
  const distributionBytes = await readFile(join(directory, 'manifest.json'))
  const distribution = distributionManifestSchema.parse(
    JSON.parse(distributionBytes.toString())
  )
  if (
    sha256(distributionBytes) !== manifest.manifestSha256 ||
    distribution.buildId !== manifest.releaseId ||
    JSON.stringify(distribution.files) !== JSON.stringify(manifest.files) ||
    JSON.stringify(distribution.packages) !== JSON.stringify(manifest.packages)
  )
    throw new Error('Distribution manifest differs from verification record')
  for (const file of manifest.files) {
    const body = await readFile(join(directory, file.path))
    if (sha256(body) !== file.sha256 || body.length !== file.bytes)
      throw new Error(`Candidate file differs from manifest: ${file.path}`)
  }
  for (const pkg of manifest.packages)
    if (
      (await derivePackageId(
        manifest.files.filter((file) =>
          file.path.startsWith(`fiscal/${pkg.jurisdictionCode}/`)
        )
      )) !== pkg.packageId
    )
      throw new Error(
        `Package identity differs from contents: ${pkg.jurisdictionCode}`
      )
  for (const name of TABLES) {
    const digest = await tableDigest(
      join(directory, 'api', `${name}.jsonl`),
      name
    )
    if (JSON.stringify(digest) !== JSON.stringify(manifest.tables[name]))
      throw new Error(`Candidate table differs from manifest: ${name}`)
  }
  return manifest
}

export async function pinManifest(
  directory: string,
  target = PUBLICATION_MANIFEST
) {
  await verifyCandidate(directory)
  await writeFile(target, await readFile(join(directory, 'manifest.json')))
}
