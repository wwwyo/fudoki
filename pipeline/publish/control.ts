import type { D1Database, D1Statement } from '@fudoki/data-contracts'

export type Lease = {
  owner: string
  fence: number
  expectedReleaseId: string | null
  expectedGeneration: number
  candidateReleaseId: string
}
const TTL_SECONDS = 600
export async function acquire(
  db: D1Database,
  owner: string,
  candidateReleaseId: string
): Promise<Lease> {
  const update = await db
    .prepare(
      `UPDATE publish_control SET owner=?,fence=fence+1,expires_at=unixepoch()+?,
    expected_release_id=(SELECT release_id FROM active_release WHERE singleton=1),
    expected_generation=coalesce((SELECT generation FROM active_release WHERE singleton=1),0),candidate_release_id=?
    WHERE singleton=1 AND expires_at<unixepoch()`
    )
    .bind(owner, TTL_SECONDS, candidateReleaseId)
    .run()
  if (update.meta.changes !== 1)
    throw new Error('Another publish or rollback holds the lease')
  const row = await db
    .prepare(
      'SELECT fence,expected_release_id,expected_generation FROM publish_control WHERE singleton=1 AND owner=?'
    )
    .bind(owner)
    .first<{
      fence: number
      expected_release_id: string | null
      expected_generation: number
    }>()
  if (!row) throw new Error('Publish lease was lost')
  return {
    owner,
    fence: row.fence,
    expectedReleaseId: row.expected_release_id,
    expectedGeneration: row.expected_generation,
    candidateReleaseId,
  }
}
function guard(db: D1Database, lease: Lease): D1Statement {
  return db
    .prepare(
      `INSERT INTO publish_guard(valid) SELECT CASE WHEN EXISTS(
    SELECT 1 FROM publish_control p WHERE p.singleton=1 AND p.owner=? AND p.fence=? AND p.expires_at>unixepoch()
      AND p.candidate_release_id=? AND p.expected_release_id IS ? AND p.expected_generation=?
      AND (SELECT release_id FROM active_release WHERE singleton=1) IS ?
      AND coalesce((SELECT generation FROM active_release WHERE singleton=1),0)=?
  ) THEN 1 ELSE 0 END`
    )
    .bind(
      lease.owner,
      lease.fence,
      lease.candidateReleaseId,
      lease.expectedReleaseId,
      lease.expectedGeneration,
      lease.expectedReleaseId,
      lease.expectedGeneration
    )
}
export async function guardedBatch(
  db: D1Database,
  lease: Lease,
  statements: D1Statement[]
) {
  return db.batch([
    guard(db, lease),
    ...statements,
    db
      .prepare(
        'UPDATE publish_control SET expires_at=unixepoch()+? WHERE singleton=1 AND owner=? AND fence=?'
      )
      .bind(TTL_SECONDS, lease.owner, lease.fence),
    db.prepare('DELETE FROM publish_guard'),
  ])
}
export async function activate(
  db: D1Database,
  lease: Lease,
  manifestKey: string,
  manifestSha256: string
) {
  await guardedBatch(db, lease, [
    db
      .prepare(
        `INSERT INTO publish_guard(valid) SELECT CASE WHEN EXISTS(SELECT 1 FROM releases WHERE release_id=? AND contract_version=1 AND manifest_sha256=?) THEN 1 ELSE 0 END`
      )
      .bind(lease.candidateReleaseId, manifestSha256),
    db
      .prepare(
        "UPDATE releases SET state='published',manifest_key=? WHERE release_id=?"
      )
      .bind(manifestKey, lease.candidateReleaseId),
    db
      .prepare(
        `INSERT INTO active_release(singleton,release_id,generation) VALUES(1,?,?)
      ON CONFLICT(singleton) DO UPDATE SET release_id=excluded.release_id,generation=excluded.generation`
      )
      .bind(lease.candidateReleaseId, lease.expectedGeneration + 1),
    db
      .prepare(
        'INSERT INTO release_history(release_id,generation) VALUES(?,?) ON CONFLICT(release_id) DO UPDATE SET generation=excluded.generation'
      )
      .bind(lease.candidateReleaseId, lease.expectedGeneration + 1),
  ])
}
export async function release(db: D1Database, lease: Lease) {
  await db
    .prepare(
      'UPDATE publish_control SET owner=NULL,expires_at=0,candidate_release_id=NULL WHERE singleton=1 AND owner=? AND fence=?'
    )
    .bind(lease.owner, lease.fence)
    .run()
}
export async function protectedReleases(db: D1Database): Promise<Set<string>> {
  const result = await db
    .prepare(
      `SELECT release_id FROM active_release
    UNION SELECT release_id FROM (SELECT release_id FROM release_history ORDER BY generation DESC LIMIT 3)
    UNION SELECT candidate_release_id AS release_id FROM publish_control WHERE candidate_release_id IS NOT NULL`
    )
    .all<{ release_id: string }>()
  return new Set(result.results.map((r) => r.release_id))
}
