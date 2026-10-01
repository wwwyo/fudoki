import { expect, test } from 'bun:test'
import { Database } from 'bun:sqlite'
import { readFile } from 'node:fs/promises'
import { sqliteD1 } from '../../apps/api/test/database'
import { initializeSchema } from './cloudflare'

test('initialization replaces only empty legacy classification storage and installs the master foreign key', async () => {
  for (const populated of [false, true]) {
    const sqlite = new Database(':memory:')
    try {
      const sql = await readFile(
        new URL('../../packages/data-contracts/schema.sql', import.meta.url),
        'utf8'
      )
      sqlite.exec(
        sql.replace(
          /CREATE TABLE IF NOT EXISTS fiscal_lines \([\s\S]*?\);/,
          'CREATE TABLE fiscal_lines(release_id TEXT,fiscal_line_id TEXT,dataset_id TEXT,source_row INTEGER,fund_code TEXT,fund_label TEXT,PRIMARY KEY(release_id,fiscal_line_id));'
        )
      )
      sqlite.exec(
        'CREATE TABLE cofog(release_id TEXT,fiscal_line_id TEXT,status TEXT)'
      )
      if (populated)
        sqlite.run(
          "INSERT INTO fiscal_lines VALUES('unused','line','dataset',1,'01','一般会計')"
        )
      if (populated) {
        await expect(initializeSchema(sqliteD1(sqlite))).rejects.toThrow(
          'Existing classification data'
        )
        expect(
          sqlite.query('SELECT count(*) AS count FROM fiscal_lines').get()
        ).toEqual({ count: 1 })
      } else {
        await initializeSchema(sqliteD1(sqlite))
        expect(
          sqlite
            .query("SELECT name FROM sqlite_master WHERE name='cofog'")
            .get()
        ).toBeNull()
        expect(
          (
            sqlite.query('PRAGMA foreign_key_list(fiscal_lines)').all() as {
              table: string
            }[]
          ).map((fk) => fk.table)
        ).toContain('cofog_codes')
        await initializeSchema(sqliteD1(sqlite))
      }
    } finally {
      sqlite.close()
    }
  }
})

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

test('initialization separates an empty legacy jurisdiction table and refuses to discard its populated rows', async () => {
  for (const populated of [false, true]) {
    const sqlite = new Database(':memory:')
    try {
      const sql = await readFile(
        new URL('../../packages/data-contracts/schema.sql', import.meta.url),
        'utf8'
      )
      sqlite.exec(
        sql.replace(
          ',\n  FOREIGN KEY (release_id, jurisdiction_code) REFERENCES release_jurisdictions(release_id, jurisdiction_code)',
          ''
        )
      )
      sqlite.exec(
        'DROP TABLE jurisdictions; CREATE TABLE jurisdictions(release_id TEXT,jurisdiction_code TEXT,name TEXT,ocd_id TEXT,caveats_json TEXT,PRIMARY KEY(release_id,jurisdiction_code))'
      )
      if (populated)
        sqlite.run('INSERT INTO jurisdictions VALUES(?,?,?,?,?)', [
          'unused',
          '000001',
          '団体',
          'test',
          '[]',
        ])
      if (populated) {
        await expect(initializeSchema(sqliteD1(sqlite))).rejects.toThrow(
          'Existing jurisdiction data'
        )
        expect(
          sqlite.query('SELECT count(*) AS count FROM jurisdictions').get()
        ).toEqual({ count: 1 })
      } else {
        await initializeSchema(sqliteD1(sqlite))
        expect(
          (
            sqlite.query('PRAGMA table_info(jurisdictions)').all() as {
              name: string
              pk: number
            }[]
          )
            .filter((c) => c.pk)
            .map((c) => c.name)
        ).toEqual(['jurisdiction_code'])
        expect(
          (
            sqlite.query('PRAGMA foreign_key_list(fiscal_datasets)').all() as {
              table: string
            }[]
          ).map((fk) => fk.table)
        ).toContain('release_jurisdictions')
        await initializeSchema(sqliteD1(sqlite))
      }
    } finally {
      sqlite.close()
    }
  }
})
