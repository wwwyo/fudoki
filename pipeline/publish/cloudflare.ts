import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  distributionKeySchema,
  type D1Database,
  type D1Statement,
} from '@fudoki/data-contracts'
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
          'Cloudflare D1 batch failed; imported rows remain visible'
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

export function cloudflareObjects(
  bucket: string,
  publicBase: string
): ObjectStore {
  if (!/^[a-z0-9-]{3,63}$/.test(bucket))
    throw new Error('Invalid R2 bucket name')
  return {
    async read(key) {
      const response = await fetch(
        new URL(key, publicBase.endsWith('/') ? publicBase : publicBase + '/'),
        { cache: 'no-store' }
      )
      if (response.status === 404) return null
      if (!response.ok)
        throw new Error(`Public R2 read failed: ${response.status}`)
      return new Uint8Array(await response.arrayBuffer())
    },
    async put(key, path, contentType) {
      if (!distributionKeySchema.safeParse(key).success)
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

export function schemaStatements(sql: string): string[] {
  const statements: string[] = []
  let remaining = sql.trim()
  while (remaining) {
    const statement = remaining.startsWith('CREATE TRIGGER')
      ? remaining.match(/^CREATE TRIGGER[\s\S]*?END;/)?.[0]
      : remaining.match(/^[^;]+;/)?.[0]
    if (!statement) throw new Error('Invalid schema statement')
    statements.push(statement)
    remaining = remaining.slice(statement.length).trim()
  }
  return statements
}

export async function initializeSchema(db: D1Database) {
  const old = await db
    .prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('fiscal_jurisdiction_versions','releases','active_release','fiscal_lines','amounts','publications','publish_control')"
    )
    .all<{ name: string }>()
  if (old.results.length)
    throw new Error(
      'Use a fresh D1 database for the new fiscal contract; legacy storage is not deleted automatically'
    )
  const columns = await db
    .prepare('PRAGMA table_info(jurisdiction_master)')
    .all<{ name: string }>()
  if (columns.results.some((column) => column.name === 'release_id'))
    throw new Error('Use a fresh D1 database for the new fiscal contract')
  const sql = await readFile(
    new URL('../../packages/data-contracts/schema.sql', import.meta.url),
    'utf8'
  )
  for (const statement of schemaStatements(sql))
    await db.prepare(statement).run()
}
