import { beforeEach, afterEach, expect, test } from 'bun:test'
import { Database } from 'bun:sqlite'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { sqliteD1 } from '../../apps/api/test/database'
import {
  TABLES,
  canonicalRow,
  manifestSchema,
  type R2Bucket,
  type ReleaseManifest,
} from '@fudoki/data-contracts'
import { Verification, type HashStream } from './verification'
import download from '../../apps/download/src/index'
const id = 'r-' + 'a'.repeat(32),
  fingerprint = 'b'.repeat(64),
  file = 'catalog.json',
  content = '{"example":true}\n'
const hash = (body: string) => createHash('sha256').update(body).digest('hex')
const hashStream: HashStream = async (stream) => {
  const hash = createHash('sha256'),
    reader = stream.getReader()
  let bytes = 0
  while (true) {
    const next = await reader.read()
    if (next.done) break
    bytes += next.value.byteLength
    hash.update(next.value)
  }
  return { bytes, sha256: hash.digest('hex') }
}
let databaseIdentity: string,
  sqlite: Database,
  objects: Map<string, string>,
  manifest: ReleaseManifest,
  verifier: Verification
beforeEach(() => {
  sqlite = new Database(':memory:')
  sqlite.exec(
    readFileSync(
      new URL('../../packages/data-contracts/schema.sql', import.meta.url),
      'utf8'
    )
  )
  databaseIdentity = (
    sqlite.query('SELECT identity FROM database_identity').get() as {
      identity: string
    }
  ).identity
  manifest = manifestSchema.parse({
    schemaVersion: 1,
    releaseId: id,
    codeRevision: 'a'.repeat(40),
    inputFingerprint: 'c'.repeat(64),
    judgmentFingerprint: 'd'.repeat(64),
    queryFingerprint: fingerprint,
    totals: [],
    files: [
      {
        path: file,
        sha256: hash(content),
        bytes: Buffer.byteLength(content),
        contentType: 'application/json; charset=utf-8',
      },
    ],
    tables: Object.fromEntries(
      TABLES.map((table) => [
        table,
        { rows: 0, sha256: hash(''), canonicalSha256: hash(''), chunks: [] },
      ])
    ),
  })
  const text = JSON.stringify(manifest) + '\n'
  sqlite.run("INSERT INTO releases VALUES(?,1,'staging',NULL,?,?,?)", [
    id,
    hash(text),
    'a'.repeat(40),
    'c'.repeat(64),
  ])
  sqlite.run('INSERT INTO files VALUES(?,?,?,?,?,?)', [
    id,
    file,
    `releases/${id}/${file}`,
    hash(content),
    Buffer.byteLength(content),
    'application/json; charset=utf-8',
  ])
  objects = new Map([
    [`_candidates/${id}/manifest.json`, text],
    [`releases/${id}/${file}`, content],
  ])
  const bucket: R2Bucket = {
    async get(key) {
      const value = objects.get(key)
      if (value === undefined) return null
      return {
        key,
        size: Buffer.byteLength(value),
        httpEtag: '"ignored"',
        body: new Blob([value]).stream(),
        async arrayBuffer() {
          return new TextEncoder().encode(value).buffer
        },
        async json<T>() {
          return JSON.parse(value) as T
        },
        writeHttpMetadata() {},
      }
    },
    async head(key) {
      const value = objects.get(key)
      return value === undefined
        ? null
        : { size: Buffer.byteLength(value), httpEtag: '"ignored"' }
    },
    async list() {
      throw new Error('No listing')
    },
  }
  verifier = new Verification(
    {
      DB: sqliteD1(sqlite),
      RELEASES: bucket,
      QUERY_FINGERPRINT: fingerprint,
      PUBLIC_API: {
        async fetch() {
          return Response.json({
            contractVersion: 1,
            queryFingerprint: fingerprint,
            databaseIdentity,
          })
        },
      },
      PUBLIC_DOWNLOAD: {
        fetch: (request) => download.fetch(request, { RELEASES: bucket }),
      },
    },
    hashStream
  )
})
afterEach(() => sqlite.close())
test('candidate files are checked by their bytes, not by object metadata or ETag', async () => {
  expect((await verifier.file(id, file)).sha256).toBe(hash(content))
  objects.set(`releases/${id}/${file}`, content.replace('true', 'null'))
  await expect(verifier.file(id, file)).rejects.toThrow('hash or size')
})
test('unpublished candidate is private until the final manifest, then download headers must match', async () => {
  await expect(verifier.downloads(id)).rejects.toThrow('not available')
  objects.set(
    `releases/${id}/manifest.json`,
    objects.get(`_candidates/${id}/manifest.json`)!
  )
  expect(await verifier.downloads(id)).toEqual({ files: 1 })
  expect(await verifier.publicContracts(id)).toEqual({
    contractVersion: 1,
    queryFingerprint: fingerprint,
    databaseIdentity,
  })
})
test('changing the candidate manifest is detected against its D1 hash', async () => {
  objects.set(
    `_candidates/${id}/manifest.json`,
    JSON.stringify({ ...manifest, codeRevision: 'e'.repeat(40) })
  )
  await expect(verifier.candidate(id)).rejects.toThrow('manifest hash differs')
})
test('table verification uses a bounded keyset and canonical values across chunk boundaries', async () => {
  const rows = []
  for (let i = 0; i < 501; i++) {
    const row = {
      jurisdiction_code: String(i).padStart(6, '0'),
      name: `団体${i}`,
      ocd_id: 'test',
      caveats_json: '[]',
    }
    rows.push(row)
    sqlite.run('INSERT INTO jurisdictions VALUES(?,?,?,?,?)', [
      id,
      row.jurisdiction_code,
      row.name,
      row.ocd_id,
      row.caveats_json,
    ])
  }
  const first = await verifier.chunk(id, 'jurisdictions')
  expect(first.rows).toBe(500)
  expect(first.sha256).toBe(
    hash(
      rows
        .slice(0, 500)
        .map((r) => canonicalRow('jurisdictions', r))
        .join('')
    )
  )
  const last = await verifier.chunk(id, 'jurisdictions', first.after)
  expect(last.rows).toBe(1)
  expect(last.sha256).toBe(hash(canonicalRow('jurisdictions', rows[500]!)))
  expect((await verifier.chunk(id, 'jurisdictions', last.after)).rows).toBe(0)
  await expect(
    verifier.chunk(id, 'jurisdictions', ["x' OR 1=1 --", 'extra'])
  ).rejects.toThrow('Invalid table continuation')
})

test('a public API bound to another D1 database refuses the candidate despite matching query code', async () => {
  sqlite.run("UPDATE database_identity SET identity='another-database'")
  await expect(verifier.publicContracts(id)).rejects.toThrow(
    'D1 binding differ'
  )
})
test('download content is verified even when all public headers and byte lengths match', async () => {
  objects.set(
    `releases/${id}/manifest.json`,
    objects.get(`_candidates/${id}/manifest.json`)!
  )
  objects.set(`releases/${id}/${file}`, content.replace('true', 'null'))
  await expect(verifier.download(id, file)).rejects.toThrow(
    'download content differs'
  )
})
