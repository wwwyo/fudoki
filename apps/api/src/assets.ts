/**
 * 静的アセット（パーティション JSON と配布物の写し）の読み口と、ファイル形式の型。
 * 形式は build.ts が書き、ここが読む。**両者はこの型で合意する。**
 */
import type { Budget, BudgetLine, CrossBudgetLine, Jurisdiction } from './contract'

/**
 * KV namespace binding の最小型。`@cloudflare/workers-types` はこの repo に入れていない
 * （tsconfig の types は `@types/bun` のみ）ので、既存の `ASSETS` と同じく使う形だけ手書きする。
 */
export interface KVNamespaceLike {
  get(key: string): Promise<string | null>
  put(key: string, value: string): Promise<void>
}

/**
 * Rate Limiting binding の最小型。`limit()` は成功/失敗の boolean しか返さない
 * （残量やウィンドウ長は取れない）。カウンターはデータセンターごとであり、
 * グローバルな厳密上限にはならない ── ここで実現しているのは濫用の抑制であって、
 * 課金保護のような厳密な上限ではない。
 */
export interface RateLimiterLike {
  limit(options: { key: string }): Promise<{ success: boolean }>
}

export interface Env {
  ASSETS: { fetch(input: Request | URL | string): Promise<Response> }
  /** ベータ用 API キー。KV のキーが SHA-256(生のキー)、値が ApiKeyEntry の JSON（src/lib/apiKey.ts） */
  API_KEYS: KVNamespaceLike
  /** キー無し（匿名）リクエスト用。IP のハッシュをキーにして呼ぶ */
  RATE_LIMIT_ANONYMOUS: RateLimiterLike
  /** 有効な API キー付きリクエスト用。キーIDをキーにして呼ぶ */
  RATE_LIMIT_AUTHENTICATED: RateLimiterLike
}

export type JurisdictionsFile = {
  revision: string
  jurisdictions: Jurisdiction[]
  /** 収録している全 budget（id 昇順）。カバレッジの正体 */
  budgets: Budget[]
}
export type LinesChunkFile = { revision: string; hasNext: boolean; lines: BudgetLine[] }
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

/**
 * パーティションレイアウトの唯一の定義。書き手（build.ts）も読み手（procedure）も
 * ここを経由し、パス文字列を独立に組み立てない。
 * family はページングの pageToken に封入される系列名（拡張子なし）。
 */
export const paths = {
  jurisdictions: 'meta/jurisdictions.json',
  files: 'meta/files.json',
  linesFamily: (jurisdiction: string, fiscalYear: string, direction: string) =>
    `lines/${jurisdiction}/${fiscalYear}-${direction}`,
  chunk: (family: string, chunk: number) => `${family}/${chunk}.json`,
  cofogFamily: (division: string, fiscalYear: string | undefined) =>
    fiscalYear === undefined ? `cofog/${division}/all` : `cofog/${division}/${fiscalYear}`,
  passthrough: (jurisdiction: string, file: string) => `datapackages/${jurisdiction}/${file}`,
}
