import { expect, test } from 'bun:test'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { SourceSelection } from '../source_selection/schema'
import { sha256 } from './lib/source'
import { prepareIngestion } from './selection'

test('archived split documents preserve target and physical expenditure scopes without changing the ledger', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'fudoki-ingestion-'))
  try {
    const bodies = [Buffer.from('first PDF fixture'), Buffer.from('second PDF fixture')]
    const hashes = bodies.map(sha256)
    const paths = bodies.map((_, index) => join(directory, `${index}.pdf`))
    await Promise.all(bodies.map((body, index) => writeFile(paths[index]!, body)))
    const selection: SourceSelection = {
      target: { jurisdiction: '132047', fiscal_year: 2024, document_kind: 'supplementary', amendment_number: 2 },
      candidates: [{
        id: 'parts', title: '分冊', landing_url: 'https://example.com/', inspected_at: '2026-10-07T00:00:00Z',
        files: hashes.map((sha256, index) => ({
          download_url: `https://example.com/${index}.pdf`, format: 'pdf', pdf_type: index === 0 ? 'text' : 'scan', sha256,
          scope: [{ account: index === 0 ? '一般会計' : '駐車場事業特別会計', direction: 'expenditure', pages: [{ start: 3, end: 8 }, { start: 10, end: 11 }] },
            { account: '一般会計', direction: 'revenue', pages: [{ start: 1, end: 2 }] }],
        })),
      }],
      selected_candidate_id: 'parts', reason: '分冊の範囲確認済み',
      archive: { bucket: 'fudoki-inputs', candidate_id: 'parts', archived_at: '2026-10-07T00:01:00Z',
        files: hashes.map((sha256, index) => ({ key: `fiscal/source-selection/132047/2024/supplementary-2-${index + 1}.pdf`, sha256, final_url: `https://example.com/${index}.pdf` })) },
    }
    const before = structuredClone(selection)
    const local = new Map(hashes.map((hash, index) => [hash, paths[index]!]))
    const request = await prepareIngestion(selection, local)
    expect(request.target).toEqual(selection.target)
    expect(request.files.map(file => file.pdf_type)).toEqual(['text', 'scan'])
    expect(request.files[1]!.scope).toEqual([selection.candidates[0]!.files[1]!.scope![0]!])
    expect(request.files[0]!.origin).toEqual({ key: selection.archive!.files[0]!.key,
      sha256: hashes[0]!, bucket: 'fudoki-inputs', bytes: bodies[0]!.length })
    expect(selection).toEqual(before)
    expect(await readFile(paths[0]!)).toEqual(bodies[0]!)
    expect(JSON.parse(JSON.stringify(request)).selection_ref).toBe('["132047",2024,"supplementary",2]')
    await expect(prepareIngestion({ ...selection, archive: null }, local)).rejects.toThrow('archived')
    await expect(prepareIngestion(selection, new Map([[hashes[0]!, paths[0]!]]))).rejects.toThrow('Missing local')
    await writeFile(paths[0]!, 'replaced object')
    await expect(prepareIngestion(selection, local)).rejects.toThrow('differs')
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test('revenue-only and unselected documents cannot enter expenditure ingestion', async () => {
  const selection: SourceSelection = {
    target: { jurisdiction: '132047', fiscal_year: 2024, document_kind: 'initial' },
    candidates: [], selected_candidate_id: null, archive: null, reason: '未選定',
  }
  await expect(prepareIngestion(selection, new Map())).rejects.toThrow('selected')
  const sha256 = 'a'.repeat(64)
  await expect(prepareIngestion({ ...selection, selected_candidate_id: 'csv',
    candidates: [{ id: 'csv', title: '歳入', landing_url: 'https://example.com/', inspected_at: '2026-10-07T00:00:00Z',
      files: [{ download_url: 'https://example.com/a.csv', format: 'csv', sha256,
        scope: [{ account: '一般会計', direction: 'revenue' }] }] }],
    archive: { bucket: 'fudoki-inputs', candidate_id: 'csv', archived_at: '2026-10-07T00:01:00Z',
      files: [{ key: 'fiscal/source-selection/132047/2024/initial.csv', sha256, final_url: 'https://example.com/a.csv' }] },
  }, new Map())).rejects.toThrow('no expenditure')
})
