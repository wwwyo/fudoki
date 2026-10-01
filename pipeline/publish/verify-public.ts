import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { z } from 'zod'
import {
  type D1Database,
  CONTRACT_VERSION,
  distributionManifestSchema,
} from '@fudoki/data-contracts'
import { verifyCandidate } from '../fdp/manifest'
import { contract } from '../../apps/api/src/contract'
import { verifyBudgetChanges } from '../verify/budget-changes'
import { createPublicClient } from '../../apps/api/src/client'

export async function verifyApiContract(
  db: D1Database,
  base: string,
  queryFingerprint: string
) {
  const response = await fetch(new URL('/v0/contract', base), {
    cache: 'no-store',
  })
  if (!response.ok)
    throw new Error(`Public API contract check failed: ${response.status}`)
  const actual = z
    .object({
      contractVersion: z.literal(CONTRACT_VERSION),
      queryFingerprint: z.literal(queryFingerprint),
      databaseIdentity: z.string(),
    })
    .parse(await response.json())
  const database = await db
    .prepare('SELECT identity FROM database_identity WHERE singleton=1')
    .first<{ identity: string }>()
  if (!database || database.identity !== actual.databaseIdentity)
    throw new Error('Public API is bound to another D1 database')
  return actual
}

/** Verify the ordinary public API after import; failed verification never hides existing rows. */
export async function verifyPublicApi(
  directory: string,
  db: D1Database,
  base: string,
  jurisdictionCodes: string[]
) {
  const verification = await verifyCandidate(directory)
  await verifyApiContract(db, base, verification.queryFingerprint)
  const manifest = distributionManifestSchema.parse(
    JSON.parse(await readFile(join(directory, 'manifest.json'), 'utf8'))
  )
  const client = createPublicClient(base)
  const results = []
  for (const version of verification.versions.filter((v) =>
    jurisdictionCodes.includes(v.jurisdictionCode)
  )) {
    const versions = [
      {
        jurisdictionCode: version.jurisdictionCode,
        versionId: version.versionId,
      },
    ]
    for (const total of verification.totals.filter(
      (t) =>
        t.jurisdictionCode === version.jurisdictionCode &&
        !t.resource.endsWith('_budget_changes')
    )) {
      const response = await fetch(
        new URL('/v0/fiscal-datasets/aggregate', base),
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            versions,
            datasetIds: [total.datasetId],
            groupBy: ['year'],
          }),
        }
      )
      if (!response.ok)
        throw new Error(
          `Public aggregate verification failed: ${response.status}`
        )
      const actual = contract.aggregateFiscalDatasets[
        '~orpc'
      ].outputSchema!.parse(await response.json())
      if (
        actual.total?.amount !== total.amount ||
        actual.total?.lineCount !== total.rows
      )
        throw new Error('Public API differs from the built data')
      results.push({
        jurisdictionCode: version.jurisdictionCode,
        versionId: version.versionId,
        datasetId: total.datasetId,
        rows: total.rows,
        amount: total.amount,
      })
    }
    const response = await client.listFiles({
      versions,
      jurisdictionCode: version.jurisdictionCode,
    })
    const actualFiles =
      contract.listFiles['~orpc'].outputSchema!.parse(response)
    if (JSON.stringify(actualFiles.versions) !== JSON.stringify(versions))
      throw new Error('Public API file versions differ')
    const expectedFiles = manifest.files.filter((file) =>
      file.path.startsWith(`fiscal/${version.jurisdictionCode}/`)
    )
    if (actualFiles.files.length !== expectedFiles.length)
      throw new Error('Public API file coverage differs')
    for (const file of expectedFiles) {
      const actual = actualFiles.files.find((row) => row.path === file.path)
      if (
        !actual ||
        actual.sha256 !== file.sha256 ||
        actual.bytes !== file.bytes ||
        actual.contentType !== file.contentType ||
        !actual.url.endsWith('/' + file.objectKey)
      )
        throw new Error('Public API file metadata differs')
    }
    for (const file of manifest.files.filter((f) =>
      f.path.startsWith(`fiscal/${version.jurisdictionCode}/`)
    )) {
      if (
        !file.objectKey.startsWith(
          `fiscal/${version.jurisdictionCode}/${version.packageId}/`
        )
      )
        throw new Error('Distribution object scope differs')
    }
  }
  const budgetChanges = await verifyBudgetChanges(
    directory,
    verification.versions.filter((v) => jurisdictionCodes.includes(v.jurisdictionCode))
      .map((v) => ({ jurisdictionCode: v.jurisdictionCode, versionId: v.versionId })),
    (input) => client.getFiscalBudgetHistory(input)
  )
  await writeFile(
    join(directory, 'public-api-verification.json'),
    JSON.stringify({ verified: true, results, budgetChanges }, null, 2) + '\n'
  )
  return results
}
