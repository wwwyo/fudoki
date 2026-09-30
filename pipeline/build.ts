import {
  mkdir,
  rm,
  readFile,
  writeFile,
  access,
  mkdtemp,
} from 'node:fs/promises'
import { join } from 'node:path'
import {
  BUILD,
  DBT_TARGET,
  INPUTS,
  INPUT_LOCK,
  PIPELINE,
  WAREHOUSE,
} from './paths'
import { writeDeclarations } from './declarations'
import { releaseIdentity, sha256 } from './release'
import { finalizeCandidate, verifyCandidate } from './fdp/manifest'

const identity = await releaseIdentity()
const candidate = join(BUILD, 'releases', identity.releaseId)
let working = candidate
const declarations = await writeDeclarations()
async function run(command: string[], cwd = PIPELINE) {
  const process = Bun.spawn(command, {
    cwd,
    env: {
      ...Bun.env,
      FUDOKI_INPUT_LOCK: INPUT_LOCK,
      FUDOKI_INPUT_DIR: INPUTS,
      FUDOKI_PACKAGE_DIR: join(working, 'fiscal'),
      FUDOKI_API_DIR: join(working, 'api'),
      FUDOKI_DECLARATIONS_DIR: declarations,
      FUDOKI_RELEASE_ID: identity.releaseId,
    },
    stdout: 'inherit',
    stderr: 'inherit',
  })
  if ((await process.exited) !== 0)
    throw new Error(`Failed: ${command.join(' ')}`)
}
await mkdir(BUILD, { recursive: true })
let complete = false
try {
  await access(join(candidate, 'complete.json'))
  complete = true
} catch {}
if (process.argv.slice(2).some((arg) => arg !== '--rebuild'))
  throw new Error('Expected only --rebuild')
let workspaceMatches = false
try {
  const marker = JSON.parse(
    await readFile(join(BUILD, 'warehouse.json'), 'utf8')
  )
  workspaceMatches = marker.releaseId === identity.releaseId
  await access(WAREHOUSE)
  await access(join(DBT_TARGET, 'manifest.json'))
} catch {
  workspaceMatches = false
}
if (complete) await verifyCandidate(candidate)
const rebuild =
  !complete || !workspaceMatches || process.argv.includes('--rebuild')
if (rebuild) {
  if (complete) working = await mkdtemp(join(BUILD, 'rebuild-'))
  await rm(join(BUILD, 'warehouse.json'), { force: true })
  await run([
    'uv',
    'run',
    'python',
    '-m',
    'ingestion.inputs',
    'restore',
    '--lock',
    INPUT_LOCK,
  ])
  const packages = join(working, 'fiscal')
  await mkdir(packages, { recursive: true })
  await mkdir(join(working, 'api'), { recursive: true })
  const sources = JSON.parse(
    await readFile(join(declarations, 'sources.json'), 'utf8')
  ) as { jurisdiction_code: string }[]
  for (const code of new Set(sources.map((s) => s.jurisdiction_code)))
    await mkdir(join(packages, code), { recursive: true })
  await rm(WAREHOUSE, { force: true })
  await rm(DBT_TARGET, { recursive: true, force: true })
  await run(
    ['uv', 'run', 'dbt', 'build', '--profiles-dir', '.', '--no-partial-parse'],
    join(PIPELINE, 'dbt')
  )
  await run(['uv', 'run', 'python', '-m', 'fdp.build'])
  await run(['uv', 'run', 'python', '-m', 'fdp.validate_d1'])
  await run(['bun', 'run', 'verify/api.ts'])
  const validation = JSON.parse(
    await readFile(join(BUILD, 'd1-validation.json'), 'utf8')
  )
  await finalizeCandidate(working, identity, validation)
  await verifyCandidate(working)
  if (complete) {
    if (
      sha256(await readFile(join(working, 'manifest.json'))) !==
      sha256(await readFile(join(candidate, 'manifest.json')))
    )
      throw new Error(
        'The same code and fixed inputs produced a different candidate'
      )
  }
  await writeFile(
    join(BUILD, 'warehouse.json'),
    JSON.stringify({
      releaseId: identity.releaseId,
      artifactDirectory: working,
    }) + '\n'
  )
}
await writeFile(
  join(BUILD, 'latest.json'),
  JSON.stringify({
    releaseId: identity.releaseId,
    inputLock: INPUT_LOCK,
    inputFingerprint: identity.inputFingerprint,
  }) + '\n'
)
console.log(
  JSON.stringify({
    releaseId: identity.releaseId,
    path: candidate,
    reused: complete,
    reconstructed: rebuild,
    determinismChecked: complete && rebuild,
  })
)
