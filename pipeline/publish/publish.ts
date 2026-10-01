import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { createReadStream } from 'node:fs'
import { createInterface } from 'node:readline'
import {
  TABLES,
  TABLE_COLUMNS,
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
  | 'report'
> {
  existingManifest(
    releaseId: string,
    sha256: string
  ): Promise<{ candidate: boolean; published: boolean }>
  existingFile(releaseId: string, path: string): Promise<boolean>
}
export type Progress = (event: Record<string, unknown>) => void
export async function publish(
  candidate: string,
  db: D1Database,
  store: ObjectStore,
  verify: Verifier,
  progress: Progress = () => {}
) {
  const manifest = await verifyCandidate(candidate)
  const manifestPath = join(candidate, 'manifest.json'),
    manifestHash = sha256(await readFile(manifestPath))
  const lease = await acquire(db, crypto.randomUUID(), manifest.releaseId)
  try {
    const existing = await verify.existingManifest(
      manifest.releaseId,
      manifestHash
    )
    const sql = db
      .prepare(
        `INSERT INTO releases(release_id,contract_version,state,manifest_sha256,code_revision,input_fingerprint)
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
          'INSERT INTO publish_guard(valid) SELECT CASE WHEN EXISTS(SELECT 1 FROM releases WHERE release_id=? AND manifest_sha256=? AND contract_version=?) THEN 1 ELSE 0 END'
        )
        .bind(manifest.releaseId, manifestHash, manifest.schemaVersion),
    ])
    if (!existing.candidate)
      await store.put(
        `_candidates/${manifest.releaseId}/manifest.json`,
        manifestPath,
        'application/json; charset=utf-8'
      )
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
    if (!existing.published)
      await store.put(
        `releases/${manifest.releaseId}/manifest.json`,
        manifestPath,
        'application/json; charset=utf-8'
      )
    const downloads = await verify.downloads(manifest.releaseId)
    for (const file of manifest.files) {
      await verify.download(manifest.releaseId, file.path)
      await guardedBatch(db, lease, [])
    }
    const reportDirectory = await mkdtemp(join(tmpdir(), 'fudoki-validation-'))
    let reportKey: string
    try {
      const body =
        JSON.stringify(
          {
            schemaVersion: 1,
            stage: 'pre-activation-verified',
            verifiedAt: new Date().toISOString(),
            releaseId: manifest.releaseId,
            manifestSha256: manifestHash,
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
      const hash = sha256(body)
      reportKey = `_verification/${manifest.releaseId}/${hash}.json`
      const path = join(reportDirectory, 'validation.json')
      await writeFile(path, body, { mode: 0o600 })
      await store.put(reportKey, path, 'application/json; charset=utf-8')
      await verify.report(manifest.releaseId, hash, Buffer.byteLength(body))
      await guardedBatch(db, lease, [])
    } finally {
      await rm(reportDirectory, { recursive: true, force: true })
    }
    await activate(
      db,
      lease,
      `releases/${manifest.releaseId}/manifest.json`,
      manifestHash
    )
    progress({ stage: 'active', releaseId: manifest.releaseId })
    return {
      releaseId: manifest.releaseId,
      previousReleaseId: lease.expectedReleaseId,
      probes,
      performance,
      reportKey,
    }
  } finally {
    await release(db, lease)
  }
}
export async function rollback(
  db: D1Database,
  verify: Verifier,
  manifest: ReleaseManifest,
  manifestHash: string
) {
  const lease = await acquire(db, crypto.randomUUID(), manifest.releaseId)
  try {
    const row = await db
      .prepare(
        'SELECT state,manifest_sha256 FROM releases WHERE release_id=? AND contract_version=?'
      )
      .bind(manifest.releaseId, manifest.schemaVersion)
      .first<{ state: string; manifest_sha256: string }>()
    if (row?.state !== 'published' || row.manifest_sha256 !== manifestHash)
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
    await activate(
      db,
      lease,
      `releases/${manifest.releaseId}/manifest.json`,
      manifestHash
    )
    return {
      releaseId: manifest.releaseId,
      previousReleaseId: lease.expectedReleaseId,
    }
  } finally {
    await release(db, lease)
  }
}
