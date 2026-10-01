import { beforeEach, afterEach, expect, test } from 'bun:test'
import { Database } from 'bun:sqlite'
import { readFile, mkdtemp, rm, mkdir } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import { sqliteD1 } from '../../apps/api/test/database'
import { resolveRelease, jurisdictions } from '../../apps/api/src/data/queries'
import download from '../../apps/download/src/index'
import type { R2Bucket } from '@fudoki/data-contracts'
import { fixture } from '../verify/fixture'
import {
  Verification,
  type HashStream,
  type VerificationEnv,
} from './verification'
import {
  publish as publishVerified,
  rollback,
  type Verifier,
  type ObjectStore,
} from './publish'

const R1 = 'r-' + '1'.repeat(32),
  R2 = 'r-' + '2'.repeat(32)
let directory: string,
  sqlite: Database,
  db: ReturnType<typeof sqliteD1>,
  objects: Map<string, Uint8Array<ArrayBuffer>>,
  verificationEnv: VerificationEnv,
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
  verificationEnv = {
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
  }
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
function verification(id: string) {
  return new Verification(
    verificationEnv,
    hashStream,
    JSON.parse(readFileSync(join(directory, id, 'verification.json'), 'utf8'))
  )
}
const manifestUrl =
  'https://raw.githubusercontent.com/wwwyo/fudoki/' +
  'a'.repeat(40) +
  '/pipeline/publish/manifest.json'
test('COFOG master is shared across releases and a conflicting definition cannot replace existing meanings', async () => {
  await publish(join(directory, R1), db, store, methods())
  await publish(join(directory, R2), db, store, methods())
  expect(
    sqlite.query('SELECT count(*) AS count FROM cofog_codes').get()
  ).toEqual({ count: 3 })
  expect(
    sqlite.query('SELECT count(*) AS count FROM fiscal_lines').get()
  ).toEqual({ count: 1002 })
  sqlite.run("UPDATE cofog_codes SET label='別の意味' WHERE code='09'")
  await expect(
    publish(join(directory, R1), db, store, methods())
  ).rejects.toThrow('COFOG master differs')
  expect(await resolveRelease(db)).toBe(R2)
})
function publish(
  candidate: string,
  db: ReturnType<typeof sqliteD1>,
  store: ObjectStore,
  verify: Verifier
) {
  return publishVerified(candidate, db, store, verify, manifestUrl)
}
function methods(overrides: Partial<Verifier> = {}): Verifier {
  return {
    existingFile: (id, path) => verification(id).existingFile(id, path),
    file: (id, path) => verification(id).file(id, path),
    chunk: (id, table, after) => verification(id).chunk(id, table, after),
    api: (id, dataset, phase) => verification(id).api(id, dataset, phase),
    publicContracts: (id) => verification(id).publicContracts(id),
    downloads: (id) => verification(id).downloads(id),
    download: (id, path) => verification(id).download(id, path),
    measure: (id) => verification(id).measure(id),
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
          if (++puts === 2) throw new Error('transfer interrupted')
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
          return verification(id).chunk(id, table, after)
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
test('another release with unchanged package contents does not upload package files again', async () => {
  const id = 'r-' + '3'.repeat(32)
  const next = await fixture(join(directory, id), id)
  await publish(join(directory, R1), db, store, methods())
  const uploaded: string[] = []
  await publish(
    join(directory, id),
    db,
    {
      async put(key, path, type) {
        uploaded.push(key)
        await store.put(key, path, type)
      },
    },
    methods()
  )
  expect(uploaded.some((key) => key.startsWith('fiscal/'))).toBe(false)
  expect(await resolveRelease(db)).toBe(id)
  expect((await verification(R1).candidate(R1)).packages).toEqual(next.packages)
  expect((await verification(id).download(id, next.files[0]!.path)).bytes).toBe(
    next.files[0]!.bytes
  )
})
test('publication evidence stays local and must be written before activation', async () => {
  const result = await publish(join(directory, R1), db, store, methods())
  const report = JSON.parse(await readFile(result.reportPath, 'utf8'))
  expect(report.stage).toBe('pre-activation-verified')
  expect(report.probes[0].amount).toBe(50100)
  expect(report.manifestUrl).toBe(manifestUrl)
  expect([...objects.keys()].every((key) => key.startsWith('fiscal/'))).toBe(
    true
  )
  await mkdir(join(directory, R2, 'publication-verification.json'))
  await expect(
    publish(join(directory, R2), db, store, methods())
  ).rejects.toThrow()
  expect(await resolveRelease(db)).toBe(R1)
  await rm(join(directory, R2, 'publication-verification.json'), {
    recursive: true,
  })
  await publish(join(directory, R2), db, store, methods())
  expect(await resolveRelease(db)).toBe(R2)
})
test('API mismatch refuses publication and cannot be bypassed by a successful file transfer', async () => {
  await expect(
    publish(
      join(directory, R1),
      db,
      store,
      methods({
        async api(id, dataset, phase) {
          const result = await verification(id).api(id, dataset, phase)
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
  expect(await verification(R2).downloads(R2)).toEqual({ files: 2 })
  sqlite.exec('DROP TRIGGER fail_activation')
  await publish(join(directory, R2), db, store, methods())
  expect(await resolveRelease(db)).toBe(R2)
  const manifest = await verification(R1).candidate(R1),
    text = await readFile(join(directory, R1, 'verification.json'))
  await rollback(
    db,
    methods(),
    manifest,
    createHash('sha256').update(text).digest('hex'),
    manifestUrl
  )
  expect(await resolveRelease(db)).toBe(R1)
  sqlite.run('UPDATE amounts SET value=999 WHERE release_id=?', [R2])
  await expect(
    rollback(
      db,
      methods(),
      await verification(R2).candidate(R2),
      createHash('sha256')
        .update(await readFile(join(directory, R2, 'verification.json')))
        .digest('hex'),
      manifestUrl
    )
  ).rejects.toThrow('D1 contents differ')
  expect(await resolveRelease(db)).toBe(R1)
})

test('a shared jurisdiction master is reused while old API metadata survives candidate failure, publication and rollback', async () => {
  await publish(join(directory, R1), db, store, methods())
  await fixture(join(directory, R2), R2, 200, 501, '新しい団体名')
  await expect(
    publish(
      join(directory, R2),
      db,
      store,
      methods({
        async chunk() {
          throw new Error('candidate interrupted')
        },
      })
    )
  ).rejects.toThrow('candidate interrupted')
  expect(await resolveRelease(db)).toBe(R1)
  expect((await jurisdictions(db, R1))[0]?.name).toBe('検証用の架空団体')
  expect(sqlite.query('SELECT name FROM jurisdictions').get()).toEqual({
    name: '新しい団体名',
  })
  await publish(join(directory, R2), db, store, methods())
  expect((await jurisdictions(db, R2))[0]?.name).toBe('新しい団体名')
  expect((await jurisdictions(db, R1))[0]?.name).toBe('検証用の架空団体')
  expect(
    sqlite.query('SELECT count(*) AS count FROM jurisdictions').get()
  ).toEqual({ count: 1 })
  expect(
    sqlite.query('SELECT count(*) AS count FROM release_jurisdictions').get()
  ).toEqual({ count: 2 })
  await rollback(
    db,
    methods(),
    await verification(R1).candidate(R1),
    createHash('sha256')
      .update(await readFile(join(directory, R1, 'verification.json')))
      .digest('hex'),
    manifestUrl
  )
  expect(await resolveRelease(db)).toBe(R1)
  expect((await jurisdictions(db, R1))[0]?.name).toBe('検証用の架空団体')
})
