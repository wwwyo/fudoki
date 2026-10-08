import { mkdir, writeFile, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { loadJurisdictions } from '@fudoki/jurisdictions'
import { cofogMaster } from '@fudoki/fiscal/cofog-master'
import { expenditureSetsuMaster } from '@fudoki/fiscal/setsu-master'
import { BY_JURISDICTION } from './ingestion/fiscal/metadata'
import { BUILD } from './runtime_paths'

export async function writeDeclarations(inputDirectory: string) {
  const directory = join(BUILD, 'declarations')
  await mkdir(directory, { recursive: true })
  await writeFile(
    join(directory, 'cofog_master.json'),
    JSON.stringify(cofogMaster())
  )
  await writeFile(
    join(directory, 'fiscal_expenditure_setsu_master.json'),
    JSON.stringify(expenditureSetsuMaster())
  )
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
          metadata?.caveats.filter((caveat) => caveat.userFacing === true) ?? []
        ),
      }
    })
  await writeFile(
    join(directory, 'jurisdiction_master.json'),
    JSON.stringify(jurisdictions)
  )
  const sourcesBody = await readFile(join(inputDirectory, 'sources.json'), 'utf8')
  const historyBody = await readFile(join(inputDirectory, 'history.json'), 'utf8')
  const sources = JSON.parse(sourcesBody) as { jurisdiction_code: string }[]
  for (const source of sources) {
    if (!BY_JURISDICTION[source.jurisdiction_code])
      throw new Error(`Missing public metadata: ${source.jurisdiction_code}`)
  }
  await writeFile(join(directory, 'sources.json'), sourcesBody)
  await writeFile(join(directory, 'history.json'), historyBody)
  return directory
}
