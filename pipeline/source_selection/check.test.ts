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
