import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { jurisdictionSelectionsSchema } from './schema'
import { planArchives, planFiles } from './archive'

/** 手で選定結果を更新した後にも使える、自治体別ファイルの構造・参照検査。 */
export async function checkSelections(directory = import.meta.dir) {
  const files = (await readdir(directory)).filter(name => /^\d{6}\.json$/.test(name)).sort()
  if (!files.length) throw new Error('No jurisdiction selection files')
  const reports = []
  for (const file of files) {
    const ledger = jurisdictionSelectionsSchema.parse(JSON.parse(await readFile(join(directory, file), 'utf8')))
    if (ledger.jurisdiction !== file.slice(0, 6)) throw new Error(`Jurisdiction mismatch: ${file}`)
    const records = ledger.selections
    const archives = planArchives(records)
    reports.push({
      jurisdiction: file.slice(0, 6),
      targets: records.length,
      candidates: records.reduce((total, record) => total + record.candidates.length, 0),
      selected: records.filter(record => record.selected_candidate_id !== null).length,
      storage_slots: archives.length,
      selected_files: archives.reduce((total, group) => total + planFiles(group).length, 0),
      unresolved_candidates: ledger.unresolved_candidates.length,
    })
  }
  return reports
}

if (import.meta.main) {
  if (Bun.argv.slice(2).length) {
    console.error('Usage: bun pipeline/source_selection/check.ts')
    process.exitCode = 2
  } else checkSelections().then(result => console.log(JSON.stringify(result, null, 2))).catch(error => {
    console.error(JSON.stringify({ error: String(error) }))
    process.exitCode = 1
  })
}
