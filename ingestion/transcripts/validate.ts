import { Manifest, fetchTargets } from './gates'

// 静的 import にすると JSON が壊れているときにパースエラーで異常終了し、
// どこが壊れているかを出せない。読み込みも自分で握る。
const path = new URL('../../data/transcripts/gates.json', import.meta.url).pathname
let raw: unknown
try {
  raw = JSON.parse(await Bun.file(path).text())
} catch (e) {
  console.error(`✗ transcript-gates.json を JSON として読めません\n  ${e instanceof Error ? e.message : String(e)}`)
  process.exit(1)
}

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
  if (t.gate.fetch === 'allow' && !t.transcriptUrl) errors.push(`${code} ${j.name}: fetch=allow なのに transcriptUrl が無い（driver が取得先を引けない）`)
  if (t.systemFamily === 'dnp' && !t.tenant) errors.push(`${code} ${j.name}: dnp なのに tenant が無い`)
  // driver は tenant 名ではなく tenantId で API を叩く。
  // ただし tenantId の取得自体が Disallow 経路への問い合わせなので、
  // 照会が通って fetch=allow になる時点までは欠けていてよい。
  if (t.systemFamily === 'dnp' && t.gate.fetch === 'allow' && t.tenantId === undefined)
    errors.push(`${code} ${j.name}: fetch=allow の dnp なのに tenantId が無い`)
  if (t.gate.fetch === 'allow' && t.gate.constraints.some((c) => c === 'rep-path-disallowed' || c === 'rep-render-still-disallowed' || c === 'publisher-ai-opt-out' || c === 'technical-block' || c === 'no-source'))
    errors.push(`${code} ${j.name}: fetch=allow なのに取得を止める constraint がある`)
  if (t.gate.fetch !== 'allow' && t.gate.constraints.length === 0) errors.push(`${code} ${j.name}: fetch=${t.gate.fetch} なのに理由（constraints）が無い`)
  // 再配布は著作権・規約の確認が済むまで allow にできない
  if (t.gate.redistribute === 'allow' && t.gate.constraints.some((c) => c === 'copyright-unverified' || c === 'terms-unverified'))
    errors.push(`${code} ${j.name}: redistribute=allow なのに権利関係が未確認`)
  if (t.robots.aiCrawler === 'disallowed' && t.gate.fetch === 'allow') errors.push(`${code} ${j.name}: AI クローラ拒否なのに fetch=allow`)
  if (t.gate.policyVersion !== m.policy.version) errors.push(`${code} ${j.name}: policyVersion が現在の policy (${m.policy.version}) と異なる`)
  for (const c of t.gate.constraints)
    if (!(c in m.policy.constraints)) errors.push(`${code} ${j.name}: constraint ${c} が policy に定義されていない`)
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
console.log(`  fetch          ${line(count((j) => j.transcript.gate.fetch))}`)
console.log(`  redistribute   ${line(count((j) => j.transcript.gate.redistribute))}`)
const constraints = js
  .flatMap(([, j]) => j.transcript.gate.constraints)
  .reduce<Record<string, number>>((a, c) => ((a[c] = (a[c] ?? 0) + 1), a), {})
console.log(`  constraints    ${line(constraints)}`)

const targets = fetchTargets(m)
if (targets.length !== js.filter(([, j]) => j.transcript.gate.fetch === 'allow').length) {
  console.error('✗ fetch=allow の団体のうち取得先 URL を引けないものがある')
  process.exit(1)
}
console.log(`\n  取得してよい   ${targets.length} 団体`)
console.log(`  照会待ち       ${js.filter(([, j]) => j.transcript.gate.fetch === 'review').length} 団体`)
console.log(`  再配布可       ${js.filter(([, j]) => j.transcript.gate.redistribute === 'allow').length} 団体（権利確認が済むまで 0）`)
