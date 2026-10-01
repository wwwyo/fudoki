import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { createReadStream } from 'node:fs'
import { createInterface } from 'node:readline'
import {
  TABLES,
  TABLE_COLUMNS,
  canonicalRow,
  jurisdictionMasterSchema,
  cofogMasterSchema,
  type D1Database,
  type ReleaseManifest,
} from '@fudoki/data-contracts'
import { verifyCandidate } from '../fdp/manifest'
import { sha256 } from '../release'
import { acquire, activate, guardedBatch, release } from './control'
import type { Verification } from './verification'

export interface ObjectStore {
  put(key: string, path: string, contentType: string): Promise<void>
}
export interface Verifier extends Pick<
  Verification,
  | 'file'
  | 'chunk'
  | 'api'
  | 'publicContracts'
  | 'downloads'
  | 'download'
  | 'measure'
> {
  existingFile(releaseId: string, path: string): Promise<boolean>
}
export type Progress = (event: Record<string, unknown>) => void
export async function publish(
  candidate: string,
  db: D1Database,
  store: ObjectStore,
  verify: Verifier,
  manifestUrl: string,
  progress: Progress = () => {}
) {
  const manifest = await verifyCandidate(candidate)
  const manifestHash = sha256(
    await readFile(join(candidate, 'verification.json'))
  )
  const lease = await acquire(db, crypto.randomUUID(), manifest.releaseId)
  try {
    const sql = db
      .prepare(
        `INSERT INTO releases(release_id,contract_version,state,verification_sha256,code_revision,input_fingerprint)
      VALUES(?,?,'staging',?,?,?) ON CONFLICT(release_id) DO NOTHING`
      )
      .bind(
        manifest.releaseId,
        manifest.schemaVersion,
        manifestHash,
        manifest.codeRevision,
        manifest.inputFingerprint
      )
    await guardedBatch(db, lease, [
      sql,
      db
        .prepare(
          'INSERT INTO publish_guard(valid) SELECT CASE WHEN EXISTS(SELECT 1 FROM releases WHERE release_id=? AND verification_sha256=? AND contract_version=?) THEN 1 ELSE 0 END'
        )
        .bind(manifest.releaseId, manifestHash, manifest.schemaVersion),
    ])
    const masters = (
      await readFile(join(candidate, 'api/jurisdictions.jsonl'), 'utf8')
    )
      .split('\n')
      .filter(Boolean)
      .map((line) => jurisdictionMasterSchema.parse(JSON.parse(line)))
    if (
      new Set(masters.map((row) => row.jurisdiction_code)).size !==
      masters.length
    )
      throw new Error('Duplicate jurisdiction master identity')
    for (let offset = 0; offset < masters.length; offset += 500) {
      const batch = masters.slice(offset, offset + 500)
      await guardedBatch(db, lease, [
        db
          .prepare(
            `INSERT INTO jurisdictions(jurisdiction_code,name,ocd_id)
         SELECT json_extract(value,'$.jurisdiction_code'),json_extract(value,'$.name'),json_extract(value,'$.ocd_id') FROM json_each(?) WHERE true
         ON CONFLICT(jurisdiction_code) DO UPDATE SET name=excluded.name,ocd_id=excluded.ocd_id`
          )
          .bind(JSON.stringify(batch)),
      ])
      const actual = await db
        .prepare(
          'SELECT jurisdiction_code,name,ocd_id FROM jurisdictions WHERE jurisdiction_code IN (SELECT value FROM json_each(?)) ORDER BY jurisdiction_code'
        )
        .bind(JSON.stringify(batch.map((row) => row.jurisdiction_code)))
        .all<Record<string, unknown>>()
      const expected = [...batch].sort((a, b) =>
        a.jurisdiction_code.localeCompare(b.jurisdiction_code)
      )
      if (
        actual.results
          .map((row) => canonicalRow('jurisdictions', row))
          .join('') !==
        expected.map((row) => canonicalRow('jurisdictions', row)).join('')
      )
        throw new Error('Jurisdiction master differs after transfer')
    }
    const codes = (
      await readFile(join(candidate, 'api/cofog_codes.jsonl'), 'utf8')
    )
      .split('\n')
      .filter(Boolean)
      .map((line) => cofogMasterSchema.parse(JSON.parse(line)))
    if (new Set(codes.map((row) => row.code)).size !== codes.length)
      throw new Error('Duplicate COFOG master identity')
    for (let offset = 0; offset < codes.length; offset += 500) {
      const batch = codes.slice(offset, offset + 500)
      await guardedBatch(db, lease, [
        db
          .prepare(
            `INSERT OR IGNORE INTO cofog_codes(code,label,level,parent_code)
        SELECT json_extract(value,'$.code'),json_extract(value,'$.label'),json_extract(value,'$.level'),json_extract(value,'$.parent_code') FROM json_each(?)`
          )
          .bind(JSON.stringify(batch)),
      ])
      const actual = await db
        .prepare(
          'SELECT code,label,level,parent_code FROM cofog_codes WHERE code IN (SELECT value FROM json_each(?)) ORDER BY code'
        )
        .bind(JSON.stringify(batch.map((row) => row.code)))
        .all<Record<string, unknown>>()
      const expected = [...batch].sort((a, b) => a.code.localeCompare(b.code))
      if (
        actual.results
          .map((row) => canonicalRow('cofog_codes', row))
          .join('') !==
        expected.map((row) => canonicalRow('cofog_codes', row)).join('')
      )
        throw new Error(
          'COFOG master differs after transfer; existing definitions cannot be reinterpreted'
        )
    }
    for (const file of manifest.files) {
      if (!(await verify.existingFile(manifest.releaseId, file.path)))
        await store.put(
          file.objectKey,
          join(candidate, file.path),
          file.contentType
        )
      await verify.file(manifest.releaseId, file.path)
      await guardedBatch(db, lease, [])
      progress({
        stage: 'file-verified',
        releaseId: manifest.releaseId,
        path: file.path,
      })
    }
    for (const table of TABLES) {
      const columns = TABLE_COLUMNS[table]
      const sql = `INSERT OR IGNORE INTO "${table}"(release_id,${columns.map((c) => `"${c}"`).join(',')}) SELECT ?,${columns.map((c) => `json_extract(value,'$.${c}')`).join(',')} FROM json_each(?)`
      let batch: Record<string, unknown>[] = []
      for await (const line of createInterface({
        input: createReadStream(join(candidate, 'api', `${table}.jsonl`)),
        crlfDelay: Infinity,
      })) {
        if (!line) continue
        batch.push(JSON.parse(line))
        if (batch.length === 500) {
          await guardedBatch(db, lease, [
            db.prepare(sql).bind(manifest.releaseId, JSON.stringify(batch)),
          ])
          batch = []
        }
      }
      if (batch.length)
        await guardedBatch(db, lease, [
          db.prepare(sql).bind(manifest.releaseId, JSON.stringify(batch)),
        ])
      let after: unknown[] | undefined,
        offset = 0
      while (true) {
        const chunk = await verify.chunk(manifest.releaseId, table, after)
        const expected = Math.min(500, manifest.tables[table].rows - offset)
        if (
          chunk.rows !== expected ||
          (expected > 0 &&
            chunk.sha256 !== manifest.tables[table].chunks[offset / 500])
        )
          throw new Error(`D1 contents differ: ${table} at row ${offset}`)
        offset += chunk.rows
        after = chunk.after
        await guardedBatch(db, lease, [])
        if (chunk.rows < 500) break
      }
      if (offset !== manifest.tables[table]!.rows)
        throw new Error(`D1 row count differs: ${table}`)
      progress({
        stage: 'table-verified',
        releaseId: manifest.releaseId,
        table,
        rows: offset,
      })
    }
    for (const file of manifest.files)
      await guardedBatch(db, lease, [
        db
          .prepare(
            `INSERT INTO files(release_id,path,object_key,sha256,bytes,content_type) VALUES(?,?,?,?,?,?) ON CONFLICT(release_id,path) DO NOTHING`
          )
          .bind(
            manifest.releaseId,
            file.path,
            file.objectKey,
            file.sha256,
            file.bytes,
            file.contentType
          ),
      ])
    const contracts = await verify.publicContracts(manifest.releaseId)
    const probes = []
    for (const total of manifest.totals) {
      const result = await verify.api(
        manifest.releaseId,
        total.datasetId,
        total.phase
      )
      if (
        result.total?.amount !== total.amount ||
        result.total?.lineCount !== total.rows
      )
        throw new Error(
          `API amounts or counts differ: ${total.datasetId}:${total.phase}`
        )
      probes.push({
        datasetId: total.datasetId,
        phase: total.phase,
        rows: total.rows,
        amount: total.amount,
        milliseconds: result.milliseconds,
      })
      await guardedBatch(db, lease, [])
    }
    const performance = await verify.measure(manifest.releaseId)
    await guardedBatch(db, lease, [])
    const downloads = await verify.downloads(manifest.releaseId)
    for (const file of manifest.files) {
      await verify.download(manifest.releaseId, file.path)
      await guardedBatch(db, lease, [])
    }
    const reportPath = join(candidate, 'publication-verification.json')
    const report =
      JSON.stringify(
        {
          schemaVersion: 1,
          stage: 'pre-activation-verified',
          verifiedAt: new Date().toISOString(),
          releaseId: manifest.releaseId,
          manifestSha256: manifest.manifestSha256,
          verificationSha256: manifestHash,
          manifestUrl,
          inputFingerprint: manifest.inputFingerprint,
          codeRevision: manifest.codeRevision,
          previousReleaseId: lease.expectedReleaseId,
          tables: manifest.tables,
          contracts,
          downloads,
          probes,
          performance,
          localValidation: JSON.parse(
            await readFile(join(candidate, 'validation.json'), 'utf8')
          ),
        },
        null,
        2
      ) + '\n'
    await writeFile(reportPath, report, { mode: 0o600 })
    if (sha256(await readFile(reportPath)) !== sha256(report))
      throw new Error('Local publication record differs')
    await guardedBatch(db, lease, [])
    await activate(db, lease, manifestUrl, manifestHash)
    progress({ stage: 'active', releaseId: manifest.releaseId })
    return {
      releaseId: manifest.releaseId,
      previousReleaseId: lease.expectedReleaseId,
      probes,
      performance,
      reportPath,
    }
  } finally {
    await release(db, lease)
  }
}
export async function rollback(
  db: D1Database,
  verify: Verifier,
  manifest: ReleaseManifest,
  manifestHash: string,
  manifestUrl: string
) {
  const lease = await acquire(db, crypto.randomUUID(), manifest.releaseId)
  try {
    const row = await db
      .prepare(
        'SELECT state,verification_sha256 FROM releases WHERE release_id=? AND contract_version=?'
      )
      .bind(manifest.releaseId, manifest.schemaVersion)
      .first<{ state: string; verification_sha256: string }>()
    if (row?.state !== 'published' || row.verification_sha256 !== manifestHash)
      throw new Error('Rollback target must be a retained, published release')
    for (const file of manifest.files) {
      await verify.file(manifest.releaseId, file.path)
      await guardedBatch(db, lease, [])
    }
    for (const table of TABLES) {
      let after: unknown[] | undefined,
        offset = 0
      while (true) {
        const chunk = await verify.chunk(manifest.releaseId, table, after)
        const expected = Math.min(500, manifest.tables[table].rows - offset)
        if (
          chunk.rows !== expected ||
          (expected > 0 &&
            chunk.sha256 !== manifest.tables[table].chunks[offset / 500])
        )
          throw new Error(`Rollback D1 contents differ: ${table}`)
        offset += chunk.rows
        after = chunk.after
        await guardedBatch(db, lease, [])
        if (chunk.rows < 500) break
      }
    }
    await verify.publicContracts(manifest.releaseId)
    await verify.downloads(manifest.releaseId)
    for (const file of manifest.files) {
      await verify.download(manifest.releaseId, file.path)
      await guardedBatch(db, lease, [])
    }
    for (const total of manifest.totals) {
      const result = await verify.api(
        manifest.releaseId,
        total.datasetId,
        total.phase
      )
      if (
        result.total?.amount !== total.amount ||
        result.total?.lineCount !== total.rows
      )
        throw new Error('Rollback API totals differ')
      await guardedBatch(db, lease, [])
    }
    await activate(db, lease, manifestUrl, manifestHash)
    return {
      releaseId: manifest.releaseId,
      previousReleaseId: lease.expectedReleaseId,
    }
  } finally {
    await release(db, lease)
  }
}
