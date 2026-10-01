import { resolve, join } from 'node:path'
import { readFileSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'

export const PIPELINE = import.meta.dirname
export const REPO = resolve(PIPELINE, '..')
export const CACHE = join(PIPELINE, '.cache')
export const BUILD = join(PIPELINE, 'build')
export const PUBLICATION_MANIFEST = join(PIPELINE, 'publish/manifest.json')
const latestPath = join(BUILD, 'latest.json')
export const LATEST = existsSync(latestPath)
  ? (JSON.parse(readFileSync(latestPath, 'utf8')) as {
      releaseId: string
      inputLock?: string
    })
  : null
const canonicalLock = join(PIPELINE, 'ingestion/fiscal/sources.lock.json')
export const INPUT_LOCK = resolve(
  process.env.FUDOKI_INPUT_LOCK ??
    (existsSync(canonicalLock)
      ? canonicalLock
      : (LATEST?.inputLock ?? canonicalLock))
)
export const SNAPSHOT = existsSync(INPUT_LOCK)
  ? createHash('sha256').update(readFileSync(INPUT_LOCK)).digest('hex')
  : null
export const INPUTS =
  process.env.FUDOKI_INPUT_DIR ??
  (SNAPSHOT
    ? join(CACHE, 'inputs', SNAPSHOT, 'raw')
    : join(CACHE, 'acquisition', 'raw'))
export const PACKAGES =
  process.env.FUDOKI_PACKAGE_DIR ??
  join(BUILD, 'releases', LATEST?.releaseId ?? 'candidate', 'fiscal')
export const WAREHOUSE = join(BUILD, 'warehouse.duckdb')
export const DBT_TARGET = join(BUILD, 'dbt')
export const REPORT = join(BUILD, 'report')
