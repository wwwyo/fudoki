import { createHash } from 'node:crypto'
import { createReadStream } from 'node:fs'
import { resolve } from 'node:path'
import { sourceSelectionsSchema, targetKey, type SourceSelection } from '../source_selection/schema'

/** 選定・保存済みの資料と、呼び出し側が用意したローカル原典を対応付ける。 */
export async function prepareIngestion(selection: SourceSelection, localFiles: ReadonlyMap<string, string>) {
  const checked = sourceSelectionsSchema.parse([selection])[0]!
  if (checked.selected_candidate_id === null || checked.archive === null) {
    throw new Error('Ingestion requires a selected and archived document')
  }
  const candidate = checked.candidates[0]!
  const files = []
  for (const [index, file] of candidate.files.entries()) {
    const scope = file.scope!.filter(content => content.direction === 'expenditure')
    if (!scope.length) continue
    const archived = checked.archive.files[index]!
    const localPath = localFiles.get(archived.sha256)
    if (!localPath) throw new Error(`Missing local original: ${archived.sha256}`)
    const path = resolve(localPath)
    const digest = createHash('sha256')
    let bytes = 0
    for await (const chunk of createReadStream(path)) {
      digest.update(chunk)
      bytes += chunk.length
    }
    if (digest.digest('hex') !== archived.sha256) {
      throw new Error(`Original differs from selected bytes: ${archived.sha256}`)
    }
    files.push({
      origin_id: archived.sha256,
      path,
      origin: { bucket: checked.archive.bucket, key: archived.key, sha256: archived.sha256, bytes },
      format: file.format,
      pdf_type: file.format === 'pdf' ? file.pdf_type : null,
      scope,
    })
  }
  if (!files.length) throw new Error('Selected document has no expenditure scope')
  return {
    selection_ref: targetKey(checked.target),
    target: checked.target,
    candidate_id: candidate.id,
    files,
  }
}
