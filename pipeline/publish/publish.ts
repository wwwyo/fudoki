import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import {
  CONTRACT_VERSION,
  TABLES,
  TABLE_COLUMNS,
  TABLE_KEYS,
  canonicalRow,
  canonicalJson,
  jurisdictionMasterSchema,
  cofogMasterSchema,
  distributionManifestSchema,
  type D1Database,
} from '@fudoki/data-contracts'
import {
  verifyCandidate,
  candidateRows,
  partitionAllRows,
  partitionRows,
  jsonLines,
} from '../fdp/manifest'
import { sha256 } from '../release'

export interface ObjectStore {
  read(key: string): Promise<Uint8Array | null>
  put(key: string, path: string, contentType: string): Promise<void>
}
export type Progress = (event: Record<string, unknown>) => void
const BATCH_SIZE = 500

/** Retry identical rows; a content address must never acquire different contents. */
async function appendRows(
  db: D1Database,
  table: keyof typeof TABLE_COLUMNS,
  rows: Record<string, unknown>[]
) {
  const columns = TABLE_COLUMNS[table]
  const keys = TABLE_KEYS[table]
  const joinKeys = keys
    .map((key) => `stored."${key}" IS json_extract(incoming.value,'$.${key}')`)
    .join(' AND ')
  for (let offset = 0; offset < rows.length; offset += BATCH_SIZE) {
    const batch = rows.slice(offset, offset + BATCH_SIZE)
    const existing = await db
      .prepare(
        `SELECT stored.* FROM "${table}" stored JOIN json_each(?) incoming ON ${joinKeys}`
      )
      .bind(JSON.stringify(batch))
      .all<Record<string, unknown>>()
    const byKey = new Map(
      batch.map((row) => [canonicalJson(keys.map((key) => row[key])), row])
    )
    for (const row of existing.results) {
      const incoming = byKey.get(canonicalJson(keys.map((key) => row[key])))!
      if (canonicalJson(row) !== canonicalJson(incoming))
        throw new Error(`Existing content differs: ${table}`)
    }
    await db
      .prepare(
        `INSERT INTO "${table}" (${columns.map((c) => `"${c}"`).join(',')}) SELECT ${columns.map((c) => `json_extract(value,'$.${c}')`).join(',')} FROM json_each(?) WHERE true ON CONFLICT(${keys.join(',')}) DO NOTHING`
      )
      .bind(JSON.stringify(batch))
      .run()
  }
}

/** Follow dataset and budget ownership to include obsolete as well as expected rows. */
function jurisdictionScope(table: (typeof TABLES)[number]): string {
  if (table === 'fiscal_datasets' || table.endsWith('_budget_items'))
    return 'jurisdiction_code=?'
  if (table.endsWith('_settlement_links')) {
    const direction = table.includes('_expenditure_')
      ? 'expenditure'
      : 'revenue'
    return `budget_item_id IN (SELECT budget_item_id FROM fiscal_${direction}_budget_items WHERE jurisdiction_code=?)`
  }
  if (table.includes('_line_')) {
    const direction = table.includes('_expenditure_')
      ? 'expenditure'
      : 'revenue'
    return `fiscal_line_id IN (SELECT fiscal_line_id FROM fiscal_settlement_${direction}_lines WHERE dataset_id IN (SELECT dataset_id FROM fiscal_datasets WHERE jurisdiction_code=?))`
  }
  return 'dataset_id IN (SELECT dataset_id FROM fiscal_datasets WHERE jurisdiction_code=?)'
}

async function verifyTables(
  db: D1Database,
  jurisdictionCode: string,
  data: Awaited<ReturnType<typeof candidateRows>>
) {
  for (const table of TABLES) {
    const keys = TABLE_KEYS[table]
    let after: unknown[] | undefined
    let count = 0
    const hash = new Bun.CryptoHasher('sha256')
    while (true) {
      const cursor = after
        ? ` AND (${keys.join(',')}) > (${keys.map(() => '?').join(',')})`
        : ''
      const page = await db
        .prepare(
          `SELECT ${TABLE_COLUMNS[table].join(',')} FROM ${table} WHERE ${jurisdictionScope(table)}${cursor} ORDER BY ${keys.join(',')} LIMIT 500`
        )
        .bind(jurisdictionCode, ...(after ?? []))
        .all<Record<string, unknown>>()
      for (const row of page.results) hash.update(canonicalRow(table, row))
      count += page.results.length
      if (page.results.length < 500) break
      after = keys.map((key) => page.results.at(-1)![key])
    }
    const expected = new Bun.CryptoHasher('sha256')
    for (const row of data[table]) expected.update(canonicalRow(table, row))
    if (
      count !== data[table].length ||
      hash.digest('hex') !== expected.digest('hex')
    )
      throw new Error(`Imported data differs: ${table}`)
  }
}

