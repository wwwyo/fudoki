import { readFile, writeFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import {
  CONTRACT_VERSION,
  TABLES,
  TABLE_COLUMNS,
  TABLE_KEYS,
  canonicalRow,
  canonicalJson,
  candidateManifestSchema,
  distributionManifestSchema,
  derivePackageId,
  contentId,
  type CandidateManifest,
  type DistributionManifest,
} from '@fudoki/data-contracts'
import { sha256, type releaseIdentity } from '../release'
import { PUBLICATION_MANIFEST } from '../paths'

type Row = Record<string, unknown>
export async function jsonLines(path: string): Promise<Row[]> {
  return (await readFile(path, 'utf8'))
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line))
}
function digestRows(table: keyof typeof TABLE_COLUMNS, rows: Row[]) {
  const canonical = createHash('sha256'),
    chunks: string[] = []
  let chunk = createHash('sha256')
  rows.forEach((row, index) => {
    const body = canonicalRow(table, row)
    canonical.update(body)
    chunk.update(body)
    if ((index + 1) % 500 === 0) {
      chunks.push(chunk.digest('hex'))
      chunk = createHash('sha256')
    }
  })
  if (rows.length % 500) chunks.push(chunk.digest('hex'))
  const hash = canonical.digest('hex')
  return { rows: rows.length, sha256: hash, canonicalSha256: hash, chunks }
}
export async function tableDigest(
  path: string,
  table: (typeof TABLES)[number]
) {
  const bytes = await readFile(path)
  const rows = bytes
    .toString()
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line))
  const expectedColumns = [...TABLE_COLUMNS[table]].sort().join(',')
  for (const row of rows)
    if (Object.keys(row).sort().join(',') !== expectedColumns)
      throw new Error(`Storage columns differ: ${table}`)
  return { ...digestRows(table, rows), sha256: sha256(bytes) }
}
export async function candidateRows(directory: string) {
  const entries = await Promise.all(
    TABLES.map(
      async (table) =>
        [
          table,
          await jsonLines(join(directory, 'api', table + '.jsonl')),
        ] as const
    )
  )
  return Object.fromEntries(entries) as Record<(typeof TABLES)[number], Row[]>
}
export function partitionAllRows(
  data: Awaited<ReturnType<typeof candidateRows>>
) {
  const datasets = new Map(
    data.fiscal_datasets.map((row) => [row.dataset_id, row.jurisdiction_code])
  )
  const lines = new Map<unknown, unknown>(),
    items = new Map<unknown, unknown>()
  for (const direction of ['expenditure', 'revenue'] as const) {
    for (const row of data[`fiscal_settlement_${direction}_lines`])
      lines.set(row.fiscal_line_id, datasets.get(row.dataset_id))
    for (const row of data[`fiscal_initial_${direction}_budget_lines`])
      lines.set(row.fiscal_line_id, datasets.get(row.dataset_id))
    for (const row of data[`fiscal_${direction}_budget_items`])
      items.set(row.budget_item_id, row.jurisdiction_code)
  }
  const partitions = new Map<string, typeof data>()
  for (const table of TABLES)
    for (const row of data[table]) {
      const owner =
        row.jurisdiction_code ??
        datasets.get(row.dataset_id) ??
        lines.get(row.fiscal_line_id) ??
        items.get(row.budget_item_id)
      if (!owner)
        throw new Error(`Cannot identify owning jurisdiction: ${table}`)
      const code = String(owner)
      if (!partitions.has(code))
        partitions.set(
          code,
          Object.fromEntries(TABLES.map((t) => [t, [] as Row[]])) as typeof data
        )
      partitions.get(code)![table].push(row)
    }
  return partitions
}
export function partitionRows(
  data: Awaited<ReturnType<typeof candidateRows>>,
  code: string,
  partitions = partitionAllRows(data)
) {
  return (
    partitions.get(code) ??
    (Object.fromEntries(TABLES.map((t) => [t, [] as Row[]])) as typeof data)
  )
}
function versionIdentity(
  facts: Omit<CandidateManifest['versions'][number], 'tables' | 'versionId'>,
  tables: CandidateManifest['tables']
) {
  return contentId('v', {
    contractVersion: CONTRACT_VERSION,
    ...facts,
    tables: Object.fromEntries(
      TABLES.map((t) => [
        t,
        { rows: tables[t].rows, sha256: tables[t].canonicalSha256 },
      ])
    ),
  })
}

