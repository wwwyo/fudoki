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
    ).toEqual({ n: 22 })
    expect(
      sqlite
        .query("SELECT count(*) AS n FROM sqlite_master WHERE type='trigger'")
        .get()
    ).toEqual({ n: 24 })
    expect(
      sqlite.query('SELECT identity FROM database_identity').get()
    ).toBeTruthy()
  } finally {
    sqlite.close()
  }
})
test('legacy storage is not silently discarded or reinterpreted', async () => {
  const sqlite = new Database(':memory:')
  try {
    sqlite.exec(
      "CREATE TABLE releases(release_id TEXT); INSERT INTO releases VALUES('old')"
    )
    await expect(initializeSchema(sqliteD1(sqlite))).rejects.toThrow('fresh D1')
    expect(sqlite.query('SELECT * FROM releases').all()).toEqual([
      { release_id: 'old' },
    ])
  } finally {
    sqlite.close()
  }
})
