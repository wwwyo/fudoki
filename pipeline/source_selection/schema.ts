import { z } from 'zod'
import { ARCHIVE_BUCKET, originObjectKey, originObjectSlot } from './storage'

const nonEmptyString = z.string().min(1).refine(value => value.trim().length > 0, { message: 'Blank text is not allowed' })
const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/)

/** 原典の会計名。団体固有の表記も保持する。 */
export const accountSchema = z.enum([
  '一般会計',
  '国民健康保険特別会計',
  '介護保険特別会計',
  '後期高齢者医療特別会計',
]).or(z.string().trim().min(1).refine(value => !/未確認|各会計/.test(value)))
export type Account = z.infer<typeof accountSchema>

/** 取り込み範囲を文字として読めるならtext。画像として読む必要があればscan。 */
export const pdfTypeSchema = z.enum(['text', 'scan'])
export type PdfType = z.infer<typeof pdfTypeSchema>

const targetFields = {
  jurisdiction: z.string().regex(/^\d{6}$/),
  fiscal_year: z.number().int().positive(),
}

/** 資料区分は金額の段階（phase）とは別。補正だけに原典の号数を持つ。 */
export const sourceTargetSchema = z.discriminatedUnion('document_kind', [
  z.object({ ...targetFields, document_kind: z.literal('initial') }).strict(),
  z.object({ ...targetFields, document_kind: z.literal('supplementary'), amendment_number: z.number().int().positive() }).strict(),
  z.object({ ...targetFields, document_kind: z.literal('settlement') }).strict(),
])
export type SourceTarget = z.infer<typeof sourceTargetSchema>

const candidateFields = {
  /** 同じ対象の候補一覧内で一意な参照用ID。 */
  id: nonEmptyString,
  title: nonEmptyString,
  landing_url: z.httpUrl(),
  /** 選定用の情報を確認した日時。本文の全量確認とは別。 */
  inspected_at: z.iso.datetime({ offset: true }),
}

/** 1始まりの物理PDF頁。startとendの両方を含む。印字された頁番号とは別。 */
export const pageRangeSchema = z.object({
  start: z.number().int().positive(),
  end: z.number().int().positive(),
}).strict().refine(range => range.start <= range.end, { message: 'Page range start exceeds end' })
export type PageRange = z.infer<typeof pageRangeSchema>

export const pdfScopeSchema = z.array(pageRangeSchema).min(1).refine(
  ranges => ranges.every((range, index) => index === 0 || range.start > ranges[index - 1]!.end),
  { message: 'Page ranges must be ascending and non-overlapping' },
)

const contentFields = {
  account: accountSchema,
  direction: z.enum(['expenditure', 'revenue']),
}
const uniqueContents = (items: { account: string; direction: string }[]) =>
  new Set(items.map(item => JSON.stringify([item.account, item.direction]))).size === items.length

/** CSVに含まれる会計・お金の向き。会計名は原典の表記。 */
export const csvScopeSchema = z.array(z.object(contentFields).strict()).min(1)
  .refine(uniqueContents, { message: 'Duplicate file content' })

/** PDFの会計・お金の向きごとの物理頁範囲。 */
export const pdfContentsSchema = z.array(z.object({
  ...contentFields,
  pages: pdfScopeSchema,
}).strict()).min(1).refine(uniqueContents, { message: 'Duplicate file content' })

const fileFields = {
  download_url: z.httpUrl(),
  sha256: sha256Schema.nullable(),
}

export const sourceFileSchema = z.discriminatedUnion('format', [
  z.object({ ...fileFields, format: z.literal('csv'), scope: csvScopeSchema.nullable() }).strict(),
  z.object({ ...fileFields, format: z.literal('pdf'), pdf_type: pdfTypeSchema, scope: pdfContentsSchema.nullable() }).strict(),
])
export type SourceFile = z.infer<typeof sourceFileSchema>

export const sourceCandidateSchema = z.object({
  ...candidateFields,
  files: z.array(sourceFileSchema).min(1),
}).strict().superRefine((candidate, ctx) => {
  const urls = new Set<string>()
  const hashes = new Set<string>()
  for (const [index, file] of candidate.files.entries()) {
    if (urls.has(file.download_url) || (file.sha256 !== null && hashes.has(file.sha256))) {
      ctx.addIssue({ code: 'custom', path: ['files', index], message: 'Duplicate candidate file' })
    }
    urls.add(file.download_url)
    if (file.sha256 !== null) hashes.add(file.sha256)
  }
})
export type SourceCandidate = z.infer<typeof sourceCandidateSchema>

/** 原典対象の情報が不足している候補。対象を確定してから選定一覧へ移す。 */
export const unresolvedCandidatesSchema = z.array(z.object({
  candidate: sourceCandidateSchema,
  missing: z.array(z.enum(['fiscal_year', 'document_kind', 'amendment_number'])).min(1)
    .refine(fields => new Set(fields).size === fields.length, { message: 'Missing fields must be unique' }),
  reason: nonEmptyString,
}).strict()).superRefine((records, ctx) => {
  const seen = new Set<string>()
  for (const [index, record] of records.entries()) {
    const key = record.candidate.id
    if (seen.has(key)) ctx.addIssue({ code: 'custom', path: [index, 'candidate', 'id'], message: 'Duplicate unresolved candidate' })
    seen.add(key)
  }
})
export type UnresolvedCandidate = z.infer<typeof unresolvedCandidatesSchema>[number]

