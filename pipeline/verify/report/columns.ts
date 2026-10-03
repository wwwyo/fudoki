import type { Manifest } from './lineage'
import type { ColDoc, ReportData } from './fiscal/schema'

/** dbt の列記述と、歳出・歳入を区別する列の宣言を検証画面へ渡す。 */
export function buildColumnDocs(
  manifest: Manifest,
  fields: Record<string, ColDoc>,
  columnsByTable: Map<string, string[]>
): ReportData['columnDocs'] {
  const resources: Record<string, Record<string, ColDoc>> = {}
  const canonical: Record<string, ColDoc> = {}
  for (const node of [
    ...Object.values(manifest.nodes),
    ...Object.values(manifest.sources),
  ]) {
    const columns: Record<string, ColDoc> = {}
    if (node.path?.startsWith('marts/')) {
      const direction = node.name.includes('expenditure')
        ? 'expenditure'
        : node.name.includes('revenue')
          ? 'revenue'
          : null
      for (const name of columnsByTable.get(node.name) ?? []) {
        const field =
          (direction && fields[`${direction}:${name}`]) || fields[name]
        if (field)
          columns[name] = { title: field.title, description: field.description }
      }
    }
    for (const [name, column] of Object.entries(node.columns ?? {})) {
      if (!column.description) continue
      columns[name] = { ...columns[name], description: column.description }
      canonical[name] ??= columns[name]!
    }
    resources[node.name] = columns
  }
  const common = new Map<string, Map<string, ColDoc>>()
  for (const columns of Object.values(resources))
    for (const [name, doc] of Object.entries(columns)) {
      const meanings = common.get(name) ?? new Map<string, ColDoc>()
      meanings.set(JSON.stringify(doc), doc)
      common.set(name, meanings)
    }
  for (const [name, meanings] of common) {
    if (meanings.size !== 1) continue
    const doc = meanings.values().next().value!
    canonical[name] = {
      title: doc.title,
      description: canonical[name]?.description ?? doc.description,
    }
  }
  return { resources, canonical }
}
