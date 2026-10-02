import { readFile, writeFile, mkdir, appendFile, rm } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { parseArgs } from 'node:util'
import { distributionManifestSchema } from '@fudoki/data-contracts'
import { BUILD, CACHE, LATEST, PIPELINE } from '../paths'
import { verifyCandidate } from '../fdp/manifest'
import { sha256 } from '../release'

const { values } = parseArgs({
  options: {
    'prepare-baseline': { type: 'boolean' },
    baseline: { type: 'string' },
  },
  strict: true,
})
const marker = join(CACHE, 'review/baseline.json')
if (values['prepare-baseline']) {
  if (values.baseline)
    throw new Error('Preparation accepts only the public baseline URL')
  const source = process.env.FUDOKI_REVIEW_BASELINE_URL
  await mkdir(join(CACHE, 'review'), { recursive: true })
  await rm(marker, { force: true })
  if (!source) {
    if (process.env.FUDOKI_REVIEW_INITIAL_RELEASE !== 'true')
      throw new Error(
        'Set the published baseline manifest URL, or explicitly declare an initial publication'
      )
    await writeFile(marker, JSON.stringify({ initialPublication: true }) + '\n')
  } else {
    const url = new URL(source)
    if (
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      (url.protocol !== 'https:' &&
        !(
          url.protocol === 'http:' &&
          ['127.0.0.1', 'localhost'].includes(url.hostname)
        )) ||
      !(
        (url.hostname === 'raw.githubusercontent.com' &&
          /^\/wwwyo\/fudoki\/[a-f0-9]{40}\/pipeline\/publish\/manifest\.json$/.test(
            url.pathname
          )) ||
        (['127.0.0.1', 'localhost'].includes(url.hostname) &&
          url.pathname === '/manifest.json')
      )
    )
      throw new Error('Expected a commit-pinned Git manifest URL')
    const response = await fetch(url)
    if (!response.ok)
      throw new Error(`Baseline manifest fetch failed: ${response.status}`)
    const body = new Uint8Array(await response.arrayBuffer())
    const manifest = distributionManifestSchema.parse(
      JSON.parse(new TextDecoder().decode(body))
    )
    const directory = join(CACHE, 'review', sha256(body))
    await mkdir(directory, { recursive: true })
    for (const file of manifest.files) {
      const result = await fetch(
        new URL(
          '/' + file.objectKey,
          process.env.FUDOKI_DOWNLOAD_BASE_URL ?? 'https://download.fudoki.dev'
        )
      )
      if (!result.ok)
        throw new Error(`Baseline file fetch failed: ${file.path}`)
      const content = new Uint8Array(await result.arrayBuffer())
      if (content.length !== file.bytes || sha256(content) !== file.sha256)
        throw new Error(`Baseline file differs: ${file.path}`)
      const target = join(directory, file.path)
      await mkdir(resolve(target, '..'), { recursive: true })
      await writeFile(target, content)
    }
    await writeFile(join(directory, 'manifest.json'), body)
    await writeFile(
      marker,
      JSON.stringify({ directory, manifestSha256: sha256(body) }) + '\n'
    )
  }
  console.log(JSON.stringify({ prepared: true, marker }))
} else {
  if (!LATEST) throw new Error('A verified candidate is required')
  const directory = join(BUILD, 'builds', LATEST.releaseId)
  await verifyCandidate(directory)
  let baseline = values.baseline
  if (!baseline) {
    const fixed = JSON.parse(await readFile(marker, 'utf8')) as {
      directory?: string
      initialPublication?: boolean
    }
    if (!fixed.directory && !fixed.initialPublication)
      throw new Error('A prepared review baseline is required')
    baseline = fixed.directory
  }
  const output = join(BUILD, 'review-summary.json')
  const child = Bun.spawn(
    [
      'uv',
      'run',
      'python',
      '-m',
      'fdp.review',
      '--candidate',
      directory,
      ...(baseline
        ? ['--baseline', resolve(baseline)]
        : ['--initial-publication']),
      '--output',
      output,
    ],
    {
      cwd: PIPELINE,
      stdout: 'inherit',
      stderr: 'inherit',
    }
  )
  if ((await child.exited) !== 0)
    throw new Error('Semantic release review failed')
  if (process.env.GITHUB_STEP_SUMMARY)
    await appendFile(
      process.env.GITHUB_STEP_SUMMARY,
      await readFile(join(BUILD, 'review-summary.md'))
    )
}
