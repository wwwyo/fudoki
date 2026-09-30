import { Database } from 'bun:sqlite'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import {
  aggregate,
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

const sqlite = new Database(join(BUILD, 'candidate.sqlite'), { readonly: true })
try {
  const db = sqliteD1(sqlite)
  const { release_id: releaseId } = sqlite
    .query('SELECT release_id FROM active_release WHERE singleton=1')
    .get() as { release_id: string }
  const validation = JSON.parse(
    await readFile(join(BUILD, 'd1-validation.json'), 'utf8')
  ) as { scopeTotals: [string, string, number, number][] }
  const datasets = datasetSchema
      .array()
      .parse(await listDatasets(db, releaseId)),
    results = []
  for (const [datasetId, phase, rows, amount] of validation.scopeTotals) {
    const start = performance.now()
    const actual = await aggregate(
      db,
      releaseId,
      aggregateQuerySchema.parse({
        datasetIds: [datasetId],
        phase,
        groupBy: ['year'],
      })
    )
    if (actual.total?.amount !== amount || actual.total?.lineCount !== rows)
      throw new Error(`API differs from dbt: ${datasetId}:${phase}`)
    lineSchema
      .array()
      .parse(
        await queryLines(
          db,
          releaseId,
          lineQuerySchema.parse({
            datasetIds: [datasetId],
            phase,
            pageSize: 50,
          })
        )
      )
    results.push({
      datasetId,
      phase,
      milliseconds: Math.round((performance.now() - start) * 100) / 100,
    })
  }
  await writeFile(
    join(BUILD, 'api-validation.json'),
    JSON.stringify(
      { releaseId, datasets: datasets.length, phases: results },
      null,
      2
    ) + '\n'
  )
  console.log(
    JSON.stringify({
      releaseId,
      datasets: datasets.length,
      datasetPhases: results.length,
      apiAndDbtMatch: true,
    })
  )
} finally {
  sqlite.close()
}
