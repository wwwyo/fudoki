import { createHash } from 'node:crypto'
import { readFile, readdir, lstat } from 'node:fs/promises'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { join, relative } from 'node:path'
import { queryFingerprint } from '../apps/api/scripts/query-fingerprint'
import { REPO, INPUT_LOCK } from './paths'

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
      !/^(?:pipeline\/|packages\/|apps\/api\/src\/|apps\/api\/scripts\/|(?:package\.json|bun\.lock|pyproject\.toml|uv\.lock|mise\.toml|tsconfig\.json)$)/.test(
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
export async function releaseIdentity() {
  const codeRevision = await git('rev-parse', 'HEAD')
  const inputFingerprint = sha256(await readFile(INPUT_LOCK))
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
  const releaseId =
    'r-' +
    sha256(
      JSON.stringify({
        codeRevision,
        codeFingerprint,
        inputFingerprint,
        judgmentFingerprint,
      })
    ).slice(0, 32)
  return {
    releaseId,
    codeRevision,
    codeFingerprint,
    inputFingerprint,
    judgmentFingerprint,
    queryFingerprint: await queryFingerprint(),
  }
}
