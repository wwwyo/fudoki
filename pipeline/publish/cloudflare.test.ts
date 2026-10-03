import { expect, test } from 'bun:test'
import { Database } from 'bun:sqlite'
import { sqliteD1 } from '../../apps/api/test/database'
import { initializeSchema } from './cloudflare'

test('fresh initialization installs all typed tables and complete triggers, and is repeatable', async () => {
  const sqlite = new Database(':memory:')
  try {
    await initializeSchema(sqliteD1(sqlite))
    await initializeSchema(sqliteD1(sqlite))
    expect(
      sqlite
        .query("SELECT count(*) AS n FROM sqlite_master WHERE type='table'")
        .get()
    ).toEqual({ n: 23 })
    expect(
      sqlite
        .query("SELECT count(*) AS n FROM sqlite_master WHERE type='trigger'")
        .get()
    ).toEqual({ n: 29 })
    expect(
      sqlite.query('SELECT identity FROM database_identity').get()
    ).toBeTruthy()
  } finally {
    sqlite.close()
  }
})
test('legacy and snapshot storage are not silently discarded or reinterpreted', async () => {
  for (const table of ['releases', 'fiscal_jurisdiction_versions']) {
    const sqlite = new Database(':memory:')
    try {
      sqlite.exec(
        `CREATE TABLE ${table}(version_id TEXT); INSERT INTO ${table} VALUES('old')`
      )
      await expect(initializeSchema(sqliteD1(sqlite))).rejects.toThrow(
        'fresh D1'
      )
      expect(sqlite.query(`SELECT * FROM ${table}`).all()).toEqual([
        { version_id: 'old' },
      ])
    } finally {
      sqlite.close()
    }
  }
})
