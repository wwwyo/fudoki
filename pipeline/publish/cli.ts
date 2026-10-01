import { parseArgs } from 'node:util'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { readFile } from 'node:fs/promises'
import { relative, resolve, sep, join } from 'node:path'
import { z } from 'zod'
import { releaseIdSchema } from '@fudoki/data-contracts'
import { BUILD, INPUT_LOCK, REPO, PUBLICATION_MANIFEST } from '../paths'
import { verifyCandidate } from '../fdp/manifest'
import { sourceFingerprint, sourceRevision, sha256 } from '../release'
import { cloudflareD1, cloudflareObjects, initializeSchema } from './cloudflare'
import { remoteVerification } from './remote'
import { publish, rollback } from './publish'

const optionsSchema = z.discriminatedUnion('command', [
  z.object({
    command: z.literal('publish'),
    releaseId: releaseIdSchema,
    dryRun: z.boolean(),
  }),
  z.object({
    command: z.literal('rollback'),
    releaseId: releaseIdSchema,
    dryRun: z.boolean(),
  }),
  z.object({ command: z.literal('init'), dryRun: z.boolean() }),
])
const databaseId = 'ae57ff6e-9684-4730-a854-43c173306f85'
const exec = promisify(execFile)

async function main() {
  const { positionals, values } = parseArgs({
    options: {
      'release-id': { type: 'string' },
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
          'Transfer, verify and activate an existing release without rebuilding it.',
        commands: z.toJSONSchema(optionsSchema),
        usage:
          'pipeline:publish publish|rollback --release-id r-<32 hex> [--dry-run]; init [--dry-run]',
      })
    )
    return
  }
  if (positionals.length !== 1) throw new Error('Expected exactly one command')
  if (positionals[0] === 'init' && values['release-id'])
    throw new Error('init does not accept --release-id')
  const input = optionsSchema.parse({
    command: positionals[0],
    releaseId: values['release-id'],
    dryRun: values['dry-run'] ?? false,
  })
  const db = cloudflareD1(databaseId)
  if (input.command === 'init') {
    if (!input.dryRun) await initializeSchema(db)
    console.log(
      JSON.stringify({ command: 'init', dryRun: input.dryRun, databaseId })
    )
    return
  }
  const directory = resolve(BUILD, 'releases', input.releaseId)
  if (
    relative(join(BUILD, 'releases'), directory)
      .split(sep)
      .some((part) => part === '..')
  )
    throw new Error('Invalid candidate directory')
  if (input.command === 'publish') {
    const manifest = await verifyCandidate(directory)
    const complete = JSON.parse(
      await readFile(join(directory, 'complete.json'), 'utf8')
    )
    if (
      manifest.releaseId !== input.releaseId ||
      complete.codeFingerprint !== (await sourceFingerprint()) ||
      manifest.inputFingerprint !== sha256(await readFile(INPUT_LOCK))
    )
      throw new Error(
        'Candidate differs from current code or fixed inputs; build the committed version explicitly'
      )
    if (
      sha256(await readFile(PUBLICATION_MANIFEST)) !== manifest.manifestSha256
    )
      throw new Error(
        'Git manifest differs from the verified candidate; run pipeline:build'
      )
    if (input.dryRun) {
      console.log(
        JSON.stringify({
          command: 'publish',
          dryRun: true,
          releaseId: manifest.releaseId,
          files: manifest.files.length,
          tables: manifest.tables,
        })
      )
      return
    }
    const { stdout: status } = await exec('git', ['status', '--porcelain'], {
      cwd: REPO,
    })
    const { stdout: revision } = await exec('git', ['rev-parse', 'HEAD'], {
      cwd: REPO,
    })
    if (
      status.trim() ||
      manifest.codeRevision !== (await sourceRevision()) ||
      INPUT_LOCK !== join(REPO, 'pipeline/ingestion/fiscal/sources.lock.json')
    )
      throw new Error(
        'Publish requires a clean commit and the canonical, remotely verified input lock'
      )
    const { stdout: committedManifest } = await exec(
      'git',
      ['show', 'HEAD:pipeline/publish/manifest.json'],
      { cwd: REPO, maxBuffer: 16 * 1024 * 1024 }
    )
    if (sha256(committedManifest) !== manifest.manifestSha256)
      throw new Error(
        'The distribution manifest must be committed before publication'
      )
    const manifestUrl = `https://raw.githubusercontent.com/wwwyo/fudoki/${revision.trim()}/pipeline/publish/manifest.json`
    const rpc = remoteVerification(manifest)
    try {
      const result = await publish(
        directory,
        db,
        cloudflareObjects('fudoki-releases'),
        rpc.verifier,
        manifestUrl,
        (event) => console.error(JSON.stringify(event))
      )
      console.log(JSON.stringify({ command: 'publish', ...result }))
    } finally {
      await rpc.dispose()
    }
  } else {
    if (input.dryRun) {
      console.log(
        JSON.stringify({
          command: 'rollback',
          dryRun: true,
          releaseId: input.releaseId,
        })
      )
      return
    }
    const manifest = await verifyCandidate(directory)
    const rpc = remoteVerification(manifest)
    try {
      const row = await db
        .prepare(
          "SELECT verification_sha256,manifest_url FROM releases WHERE release_id=? AND state='published'"
        )
        .bind(input.releaseId)
        .first<{ verification_sha256: string; manifest_url: string }>()
      if (!row) throw new Error('Rollback target is not retained and published')
      console.log(
        JSON.stringify({
          command: 'rollback',
          ...(await rollback(
            db,
            rpc.verifier,
            manifest,
            row.verification_sha256,
            row.manifest_url
          )),
        })
      )
    } finally {
      await rpc.dispose()
    }
  }
}
await main().catch((error) => {
  console.error(
    JSON.stringify({
      error: error instanceof Error ? error.message : 'Publication failed',
    })
  )
  process.exitCode = 1
})
