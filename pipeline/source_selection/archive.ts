import { createHash, randomUUID } from 'node:crypto'
import { mkdtemp, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { jurisdictionSelectionsSchema, sourceSelectionsSchema, targetKey, type SourceFile, type SourceSelection } from './schema'
import { ARCHIVE_BUCKET, originObjectKey, originObjectSlot } from './storage'

const MAX_BYTES = 300_000_000
const digest = (body: Uint8Array) => createHash('sha256').update(body).digest('hex')

async function saveSelections(path: string, data: unknown) {
  const temporary = `${path}.${randomUUID()}.tmp`
  try {
    await writeFile(temporary, JSON.stringify(data, null, 2) + '\n')
    await rename(temporary, path)
  } finally { await rm(temporary, { force: true }) }
}

export type ArchiveTransport = {
  download(url: string): Promise<{ body: Uint8Array; final_url: string }>
  put(key: string, body: Uint8Array, contentType: string): Promise<void>
  list(prefix: string): Promise<string[]>
  remove(key: string): Promise<void>
}

/** 同じ保存範囲のファイルを、確認済みバイト列ごとに共有する。 */
export function planFiles(group: SourceSelection[], previous?: SourceSelection, nextPart?: number): { file: SourceFile; key: string }[] {
  if (!group.length) throw new Error('Empty archive group')
  sourceSelectionsSchema.parse(group)
  const slot = originObjectSlot(group[0]!.target)
  const byHash = new Map<string, SourceFile>()
  const urls = new Map<string, string>()
  for (const selection of group) {
    if (selection.selected_candidate_id === null || originObjectSlot(selection.target) !== slot) throw new Error('Expected one selected document group')
    const candidate = selection.candidates.find(item => item.id === selection.selected_candidate_id)!
    for (const file of candidate.files) {
      if (file.sha256 === null) throw new Error('Selected file needs inspected byte identity')
      const previous = urls.get(file.download_url)
      if (previous && previous !== file.sha256) throw new Error('Conflicting byte identities for the same URL')
      urls.set(file.download_url, file.sha256)
      const same = byHash.get(file.sha256)
      if (same && same.format !== file.format) throw new Error('Conflicting formats for the same bytes')
      if (!same || file.download_url < same.download_url) byHash.set(file.sha256, file)
    }
  }
  const files = [...byHash.values()].sort((a, b) => a.sha256!.localeCompare(b.sha256!))
  const receipts = retainedReceipts(group, previous)
  const highest = Math.max(0, ...[...receipts.values()].map(item => Number(item.key.slice(slot.length).match(/^-(\d+)\./)?.[1] ?? 0)))
  if (nextPart !== undefined && (!previous || !Number.isSafeInteger(nextPart) || nextPart <= highest || !files.some(file => !receipts.has(file.sha256!)))) {
    throw new Error('next-part requires new replacement bytes and an integer above the saved part numbers')
  }
  let next = nextPart === undefined ? highest : nextPart - 1
  const planned = files.map((file, index) => ({ file, key: receipts.get(file.sha256!)?.key ?? originObjectKey(
    group[0]!.target, file.format, receipts.size ? ++next : files.length === 1 ? undefined : index + 1) }))
  const keys = planned.map(item => item.key)
  if (new Set(keys).size !== keys.length) throw new Error('Duplicate planned original key')
  // Validate the future receipt before performing any transfer (including single-key/part changes).
  for (const selection of group) {
    const candidate = selection.candidates.find(item => item.id === selection.selected_candidate_id)!
    sourceSelectionsSchema.parse([{ ...selection, archive: { bucket: ARCHIVE_BUCKET, candidate_id: candidate.id,
      archived_at: new Date().toISOString(), files: candidate.files.map(file => ({ key: planned.find(item => item.file.sha256 === file.sha256)!.key,
        sha256: file.sha256!, final_url: file.download_url })) } }])
  }
  return planned
}

function retainedReceipts(group: SourceSelection[], previous?: SourceSelection) {
  if (previous) {
    sourceSelectionsSchema.parse([previous])
    if (group.length !== 1 || targetKey(previous.target) !== targetKey(group[0]!.target) || !previous.archive) {
      throw new Error('Replacement requires the same archived target')
    }
  }
  const receipts = new Map<string, { key: string; sha256: string; final_url: string }>()
  const keys = new Set<string>()
  const formats = new Map<string, string>()
  for (const selection of [...group, ...(previous ? [previous] : [])]) {
    const candidate = selection.candidates.find(item => item.id === selection.selected_candidate_id)
    for (const file of candidate?.files ?? []) {
      const format = formats.get(file.sha256!)
      if (format && format !== file.format) throw new Error('Conflicting formats for retained bytes')
      formats.set(file.sha256!, file.format)
    }
    for (const receipt of selection.archive?.files ?? []) {
      const saved = receipts.get(receipt.sha256)
      if (saved && saved.key !== receipt.key) throw new Error('Conflicting retained keys for the same bytes')
      if (!saved && keys.has(receipt.key)) throw new Error('Duplicate retained original key')
      keys.add(receipt.key)
      receipts.set(receipt.sha256, receipt)
    }
  }
  if (previous) {
    const selected = group[0]!.candidates.find(item => item.id === group[0]!.selected_candidate_id)!
    const hashes = new Set(selected.files.map(file => file.sha256))
    if (previous.archive!.files.some(receipt => !hashes.has(receipt.sha256))) throw new Error('Replacement must retain previously archived files')
  }
  return receipts
}

export function planArchives(selections: SourceSelection[]): SourceSelection[][] {
  sourceSelectionsSchema.parse(selections)
  const groups = selections.filter(selection => selection.selected_candidate_id !== null).map(selection => [selection])
  for (const group of groups) planFiles(group)
  return groups
}

export function isArchived(group: SourceSelection[], previous?: SourceSelection, nextPart?: number): boolean {
  const keys = new Map(planFiles(group, previous, nextPart).map(item => [item.file.sha256!, item.key]))
  return group.every(selection => {
    if (selection.selected_candidate_id === null || selection.archive === null) return false
    const candidate = selection.candidates.find(item => item.id === selection.selected_candidate_id)!
    return selection.archive.candidate_id === candidate.id && selection.archive.files.length === candidate.files.length &&
      candidate.files.every((file, index) => selection.archive!.files[index]!.sha256 === file.sha256 && selection.archive!.files[index]!.key === keys.get(file.sha256!))
  })
}

export async function archiveSelected(selection: SourceSelection, transport: ArchiveTransport): Promise<SourceSelection> {
  sourceSelectionsSchema.parse([selection])
  if (selection.selected_candidate_id === null) return selection
  return (await archiveGroup([selection], transport))[0]!
}

/** 全ファイルの取得内容を照合し、アップロードと不要ファイルの削除が成功してから記録する。 */
export async function archiveGroup(group: SourceSelection[], transport: ArchiveTransport, previous?: SourceSelection, nextPart?: number): Promise<SourceSelection[]> {
  const groups = planArchives(group)
  if (groups.length !== 1 || groups[0]!.length !== group.length) throw new Error('Expected one selected document group')
  if (isArchived(group, previous, nextPart)) return group
  const planned = planFiles(group, previous, nextPart)
  const retained = retainedReceipts(group, previous)
  const prefix = originObjectSlot(group[0]!.target) + '-'
  const previousKeys = await transport.list(prefix)
  if (previousKeys.some(key => !key.startsWith(prefix))) throw new Error('Object listing escaped the requested prefix')
  if (previous && planned.some(item => !retained.has(item.file.sha256!) && previousKeys.includes(item.key))) throw new Error('New original key already exists; refusing overwrite')
  const directory = await mkdtemp(join(tmpdir(), 'fudoki-origin-parts-'))
  try {
    const downloaded = []
    for (const item of planned) {
      if (retained.has(item.file.sha256!)) continue
      const response = await transport.download(item.file.download_url)
      if (digest(response.body) !== item.file.sha256) throw new Error(`Original changed; inspect and reselect before archiving: ${item.file.download_url}`)
      if (response.body.byteLength > MAX_BYTES) throw new Error('Original exceeds the cf upload size limit')
      const path = join(directory, String(downloaded.length))
      await writeFile(path, response.body)
      downloaded.push({ ...item, path, final_url: response.final_url })
    }
    for (const item of downloaded) await transport.put(item.key, await readFile(item.path), item.file.format === 'pdf' ? 'application/pdf' : 'text/csv')
    const keep = new Set(planned.map(item => item.key))
    const oldKeys = new Set([...previousKeys, originObjectKey(group[0]!.target, 'csv'), originObjectKey(group[0]!.target, 'pdf')])
    if (!previous) for (const key of oldKeys) if (!keep.has(key)) await transport.remove(key)
    const saved = new Map([...retained, ...downloaded.map(item => [item.file.sha256!, { key: item.key, sha256: item.file.sha256!, final_url: item.final_url }] as const)])
    const archived_at = new Date().toISOString()
    const result = group.filter(selection => selection.selected_candidate_id !== null).map(selection => {
      const candidate = selection.candidates.find(item => item.id === selection.selected_candidate_id)!
      return { ...selection, archive: { bucket: ARCHIVE_BUCKET, candidate_id: candidate.id, files: candidate.files.map(file => saved.get(file.sha256!)!), archived_at } }
    })
    sourceSelectionsSchema.parse(result)
    return result
  } finally { await rm(directory, { recursive: true, force: true }) }
}

export function isMissingR2ObjectError(stderr: string): boolean {
  return /(?:HTTP(?: status)?[ :]+404|404 Not Found|"status"\s*:\s*404|NoSuchKey|\[10007\]\s+The specified key does not exist\.)/i.test(stderr)
}

async function runCf(args: string[], allowMissing = false, capture = false): Promise<string> {
  const process = Bun.spawn(['cf', 'r2', 'objects', ...args, '--bucket-name', ARCHIVE_BUCKET, '--quiet'], {
    stdout: capture ? 'pipe' : 'ignore', stderr: 'pipe',
  })
  const [stderr, stdout, status] = await Promise.all([
    new Response(process.stderr).text(), capture ? new Response(process.stdout).text() : Promise.resolve(''), process.exited,
  ])
  if (status !== 0 && !(allowMissing && isMissingR2ObjectError(stderr))) throw new Error(`cf R2 ${args[0]} failed (exit ${status})`)
  return stdout
}

const cfTransport: ArchiveTransport = {
  async download(url) {
    const response = await fetch(url, { signal: AbortSignal.timeout(120_000) })
    if (!response.ok || !response.body) throw new Error(`Original download failed (HTTP ${response.status})`)
    const reader = response.body.getReader()
    const chunks: Uint8Array[] = []
    let size = 0
    try {
      for (;;) {
        const chunk = await reader.read()
        if (chunk.done) break
        size += chunk.value.byteLength
        if (size > MAX_BYTES) throw new Error('Original exceeds the cf upload size limit')
        chunks.push(chunk.value)
      }
    } finally { await reader.cancel() }
    const body = new Uint8Array(size)
    let offset = 0
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength }
    return { body, final_url: response.url }
  },
  async put(key, body, contentType) {
    const directory = await mkdtemp(join(tmpdir(), 'fudoki-origin-'))
    try {
      const path = join(directory, 'origin')
      await writeFile(path, body)
      await runCf(['put', key, '--file', path, '--content-type', contentType])
    } finally { await rm(directory, { recursive: true, force: true }) }
  },
  async list(prefix) {
    const keys: string[] = []
    let after: string | undefined
    for (;;) {
      const args = ['list', '--prefix', prefix, '--per-page', '1000']
      if (after) args.push('--start-after', after)
      const page: unknown = JSON.parse(await runCf(args, false, true))
      if (!Array.isArray(page) || page.some(item => typeof item?.key !== 'string')) throw new Error('Invalid cf object metadata response')
      const current: string[] = page.map(item => item.key).sort()
      if (current.some(key => !key.startsWith(prefix) || (after !== undefined && key <= after))) throw new Error('Invalid object listing boundary')
      keys.push(...current)
      if (current.length < 1000) return keys
      after = current.at(-1)!
    }
  },
  async remove(key) { await runCf(['delete', key, '--force'], true) },
}

