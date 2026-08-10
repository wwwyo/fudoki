/**
 * 議会だより CSV を実際に取得し、jp-municipal-bulletin/1.0 との適合を測る。
 * manifest の openData.gikaiDayori.schemaCheck はこのスクリプトの出力から作る
 * （手で書かない）。ネットワークを叩くので CI では回さない。
 *
 *   bun run scripts/check-bulletins.ts            # 結果を表示
 *   bun run scripts/check-bulletins.ts --write    # manifest へ書き戻す
 */
import { checkConformance, toRow, BULLETIN_SCHEMA_ID } from '../src/schema/jp-municipal-bulletin'
import { Manifest } from '../src/extract/sources/schema'

const UA = 'kotonoha/0.1 (+https://github.com/wwwyo/kotonoha)'
const MANIFEST = new URL('../src/extract/sources/manifest.json', import.meta.url).pathname
const write = process.argv.includes('--write')

const m = Manifest.parse(JSON.parse(await Bun.file(MANIFEST).text()))
const targets = Object.entries(m.jurisdictions).flatMap(([code, j]) => {
  const g = j.openData.gikaiDayori
  return g?.url ? [{ code, name: j.name, url: g.url }] : []
})

/** ヘッダ1行だけ取れれば十分なので、行分割は素朴でよい（引用符内の改行は想定しない） */
function splitCsvLine(line: string): string[] {
  const out: string[] = []
  let cur = '',
    q = false
  for (const ch of line) {
    if (ch === '"') q = !q
    else if (ch === ',' && !q) (out.push(cur), (cur = ''))
    else cur += ch
  }
  out.push(cur)
  return out
}

function decode(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  const utf8 = new TextDecoder('utf-8', { fatal: false }).decode(bytes)
  // cp932 の CSV が UTF-8 として置換文字だらけになるケースを拾う
  return utf8.includes('�') ? new TextDecoder('shift_jis').decode(bytes) : utf8
}

const results: Record<string, unknown> = {}
let conformant = 0,
  variant = 0,
  broken = 0

for (const t of targets) {
  let body: string
  try {
    const res = await fetch(t.url, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(20_000) })
    body = decode(await res.arrayBuffer())
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
  // 1行パースして実際に読めることまで確かめる
  let sample: string | null = null
  const first = rest.find((l) => l.trim())
  if (first) {
    try {
      sample = toRow(header, splitCsvLine(first)).名称
    } catch (e) {
      sample = `parse 失敗: ${e instanceof Error ? e.message.slice(0, 60) : e}`
    }
  }
  results[t.code] = {
    standard: BULLETIN_SCHEMA_ID,
    conformance: r.conformance,
    columns: r.columns,
    extraColumns: r.extra.length ? r.extra : null,
    checkedAt: new Date().toISOString().slice(0, 10),
    note: r.conformance === 'conformant' ? null : `missing=${r.missing.join('/') || 'なし'} extra=${r.extra.join('/') || 'なし'}`,
  }
  if (r.conformance === 'conformant') conformant++
  else {
    variant++
    console.log(`  △ ${t.code} ${t.name} — extra=${r.extra.join(', ') || 'なし'} missing=${r.missing.join(', ') || 'なし'}`)
  }
  if (sample?.startsWith('parse 失敗')) console.log(`     ${sample}`)
}

console.log(`\n${BULLETIN_SCHEMA_ID}: 適合 ${conformant} / 差異 ${variant} / 取得不可 ${broken}  （計 ${targets.length}）`)

if (write) {
  const raw = JSON.parse(await Bun.file(MANIFEST).text())
  for (const [code, sc] of Object.entries(results)) {
    const g = raw.jurisdictions[code]?.openData?.gikaiDayori
    if (g) g.schemaCheck = sc
  }
  await Bun.write(MANIFEST, JSON.stringify(raw, null, 2) + '\n')
  console.log('manifest へ書き戻した')
}
