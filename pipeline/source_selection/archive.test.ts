import { createHash } from 'node:crypto'
import { expect, test } from 'bun:test'
import { archiveGroup, archiveSelected, isMissingR2ObjectError, planArchives, planFiles, isArchived, type ArchiveTransport } from './archive'
import { sourceSelectionsSchema, type SourceFile, type SourceSelection } from './schema'
import { originObjectKey } from './storage'

const body = new TextEncoder().encode('名称,金額\n事業,100\n')
const secondBody = new TextEncoder().encode('second part')
const hash = (value: Uint8Array) => createHash('sha256').update(value).digest('hex')
const csv: SourceFile = { scope: [{ account: '一般会計', direction: 'expenditure' }], download_url: 'https://example.com/budget.csv', format: 'csv', sha256: hash(body) }
const pdf: SourceFile = { download_url: 'https://example.com/first.pdf', format: 'pdf', pdf_type: 'text', sha256: hash(body), scope: [{ account: '一般会計', direction: 'expenditure', pages: [{ start: 1, end: 3 }] }] }
const second: SourceFile = { ...pdf, download_url: 'https://example.com/second.pdf', sha256: hash(secondBody) }
const selection: SourceSelection = { target: { jurisdiction: '132047', fiscal_year: 2024, document_kind: 'initial' }, candidates: [{ id: 'one', title: '令和6年度予算', landing_url: 'https://example.com/budget', inspected_at: '2026-10-07T00:00:00Z', files: [csv] }], selected_candidate_id: 'one', archive: null, reason: '必要な名称・金額を持つ資料' }
const withFiles = (files: SourceFile[]): SourceSelection => ({ ...selection, candidates: [{ ...selection.candidates[0]!, files }] })
function transport(previous: string[] = []) {
  const uploads: { key: string; body: Uint8Array; contentType: string }[] = []
  const removed: string[] = []
  const downloads: string[] = []
  const api: ArchiveTransport = {
    async download(url) { downloads.push(url); return { body: url.includes('second') ? secondBody : body, final_url: url } },
    async put(key, body, contentType) { uploads.push({ key, body, contentType }) },
    async list() { return previous },
    async remove(key) { removed.push(key) },
  }
  return { api, uploads, removed, downloads }
}

test('missing-object cleanup ignores only genuine key-not-found errors', () => {
  for (const error of ['[10007] The specified key does not exist.', 'HTTP status 404', 'NoSuchKey']) expect(isMissingR2ObjectError(error)).toBe(true)
  for (const error of ['HTTP 403', '[10007] Permission denied.', '[10000] The specified key does not exist.', 'Network timeout']) expect(isMissingR2ObjectError(error)).toBe(false)
})

test('unselected targets cause no transfer and uploaded receipts are trusted without readback', async () => {
  const fake = transport()
  const pending = { ...selection, selected_candidate_id: null, archive: null }
  expect(await archiveSelected(pending, fake.api)).toEqual(pending)
  expect(fake.downloads).toHaveLength(0)
  const result = await archiveSelected(selection, fake.api)
  expect(result.archive!.files).toEqual([{ key: 'fiscal/source-selection/132047/2024/initial.csv', sha256: csv.sha256!, final_url: csv.download_url }])
  expect(result.candidates[0]!.inspected_at).toBe(selection.candidates[0]!.inspected_at)
  expect(fake.removed).toEqual(['fiscal/source-selection/132047/2024/initial.pdf'])
  expect(await archiveSelected(result, fake.api)).toEqual(result)
  expect(fake.downloads).toHaveLength(1)
  expect(fake.uploads).toHaveLength(1)
  expect(sourceSelectionsSchema.safeParse([result]).success).toBe(true)
})

