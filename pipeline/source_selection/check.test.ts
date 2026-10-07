import { expect, test } from 'bun:test'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { checkSelections } from './check'
import type { JurisdictionSelections, SourceCandidate } from './schema'

test('selection checks work with municipality files alone and reject a mismatched filename', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'fudoki-selection-check-'))
  const candidate: SourceCandidate = {
    id: 'csv', title: '一般会計歳出', landing_url: 'https://example.com/budget',
    inspected_at: '2026-10-07T00:00:00Z',
    files: [{ download_url: 'https://example.com/budget.csv', sha256: 'a'.repeat(64), format: 'csv', scope: [{ account: '一般会計', direction: 'expenditure' }] }],
  }
  const ledger: JurisdictionSelections = {
    jurisdiction: '132241', name: '多摩市', official_url: 'https://www.city.tama.lg.jp/',
    selections: [{
      target: { jurisdiction: '132241', fiscal_year: 2023, document_kind: 'initial' },
      candidates: [candidate], selected_candidate_id: candidate.id, archive: null, reason: '単独で必要な情報を持つ。',
    }],
    unresolved_candidates: [{ candidate: { ...candidate, id: 'unknown' }, missing: ['fiscal_year'], reason: '会計が未確定。' }],
  }
  try {
    await writeFile(join(directory, '132241.json'), JSON.stringify(ledger))
    expect(await checkSelections(directory)).toEqual([{
      jurisdiction: '132241', targets: 1, candidates: 1, selected: 1,
      storage_slots: 1, selected_files: 1, unresolved_candidates: 1,
    }])
    await rm(join(directory, '132241.json'))
    await writeFile(join(directory, '132047.json'), JSON.stringify(ledger))
    await expect(checkSelections(directory)).rejects.toThrow('Jurisdiction mismatch')
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test('upload receipts must map every file to its planned flat key', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'fudoki-selection-keys-'))
  const files = ['a', 'b'].map(value => ({
    download_url: `https://example.com/${value}.csv`, sha256: value.repeat(64), format: 'csv' as const,
    scope: [{ account: '一般会計', direction: 'expenditure' as const }],
  }))
  const ledger = {
    jurisdiction: '132241', name: '多摩市', official_url: 'https://www.city.tama.lg.jp/', unresolved_candidates: [],
    selections: [{
      target: { jurisdiction: '132241', fiscal_year: 2023, document_kind: 'initial' },
      candidates: [{ id: 'csv', title: '予算', landing_url: 'https://example.com/budget', inspected_at: '2026-10-07T00:00:00Z', files }],
      selected_candidate_id: 'csv', reason: '必要な分冊。',
      archive: { bucket: 'fudoki-inputs', candidate_id: 'csv', archived_at: '2026-10-07T00:01:00Z', files: files.map((file, index) => ({
        key: `fiscal/source-selection/132241/2023/initial-${index + 1}.csv`, sha256: file.sha256, final_url: file.download_url,
      })) },
    }],
  }
  const path = join(directory, '132241.json')
  try {
    await writeFile(path, JSON.stringify(ledger))
    expect((await checkSelections(directory))[0]!.selected).toBe(1)
    for (const indices of [[2, 1], [1, 7]]) {
      const invalid = structuredClone(ledger)
      invalid.selections[0]!.archive.files.forEach((file, index) => { file.key = `fiscal/source-selection/132241/2023/initial-${indices[index]}.csv` })
      await writeFile(path, JSON.stringify(invalid))
      await expect(checkSelections(directory)).rejects.toThrow('Archive key differs')
    }
  } finally { await rm(directory, { recursive: true, force: true }) }
})
