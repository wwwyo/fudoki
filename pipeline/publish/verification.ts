import {
  TABLES,
  TABLE_COLUMNS,
  TABLE_KEYS,
  canonicalRow,
  manifestSchema,
  releaseIdSchema,
  type D1Database,
  type D1Statement,
  type R2Bucket,
  type ReleaseManifest,
} from '@fudoki/data-contracts'
import { z } from 'zod'
import {
  aggregate,
  listDatasets,
  queryLines,
} from '../../apps/api/src/data/queries'
import {
  aggregateQuerySchema,
  lineQuerySchema,
  lineSchema,
} from '../../apps/api/src/contract'

export type HashStream = (
  stream: ReadableStream<Uint8Array>
) => Promise<{ sha256: string; bytes: number }>
export interface VerificationEnv {
  DB: D1Database
  RELEASES: R2Bucket
  QUERY_FINGERPRINT: string
  PUBLIC_API: { fetch(request: Request): Promise<Response> }
  PUBLIC_DOWNLOAD: { fetch(request: Request): Promise<Response> }
}
const CHUNK_SIZE = 500
export class Verification {
  constructor(
    private env: VerificationEnv,
    private hashStream: HashStream
  ) {}
  async existingManifest(releaseId: string, sha256: string) {
    releaseIdSchema.parse(releaseId)
    z.string()
      .regex(/^[a-f0-9]{64}$/)
      .parse(sha256)
    const result = { candidate: false, published: false }
    for (const [kind, key] of [
      ['candidate', `_candidates/${releaseId}/manifest.json`],
      ['published', `releases/${releaseId}/manifest.json`],
    ] as const) {
      const object = await this.env.RELEASES.get(key)
      if (!object) continue
      const actual = await this.hashStream(object.body)
      if (actual.sha256 !== sha256)
        throw new Error(
          'Refusing to overwrite an existing release manifest with different content'
        )
      result[kind] = true
    }
    return result
  }
  async existingFile(releaseId: string, path: string) {
    const manifest = await this.candidate(releaseId)
    const file = manifest.files.find((f) => f.path === path)
    if (!file) throw new Error('File is not listed in candidate manifest')
    const object = await this.env.RELEASES.get(`releases/${releaseId}/${path}`)
    if (!object) return false
    const actual = await this.hashStream(object.body)
    if (actual.sha256 !== file.sha256 || actual.bytes !== file.bytes)
      throw new Error(
        'Refusing to overwrite an existing release file with different content'
      )
    return true
  }
  async candidate(releaseId: string): Promise<ReleaseManifest> {
    releaseIdSchema.parse(releaseId)
    const release = await this.env.DB.prepare(
      'SELECT contract_version,manifest_sha256,state FROM releases WHERE release_id=?'
    )
      .bind(releaseId)
      .first<{
        contract_version: number
        manifest_sha256: string
        state: string
      }>()
    const object = await this.env.RELEASES.get(
      release?.state === 'published'
        ? `releases/${releaseId}/manifest.json`
        : `_candidates/${releaseId}/manifest.json`
    )
    if (!object || object.size > 4 * 1024 * 1024)
      throw new Error('Candidate manifest is missing or too large')
    const body = await object.arrayBuffer()
    const manifest = manifestSchema.parse(
      JSON.parse(new TextDecoder().decode(body))
    )
    if (
      manifest.releaseId !== releaseId ||
      (release?.state !== 'published' &&
        manifest.queryFingerprint !== this.env.QUERY_FINGERPRINT)
    )
      throw new Error('Candidate differs from verification Worker contract')
    const verified = await this.hashStream(new Blob([body]).stream())
    if (
      !release ||
      release.contract_version !== manifest.schemaVersion ||
      verified.sha256 !== release.manifest_sha256
    )
      throw new Error('D1 candidate contract or manifest hash differs')
    return manifest
  }
  async file(releaseId: string, path: string) {
    const manifest = await this.candidate(releaseId)
    const file = manifest.files.find((f) => f.path === path)
    if (!file) throw new Error('File is not listed in candidate manifest')
    const object = await this.env.RELEASES.get(
      `releases/${releaseId}/${file.path}`
    )
    if (!object) throw new Error('Candidate file is missing')
    const result = await this.hashStream(object.body)
    if (result.sha256 !== file.sha256 || result.bytes !== file.bytes)
      throw new Error('Candidate file differs from its hash or size')
    return result
  }
  async chunk(
    releaseId: string,
    table: (typeof TABLES)[number],
    after?: unknown[]
  ) {
    await this.candidate(releaseId)
    z.enum(TABLES).parse(table)
    const keys = TABLE_KEYS[table],
      columns = TABLE_COLUMNS[table]
    if (after) {
      if (
        after.length !== keys.length ||
        after.some((value, i) =>
          keys[i] === 'ordinal'
            ? typeof value !== 'number' || !Number.isInteger(value)
            : typeof value !== 'string' || value.length > 512
        )
      )
        throw new Error('Invalid table continuation')
    }
    const continuation = after
      ? ` AND (${keys.map((k) => `"${k}"`).join(',')}) > (${keys.map(() => '?').join(',')})`
      : ''
    const result = await this.env.DB.prepare(
      `SELECT ${columns.map((c) => `"${c}"`).join(',')} FROM "${table}" WHERE release_id=?${continuation} ORDER BY ${keys.map((k) => `"${k}"`).join(',')} LIMIT ${CHUNK_SIZE}`
    )
      .bind(releaseId, ...(after ?? []))
      .all<Record<string, unknown>>()
    if (!result.success) throw new Error('Candidate table query failed')
    const body = new TextEncoder().encode(
      result.results.map((row) => canonicalRow(table, row)).join('')
    )
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(body)
        controller.close()
      },
    })
    const { sha256 } = await this.hashStream(stream)
    return {
      rows: result.results.length,
      sha256,
      after: result.results.length
        ? keys.map((k) => result.results.at(-1)![k])
        : after,
      meta: result.meta,
    }
  }
  async api(releaseId: string, datasetId: string, phase: string) {
    await this.candidate(releaseId)
    const input = aggregateQuerySchema.parse({
      datasetIds: [datasetId],
      phase,
      groupBy: ['year'],
      consolidation: 'all',
    })
    const datasets = await listDatasets(this.env.DB, releaseId)
    const selected = datasets.find((d) => d.id === datasetId)
    if (!selected) throw new Error('Dataset is missing')
    const start = Date.now()
    const total = await aggregate(this.env.DB, releaseId, input)
    const lines = await queryLines(
      this.env.DB,
      releaseId,
      lineQuerySchema.parse({
        datasetIds: [datasetId],
        phase,
        pageSize: 50,
        consolidation: 'all',
      })
    )
    return {
      dataset: selected,
      total: total.total,
      lines: lineSchema.array().parse(lines.slice(0, 50)),
      milliseconds: Date.now() - start,
    }
  }
  async measure(releaseId: string) {
    const manifest = await this.candidate(releaseId),
      measurements: {
        kind: string
        milliseconds: number
        rowsRead: number | null
      }[] = []
    const datasets = await listDatasets(this.env.DB, releaseId)
    const selected = datasets.find(
      (dataset) => dataset.direction === 'expenditure'
    )
    if (!selected)
      throw new Error('Performance probes require an expenditure dataset')
    const phase = selected.phases.includes('approved')
      ? 'approved'
      : selected.phases[0]!
    let reads: number | null = 0
    const thisEnv = this.env
    const statement = (sql: string, values: unknown[] = []): D1Statement => ({
      bind: (...args) => statement(sql, args),
      async all<T>() {
        const result = await thisEnv.DB.prepare(sql)
          .bind(...values)
          .all<T>()
        reads =
          result.meta?.rows_read === undefined
            ? null
            : reads === null
              ? null
              : reads + result.meta.rows_read
        return result
      },
      async first<T>() {
        const result = await this.all<T>()
        return result.results[0] ?? null
      },
      async run() {
        throw new Error('Performance probes cannot write')
      },
    })
    const db: D1Database = {
      prepare: (sql) => statement(sql),
      async batch() {
        throw new Error('Performance probes cannot write')
      },
    }
    const probe = async (kind: string, run: () => Promise<unknown>) => {
      reads = 0
      const start = Date.now()
      await run()
      measurements.push({
        kind,
        milliseconds: Date.now() - start,
        rowsRead: reads,
      })
    }
    const input = lineQuerySchema.parse({
      datasetIds: [selected.id],
      phase,
      pageSize: 50,
    })
    let first: Awaited<ReturnType<typeof queryLines>> = []
    await probe('line-page', async () => {
      first = await queryLines(db, releaseId, input)
    })
    const name = first[0]?.names.find((name) => name.value)?.value
    if (name)
      await probe('literal-name-search', () =>
        queryLines(db, releaseId, { ...input, name })
      )
    const hierarchy = first[0]?.hierarchy.slice(0, 3) ?? []
    if (hierarchy.length)
      await probe('hierarchy-filter', () =>
        queryLines(
          db,
          releaseId,
          lineQuerySchema.parse({
            ...input,
            hierarchy: hierarchy.map(({ level, code }) => ({ level, code })),
          })
        )
      )
    await probe('cofog-parent-aggregate', () =>
      aggregate(
        db,
        releaseId,
        aggregateQuerySchema.parse({
          datasetIds: [selected.id],
          phase,
          groupBy: ['cofog.division'],
        })
      )
    )
    const scopes = new Set<string>()
    const comparison = datasets.filter((dataset) => {
      const key = `${dataset.jurisdictionCode}:${dataset.fiscalYear}:${dataset.direction}`
      if (
        dataset.direction !== 'expenditure' ||
        !dataset.phases.includes(phase) ||
        scopes.has(key)
      )
        return false
      scopes.add(key)
      return true
    })
    await probe('jurisdiction-year-comparison', async () => {
      const result = await aggregate(
        db,
        releaseId,
        aggregateQuerySchema.parse({
          datasetIds: comparison.slice(0, 100).map((d) => d.id),
          phase,
          groupBy: ['jurisdiction', 'year', 'cofog.division'],
        })
      )
      for (const total of result.totals) {
        const expected = manifest.totals.find(
          (value) =>
            value.datasetId === total.datasetId && value.phase === phase
        )
        if (
          !expected ||
          expected.amount !== total.amount ||
          expected.rows !== total.lineCount
        )
          throw new Error('Comparison probe differs from candidate totals')
      }
    })
    return { releaseId, measurements }
  }
  async publicContracts(releaseId: string) {
    const manifest = await this.candidate(releaseId)
    const [api, download] = await Promise.all([
      this.env.PUBLIC_API.fetch(
        new Request('https://api.internal/v0/contract')
      ),
      this.env.PUBLIC_DOWNLOAD.fetch(
        new Request('https://download.internal/contract')
      ),
    ])
    if (!api.ok || !download.ok) throw new Error('Public Workers are not ready')
    const a = (await api.json()) as {
        contractVersion: number
        queryFingerprint: string
        databaseIdentity: string
      },
      d = (await download.json()) as { contractVersion: number }
    const database = await this.env.DB.prepare(
      'SELECT identity FROM database_identity WHERE singleton=1'
    ).first<{ identity: string }>()
    if (
      !database ||
      a.databaseIdentity !== database.identity ||
      a.contractVersion !== manifest.schemaVersion ||
      a.queryFingerprint !== this.env.QUERY_FINGERPRINT ||
      d.contractVersion !== manifest.schemaVersion
    )
      throw new Error(
        'Public Worker contracts or D1 binding differ from candidate'
      )
    return {
      contractVersion: manifest.schemaVersion,
      queryFingerprint: manifest.queryFingerprint,
      databaseIdentity: database.identity,
    }
  }
  async downloads(releaseId: string) {
    const manifest = await this.candidate(releaseId)
    const response = await this.env.PUBLIC_DOWNLOAD.fetch(
      new Request(
        `https://download.internal/releases/${releaseId}/manifest.json`
      )
    )
    if (!response.ok || response.headers.get('X-Fudoki-Release') !== releaseId)
      throw new Error(
        'Finalized manifest is not available through download Worker'
      )
    const published = manifestSchema.parse(await response.json())
    if (JSON.stringify(published) !== JSON.stringify(manifest))
      throw new Error('Published and candidate manifests differ')
    const metadata = await this.env.DB.prepare(
      'SELECT path,object_key,sha256,bytes,content_type FROM files WHERE release_id=? ORDER BY path'
    )
      .bind(releaseId)
      .all<{
        path: string
        object_key: string
        sha256: string
        bytes: number
        content_type: string
      }>()
    if (metadata.results.length !== manifest.files.length)
      throw new Error('D1 file count differs from manifest')
    for (const file of manifest.files) {
      const row = metadata.results.find((r) => r.path === file.path)
      if (
        !row ||
        row.object_key !== `releases/${releaseId}/${file.path}` ||
        row.sha256 !== file.sha256 ||
        row.bytes !== file.bytes ||
        row.content_type !== file.contentType
      )
        throw new Error('D1 file metadata differs from manifest')
    }
    return { files: manifest.files.length }
  }
  async download(releaseId: string, path: string) {
    const manifest = await this.candidate(releaseId),
      file = manifest.files.find((file) => file.path === path)
    if (!file) throw new Error('File is not listed in manifest')
    const response = await this.env.PUBLIC_DOWNLOAD.fetch(
      new Request(`https://download.internal/releases/${releaseId}/${path}`)
    )
    if (
      !response.ok ||
      response.headers.get('ETag') !== `"${file.sha256}"` ||
      Number(response.headers.get('Content-Length')) !== file.bytes ||
      response.headers.get('Content-Type') !== file.contentType ||
      response.headers.get('X-Fudoki-Release') !== releaseId
    )
      throw new Error(`Download headers differ: ${path}`)
    if (!response.body) throw new Error('Download body is missing')
    const actual = await this.hashStream(response.body)
    if (actual.sha256 !== file.sha256 || actual.bytes !== file.bytes)
      throw new Error('Public download content differs from manifest')
    return actual
  }
}