test('a split document shares one file across its content sections and uploads each physical file once', async () => {
  const fake = transport(['fiscal/source-selection/132047/2024/initial-1.pdf', 'fiscal/source-selection/132047/2024/initial-2.pdf'])
  const shared: SourceFile = { ...second, format: 'pdf', pdf_type: 'scan',
    scope: [{ account: '一般会計', direction: 'expenditure', pages: [{ start: 1, end: 3 }] },
      { account: '駐車場事業特別会計', direction: 'revenue', pages: [{ start: 8, end: 12 }] }] }
  const result = await archiveSelected(withFiles([pdf, shared]), fake.api)
  expect(fake.uploads).toHaveLength(2)
  expect(fake.downloads).toHaveLength(2)
  expect(new Set(fake.uploads.map(item => item.key))).toEqual(new Set(['fiscal/source-selection/132047/2024/initial-1.pdf', 'fiscal/source-selection/132047/2024/initial-2.pdf']))
  expect(result.candidates[0]!.files[1]!.scope).toEqual(shared.scope)
  expect(sourceSelectionsSchema.safeParse([result]).success).toBe(true)
})

test('all parts are checked before the first upload and a failed part cannot produce receipts', async () => {
  const fake = transport()
  await expect(archiveGroup([withFiles([pdf, { ...second, sha256: 'a'.repeat(64) }])], fake.api)).rejects.toThrow('Original changed')
  expect(fake.uploads).toHaveLength(0)
  const fail = transport()
  let puts = 0
  const input = withFiles([pdf, second])
  const before = structuredClone(input)
  await expect(archiveGroup([input], { ...fail.api, async put() { if (++puts === 2) throw new Error('upload failed') } })).rejects.toThrow('upload failed')
  expect(fail.removed).toHaveLength(0)
  expect(input).toEqual(before)
})

test('a smaller selection overwrites the current file and removes obsolete flat parts', async () => {
  const stale = ['fiscal/source-selection/132047/2024/initial-1.pdf', 'fiscal/source-selection/132047/2024/initial-2.pdf']
  const fake = transport(stale)
  await archiveSelected(selection, fake.api)
  expect(fake.uploads[0]!.key).toBe('fiscal/source-selection/132047/2024/initial.csv')
  expect(fake.removed).toEqual([...stale, 'fiscal/source-selection/132047/2024/initial.pdf'])
  expect(originObjectKey({ ...selection.target, document_kind: 'supplementary', amendment_number: 1 }, 'pdf', 2)).toBe('fiscal/source-selection/132047/2024/supplementary-1-2.pdf')
})

test('conflicting identities and metadata outside the slot stop before any transfer', async () => {
  const fake = transport()
  const conflicting = { ...withFiles([{ ...csv, sha256: 'a'.repeat(64) }]), target: { ...selection.target } }
  await expect(archiveGroup([selection, conflicting], fake.api)).rejects.toThrow()
  expect(fake.downloads).toHaveLength(0)
  const wrong = transport(['another/initial-1.pdf'])
  await expect(archiveSelected(selection, wrong.api)).rejects.toThrow('escaped')
  expect(wrong.uploads).toHaveLength(0)
  expect(wrong.removed).toHaveLength(0)
})

function additiveReplacement() {
  const thirdBody = new TextEncoder().encode('third retained part')
  const newBody = new TextEncoder().encode('new text PDF')
  const third: SourceFile = { ...pdf, download_url: 'https://example.com/third.pdf', sha256: hash(thirdBody) }
  const added: SourceFile = { ...pdf, download_url: 'https://example.com/new.pdf', sha256: hash(newBody) }
  const original = withFiles([pdf, second, third])
  const previous: SourceSelection = { ...original, selected_candidate_id: 'one', archive: { bucket: 'fudoki-inputs', candidate_id: 'one',
    archived_at: '2026-10-07T00:00:00Z', files: [pdf, second, third].map((file, index) => ({
      key: originObjectKey(original.target, 'pdf', index + 1), sha256: file.sha256!, final_url: file.download_url })) } }
  const replacement = withFiles([pdf, second, third, added])
  return { previous, replacement, newBody, added }
}

