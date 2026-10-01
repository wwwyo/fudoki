import { expect, test } from 'bun:test'
import { Database } from 'bun:sqlite'
import { readFile } from 'node:fs/promises'
import { sqliteD1 } from '../../apps/api/test/database'
import { initializeSchema } from './cloudflare'

test('initialization replaces the empty pre-publication metadata columns and remains repeatable', async () => {
  const sqlite = new Database(':memory:')
  try {
    const sql = await readFile(
      new URL('../../packages/data-contracts/schema.sql', import.meta.url),
      'utf8'
    )
    sqlite.exec(
      sql
        .replace('manifest_url', 'manifest_key')
        .replace('verification_sha256', 'manifest_sha256')
    )
    await initializeSchema(sqliteD1(sqlite))
    await initializeSchema(sqliteD1(sqlite))
    const columns = sqlite.query('PRAGMA table_info(releases)').all() as {
      name: string
    }[]
    expect(columns.map((column) => column.name)).toContain('manifest_url')
    expect(columns.map((column) => column.name)).toContain(
      'verification_sha256'
    )
    expect(columns.map((column) => column.name)).not.toContain('manifest_key')
  } finally {
    sqlite.close()
  }
})

test('initialization refuses to reinterpret existing publication data', async () => {
  const sqlite = new Database(':memory:')
  try {
    const sql = await readFile(
      new URL('../../packages/data-contracts/schema.sql', import.meta.url),
      'utf8'
    )
    sqlite.exec(
      sql
        .replace('manifest_url', 'manifest_key')
        .replace('verification_sha256', 'manifest_sha256')
    )
    sqlite
      .prepare(
        "INSERT INTO releases(release_id,contract_version,state,code_revision,input_fingerprint) VALUES(?,1,'published',?,?)"
      )
      .run('r-' + '1'.repeat(32), 'a'.repeat(40), 'b'.repeat(64))
    await expect(initializeSchema(sqliteD1(sqlite))).rejects.toThrow(
      'explicit schema reconstruction'
    )
    expect(
      sqlite.query('SELECT count(*) AS count FROM releases').get()
    ).toEqual({ count: 1 })
  } finally {
    sqlite.close()
  }
})
