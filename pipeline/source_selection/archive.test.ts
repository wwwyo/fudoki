import { createHash } from 'node:crypto'
import { expect, test } from 'bun:test'
import { archiveGroup, archiveSelected, isMissingR2ObjectError, planArchives, type ArchiveTransport } from './archive'
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
  const fake = transport()
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
  await expect(archiveGroup([withFiles([pdf, second])], { ...fail.api, async put() { if (++puts === 2) throw new Error('upload failed') } })).rejects.toThrow('upload failed')
  expect(fail.removed).toHaveLength(0)
  expect(selection.archive).toBeNull()
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
