import { implement, ORPCError } from '@orpc/server'
import { contract } from './contract'
import type { Env } from './env'
import {
  aggregate,
  budgetHistory,
  files,
  jurisdictions,
  listDatasets,
  pageLines,
  QueryError,
  resolveVersions,
} from './data/queries'

const os = implement(contract)
  .$context<{ env: Env }>()
  .use(async ({ next }) => {
    try {
      return await next()
    } catch (error) {
      if (error instanceof QueryError)
        throw new ORPCError(error.code, {
          status:
            error.code === 'VERSION_EXPIRED'
              ? 410
              : error.code === 'UNAVAILABLE'
                ? 503
                : undefined,
          message: error.message,
          data:
            error.code === 'BAD_REQUEST'
              ? { reason: error.message }
              : undefined,
        })
      throw error
    }
  })
export const router = os.router({
  getFiscalDataset: os.getFiscalDataset.handler(
    async ({ input, context: { env } }) => {
      const dataset = (
        await listDatasets(env.DB, { ...input, datasetIds: [input.datasetId] })
      ).find((d) => d.id === input.datasetId)
      if (!dataset)
        throw new QueryError(
          'NOT_FOUND',
          'Dataset is not present in the selected jurisdiction version'
        )
      return {
        versions: [
          {
            jurisdictionCode: dataset.jurisdictionCode,
            versionId: dataset.versionId,
          },
        ],
        dataset,
      }
    }
  ),
  listJurisdictions: os.listJurisdictions.handler(
    ({ input, context: { env } }) => jurisdictions(env.DB, input.versions)
  ),
  listFiscalDatasets: os.listFiscalDatasets.handler(
    async ({ input, context: { env } }) => {
      const versions = await resolveVersions(env.DB, input.versions)
      return { versions, datasets: await listDatasets(env.DB, input, versions) }
    }
  ),
  searchFiscalLines: os.searchFiscalLines.handler(
    ({ input, context: { env } }) => pageLines(env.DB, env.CURSOR_SECRET, input)
  ),
  getFiscalLines: os.getFiscalLines.handler(({ input, context: { env } }) =>
    pageLines(env.DB, env.CURSOR_SECRET, input)
  ),
  aggregateFiscalDatasets: os.aggregateFiscalDatasets.handler(
    ({ input, context: { env } }) => aggregate(env.DB, input)
  ),
  getFiscalBudgetHistory: os.getFiscalBudgetHistory.handler(
    ({ input, context: { env } }) => budgetHistory(env.DB, input)
  ),
  listFiles: os.listFiles.handler(({ input, context: { env } }) =>
    files(env.DB, env.DOWNLOAD_BASE_URL, input)
  ),
})
export type Router = typeof router
