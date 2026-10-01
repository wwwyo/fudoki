import { readdir, readFile } from 'node:fs/promises'
import { dirname, join, resolve, relative } from 'node:path'
import { REPO } from '../paths'

async function files(directory: string): Promise<string[]> {
  const out: string[] = []
  for (const item of await readdir(directory, { withFileTypes: true })) {
    if (
      [
        'node_modules',
        'dist',
        'build',
        '.cache',
        '.wrangler',
        '.cloudflare',
        '.git',
      ].includes(item.name)
    )
      continue
    const path = join(directory, item.name)
    if (
      item.name.endsWith('.test.ts') ||
      item.name.endsWith('.test.tsx') ||
      item.name === 'test'
    )
      continue
    if (item.isDirectory()) out.push(...(await files(path)))
    else if (item.isFile() && /\.(?:ts|tsx|js|mjs|jsonc)$/.test(path))
      out.push(path)
  }
  return out
}
for (const root of ['apps', 'packages'])
  for (const path of await files(join(REPO, root))) {
    const body = await readFile(path, 'utf8')
    for (const match of body.matchAll(
      /(?:from\s*|import\s*\(|require\s*\()\s*['"]([^'"]+)['"]/g
    )) {
      const name = match[1]!,
        target = name.startsWith('.')
          ? relative(REPO, resolve(dirname(path), name))
          : name
      if (
        root === 'apps' &&
        (target.startsWith('pipeline/') ||
          name === '@fudoki/report' ||
          name.startsWith('@fudoki/report/'))
      )
        throw new Error(
          `Public app imports pipeline internals: ${relative(REPO, path)}`
        )
      if (
        root === 'packages' &&
        (target.startsWith('pipeline/') ||
          target.startsWith('apps/') ||
          name === '@fudoki/report' ||
          /^@fudoki\/(?:api|pipeline)/.test(name))
      )
        throw new Error(
          `Shared package imports an application: ${relative(REPO, path)}`
        )
    }
  }
const apiConfig = await readFile(
  join(REPO, 'apps/api/cloudflare.config.ts'),
  'utf8'
)
if (/\b(?:assets\s*:|bindings\.(?:r2|assets)\s*\()/.test(apiConfig))
  throw new Error(
    'API must query D1 and return download URLs without a data assets or R2 binding'
  )
async function publishedFiles(directory: string): Promise<string[]> {
  const out: string[] = []
  for (const item of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, item.name)
    if (item.isDirectory()) out.push(...(await publishedFiles(path)))
    else out.push(path)
  }
  return out
}
for (const path of await publishedFiles(join(REPO, 'apps/web/dist'))) {
  const name = relative(join(REPO, 'apps/web/dist'), path)
  if (
    /(?:^|\/)(?:pipeline|preview|ocr|provenance)(?:\.|\/|$)|\.(?:pdf|parquet|csv|duckdb|jsonl)$/.test(
      name
    )
  )
    throw new Error(`Private pipeline output in public web: ${name}`)
}
console.log(
  JSON.stringify({
    publicAppsIndependent: true,
    sharedPackagesIndependent: true,
    publicWebContainsNoPipelineOutputs: true,
  })
)