test('additive replacement retains three exact keys and bytes and puts only the fourth original', async () => {
  const { previous, replacement, newBody, added } = additiveReplacement()
  const oldObjects = new Map<string, Uint8Array>(previous.archive!.files.map((item, i) => [item.key, [body, secondBody, new TextEncoder().encode('third retained part')][i]!]))
  const oldBytes = structuredClone(oldObjects)
  const fake = transport([...oldObjects.keys()])
  const result = (await archiveGroup([replacement], { ...fake.api,
    async download(url) { fake.downloads.push(url); return { body: newBody, final_url: url } },
    async put(key, bytes, contentType) { fake.uploads.push({ key, body: bytes, contentType }); oldObjects.set(key, bytes) },
  }, previous))[0]!
  expect(fake.downloads).toEqual([added.download_url])
  expect(fake.uploads.map(item => item.key)).toEqual(['fiscal/source-selection/132047/2024/initial-4.pdf'])
  expect(fake.removed).toHaveLength(0)
  for (const [key, bytes] of oldBytes) expect(oldObjects.get(key)).toEqual(bytes)
  expect(result.archive!.files.slice(0, 3)).toEqual(previous.archive!.files)
  expect(planFiles([result]).map(item => item.key)).toEqual(planFiles([replacement], previous).map(item => item.key))
  expect(isArchived([result])).toBe(true)
  expect(sourceSelectionsSchema.safeParse([result]).success).toBe(true)
})

test('replacement collision, changed original, invalid target and retained format stop without altering either selection', async () => {
  for (const reason of ['collision', 'changed', 'target', 'format', 'upload']) {
    const { previous, replacement, newBody } = additiveReplacement()
    const other = structuredClone(selection)
    const before = structuredClone({ previous, replacement, other })
    const fake = transport(reason === 'collision' ? ['fiscal/source-selection/132047/2024/initial-4.pdf'] : [])
    const candidate = structuredClone(replacement)
    if (reason === 'target') candidate.target.fiscal_year++
    if (reason === 'format') candidate.candidates[0]!.files[0] = csv
    await expect(archiveGroup([candidate], { ...fake.api,
      async download(url) { fake.downloads.push(url); return { body: reason === 'changed' ? body : newBody, final_url: url } },
      async put() { throw new Error('upload failed') },
    }, previous)).rejects.toThrow()
    expect({ previous, replacement, other }).toEqual(before)
    expect(fake.uploads).toHaveLength(0)
    expect(fake.removed).toHaveLength(0)
    if (reason !== 'changed' && reason !== 'upload') expect(fake.downloads).toHaveLength(0)
  }
})

test('replacement next-part skips an unregistered fourth object and still refuses collisions and invalid numbers', async () => {
  const { previous, replacement, newBody, added } = additiveReplacement()
  const fourth = 'fiscal/source-selection/132047/2024/initial-4.pdf'
  const fifth = 'fiscal/source-selection/132047/2024/initial-5.pdf'
  const fake = transport([fourth])
  const api = { ...fake.api, async download(url: string) { fake.downloads.push(url); return { body: newBody, final_url: url } } }
  expect(planFiles([replacement], previous, 5).find(item => item.file.sha256 === added.sha256)!.key).toBe(fifth)
  const result = (await archiveGroup([replacement], api, previous, 5))[0]!
  expect(fake.uploads.map(item => item.key)).toEqual([fifth])
  expect(fake.removed).toHaveLength(0)
  expect(result.archive!.files.slice(0, 3)).toEqual(previous.archive!.files)
  expect(isArchived([result])).toBe(true)
  await expect(archiveGroup([replacement], { ...api, async list() { return [fourth, fifth] } }, previous, 5)).rejects.toThrow('refusing overwrite')
  expect(fake.downloads).toHaveLength(1)
  for (const value of [0, 3, 4.5, Number.MAX_SAFE_INTEGER + 1]) expect(() => planFiles([replacement], previous, value)).toThrow('next-part')
  expect(() => planFiles([replacement], undefined, 5)).toThrow('next-part')
})
