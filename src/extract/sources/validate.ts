import { Manifest, eligibleJurisdictions } from './schema'
import raw from './manifest.json'

const parsed = Manifest.safeParse(raw)

if (!parsed.success) {
  console.error('✗ manifest.json がスキーマに適合していません\n')
  for (const issue of parsed.error.issues) {
    console.error(`  ${issue.path.join('.')}: ${issue.message}`)
  }
  process.exit(1)
}

const m = parsed.data
const js = Object.entries(m.jurisdictions)

// スキーマでは表現できない整合性をここで見る
const errors: string[] = []
for (const [code, j] of js) {
  const t = j.transcript
  if (!j.ocdId.endsWith(`city:${code}`)) errors.push(`${code} ${j.name}: ocdId が団体コードと不一致`)
  if (t.systemFamily === 'none' && t.transcriptUrl) errors.push(`${code} ${j.name}: systemFamily=none なのに transcriptUrl がある`)
  if (t.systemFamily === 'dnp' && !t.tenant) errors.push(`${code} ${j.name}: dnp なのに tenant が無い`)
  if (t.fetchPolicy.eligible !== (t.fetchPolicy.blockedBy === null)) errors.push(`${code} ${j.name}: eligible と blockedBy が矛盾`)
  if (t.fetchPolicy.revisitable && t.fetchPolicy.blockedBy !== 'permission') errors.push(`${code} ${j.name}: revisitable なのに blockedBy が permission でない`)
  if (t.robots.aiCrawler === 'disallowed' && t.fetchPolicy.eligible) errors.push(`${code} ${j.name}: AI クローラ拒否なのに eligible`)
}

if (errors.length) {
  console.error('✗ 整合性エラー\n')
  errors.forEach((e) => console.error('  ' + e))
  process.exit(1)
}

const count = <T extends string>(f: (j: (typeof js)[number][1]) => T) =>
  js.reduce<Record<string, number>>((a, [, j]) => ((a[f(j)] = (a[f(j)] ?? 0) + 1), a), {})

const line = (o: Record<string, number>) =>
  Object.entries(o)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k}=${v}`)
    .join('  ')

console.log(`✓ manifest.json は妥当（${js.length} 団体・${m.generatedAt} 実測）\n`)
console.log(`  systemFamily   ${line(count((j) => j.transcript.systemFamily))}`)
console.log(`  robots         ${line(count((j) => j.transcript.robots.verdict))}`)
console.log(`  aiCrawler      ${line(count((j) => j.transcript.robots.aiCrawler))}`)
console.log(`  reason         ${line(count((j) => j.transcript.fetchPolicy.reason))}`)
console.log(`\n  取得対象       ${eligibleJurisdictions(m).length} 団体`)
console.log(`  許諾で解除可   ${js.filter(([, j]) => j.transcript.fetchPolicy.revisitable).length} 団体`)