/** R2へのアップロードが成功した原典。取得は本文の検査日時を変更しない。 */
export const archivedOriginSchema = z.object({
  bucket: z.literal(ARCHIVE_BUCKET),
  candidate_id: nonEmptyString,
  files: z.array(z.object({
    key: nonEmptyString,
    sha256: sha256Schema,
    final_url: z.httpUrl(),
  }).strict()).min(1),
  archived_at: z.iso.datetime({ offset: true }),
}).strict()
export type ArchivedOrigin = z.infer<typeof archivedOriginSchema>

const selectionFields = {
  target: sourceTargetSchema,
  candidates: z.array(sourceCandidateSchema),
  /** 選定理由または未確定理由。判断に必要な情報と不足を残す。 */
  reason: nonEmptyString,
}

export const sourceSelectionSchema = z.union([
  z.object({ ...selectionFields, selected_candidate_id: z.null(), archive: z.null() }).strict(),
  z.object({ ...selectionFields, candidates: z.array(sourceCandidateSchema).length(1), selected_candidate_id: nonEmptyString, archive: archivedOriginSchema.nullable() }).strict(),
])
export type SourceSelection = z.infer<typeof sourceSelectionSchema>

export const sourceSelectionsSchema = z.array(sourceSelectionSchema).superRefine((selections, ctx) => {
  const targets = new Set<string>()
  for (const [index, selection] of selections.entries()) {
    const key = targetKey(selection.target)
    if (targets.has(key)) ctx.addIssue({ code: 'custom', path: [index, 'target'], message: 'Duplicate target' })
    targets.add(key)
    const ids = selection.candidates.map(candidate => candidate.id)
    if (new Set(ids).size !== ids.length) ctx.addIssue({ code: 'custom', path: [index, 'candidates'], message: 'Duplicate candidate ID' })
    if (selection.selected_candidate_id !== null && !ids.includes(selection.selected_candidate_id)) {
      ctx.addIssue({ code: 'custom', path: [index, 'selected_candidate_id'], message: 'Selected candidate is missing' })
    }
    const selectedIndex = selection.candidates.findIndex(candidate => candidate.id === selection.selected_candidate_id)
    const selected = selection.candidates[selectedIndex]
    for (const [fileIndex, file] of (selected?.files ?? []).entries()) {
      if (file.sha256 === null) {
        ctx.addIssue({ code: 'custom', path: [index, 'candidates', selectedIndex, 'files', fileIndex, 'sha256'], message: 'Selected file needs inspected byte identity' })
      }
      if (file.scope === null) {
        ctx.addIssue({ code: 'custom', path: [index, 'candidates', selectedIndex, 'files', fileIndex, 'scope'], message: 'Selected file needs an ingestion content scope' })
      }
    }
    if (selection.archive) {
      const receipt = selection.archive
      if (!selected || receipt.candidate_id !== selected.id || receipt.files.length !== selected.files.length) {
        ctx.addIssue({ code: 'custom', path: [index, 'archive'], message: 'Archive differs from the selected candidate' })
      } else {
        const keys = new Set<string>()
        for (const [fileIndex, file] of selected.files.entries()) {
          const saved = receipt.files[fileIndex]!
          const numberedPrefix = originObjectSlot(selection.target) + '-'
          const suffix = saved.key.startsWith(numberedPrefix) ? saved.key.slice(numberedPrefix.length) : ''
          const numbered = new RegExp(`^[1-9]\\d*\\.${file.format}$`).test(suffix)
          const single = selected.files.length === 1 && saved.key === originObjectKey(selection.target, file.format)
          if ((!single && !numbered) || saved.sha256 !== file.sha256 || keys.has(saved.key)) {
            ctx.addIssue({ code: 'custom', path: [index, 'archive', 'files', fileIndex], message: 'Archive differs from the selected target or file' })
          }
          keys.add(saved.key)
        }
      }
    }
  }
})

/** ファイルや列挙順によらない原典対象の識別。 */
export function targetKey(target: SourceTarget): string {
  return JSON.stringify([
    target.jurisdiction, target.fiscal_year, target.document_kind,
    target.document_kind === 'supplementary' ? target.amendment_number : null,
  ])
}

/** 1自治体の選定と対象未確定の候補をまとめる。 */
export const jurisdictionSelectionsSchema = z.object({
  jurisdiction: z.string().regex(/^\d{6}$/),
  name: nonEmptyString,
  official_url: z.httpUrl(),
  selections: sourceSelectionsSchema,
  unresolved_candidates: unresolvedCandidatesSchema,
}).strict().superRefine((file, ctx) => {
  for (const [index, selection] of file.selections.entries()) {
    if (selection.target.jurisdiction !== file.jurisdiction) {
      ctx.addIssue({ code: 'custom', path: ['selections', index, 'target', 'jurisdiction'], message: 'Target belongs to another jurisdiction' })
    }
  }
})
export type JurisdictionSelections = z.infer<typeof jurisdictionSelectionsSchema>
