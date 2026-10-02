import { Database } from 'bun:sqlite'
import { readFile, writeFile } from 'node:fs/promises'
import { join, dirname } from 'node:path'
import {
  aggregate,
  budgetHistory,
  listDatasets,
  queryLines,
} from '../../apps/api/src/data/queries'
import {
  aggregateQuerySchema,
  datasetSchema,
  lineQuerySchema,
  lineSchema,
} from '../../apps/api/src/contract'
import { sqliteD1 } from '../../apps/api/test/database'
import { BUILD } from '../paths'
import { candidateManifestSchema } from '@fudoki/data-contracts'
import { verifyBudgetChanges } from './budget-changes'

const sqlite = new Database(join(BUILD, 'candidate.sqlite'), { readonly: true })
try {
  const db = sqliteD1(sqlite)
  const validation = JSON.parse(
    await readFile(join(BUILD, 'd1-validation.json'), 'utf8')
  ) as { scopeTotals: [string, string, string, number, number][] }
  const datasets = datasetSchema.array().parse(await listDatasets(db)),
    results = []
  for (const [
    datasetId,
    jurisdictionCode,
    resource,
    rows,
    amount,
  ] of validation.scopeTotals) {
    if (resource.endsWith('_budget_changes')) continue
    const start = performance.now(),
      input = aggregateQuerySchema.parse({
        datasetIds: [datasetId],
        groupBy: ['year'],
      })
    const actual = await aggregate(db, input)
    if (actual.total?.amount !== amount || actual.total?.lineCount !== rows)
      throw new Error(`API differs from dbt: ${datasetId}`)
    lineSchema.array().parse(
      await queryLines(
        db,
        datasets.filter((d) => d.id === datasetId),
        lineQuerySchema.parse({ datasetIds: [datasetId], pageSize: 50 })
      )
    )
    results.push({
      datasetId,
      jurisdictionCode,
      resource,
      milliseconds: Math.round((performance.now() - start) * 100) / 100,
    })
  }
  if (!process.env.FUDOKI_API_DIR) throw new Error('A build directory is required')
  const directory = dirname(process.env.FUDOKI_API_DIR)
  const candidate = candidateManifestSchema.parse(JSON.parse(
    await readFile(join(directory, 'verification.json'), 'utf8')
  ))
  const budgetChanges = await verifyBudgetChanges(directory,
    candidate.versions.map((v) => ({ jurisdictionCode: v.jurisdictionCode, versionId: v.versionId })),
    (input) => budgetHistory(db, input))
  await writeFile(
    join(BUILD, 'api-validation.json'),
    JSON.stringify({ datasets: datasets.length, results, budgetChanges }, null, 2) + '\n'
  )
  console.log(
    JSON.stringify({
      datasets: datasets.length,
      checked: results.length,
      apiAndDbtMatch: true,
    })
  )
} finally {
  sqlite.close()
}
