import { COFOG_NAMES, COFOG_DEPTHS } from './detail'

/** Codes used by the current rules, including every parent needed for their hierarchy. */
export function cofogMaster() {
  const rows = COFOG_DEPTHS.flatMap((level) =>
    Object.entries(COFOG_NAMES[level]).map(([code, label]) => ({
      code,
      label,
      level,
      parent_code: code.includes('.')
        ? code.slice(0, code.lastIndexOf('.'))
        : null,
    }))
  ).sort((a, b) => a.code.localeCompare(b.code))
  const codes = new Set(rows.map((row) => row.code))
  for (const row of rows)
    if (row.parent_code !== null && !codes.has(row.parent_code))
      throw new Error(`COFOG parent is missing: ${row.code}`)
  return rows
}
