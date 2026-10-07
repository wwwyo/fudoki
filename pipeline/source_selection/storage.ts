import type { SourceTarget } from './schema'

export const ARCHIVE_BUCKET = 'fudoki-inputs' as const

/** 同じ団体・年度・資料区分は、会計・歳入／歳出をまたいで選定ファイルを共有する。 */
export function originObjectSlot(target: SourceTarget): string {
  const kind = target.document_kind === 'supplementary' ? `supplementary-${target.amendment_number}` : target.document_kind
  return `fiscal/source-selection/${target.jurisdiction}/${target.fiscal_year}/${kind}`
}

export function originObjectKey(target: SourceTarget, format: 'csv' | 'pdf', index?: number): string {
  return index === undefined ? `${originObjectSlot(target)}.${format}` : `${originObjectSlot(target)}-${index}.${format}`
}
