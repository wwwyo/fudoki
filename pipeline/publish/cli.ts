import { parseArgs } from 'node:util'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { z } from 'zod'
import { buildIdSchema, jurisdictionCodeSchema } from '@fudoki/data-contracts'
import { BUILD, INPUT_LOCK, REPO, PUBLICATION_MANIFEST } from '../paths'
import { verifyCandidate } from '../fdp/manifest'
import { sourceFingerprint, sha256 } from '../release'
import { cloudflareD1, cloudflareObjects, initializeSchema } from './cloudflare'
import { publish } from './publish'
import { verifyApiContract, verifyPublicApi } from './verify-public'
import { D1_DATABASE_ID } from '../../apps/api/resources'

const optionsSchema = z.discriminatedUnion('command', [
  z
    .object({
      command: z.literal('publish'),
      buildId: buildIdSchema,
      jurisdictionCodes: z.array(jurisdictionCodeSchema),
      dryRun: z.boolean(),
    })
    .strict(),
  z.object({ command: z.literal('init'), dryRun: z.boolean() }).strict(),
])
const exec = promisify(execFile)
async function main() {
  const { positionals, values } = parseArgs({
    options: {
      'build-id': { type: 'string' },
      jurisdiction: { type: 'string', multiple: true },
      'dry-run': { type: 'boolean' },
      help: { type: 'boolean' },
    },
    allowPositionals: true,
    strict: true,
  })
  if (values.help || positionals[0] === 'schema') {
    console.log(
      JSON.stringify({
        description:
          'Import verified municipality versions and immutable R2 files. Rows become visible during import.',
        commands: z.toJSONSchema(optionsSchema),
        usage:
          'pipeline:publish publish --build-id r-<32 hex> [--jurisdiction <6 digits>] [--dry-run]; init [--dry-run]',
      })
    )
    return
  }
  if (positionals.length !== 1) throw new Error('Expected exactly one command')
  if (positionals[0] === 'init' && (values['build-id'] || values.jurisdiction))
    throw new Error('init does not accept a build or jurisdiction')
  const input = optionsSchema.parse(
    positionals[0] === 'init'
      ? { command: 'init', dryRun: values['dry-run'] ?? false }
      : {
          command: positionals[0],
          buildId: values['build-id'],
          jurisdictionCodes: values.jurisdiction ?? [],
          dryRun: values['dry-run'] ?? false,
        }
  )
  const db = cloudflareD1(D1_DATABASE_ID)
  if (input.command === 'init') {
    if (!input.dryRun) await initializeSchema(db)
    console.log(
      JSON.stringify({
        command: 'init',
        dryRun: input.dryRun,
        databaseId: D1_DATABASE_ID,
      })
    )
    return
  }
  const directory = join(BUILD, 'builds', input.buildId)
  const manifest = await verifyCandidate(directory)
  const complete = JSON.parse(
    await readFile(join(directory, 'complete.json'), 'utf8')
  )
  if (
    manifest.buildId !== input.buildId ||
    complete.codeFingerprint !== (await sourceFingerprint()) ||
    manifest.inputFingerprint !== sha256(await readFile(INPUT_LOCK))
  )
    throw new Error(
      'Candidate differs from current code or fixed inputs; rebuild first'
    )
  if (sha256(await readFile(PUBLICATION_MANIFEST)) !== manifest.manifestSha256)
    throw new Error('Git manifest differs from verified candidate')
  const jurisdictionCodes = input.jurisdictionCodes.length
    ? input.jurisdictionCodes
    : manifest.versions.map((v) => v.jurisdictionCode)
  if (
    jurisdictionCodes.some(
      (code) => !manifest.versions.some((v) => v.jurisdictionCode === code)
    )
  )
    throw new Error('Unknown jurisdiction in candidate')
  if (input.dryRun) {
    console.log(
      JSON.stringify({
        command: 'publish',
        dryRun: true,
        buildId: manifest.buildId,
        versions: manifest.versions
          .filter((v) => jurisdictionCodes.includes(v.jurisdictionCode))
          .map(({ tables, ...version }) => version),
      })
    )
    return
  }
  const [
    { stdout: status },
    { stdout: revision },
    { stdout: committedManifest },
  ] = await Promise.all([
    exec('git', ['status', '--porcelain'], { cwd: REPO }),
    exec('git', ['rev-parse', 'HEAD'], { cwd: REPO }),
    exec('git', ['show', 'HEAD:pipeline/publish/manifest.json'], {
      cwd: REPO,
      maxBuffer: 16 * 1024 * 1024,
    }),
  ])
  if (
    status.trim() ||
    INPUT_LOCK !== join(REPO, 'pipeline/ingestion/fiscal/sources.lock.json')
  )
    throw new Error(
      'Publish requires a clean commit and the canonical remotely verified input lock'
    )
  if (sha256(committedManifest) !== manifest.manifestSha256)
    throw new Error('Commit the distribution manifest before publication')
  const manifestUrl = `https://raw.githubusercontent.com/wwwyo/fudoki/${revision.trim()}/pipeline/publish/manifest.json`
  await verifyApiContract(
    db,
    'https://api.fudoki.dev/',
    manifest.queryFingerprint
  )
  const result = await publish(
    directory,
    db,
    cloudflareObjects('fudoki-releases', 'https://download.fudoki.dev/'),
    manifestUrl,
    (event) => console.error(JSON.stringify(event)),
    { jurisdictionCodes }
  )
  await verifyPublicApi(
    directory,
    db,
    'https://api.fudoki.dev/',
    jurisdictionCodes
  )
  console.log(
    JSON.stringify({ command: 'publish', ...result, publicApiVerified: true })
  )
}
await main().catch((error) => {
  console.error(
    JSON.stringify({
      error: error instanceof Error ? error.message : 'Import failed',
    })
  )
  process.exitCode = 1
})
