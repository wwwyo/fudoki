import { beforeEach, afterEach, expect, test } from 'bun:test'
import { Database } from 'bun:sqlite'
import { readFile, mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import { sqliteD1 } from '../../apps/api/test/database'
import { resolveRelease } from '../../apps/api/src/data/queries'
import download from '../../apps/download/src/index'
import type { R2Bucket } from '@fudoki/data-contracts'
import { fixture } from '../verify/fixture'
import { Verification, type HashStream } from './verification'
import { publish, rollback, type Verifier, type ObjectStore } from './publish'

const R1 = 'r-' + '1'.repeat(32),
  R2 = 'r-' + '2'.repeat(32)
let directory: string,
  sqlite: Database,
  db: ReturnType<typeof sqliteD1>,
  objects: Map<string, Uint8Array<ArrayBuffer>>,
  verifier: Verification,
  store: ObjectStore
const hashStream: HashStream = async (stream) => {
  const hash = createHash('sha256'),
    reader = stream.getReader()
  let bytes = 0
  while (true) {
    const next = await reader.read()
    if (next.done) break
    hash.update(next.value)
    bytes += next.value.byteLength
  }
  return { bytes, sha256: hash.digest('hex') }
}
beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), 'fudoki-publish-test-'))
  await fixture(join(directory, R1), R1)
  await fixture(join(directory, R2), R2, 200)
  sqlite = new Database(':memory:')
  sqlite.exec(
    await readFile(
      new URL('../../packages/data-contracts/schema.sql', import.meta.url),
      'utf8'
    )
  )
  db = sqliteD1(sqlite)
  objects = new Map()
  const bucket: R2Bucket = {
    async get(key) {
      const value = objects.get(key)
      if (!value) return null
      return {
        key,
        size: value.byteLength,
        httpEtag: '"metadata"',
        body: new Blob([value]).stream(),
        async arrayBuffer() {
          return value.slice().buffer
        },
        async json<T>() {
          return JSON.parse(new TextDecoder().decode(value)) as T
        },
        writeHttpMetadata() {},
      }
    },
    async head(key) {
      const value = objects.get(key)
      return value ? { size: value.byteLength, httpEtag: '"metadata"' } : null
    },
    async list() {
      throw new Error('No listing')
    },
  }
  verifier = new Verification(
    {
      DB: db,
      RELEASES: bucket,
      QUERY_FINGERPRINT: 'e'.repeat(64),
      PUBLIC_API: {
        async fetch() {
          return Response.json({
            contractVersion: 1,
            queryFingerprint: 'e'.repeat(64),
            databaseIdentity: (
              sqlite.query('SELECT identity FROM database_identity').get() as {
                identity: string
              }
            ).identity,
          })
        },
      },
      PUBLIC_DOWNLOAD: {
        fetch: (request) => download.fetch(request, { RELEASES: bucket }),
      },
    },
    hashStream
  )
  store = {
    async put(key, path) {
      objects.set(key, new Uint8Array(await readFile(path)))
    },
  }
})
afterEach(async () => {
  sqlite.close()
  await rm(directory, { recursive: true, force: true })
})
function methods(overrides: Partial<Verifier> = {}): Verifier {
  return {
    existingManifest: verifier.existingManifest.bind(verifier),
    existingFile: verifier.existingFile.bind(verifier),
    file: verifier.file.bind(verifier),
    chunk: verifier.chunk.bind(verifier),
    api: verifier.api.bind(verifier),
    publicContracts: verifier.publicContracts.bind(verifier),
    downloads: verifier.downloads.bind(verifier),
    download: verifier.download.bind(verifier),
    measure: verifier.measure.bind(verifier),
    ...overrides,
  }
}
test('an interrupted file transfer cannot become active and can be resumed without overwriting verified files', async () => {
  let puts = 0
  await expect(
    publish(
      join(directory, R1),
      db,
      {
        async put(key, path, type) {
          if (++puts === 3) throw new Error('transfer interrupted')
          await store.put(key, path, type)
        },
      },
      methods()
    )
  ).rejects.toThrow('interrupted')
  await expect(resolveRelease(db)).rejects.toMatchObject({
    code: 'UNAVAILABLE',
  })
  expect(objects.has(`releases/${R1}/manifest.json`)).toBe(false)
  await publish(join(directory, R1), db, store, methods())
  expect(await resolveRelease(db)).toBe(R1)
  expect(
    sqlite.query('SELECT count(*) AS count FROM fiscal_lines').get()
  ).toEqual({ count: 501 })
})
test('a D1 verification failure preserves the prior release and retry checks the existing rows', async () => {
  await publish(join(directory, R1), db, store, methods())
  await expect(
    publish(
      join(directory, R2),
      db,
      store,
      methods({
        async chunk(id, table, after) {
          if (table === 'fiscal_lines')
            throw new Error('verification interrupted')
          return verifier.chunk(id, table, after)
        },
      })
    )
  ).rejects.toThrow('interrupted')
  expect(await resolveRelease(db)).toBe(R1)
  expect(objects.has(`releases/${R2}/manifest.json`)).toBe(false)
  await publish(join(directory, R2), db, store, methods())
  expect(await resolveRelease(db)).toBe(R2)
  expect(
    sqlite.query('SELECT count(*) AS count FROM fiscal_lines').get()
  ).toEqual({ count: 1002 })
})
test('API mismatch refuses publication and cannot be bypassed by a successful file transfer', async () => {
  await expect(
    publish(
      join(directory, R1),
      db,
      store,
      methods({
        async api(id, dataset, phase) {
          const result = await verifier.api(id, dataset, phase)
          return { ...result, total: { amount: 0, lineCount: 501 } }
        },
      })
    )
  ).rejects.toThrow('amounts or counts differ')
  expect(objects.has(`releases/${R1}/manifest.json`)).toBe(false)
  await expect(resolveRelease(db)).rejects.toMatchObject({
    code: 'UNAVAILABLE',
  })
})
test('activation failure keeps the API on the old version while finalized downloads remain available, and retry completes', async () => {
  await publish(join(directory, R1), db, store, methods())
  sqlite.exec(
    "CREATE TRIGGER fail_activation BEFORE UPDATE ON active_release BEGIN SELECT RAISE(ABORT,'activation interrupted'); END"
  )
  await expect(
    publish(join(directory, R2), db, store, methods())
  ).rejects.toThrow('activation interrupted')
  expect(await resolveRelease(db)).toBe(R1)
  await expect(resolveRelease(db, R2)).rejects.toMatchObject({
    code: 'RELEASE_EXPIRED',
  })
  expect(await verifier.downloads(R2)).toEqual({ files: 2 })
  sqlite.exec('DROP TRIGGER fail_activation')
  await publish(join(directory, R2), db, store, methods())
  expect(await resolveRelease(db)).toBe(R2)
  const manifest = await verifier.candidate(R1),
    text = objects.get(`releases/${R1}/manifest.json`)!
  await rollback(
    db,
    methods(),
    manifest,
    createHash('sha256').update(text).digest('hex')
  )
  expect(await resolveRelease(db)).toBe(R1)
  sqlite.run('UPDATE amounts SET value=999 WHERE release_id=?', [R2])
  await expect(
    rollback(
      db,
      methods(),
      await verifier.candidate(R2),
      createHash('sha256')
        .update(objects.get(`releases/${R2}/manifest.json`)!)
        .digest('hex')
    )
  ).rejects.toThrow('D1 contents differ')
  expect(await resolveRelease(db)).toBe(R1)
})
