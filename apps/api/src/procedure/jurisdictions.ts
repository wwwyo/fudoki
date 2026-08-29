/** jurisdictions リソースの procedure。パーティション meta/jurisdictions.json を読むだけ */
import { os, readMeta } from './shared'

export const listJurisdictions = os.listJurisdictions.handler(async ({ context }) => {
  const meta = await readMeta(context.env)
  return { jurisdictions: meta.jurisdictions, revision: meta.revision }
})

export const getJurisdiction = os.getJurisdiction.handler(async ({ context, input, errors }) => {
  const meta = await readMeta(context.env)
  const jurisdiction = meta.jurisdictions.find((j) => j.id === input.jurisdiction)
  if (!jurisdiction) throw errors.NOT_FOUND({ message: `unknown jurisdiction: ${input.jurisdiction}` })
  return { jurisdiction, revision: meta.revision }
})
