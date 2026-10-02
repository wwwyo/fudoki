import { Database } from 'bun:sqlite'
import type { D1Database, D1Statement } from '@fudoki/data-contracts'

export function sqliteD1(sqlite: Database): D1Database {
  const records = new WeakMap<D1Statement, { sql: string; values: unknown[] }>()
  function execute<T>(sql: string, values: unknown[]) {
    const results = sqlite.query(sql).all(...(values as any[])) as T[]
    const changes = (
      sqlite.query('SELECT changes() AS changes').get() as { changes: number }
    ).changes
    return { success: true, results, meta: { changes } }
  }
  function statement(sql: string, values: unknown[] = []): D1Statement {
    const instance: D1Statement = {
      bind(...args) {
        return statement(sql, args)
      },
      async all<T>() {
        return execute<T>(sql, values)
      },
      async first<T>() {
        return sqlite.query(sql).get(...(values as any[])) as T | null
      },
      async run() {
        return {
          success: true,
          meta: {
            changes: sqlite.query(sql).run(...(values as any[])).changes,
          },
        }
      },
    }
    records.set(instance, { sql, values })
    return instance
  }
  return {
    prepare: (sql) => statement(sql),
    async batch<T>(statements: D1Statement[]) {
      return sqlite.transaction(() =>
        statements.map((s) => {
          const { sql, values } = records.get(s)!
          return execute<T>(sql, values)
        })
      )()
    },
  }
}