/** Rows become visible as they are inserted; failed imports remain resumable. */
export async function publish(
  directory: string,
  db: D1Database,
  store: ObjectStore,
  manifestUrl: string,
  progress: Progress = () => {},
  options: { jurisdictionCodes?: string[]; registeredAt?: string } = {}
) {
  const verification = await verifyCandidate(directory)
  const manifest = distributionManifestSchema.parse(
    JSON.parse(await readFile(join(directory, 'manifest.json'), 'utf8'))
  )
  const wanted = new Set(
    options.jurisdictionCodes ??
      verification.versions.map((v) => v.jurisdictionCode)
  )
  if (
    [...wanted].some(
      (code) => !verification.versions.some((v) => v.jurisdictionCode === code)
    )
  )
    throw new Error('Unknown jurisdiction in candidate')
  const parsedUrl = new URL(manifestUrl)
  if (parsedUrl.protocol !== 'https:')
    throw new Error('The manifest must have an HTTPS URL')
  const data = await candidateRows(directory)
  const partitions = partitionAllRows(data)
  const masters = jurisdictionMasterSchema
    .array()
    .parse(await jsonLines(join(directory, 'api/jurisdictions.jsonl')))

  for (const master of masters.filter((row) =>
    wanted.has(row.jurisdiction_code)
  )) {
    await db
      .prepare(
        'INSERT INTO jurisdictions VALUES(?,?,?) ON CONFLICT(jurisdiction_code) DO UPDATE SET name=excluded.name,ocd_id=excluded.ocd_id'
      )
      .bind(master.jurisdiction_code, master.name, master.ocd_id)
      .run()
  }
  const cofog = cofogMasterSchema
    .array()
    .parse(await jsonLines(join(directory, 'api/cofog_codes.jsonl')))
  await appendRows(db, 'cofog_codes', cofog)
  const versions = []
  for (const version of verification.versions.filter((v) =>
    wanted.has(v.jurisdictionCode)
  )) {
    const files = manifest.files.filter((file) =>
      file.path.startsWith(`fiscal/${version.jurisdictionCode}/`)
    )
    for (const file of files) {
      const current = await store.read(file.objectKey)
      if (current) {
        if (
          current.byteLength !== file.bytes ||
          sha256(current) !== file.sha256
        )
          throw new Error('Existing immutable object differs')
      } else {
        await store.put(
          file.objectKey,
          join(directory, file.path),
          file.contentType
        )
        const uploaded = await store.read(file.objectKey)
        if (
          !uploaded ||
          uploaded.byteLength !== file.bytes ||
          sha256(uploaded) !== file.sha256
        )
          throw new Error('Uploaded immutable object differs')
      }
      progress({
        stage: 'object',
        jurisdictionCode: version.jurisdictionCode,
        path: file.path,
        reused: !!current,
      })
    }
    const values = {
      version_id: version.versionId,
      jurisdiction_code: version.jurisdictionCode,
      contract_version: CONTRACT_VERSION,
      package_id: version.packageId,
      name_snapshot: version.name,
      ocd_id_snapshot: version.ocdId,
      caveats_json: JSON.stringify(version.caveats),
    }
    const existing = await db
      .prepare(
        'SELECT * FROM fiscal_jurisdiction_data WHERE jurisdiction_code=?'
      )
      .bind(version.jurisdictionCode)
      .first<Record<string, unknown>>()
    if (existing?.version_id === version.versionId) {
      for (const [key, value] of Object.entries(values))
        if (existing[key] !== value)
          throw new Error('Existing version metadata differs')
    } else {
      const row = {
        ...values,
        registered_at: options.registeredAt ?? new Date().toISOString(),
        manifest_url: manifestUrl,
        manifest_sha256: verification.manifestSha256,
      }
      await db.batch([
        db
          .prepare('DELETE FROM fiscal_datasets WHERE jurisdiction_code=?')
          .bind(version.jurisdictionCode),
        db
          .prepare(
            'DELETE FROM fiscal_expenditure_budget_items WHERE jurisdiction_code=?'
          )
          .bind(version.jurisdictionCode),
        db
          .prepare(
            'DELETE FROM fiscal_revenue_budget_items WHERE jurisdiction_code=?'
          )
          .bind(version.jurisdictionCode),
        db
          .prepare('DELETE FROM fiscal_package_files WHERE jurisdiction_code=?')
          .bind(version.jurisdictionCode),
        db
          .prepare(
            `INSERT INTO fiscal_jurisdiction_data (${Object.keys(row).join(',')}) VALUES (${Object.keys(
              row
            )
              .map(() => '?')
              .join(
                ','
              )}) ON CONFLICT(jurisdiction_code) DO UPDATE SET ${Object.keys(
              row
            )
              .filter((key) => key !== 'jurisdiction_code')
              .map((key) => `${key}=excluded.${key}`)
              .join(',')}`
          )
          .bind(...Object.values(row)),
      ])
    }
    progress({
      stage: 'registered',
      jurisdictionCode: version.jurisdictionCode,
      versionId: version.versionId,
    })
    const scoped = partitionRows(data, version.jurisdictionCode, partitions)
    for (const table of TABLES) {
      await appendRows(db, table, scoped[table])
      progress({
        stage: 'table',
        jurisdictionCode: version.jurisdictionCode,
        versionId: version.versionId,
        table,
        rows: scoped[table].length,
      })
    }
    for (const file of files) {
      const row = {
        path: file.path,
        jurisdiction_code: version.jurisdictionCode,
        object_key: file.objectKey,
        sha256: file.sha256,
        bytes: file.bytes,
        content_type: file.contentType,
      }
      const old = await db
        .prepare('SELECT * FROM fiscal_package_files WHERE path=?')
        .bind(file.path)
        .first<Record<string, unknown>>()
      if (old && canonicalJson(old) !== canonicalJson(row))
        throw new Error('Existing file metadata differs')
      if (!old)
        await db
          .prepare(
            `INSERT INTO fiscal_package_files VALUES(${Object.keys(row)
              .map(() => '?')
              .join(',')})`
          )
          .bind(...Object.values(row))
          .run()
    }
    await verifyTables(db, version.jurisdictionCode, scoped)
    versions.push({
      jurisdictionCode: version.jurisdictionCode,
      versionId: version.versionId,
    })
    progress({
      stage: 'verified',
      jurisdictionCode: version.jurisdictionCode,
      versionId: version.versionId,
    })
  }
  const result = { buildId: verification.buildId, versions, imported: true }
  await writeFile(
    join(directory, 'publish-result.json'),
    JSON.stringify(result, null, 2) + '\n'
  )
  return result
}
