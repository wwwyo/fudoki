import {
  mkdir,
  rm,
  readFile,
  writeFile,
  access,
  mkdtemp,
  rename,
  cp,
} from 'node:fs/promises'
import { join } from 'node:path'
import { parseArgs } from 'node:util'
import {
  BUILD,
  DBT_TARGET,
  PIPELINE,
  WAREHOUSE,
} from './runtime_paths'
import { writeDeclarations } from './declarations'
import { buildIdentity } from './identity'
import { artifactHashes, verifyArtifacts } from './artifacts'

const { values: options } = parseArgs({
  args: process.argv.slice(2),
  options: {
    rebuild: { type: 'boolean' },
    manifest: { type: 'string', multiple: true },
  },
})
const preparation = Bun.spawn([
  'uv', 'run', 'python', '-m', 'build_inputs', 'prepare',
  ...(options.manifest ?? []).flatMap((path) => ['--manifest', path]),
], { cwd: PIPELINE, stdout: 'pipe', stderr: 'inherit' })
const preparedBody = await new Response(preparation.stdout).text()
if ((await preparation.exited) !== 0)
  throw new Error('Unable to prepare saved ingestion inputs')
const prepared = JSON.parse(preparedBody) as {
  inputFingerprint: string
  catalog: string
  inputs: string
  tables: number
  manifests: number
}
const identity = await buildIdentity(prepared.inputFingerprint)
const candidate = join(BUILD, 'builds', identity.buildId)
const declarations = await writeDeclarations()
await mkdir(join(BUILD, 'builds'), { recursive: true })
let expected: Record<string, string> | null = null
try {
  expected = JSON.parse(
    await readFile(join(candidate, 'verification.json'), 'utf8')
  ).files
  if (!expected) throw new Error('Build verification record lacks file hashes')
  await verifyArtifacts(candidate, expected)
} catch (error) {
  if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  // A partial build must not become the baseline for a determinism check.
  try {
    await access(candidate)
    throw new Error('Existing build lacks its verification record')
  } catch (missing) {
    if ((missing as NodeJS.ErrnoException).code !== 'ENOENT') throw missing
  }
}
const working = join(BUILD, 'workspace')
async function run(command: string[], cwd = PIPELINE) {
  const child = Bun.spawn(command, {
    cwd,
    env: {
      ...Bun.env,
      FUDOKI_INPUT_CATALOG: prepared.catalog,
      FUDOKI_INPUT_DIR: prepared.inputs,
      FUDOKI_PACKAGE_DIR: join(working, 'fiscal'),
      FUDOKI_INTERNAL_PACKAGE_DIR: join(working, 'internal/fiscal'),
      FUDOKI_DECLARATIONS_DIR: declarations,
    },
    stdout: 'inherit',
    stderr: 'inherit',
  })
  if ((await child.exited) !== 0)
    throw new Error(`Failed: ${command.join(' ')}`)
}
await rm(join(BUILD, 'warehouse.json'), { force: true })
try {
  await rm(working, { recursive: true, force: true })
  await mkdir(working, { recursive: true })
  const catalog = JSON.parse(await readFile(prepared.catalog, 'utf8')) as {
    tables: { target: { jurisdiction: string } }[]
  }
  for (const code of new Set(catalog.tables.map((table) => table.target.jurisdiction))) {
    await mkdir(join(working, 'fiscal', code), { recursive: true })
    await mkdir(join(working, 'internal/fiscal', code), { recursive: true })
  }
  await rm(WAREHOUSE, { force: true })
  await rm(DBT_TARGET, { recursive: true, force: true })
  await run(
    ['uv', 'run', 'dbt', 'build', '--profiles-dir', '.', '--no-partial-parse'],
    join(PIPELINE, 'dbt')
  )
  const files = await artifactHashes(working)
  if (expected && JSON.stringify(files) !== JSON.stringify(expected)) {
    const changed = Object.keys({ ...expected, ...files }).filter(
      (file) => expected[file] !== files[file]
    )
    throw new Error(
      `The same code and fixed inputs produced different CSV files: ${changed.join(', ')}`
    )
  }
  await writeFile(
    join(working, 'verification.json'),
    JSON.stringify({ ...identity, files }) + '\n'
  )
  if (!expected) {
    const staged = await mkdtemp(join(BUILD, 'builds', 'build-'))
    try {
      await cp(working, staged, { recursive: true })
      await rename(staged, candidate)
    } catch (error) {
      await rm(staged, { recursive: true, force: true })
      throw error
    }
  }
  await writeFile(
    join(BUILD, 'latest.json'),
    JSON.stringify({ ...identity, inputMode: 'ingestion-manifests',
      inputCatalog: prepared.catalog, inputDir: prepared.inputs }) + '\n'
  )
  await writeFile(
    join(BUILD, 'warehouse.json'),
    JSON.stringify({ buildId: identity.buildId }) + '\n'
  )
  console.log(
    JSON.stringify({
      buildId: identity.buildId,
      path: candidate,
      determinismChecked: expected !== null,
    })
  )
} catch (error) {
  await rm(working, { recursive: true, force: true })
  throw error
}