function versionTables(data: Awaited<ReturnType<typeof candidateRows>>) {
  return Object.fromEntries(
    TABLES.map((table) => [table, digestRows(table, data[table])])
  ) as CandidateManifest['tables']
}
export async function prepareCandidate(
  directory: string,
  identity: Awaited<ReturnType<typeof releaseIdentity>>
): Promise<CandidateManifest> {
  const data = await candidateRows(directory)
  const partitions = partitionAllRows(data)
  const metadata = await jsonLines(
    join(directory, 'api/jurisdiction_metadata.jsonl')
  )
  const packages: DistributionManifest['packages'] = [],
    files: DistributionManifest['files'] = []
  for (const code of (await readdir(join(directory, 'fiscal'))).sort()) {
    if (!/^\d{6}$/.test(code)) throw new Error('Invalid distribution directory')
    const contents = []
    for (const name of (
      await readdir(join(directory, 'fiscal', code))
    ).sort()) {
      const path = `fiscal/${code}/${name}`,
        body = await readFile(join(directory, path))
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
      datasetIds: data.fiscal_datasets
        .filter((d) => d.jurisdiction_code === code)
        .map((d) => String(d.dataset_id))
        .sort(),
    })
    files.push(
      ...contents.map((f) => ({
        ...f,
        objectKey: `fiscal/${code}/${packageId}/${f.path.split('/')[2]}`,
      }))
    )
  }
  const versions: CandidateManifest['versions'] = []
  for (const row of metadata) {
    const jurisdictionCode = String(row.jurisdiction_code),
      tables = versionTables(partitionRows(data, jurisdictionCode, partitions))
    const packageId =
      packages.find((p) => p.jurisdictionCode === jurisdictionCode)
        ?.packageId ?? null
    const facts = {
      jurisdictionCode,
      packageId,
      name: String(row.name_snapshot),
      ocdId: String(row.ocd_id_snapshot),
      caveats: JSON.parse(String(row.caveats_json)),
    }
    const versionId = await versionIdentity(facts, tables)
    versions.push({ ...facts, versionId, tables })
  }
  const distribution = distributionManifestSchema.parse({
    schemaVersion: CONTRACT_VERSION,
    jurisdictions: versions.map(({ tables, ...version }) => version),
    datasets: data.fiscal_datasets,
    packages,
    files,
    amountUnit: 'JPY',
    selection:
      'Select one dataset per jurisdiction, year and direction. Imported rows are visible while ingestion is in progress.',
  })
  const distributionText = JSON.stringify(distribution, null, 2) + '\n'
  await writeFile(join(directory, 'manifest.json'), distributionText)
  const tables = {} as CandidateManifest['tables']
  for (const table of TABLES)
    tables[table] = await tableDigest(
      join(directory, 'api', table + '.jsonl'),
      table
    )
  const totals: CandidateManifest['totals'] = []
  for (const table of TABLES.filter(
    (t) => t.endsWith('_lines') || t.endsWith('_budget_changes')
  )) {
    const groups = new Map<string, { rows: number; amount: number }>()
    for (const row of data[table]) {
      const key = String(row.dataset_id),
        total = groups.get(key) ?? { rows: 0, amount: 0 }
      total.rows++
      total.amount += Number(row.amount ?? row.amount_delta)
      groups.set(key, total)
    }
    for (const [datasetId, total] of groups) {
      const dataset = data.fiscal_datasets.find(
        (d) => d.dataset_id === datasetId
      )
      if (!dataset) throw new Error('Total has no dataset')
      totals.push({
        datasetId,
        jurisdictionCode: String(dataset.jurisdiction_code),
        resource: table,
        ...total,
      })
    }
  }
  totals.sort((a, b) =>
    a.datasetId < b.datasetId
      ? -1
      : a.datasetId > b.datasetId
        ? 1
        : a.resource.localeCompare(b.resource)
  )
  const manifest = candidateManifestSchema.parse({
    schemaVersion: CONTRACT_VERSION,
    buildId: identity.releaseId,
    codeRevision: identity.codeRevision,
    inputFingerprint: identity.inputFingerprint,
    judgmentFingerprint: identity.judgmentFingerprint,
    queryFingerprint: identity.queryFingerprint,
    manifestSha256: sha256(distributionText),
    jurisdictionMasterSha256: sha256(
      await readFile(join(directory, 'api/jurisdiction_master.jsonl'))
    ),
    cofogMasterSha256: sha256(
      await readFile(join(directory, 'api/cofog_master.jsonl'))
    ),
    expenditureSetsuMasterSha256: sha256(
      await readFile(
        join(directory, 'api/fiscal_expenditure_setsu_master.jsonl')
      )
    ),
    tables,
    versions,
    totals,
  })
  await writeFile(
    join(directory, 'verification.json'),
    JSON.stringify(manifest, null, 2) + '\n'
  )
  return manifest
}
export async function finalizeCandidate(
  directory: string,
  identity: Awaited<ReturnType<typeof releaseIdentity>>,
  validation: Record<string, any>
): Promise<CandidateManifest> {
  const manifest = await prepareCandidate(directory, identity)
  for (const table of TABLES)
    if (
      manifest.tables[table].rows !== validation.tables[table]?.rows ||
      manifest.tables[table].sha256 !== validation.tables[table]?.sha256
    )
      throw new Error(`Validation differs: ${table}`)
  await writeFile(
    join(directory, 'validation.json'),
    JSON.stringify(validation, null, 2) + '\n'
  )
  await writeFile(
    join(directory, 'complete.json'),
    JSON.stringify(
      {
        ...identity,
        buildId: identity.releaseId,
        verificationSha256: sha256(
          await readFile(join(directory, 'verification.json'))
        ),
      },
      null,
      2
    ) + '\n'
  )
  return manifest
}
export async function verifyCandidate(
  directory: string
): Promise<CandidateManifest> {
  const bytes = await readFile(join(directory, 'verification.json')),
    manifest = candidateManifestSchema.parse(JSON.parse(bytes.toString()))
  const complete = JSON.parse(
    await readFile(join(directory, 'complete.json'), 'utf8')
  )
  if (
    complete.verificationSha256 !== sha256(bytes) ||
    complete.buildId !== manifest.buildId
  )
    throw new Error('Candidate completion record differs')
  const distributionBytes = await readFile(join(directory, 'manifest.json')),
    distribution = distributionManifestSchema.parse(
      JSON.parse(distributionBytes.toString())
    )
  if (
    sha256(distributionBytes) !== manifest.manifestSha256 ||
    canonicalJson(distribution.jurisdictions) !==
      canonicalJson(manifest.versions.map(({ tables, ...version }) => version))
  )
    throw new Error('Distribution manifest differs')
  for (const file of distribution.files) {
    const body = await readFile(join(directory, file.path))
    if (body.length !== file.bytes || sha256(body) !== file.sha256)
      throw new Error(`Candidate file differs: ${file.path}`)
  }
  for (const pkg of distribution.packages)
    if (
      (await derivePackageId(
        distribution.files.filter((f) =>
          f.path.startsWith(`fiscal/${pkg.jurisdictionCode}/`)
        )
      )) !== pkg.packageId
    )
      throw new Error('Package contents differ')
  for (const table of TABLES)
    if (
      canonicalJson(
        await tableDigest(join(directory, 'api', table + '.jsonl'), table)
      ) !== canonicalJson(manifest.tables[table])
    )
      throw new Error(`Candidate table differs: ${table}`)
  const data = await candidateRows(directory)
  const partitions = partitionAllRows(data)
  for (const version of manifest.versions) {
    const tables = versionTables(
      partitionRows(data, version.jurisdictionCode, partitions)
    )
    if (canonicalJson(tables) !== canonicalJson(version.tables))
      throw new Error('Jurisdiction table contents differ')
    const { tables: _, versionId, ...facts } = version
    if ((await versionIdentity(facts, tables)) !== versionId)
      throw new Error('Jurisdiction version identity differs')
  }
  for (const [file, key] of [
    ['jurisdiction_master', 'jurisdictionMasterSha256'],
    ['cofog_master', 'cofogMasterSha256'],
    ['fiscal_expenditure_setsu_master', 'expenditureSetsuMasterSha256'],
  ] as const)
    if (
      sha256(await readFile(join(directory, 'api', file + '.jsonl'))) !==
      manifest[key]
    )
      throw new Error('Master contents differ')
  return manifest
}
export async function pinManifest(
  directory: string,
  target = PUBLICATION_MANIFEST
) {
  await verifyCandidate(directory)
  await writeFile(target, await readFile(join(directory, 'manifest.json')))
}
