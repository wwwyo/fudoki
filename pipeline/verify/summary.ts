import { readFile, writeFile, appendFile } from 'node:fs/promises'
import { join } from 'node:path'
import { BUILD, LATEST } from '../paths'
import { verifyCandidate } from '../fdp/manifest'

if (!LATEST) throw new Error('A verified candidate is required')
const manifest = await verifyCandidate(
  join(BUILD, 'releases', LATEST.releaseId)
)
const summary = {
  releaseId: manifest.releaseId,
  inputFingerprint: manifest.inputFingerprint,
  codeRevision: manifest.codeRevision,
  files: manifest.files,
  tables: manifest.tables,
  totals: manifest.totals,
}
await writeFile(
  join(BUILD, 'review-summary.json'),
  JSON.stringify(summary, null, 2) + '\n'
)
if (process.env.GITHUB_STEP_SUMMARY)
  await appendFile(
    process.env.GITHUB_STEP_SUMMARY,
    `全量の固定入力から build 済み: ${manifest.releaseId}\n\n配布ファイル: ${manifest.files.length}、D1 行数: ${Object.values(manifest.tables).reduce((sum, table) => sum + table.rows, 0)}。内容ハッシュ・dataset/phase 別の件数と金額を artifact に記録。\n`
  )
console.log(
  JSON.stringify({
    path: 'pipeline/build/review-summary.json',
    releaseId: manifest.releaseId,
  })
)
