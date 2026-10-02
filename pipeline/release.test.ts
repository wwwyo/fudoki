import { expect, test } from 'bun:test'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { sourceRevision } from './release'

test('committing the generated manifest does not change the code revision used to generate it', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'fudoki-source-revision-'))
  const git = async (...args: string[]) =>
    (await promisify(execFile)('git', args, { cwd: directory })).stdout.trim()
  try {
    await git('init')
    await git('config', 'user.name', 'Fixture')
    await git('config', 'user.email', 'fixture@example.org')
    await mkdir(join(directory, 'pipeline/publish'), { recursive: true })
    await writeFile(join(directory, 'pipeline/build.ts'), 'first code')
    await git('add', 'pipeline/build.ts')
    await git(
      '-c',
      'commit.gpgsign=false',
      'commit',
      '-m',
      'Define the fixture build'
    )
    const codeRevision = await sourceRevision(directory)
    await writeFile(join(directory, 'pipeline/publish/manifest.json'), '{}')
    await git('add', 'pipeline/publish/manifest.json')
    await git(
      '-c',
      'commit.gpgsign=false',
      'commit',
      '-m',
      'Record the generated manifest'
    )
    expect(await git('rev-parse', 'HEAD')).not.toBe(codeRevision)
    expect(await sourceRevision(directory)).toBe(codeRevision)
    await writeFile(join(directory, 'pipeline/build.ts'), 'changed code')
    await git('add', 'pipeline/build.ts')
    await git(
      '-c',
      'commit.gpgsign=false',
      'commit',
      '-m',
      'Change the fixture build'
    )
    expect(await sourceRevision(directory)).not.toBe(codeRevision)
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})
