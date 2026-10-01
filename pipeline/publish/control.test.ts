import { beforeEach, afterEach, expect, test } from 'bun:test'
import { Database } from 'bun:sqlite'
import { readFileSync } from 'node:fs'
import { sqliteD1 } from '../../apps/api/test/database'
import {
  acquire,
  activate,
  guardedBatch,
  protectedReleases,
  release,
} from './control'
let sqlite: Database, db: ReturnType<typeof sqliteD1>
const R1 = 'r-' + '1'.repeat(32),
  R2 = 'r-' + '2'.repeat(32),
  R3 = 'r-' + '3'.repeat(32),
  sha = 'a'.repeat(64)
beforeEach(() => {
  sqlite = new Database(':memory:')
  sqlite.exec(
    readFileSync(
      new URL('../../packages/data-contracts/schema.sql', import.meta.url),
      'utf8'
    )
  )
  db = sqliteD1(sqlite)
  for (const id of [R1, R2, R3])
    sqlite.run("INSERT INTO releases VALUES(?,1,'staging',NULL,?,?,?)", [
      id,
      sha,
      'a'.repeat(40),
      'b'.repeat(64),
    ])
})
afterEach(() => sqlite.close())
test('publish and rollback share one exclusive executor', async () => {
  const lease = await acquire(db, 'publisher', R1)
  await expect(acquire(db, 'rollback', R2)).rejects.toThrow('holds the lease')
  await release(db, lease)
  expect((await acquire(db, 'rollback', R2)).owner).toBe('rollback')
})
test('a failed batch leaves both publication state and active release unchanged', async () => {
  const lease = await acquire(db, 'publisher', R1)
  await expect(
    guardedBatch(db, lease, [
      db
        .prepare("UPDATE releases SET state='published' WHERE release_id=?")
        .bind(R1),
      db.prepare('INSERT INTO publish_guard VALUES(0)'),
    ])
  ).rejects.toThrow()
  expect(
    await db
      .prepare('SELECT state FROM releases WHERE release_id=?')
      .bind(R1)
      .first<{ state: string }>()
  ).toEqual({ state: 'staging' })
  expect(await db.prepare('SELECT * FROM active_release').first()).toBeNull()
})
test('a stale attempt cannot reactivate its candidate after rollback, even when the release ID is the same', async () => {
  const initial = await acquire(db, 'initial', R1)
  await activate(
    db,
    initial,
    'https://raw.githubusercontent.com/wwwyo/fudoki/' +
      'a'.repeat(40) +
      '/pipeline/publish/manifest.json',
    sha
  )
  await release(db, initial)
  const stale = await acquire(db, 'stale', R2)
  sqlite.run('UPDATE publish_control SET expires_at=0')
  const rollback = await acquire(db, 'rollback', R1)
  await activate(
    db,
    rollback,
    'https://raw.githubusercontent.com/wwwyo/fudoki/' +
      'a'.repeat(40) +
      '/pipeline/publish/manifest.json',
    sha
  )
  await release(db, rollback)
  await expect(
    activate(
      db,
      stale,
      'https://raw.githubusercontent.com/wwwyo/fudoki/' +
        'b'.repeat(40) +
        '/pipeline/publish/manifest.json',
      sha
    )
  ).rejects.toThrow()
  expect(
    await db
      .prepare('SELECT release_id,generation FROM active_release')
      .first<{ release_id: string; generation: number }>()
  ).toEqual({ release_id: R1, generation: 2 })
  expect(
    await db
      .prepare('SELECT state FROM releases WHERE release_id=?')
      .bind(R2)
      .first<{ state: string }>()
  ).toEqual({ state: 'staging' })
})
test('manifest mismatch cannot publish and cleanup protects active, retained and running candidate releases', async () => {
  const lease = await acquire(db, 'publisher', R1)
  await expect(
    activate(
      db,
      lease,
      'https://raw.githubusercontent.com/wwwyo/fudoki/' +
        'a'.repeat(40) +
        '/pipeline/publish/manifest.json',
      'b'.repeat(64)
    )
  ).rejects.toThrow()
  expect((await protectedReleases(db)).has(R1)).toBe(true)
  await activate(
    db,
    lease,
    'https://raw.githubusercontent.com/wwwyo/fudoki/' +
      'a'.repeat(40) +
      '/pipeline/publish/manifest.json',
    sha
  )
  await release(db, lease)
  const next = await acquire(db, 'next', R2)
  expect(await protectedReleases(db)).toEqual(new Set([R1, R2]))
  await release(db, next)
})
