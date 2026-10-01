import { implement, ORPCError } from '@orpc/server'
import { contract } from './contract'
import type { Env } from './env'
import {
  aggregate,
  files,
  jurisdictions,
  listDatasets,
  pageLines,
  QueryError,
  resolveRelease,
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
            error.code === 'RELEASE_EXPIRED'
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
      const releaseId = await resolveRelease(env.DB, input.releaseId)
      const selected = await listDatasets(env.DB, releaseId)
      const dataset = selected.find((d) => d.id === input.datasetId)
      if (!dataset)
        throw new QueryError(
          'NOT_FOUND',
          'Dataset is not present in this release'
        )
      return { releaseId, dataset }
    }
  ),
  listJurisdictions: os.listJurisdictions.handler(
    async ({ input, context: { env } }) => {
      const releaseId = await resolveRelease(env.DB, input.releaseId)
      return {
        releaseId,
        jurisdictions: await jurisdictions(env.DB, releaseId),
      }
    }
  ),
  listFiscalDatasets: os.listFiscalDatasets.handler(
    async ({ input, context: { env } }) => {
      const releaseId = await resolveRelease(env.DB, input.releaseId)
      return {
        releaseId,
        datasets: await listDatasets(env.DB, releaseId, input),
      }
    }
  ),
  searchFiscalLines: os.searchFiscalLines.handler(
    ({ input, context: { env } }) => pageLines(env.DB, env.CURSOR_SECRET, input)
  ),
  getFiscalLines: os.getFiscalLines.handler(({ input, context: { env } }) =>
    pageLines(env.DB, env.CURSOR_SECRET, input)
  ),
  aggregateFiscalDatasets: os.aggregateFiscalDatasets.handler(
    async ({ input, context: { env } }) =>
      aggregate(env.DB, await resolveRelease(env.DB, input.releaseId), input)
  ),
  listFiles: os.listFiles.handler(async ({ input, context: { env } }) => {
    const releaseId = await resolveRelease(env.DB, input.releaseId)
    const publication = await env.DB.prepare(
      'SELECT manifest_url FROM releases WHERE release_id=?'
    )
      .bind(releaseId)
      .first<{ manifest_url: string | null }>()
    if (!publication?.manifest_url) throw new ORPCError('SERVICE_UNAVAILABLE')
    return {
      releaseId,
      manifestUrl: publication.manifest_url,
      files: await files(
        env.DB,
        releaseId,
        env.DOWNLOAD_BASE_URL,
        input.jurisdictionCode
      ),
    }
  }),
})
export type Router = typeof router