async function main(args: string[]) {
  if (args.includes('--help')) {
    console.log('Usage: bun pipeline/source_selection/archive.ts [--write] [--jurisdiction CODE] [--replacement-selection JSON] [--next-part N]\nDefault: read-only selected-original plan. JSON is a file containing one existing source-selection schema object with archive:null. Replacement retains the same target\'s saved files and keys, uploads only new bytes at the next part number, and saves the selection after all receipts succeed; it never deletes old objects. Optional --next-part requires replacement and sets the first new part number above all saved receipt numbers; plan and write use the same argument, and existing objects still cause an error. Without replacement, --write preserves the existing archive flow. No readback.')
    return
  }
  let write = false
  let jurisdiction: string | undefined
  let replacementPath: string | undefined
  let nextPart: number | undefined
  for (let index = 0; index < args.length; index++) {
    if (args[index] === '--write' && !write) write = true
    else if (args[index] === '--jurisdiction' && /^\d{6}$/.test(args[index + 1] ?? '') && !jurisdiction) jurisdiction = args[++index]
    else if (args[index] === '--replacement-selection' && args[index + 1] && !replacementPath) replacementPath = args[++index]
    else if (args[index] === '--next-part' && /^[1-9]\d*$/.test(args[index + 1] ?? '') && nextPart === undefined) nextPart = Number(args[++index])
    else throw new Error(`Unknown or incomplete argument: ${args[index]}`)
  }
  if (nextPart !== undefined && (!replacementPath || !Number.isSafeInteger(nextPart))) throw new Error('next-part requires replacement and a positive safe integer')
  const replacement = replacementPath ? sourceSelectionsSchema.parse([JSON.parse(await readFile(replacementPath, 'utf8'))])[0]! : undefined
  if (replacement) {
    if (replacement.selected_candidate_id === null || replacement.archive !== null) throw new Error('Replacement must be selected with archive:null')
    if (jurisdiction && jurisdiction !== replacement.target.jurisdiction) throw new Error('Replacement jurisdiction differs from requested jurisdiction')
    jurisdiction = replacement.target.jurisdiction
  }
  const names = (await readdir(import.meta.dir)).filter(name => /^\d{6}\.json$/.test(name) && (!jurisdiction || name === `${jurisdiction}.json`)).sort()
  if (!names.length) throw new Error('No matching jurisdiction file')
  const files = await Promise.all(names.map(async name => ({
    path: join(import.meta.dir, name),
    data: jurisdictionSelectionsSchema.parse(JSON.parse(await readFile(join(import.meta.dir, name), 'utf8'))),
  })))
  const selected = files.flatMap(file => file.data.selections.filter(selection => selection.selected_candidate_id !== null))
  // 全件の宣言・保存先の衝突を検査してから、最初の取得・上書きを始める。
  let groups = planArchives(files.flatMap(file => file.data.selections))
  for (const file of files) if (`${file.data.jurisdiction}.json` !== file.path.split('/').at(-1)) throw new Error(`Jurisdiction differs from file: ${file.path}`)
  const locations = new Map(files.flatMap(file => file.data.selections.map((selection, index) => [selection, { file, index }] as const)))
  let previous: SourceSelection | undefined
  if (replacement) {
    previous = selected.find(selection => targetKey(selection.target) === targetKey(replacement.target))
    if (!previous) throw new Error('Replacement target is absent from the current selected registry')
    const location = locations.get(previous)!
    planFiles([replacement], previous, nextPart)
    locations.set(replacement, location)
    groups = [[replacement]]
  }
  let archived = 0
  let uploadedFiles = 0
  let skipped = 0
  if (write) {
    for (const group of groups) {
      if (isArchived(group, previous, nextPart)) { skipped++; continue }
      const touched = new Set(group.map(selection => locations.get(selection)!.file))
      // 書き換えが完了するまで保存記録を無効にする。
      if (!previous) for (const selection of group) {
        const { file, index } = locations.get(selection)!
        file.data.selections[index] = { ...selection, archive: null }
      }
      if (!previous) for (const file of touched) await saveSelections(file.path, file.data)
      const results = await archiveGroup(group, cfTransport, previous, nextPart)
      for (const [offset, selection] of group.entries()) {
        const { file, index } = locations.get(selection)!
        file.data.selections[index] = results[offset]!
      }
      for (const file of touched) {
        jurisdictionSelectionsSchema.parse(file.data)
        await saveSelections(file.path, file.data)
      }
      archived++
      uploadedFiles += planFiles(group, previous, nextPart).filter(item => !retainedReceipts(group, previous).has(item.file.sha256!)).length
      console.error(JSON.stringify({ archived, slot: originObjectSlot(group[0]!.target), files: planFiles(group, previous, nextPart).length, targets: group.length }))
    }
  }
  console.log(JSON.stringify({ mode: write ? 'write' : 'plan', bucket: ARCHIVE_BUCKET, selected_targets: replacement ? 1 : selected.length, selected_files: groups.reduce((n, group) => n + planFiles(group, previous, nextPart).length, 0), storage_slots: groups.length, uploaded_files: uploadedFiles, skipped_slots: skipped, objects: groups.map(group => ({ targets: group.length, keys: planFiles(group, previous, nextPart).map(item => item.key) })) }, null, 2))
}

if (import.meta.main) main(Bun.argv.slice(2)).catch(error => { console.error(JSON.stringify({ error: String(error) })); process.exitCode = 1 })
