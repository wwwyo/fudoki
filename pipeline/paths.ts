// パイプラインの入出力を作業ディレクトリに依存せず解決する。
// 環境変数の相対指定は PIPELINE からの相対とみなす。
// pipeline/ingestion/paths.py と同じ解決規則の twin 実装。片方を変えたらもう片方も同期する。
import { resolve, join } from 'node:path'
import { readFileSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { PIPELINE, CACHE, BUILD } from './runtime_paths'
export { PIPELINE, REPO, CACHE, BUILD, WAREHOUSE, DBT_TARGET, REPORT } from './runtime_paths'

const latestPath = join(BUILD, 'latest.json')
export const LATEST = existsSync(latestPath)
  ? (JSON.parse(readFileSync(latestPath, 'utf8')) as {
      buildId: string
      inputLock?: string
    })
  : null
const anchor = (path: string) => resolve(PIPELINE, path)
const canonicalLock = join(PIPELINE, 'ingestion/fiscal/sources.lock.json')
export const INPUT_LOCK = anchor(
  process.env.FUDOKI_INPUT_LOCK ??
    (existsSync(canonicalLock)
      ? canonicalLock
      : (LATEST?.inputLock ?? canonicalLock))
)
export const SNAPSHOT = existsSync(INPUT_LOCK)
  ? createHash('sha256').update(readFileSync(INPUT_LOCK)).digest('hex')
  : null
export const INPUTS = anchor(
  process.env.FUDOKI_INPUT_DIR ??
    (SNAPSHOT
      ? join(CACHE, 'inputs', SNAPSHOT, 'raw')
      : join(CACHE, 'acquisition', 'raw'))
)
export const PACKAGES = anchor(
  process.env.FUDOKI_PACKAGE_DIR ??
    join(BUILD, 'builds', LATEST?.buildId ?? 'candidate', 'fiscal')
)
