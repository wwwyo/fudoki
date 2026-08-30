/**
 * AIP-160 の部分集合のパーサ。`field = value` を `AND` でつなぐ形だけを受ける。
 * 対応フィールドは4つ。文法とフィールドの拡張は contract の説明文と同時に行うこと。
 */

export type ParsedFilter = {
  jurisdiction?: string
  fiscalYear?: string
  direction?: 'expenditure' | 'revenue'
  phase?: string
  cofogDivision?: string
  cofogGroup?: string
  cofogClass?: string
}

export class FilterSyntaxError extends Error {}

const FIELDS: Record<string, keyof ParsedFilter> = {
  'jurisdiction': 'jurisdiction',
  'fiscalYear': 'fiscalYear',
  'direction': 'direction',
  'phase': 'phase',
  'cofog.division': 'cofogDivision',
  'cofog.group': 'cofogGroup',
  'cofog.class': 'cofogClass',
}

/** `a = "x" AND b = 1` を分解する。未対応の文法・フィールド・重複は FilterSyntaxError */
export function parseFilter(filter: string): ParsedFilter {
  const out: ParsedFilter = {}
  const conditions = filter.split(/\s+AND\s+/)
  for (const cond of conditions) {
    const m = cond.trim().match(/^([A-Za-z][\w.]*)\s*=\s*("([^"]*)"|[\w-]+)$/)
    if (!m) {
      throw new FilterSyntaxError(
        `unsupported filter syntax: ${JSON.stringify(cond.trim())}. ` +
          'Only `field = value` joined by AND is supported.',
      )
    }
    const fieldName = m[1]!
    const key = FIELDS[fieldName]
    if (!key) {
      throw new FilterSyntaxError(
        `unknown filter field: ${fieldName}. Supported: ${Object.keys(FIELDS).join(', ')}`,
      )
    }
    if (out[key] !== undefined) throw new FilterSyntaxError(`duplicate filter field: ${fieldName}`)
    const value = m[3] !== undefined ? m[3] : m[2]!
    if (key === 'direction') {
      if (value !== 'expenditure' && value !== 'revenue') {
        throw new FilterSyntaxError(`direction must be expenditure or revenue, got ${value}`)
      }
      out.direction = value
    } else {
      out[key] = value
    }
  }
  return out
}

/**
 * pageToken に封入するフィルタの指紋。**pageSize は含めない**
 * （AIP-158 は継続取得の途中で pageSize を変えることを認めている）。
 */
export function filterFingerprint(parsed: ParsedFilter): string {
  const canonical = JSON.stringify(
    Object.fromEntries(Object.entries(parsed).filter(([, v]) => v !== undefined).sort()),
  )
  // FNV-1a 32bit。暗号強度は不要（改竄対策ではなく、取り違え検出のため）
  let hash = 0x811c9dc5
  for (let i = 0; i < canonical.length; i++) {
    hash ^= canonical.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return hash.toString(16).padStart(8, '0')
}
