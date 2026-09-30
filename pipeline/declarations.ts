import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { loadJurisdictions } from '@fudoki/jurisdictions'
import { BY_JURISDICTION } from './ingestion/fiscal/metadata'
import { BUILD, PIPELINE } from './paths'

export async function writeDeclarations() {
  const directory = join(BUILD, 'declarations')
  await mkdir(directory, { recursive: true })
  const registry = await loadJurisdictions()
  const jurisdictions = Object.entries(registry.jurisdictions)
    .sort()
    .map(([code, jurisdiction]) => {
      const metadata = BY_JURISDICTION[code]
      if (metadata) {
        for (const category of [
          'coverage',
          'phaseSemantics',
          'classification',
          'sourceAndLicense',
        ]) {
          if (!metadata.caveats.some((caveat) => caveat.category === category))
            throw new Error(`Missing ${category} caveat: ${code}`)
        }
      }
      return {
        jurisdiction_code: code,
        name: jurisdiction.name,
        ocd_id: jurisdiction.ocdId,
        caveats_json: JSON.stringify(
          metadata?.caveats.filter((caveat) => caveat.api === true) ?? []
        ),
      }
    })
  await writeFile(
    join(directory, 'jurisdictions.json'),
    JSON.stringify(jurisdictions)
  )
  const process = Bun.spawn(
    ['uv', 'run', 'python', '-m', 'ingestion.declarations'],
    { cwd: PIPELINE, stderr: 'inherit', stdout: 'pipe' }
  )
  const body = await new Response(process.stdout).text()
  if ((await process.exited) !== 0)
    throw new Error('Unable to read ingestion declarations')
  const sources = JSON.parse(body) as { jurisdiction_code: string }[]
  for (const source of sources) {
    if (!BY_JURISDICTION[source.jurisdiction_code])
      throw new Error(`Missing public metadata: ${source.jurisdiction_code}`)
  }
  await writeFile(join(directory, 'sources.json'), JSON.stringify(sources))
  return directory
}
