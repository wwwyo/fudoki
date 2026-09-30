import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { D1Database, D1Statement } from '@fudoki/data-contracts'
import type { ObjectStore } from './publish'

const exec = promisify(execFile)
type Statement = { sql: string; params: unknown[] }
type Result = {
  success: boolean
  results: Record<string, unknown>[]
  meta: { changes: number; rows_read?: number; rows_written?: number }
}

/** Use cf's authenticated REST batch without interpolating values into SQL. */
export function cloudflareD1(databaseId: string): D1Database {
  if (!/^[a-f0-9-]{36}$/.test(databaseId))
    throw new Error('Invalid D1 database ID')
  const statements = new WeakMap<D1Statement, Statement>()
  async function query(batch: Statement[]): Promise<Result[]> {
    if (!batch.length) return []
    const directory = await mkdtemp(join(tmpdir(), 'fudoki-d1-'))
    try {
      const path = join(directory, 'batch.json')
      await writeFile(path, JSON.stringify(batch), { mode: 0o600 })
      let stdout: string
      try {
        ;({ stdout } = await exec(
          'cf',
          ['d1', 'query', databaseId, '--batch', `@${path}`, '--quiet'],
          { maxBuffer: 32 * 1024 * 1024 }
        ))
      } catch {
        throw new Error(
          'Cloudflare D1 batch failed; publication remains incomplete'
        )
      }
      const result = JSON.parse(stdout) as Result[]
      if (
        !Array.isArray(result) ||
        result.length !== batch.length ||
        result.some((r) => !r.success || !Array.isArray(r.results))
      )
        throw new Error('Unexpected Cloudflare D1 response')
      return result
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  }
  function statement(sql: string, params: unknown[] = []): D1Statement {
    const instance: D1Statement = {
      bind(...values) {
        return statement(sql, values)
      },
      async all<T>() {
        const r = (await query([{ sql, params }]))[0]!
        return { ...r, results: r.results as T[] }
      },
      async first<T>() {
        return (
          ((await query([{ sql, params }]))[0]!.results[0] as T | undefined) ??
          null
        )
      },
      async run() {
        const r = (await query([{ sql, params }]))[0]!
        return { success: r.success, meta: r.meta }
      },
    }
    statements.set(instance, { sql, params })
    return instance
  }
  return {
    prepare: (sql) => statement(sql),
    async batch<T>(values: D1Statement[]) {
      const batch = values.map((value) => {
        const record = statements.get(value)
        if (!record) throw new Error('Foreign D1 statement')
        return record
      })
      return (await query(batch)).map((r) => ({
        ...r,
        results: r.results as T[],
      }))
    },
  }
}

export function cloudflareObjects(bucket: string): ObjectStore {
  if (!/^[a-z0-9-]{3,63}$/.test(bucket))
    throw new Error('Invalid R2 bucket name')
  return {
    async put(key, path, contentType) {
      if (
        !/^(?:_candidates|releases)\/r-[a-f0-9]{32}\/(?:manifest\.json|catalog\.json|fiscal\/\d{6}\/[a-z_]+\.(?:csv|json))$/.test(
          key
        )
      )
        throw new Error('Invalid release object key')
      await exec(
        'cf',
        [
          'r2',
          'objects',
          'put',
          key,
          '--bucket-name',
          bucket,
          '--file',
          path,
          '--content-type',
          contentType,
          '--quiet',
        ],
        { maxBuffer: 1024 * 1024 }
      )
    },
  }
}

export async function initializeSchema(db: D1Database) {
  const sql = await readFile(
    new URL('../../packages/data-contracts/schema.sql', import.meta.url),
    'utf8'
  )
  await db.batch(
    sql
      .split(';')
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => db.prepare(part))
  )
}
