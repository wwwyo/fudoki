import { expect, test } from 'bun:test'
import worker from './index'
import {
  TABLES,
  manifestSchema,
  type R2Bucket,
  type ReleaseManifest,
} from '@fudoki/data-contracts'
const releaseId = 'r-' + 'a'.repeat(32)
const file = 'fiscal/132195/expenditure.csv'
const body = 'value\n100\n'
const manifest: ReleaseManifest = manifestSchema.parse({
  schemaVersion: 1,
  releaseId,
  codeRevision: 'a'.repeat(40),
  inputFingerprint: 'b'.repeat(64),
  judgmentFingerprint: 'c'.repeat(64),
  queryFingerprint: 'e'.repeat(64),
  totals: [],
  files: [
    {
      path: file,
      sha256: 'd'.repeat(64),
      bytes: body.length,
      contentType: 'text/csv; charset=utf-8',
    },
  ],
  tables: Object.fromEntries(
    TABLES.map((table) => [
      table,
      {
        rows: 0,
        sha256: 'a'.repeat(64),
        canonicalSha256: 'a'.repeat(64),
        chunks: [],
      },
    ])
  ),
})
function storage(published: boolean) {
  const reads: string[] = []
  const bucket: R2Bucket = {
    async get(key) {
      reads.push(key)
      if (key.endsWith('/manifest.json') && !published) return null
      const value = key.endsWith('/manifest.json')
        ? JSON.stringify(manifest)
        : body
      return {
        key,
        size: value.length,
        httpEtag: '"r2-etag"',
        body: new Blob([value]).stream(),
        async json<T>() {
          return JSON.parse(value) as T
        },
        async arrayBuffer() {
          return new TextEncoder().encode(value).buffer
        },
        writeHttpMetadata() {},
      }
    },
    async head(key) {
      reads.push(key)
      return { size: body.length, httpEtag: '"r2-etag"' }
    },
    async list() {
      throw new Error('File downloads do not enumerate objects')
    },
  }
  return { bucket, reads }
}
const request = (path: string, method = 'GET') =>
  new Request(`https://download.example.org${path}`, { method })
test('candidate objects are inaccessible before their finalized public manifest exists', async () => {
  const { bucket, reads } = storage(false)
  const response = await worker.fetch(
    request(`/releases/${releaseId}/${file}`),
    { RELEASES: bucket }
  )
  expect(response.status).toBe(404)
  expect(reads).toEqual([`releases/${releaseId}/manifest.json`])
})
test('only listed files are served; internal objects and write methods are refused', async () => {
  const { bucket, reads } = storage(true)
  for (const path of [
    '/inputs/origin/sha256/x',
    `/releases/${releaseId}/api/amounts.jsonl`,
    `/releases/${releaseId}/fiscal/132195/unlisted.csv`,
  ])
    expect(
      (await worker.fetch(request(path), { RELEASES: bucket })).status
    ).toBe(404)
  expect(
    (
      await worker.fetch(request(`/releases/${releaseId}/${file}`, 'PUT'), {
        RELEASES: bucket,
      })
    ).status
  ).toBe(405)
  expect(reads.every((k) => k.endsWith('/manifest.json'))).toBe(true)
})
test('file body streams without arrayBuffer or json and exposes immutable hash and release headers', async () => {
  const { bucket } = storage(true),
    get = bucket.get
  bucket.get = async (key) => {
    const object = await get(key)
    if (object && !key.endsWith('/manifest.json')) {
      object.arrayBuffer = async () => {
        throw new Error('Do not buffer CSV')
      }
      object.json = async () => {
        throw new Error('Do not parse CSV')
      }
    }
    return object
  }
  const response = await worker.fetch(
    request(`/releases/${releaseId}/${file}`),
    { RELEASES: bucket }
  )
  expect(response.status).toBe(200)
  expect(await response.text()).toBe(body)
  expect(response.headers.get('ETag')).toBe('"' + 'd'.repeat(64) + '"')
  expect(response.headers.get('X-Fudoki-Release')).toBe(releaseId)
  expect(response.headers.get('Cache-Control')).toContain('immutable')
})
test('HEAD and conditional GET omit the file body', async () => {
  const { bucket, reads } = storage(true)
  expect(
    await (
      await worker.fetch(request(`/releases/${releaseId}/${file}`, 'HEAD'), {
        RELEASES: bucket,
      })
    ).text()
  ).toBe('')
  const conditional = request(`/releases/${releaseId}/${file}`)
  conditional.headers.set('if-none-match', '"' + 'd'.repeat(64) + '"')
  expect((await worker.fetch(conditional, { RELEASES: bucket })).status).toBe(
    304
  )
  expect(reads.filter((k) => k.endsWith('/expenditure.csv')).length).toBe(1)
})
