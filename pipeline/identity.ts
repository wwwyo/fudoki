import { createHash } from 'node:crypto'
import { readFile, readdir, lstat } from 'node:fs/promises'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { join, relative } from 'node:path'
import { REPO } from './runtime_paths'

export function sha256(body: string | Uint8Array): string {
  return createHash('sha256').update(body).digest('hex')
}
async function git(...args: string[]) {
  return (
    await promisify(execFile)('git', args, {
      cwd: REPO,
      maxBuffer: 16 * 1024 * 1024,
    })
  ).stdout.trimEnd()
}
export async function sourceFingerprint(): Promise<string> {
  const paths = [
    ...new Set(
      (
        await git(
          'ls-files',
          '-z',
          '--cached',
          '--others',
          '--exclude-standard'
        )
      )
        .split('\0')
        .filter(Boolean)
    ),
  ].sort()
  const hash = createHash('sha256')
  for (const path of paths) {
    if (
      !/^(?:pipeline\/|packages\/|(?:package\.json|bun\.lock|pyproject\.toml|uv\.lock|mise\.toml|tsconfig\.json)$)/.test(
        path
      )
    )
      continue
    const file = join(REPO, path)
    try {
      const info = await lstat(file)
      if (!info.isFile()) continue
      const body = await readFile(file)
      hash
        .update(path + '\0')
        .update(body)
        .update('\0')
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
    }
  }
  return hash.digest('hex')
}
async function directoryHash(path: string): Promise<string> {
  const hash = createHash('sha256')
  async function visit(directory: string) {
    for (const name of (await readdir(directory)).sort()) {
      const file = join(directory, name),
        info = await lstat(file)
      if (info.isDirectory()) await visit(file)
      else if (info.isFile())
        hash
          .update(relative(path, file) + '\0')
          .update(await readFile(file))
          .update('\0')
    }
  }
  await visit(path)
  return hash.digest('hex')
}
export async function sourceRevision(repo = REPO): Promise<string> {
  const { stdout } = await promisify(execFile)(
    'git',
    [
      'log',
      '-1',
      '--format=%H',
      '--',
      'pipeline',
      'packages',
      'package.json',
      'bun.lock',
      'pyproject.toml',
      'uv.lock',
      'mise.toml',
      'tsconfig.json',
    ],
    { cwd: repo }
  )
  return stdout.trim()
}
export async function buildIdentity(inputFingerprint?: string) {
  // Legacy coverage consumers still identify their old fixed input list.
  // The manifest-based build supplies the validated manifest/declaration fingerprint.
  if (inputFingerprint === undefined) {
    const { INPUT_LOCK } = await import('./paths')
    inputFingerprint = sha256(await readFile(INPUT_LOCK))
  }
  if (!/^[a-f0-9]{64}$/.test(inputFingerprint))
    throw new Error('Expected a validated build input fingerprint')
  const codeRevision = await sourceRevision()
  const codeFingerprint = await sourceFingerprint()
  const judgmentFingerprint = sha256(
    JSON.stringify({
      seeds: await directoryHash(join(REPO, 'pipeline/dbt/seeds')),
      declarations: sha256(
        await readFile(join(REPO, 'pipeline/dbt/dbt_project.yml'))
      ),
      notes: sha256(
        await readFile(join(REPO, 'pipeline/ingestion/fiscal/metadata.ts'))
      ),
    })
  )
  const buildId =
    'b-' +
    sha256(
      JSON.stringify({
        codeRevision,
        codeFingerprint,
        inputFingerprint,
        judgmentFingerprint,
      })
    ).slice(0, 32)
  return {
    buildId,
    codeRevision,
    codeFingerprint,
    inputFingerprint,
    judgmentFingerprint,
  }
}
