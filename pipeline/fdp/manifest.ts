import { readFile, writeFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { createReadStream } from 'node:fs'
import { createInterface } from 'node:readline'
import { createHash } from 'node:crypto'
import {
  manifestSchema,
  TABLES,
  canonicalRow,
  type ReleaseManifest,
} from '@fudoki/data-contracts'
import { sha256, type releaseIdentity } from '../release'

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
    await jsonLines(join(directory, 'api/jurisdictions.jsonl'))
  ).map((row) => ({
    ...row,
    caveats: JSON.parse(row.caveats_json as string),
    caveats_json: undefined,
  }))
  const datasets = (
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
  const catalog = {
    schemaVersion: 1,
    releaseId: identity.releaseId,
    jurisdictions,
    datasets,
    amountUnit: 'JPY',
    documents: ['budget', 'supplementary', 'settlement'],
    phases: ['approved', 'adjusted', 'adjusted-before-transfer', 'executed'],
    selection:
      'Choose one document and edition per jurisdiction, year and direction. Comparisons keep jurisdictions and years separate.',
  }
  await writeFile(
    join(directory, 'catalog.json'),
    JSON.stringify(catalog, null, 2) + '\n'
  )
  const files: ReleaseManifest['files'] = []
  for (const code of (await readdir(join(directory, 'fiscal'))).sort()) {
    if (!/^\d{6}$/.test(code))
      throw new Error('Unexpected distribution directory')
    for (const file of (
      await readdir(join(directory, 'fiscal', code))
    ).sort()) {
      const path = `fiscal/${code}/${file}`
      const body = await readFile(join(directory, path))
      files.push({
        path,
        sha256: sha256(body),
        bytes: body.length,
        contentType: file.endsWith('.csv')
          ? 'text/csv; charset=utf-8'
          : 'application/json; charset=utf-8',
      })
    }
  }
  const body = await readFile(join(directory, 'catalog.json'))
  files.push({
    path: 'catalog.json',
    sha256: sha256(body),
    bytes: body.length,
    contentType: 'application/json; charset=utf-8',
  })
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
    files,
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
  await writeFile(join(directory, 'manifest.json'), text)
  await writeFile(
    join(directory, 'validation.json'),
    JSON.stringify(validation, null, 2) + '\n'
  )
  await writeFile(
    join(directory, 'complete.json'),
    JSON.stringify({ ...identity, manifestSha256: sha256(text) }, null, 2) +
      '\n'
  )
  return manifest
}
export async function verifyCandidate(
  directory: string
): Promise<ReleaseManifest> {
  const raw = await readFile(join(directory, 'manifest.json'))
  const manifest = manifestSchema.parse(JSON.parse(raw.toString()))
  const complete = JSON.parse(
    await readFile(join(directory, 'complete.json'), 'utf8')
  )
  if (
    complete.manifestSha256 !== sha256(raw) ||
    complete.releaseId !== manifest.releaseId
  )
    throw new Error('Candidate completion marker differs from manifest')
  for (const file of manifest.files) {
    const body = await readFile(join(directory, file.path))
    if (sha256(body) !== file.sha256 || body.length !== file.bytes)
      throw new Error(`Candidate file differs from manifest: ${file.path}`)
  }
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
