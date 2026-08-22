/**
 * 議会だより CSV を実際に取得し、このプロファイルとの適合を測る。
 * manifest の openData.gikaiDayori.schemaCheck はこのスクリプトの出力から作る
 * （手で書かない）。ネットワークを叩くので CI では回さない。
 *
 *   bun run scripts/check-bulletins.ts            # 結果を表示
 *   bun run scripts/check-bulletins.ts --write    # manifest へ書き戻す
 */
import { checkConformance, toRow, BULLETIN_SCHEMA_ID } from './bulletin-profile'
import { UA, decodeText, loadManifest, MANIFEST_PATH, splitCsvLine } from '../lib/source'

const write = process.argv.includes('--write')

const m = await loadManifest()
const targets = Object.entries(m.jurisdictions).flatMap(([code, j]) => {
  const g = j.openData.gikaiDayori
  return g?.url ? [{ code, name: j.name, url: g.url }] : []
})

const results: Record<string, unknown> = {}
let conformant = 0,
  variant = 0,
  broken = 0

for (const t of targets) {
  let body: string
  try {
    const res = await fetch(t.url, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(20_000) })
    body = decodeText(new Uint8Array(await res.arrayBuffer()))
  } catch (e) {
    results[t.code] = {
      standard: BULLETIN_SCHEMA_ID,
      conformance: 'broken',
      columns: null,
      extraColumns: null,
      checkedAt: new Date().toISOString().slice(0, 10),
      note: `取得できない: ${e instanceof Error ? e.message : e}`,
    }
    broken++
    console.log(`  ✗ ${t.code} ${t.name} — 取得できない`)
    continue
  }
  if (/^\s*<(!DOCTYPE|html)/i.test(body)) {
    results[t.code] = {
      standard: BULLETIN_SCHEMA_ID,
      conformance: 'broken',
      columns: null,
      extraColumns: null,
      checkedAt: new Date().toISOString().slice(0, 10),
      note: 'CSV ではなく HTML が返る',
    }
    broken++
    console.log(`  ✗ ${t.code} ${t.name} — HTML が返る`)
    continue
  }
  const [head, ...rest] = body.split(/\r?\n/)
  const header = splitCsvLine(head ?? '')
  const r = checkConformance(header)
  // ヘッダが合っていても中身が読めなければ適合とは言えないので、全行を通す
  const rows = rest.filter((l) => l.trim())
  const failures: string[] = []
  for (const [i, line] of rows.entries()) {
    try {
      toRow(header, splitCsvLine(line))
    } catch (e) {
      failures.push(`${i + 2}行目: ${e instanceof Error ? e.message.slice(0, 60) : e}`)
      if (failures.length >= 3) break
    }
  }
  // parse に失敗する行があれば conformance を下げる（以前はログを出すだけで結果に反映していなかった）
  const conformance = failures.length ? 'broken' : r.conformance
  results[t.code] = {
    standard: BULLETIN_SCHEMA_ID,
    conformance,
    rows: rows.length,
    rowFailures: failures.length ? failures : null,
    columns: r.columns,
    extraColumns: r.extra.length ? r.extra : null,
    checkedAt: new Date().toISOString().slice(0, 10),
    note: failures.length
      ? `${failures.length} 行が parse 失敗: ${failures[0]}`
      : r.conformance === 'conformant'
        ? null
        : `missing=${r.missing.join('/') || 'なし'} extra=${r.extra.join('/') || 'なし'}`,
  }
  if (conformance === 'conformant') conformant++
  else if (conformance === 'broken') {
    broken++
    console.log(`  ✗ ${t.code} ${t.name} — ${failures.length} 行 parse 失敗  ${failures[0]}`)
  } else {
    variant++
    console.log(`  △ ${t.code} ${t.name} — extra=${r.extra.join(', ') || 'なし'} missing=${r.missing.join(', ') || 'なし'}`)
  }
}

console.log(`\n${BULLETIN_SCHEMA_ID}: 適合 ${conformant} / 差異 ${variant} / 取得不可 ${broken}  （計 ${targets.length}）`)

if (write) {
  const raw = JSON.parse(await Bun.file(MANIFEST_PATH).text())
  for (const [code, sc] of Object.entries(results)) {
    const g = raw.jurisdictions[code]?.openData?.gikaiDayori
    if (g) g.schemaCheck = sc
  }
  await Bun.write(MANIFEST_PATH, JSON.stringify(raw, null, 2) + '\n')
  console.log('manifest へ書き戻した')
}
