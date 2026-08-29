/**
 * 静的アセット（パーティション JSON と配布物の写し）の読み口と、ファイル形式の型。
 * 形式は build.ts が書き、ここが読む。**両者はこの型で合意する。**
 */
import type { Budget, BudgetLine, CrossBudgetLine, Jurisdiction } from './contract'

export interface Env {
  ASSETS: { fetch(input: Request | URL | string): Promise<Response> }
}

export type JurisdictionsFile = {
  revision: string
  jurisdictions: Jurisdiction[]
  /** 収録している全 budget（id 昇順）。カバレッジの正体 */
  budgets: Budget[]
}
export type LinesFile = { revision: string; lines: BudgetLine[] }
export type CofogChunkFile = { revision: string; hasNext: boolean; lines: CrossBudgetLine[] }
export type FilesFile = {
  revision: string
  files: Record<string, Record<string, { sha256: string; size: number; contentType: string }>>
}

/** アセットのパスは binding には URL として渡す（ホスト名は何でもよい） */
export async function readAsset(env: Env, path: string): Promise<Response> {
  return env.ASSETS.fetch(new URL(path, 'https://assets.internal/').toString())
}

export async function readJsonAsset<T>(env: Env, path: string): Promise<T | null> {
  const res = await readAsset(env, path)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`asset read failed: ${path} -> ${res.status}`)
  return (await res.json()) as T
}

export const paths = {
  jurisdictions: 'meta/jurisdictions.json',
  files: 'meta/files.json',
  lines: (jurisdiction: string, fiscalYear: string, direction: string) =>
    `lines/${jurisdiction}/${fiscalYear}-${direction}.json`,
  cofogChunk: (family: string, chunk: number) => `${family}/${chunk}.json`,
  cofogFamily: (division: string, fiscalYear: string | undefined) =>
    fiscalYear === undefined ? `cofog/${division}/all` : `cofog/${division}/${fiscalYear}`,
  passthrough: (jurisdiction: string, file: string) => `datapackages/${jurisdiction}/${file}`,
}
