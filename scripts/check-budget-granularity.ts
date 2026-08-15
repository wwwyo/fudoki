/**
 * 予算・決算系オープンデータを**カタログ横断で探して**取得し、中身の粒度を測る。
 *
 * パーサ設計の原則3「資料名ではなく中身の粒度で判定する」の実装。
 *
 * ⚠️ 過去に2度、母集団の取り方で誤った結論を出している。
 * 1度目は manifest の `openData.budget`（団体ごとの代表1件）だけを見て「事業単位のデータは0件」と判定した。
 * 2度目は organization が `t` + 6桁なら何でも団体として数え、東京都の部局（`t000001` 等）や
 * 都外の団体まで観測に混ぜた（42件中25件が圏外だった）。
 * **母集団は manifest の62団体との積で必ず絞る。**
 *
 * 出力は data/observations/budget-granularity.json。
 * **全候補と失敗理由を残し、団体ごとの最良は派生として別に持つ**（要約ではなく観測を SSOT にする）。
 *
 *   bun run scripts/check-budget-granularity.ts            # 結果を表示
 *   bun run scripts/check-budget-granularity.ts --write    # observations へ書き出す
 */
import { Manifest } from '../src/extract/sources/schema'

const UA = 'fudoki/0.1 (+https://github.com/wwwyo/fudoki)'
const CKAN = 'https://catalog.data.metro.tokyo.lg.jp/api/3/action/package_search'
const MANIFEST = new URL('../src/extract/sources/manifest.json', import.meta.url).pathname
const OUT = new URL('../data/observations/budget-granularity.json', import.meta.url).pathname
const QUERIES = ['歳出', '当初予算', '決算書', '予算データ']
const PAGE = 300
const MAX_BYTES = 20 * 1024 * 1024
const write = process.argv.includes('--write')

/** 到達した粒度。① が「目まで届いているか」だけが本質的な区別 */
type Granularity = 'project' | 'account-item' | 'category' | 'indicator' | 'unchecked'
/** 歳出か歳入か。歳出の粒度を測るのが目的なので、歳入を歳出の代表にしてはいけない */
type Direction = 'expenditure' | 'revenue' | 'unknown'

const RANK: Record<Granularity, number> = { project: 4, 'account-item': 3, category: 2, indicator: 1, unchecked: 0 }

const KEY = {
  /** 「事項」は三鷹、「大事業/中事業/小事業」は狛江の実列名 */
  project: ['事業', '事項', '施策'],
  /** 1文字なので正規化後の完全一致でしか見ない */
  exact: ['款', '項', '目', '節'],
  category: ['目的別', '性質別'],
  indicator: ['比率', '指標', '財政力', '経常収支', '将来負担'],
  amount: ['予算額', '決算額', '金額', '予算計', '執行', '額'],
  /** 「事業者名」「事業所」は事業階層ではない */
  notProject: ['事業者', '事業所', '事業年度'],
  /** CKAN の q は説明文まで全文一致するため、無関係なデータセットが大量に混ざる。表題で足切りする */
  relevant: ['予算', '決算', '歳出', '財政'],
} as const

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
  return out.map((s) => s.replace(/^﻿/, '').trim())
}

/** 列名の連番プレフィックスと単位の括弧を外す（三鷹は `04目`、狛江は `予算額(円)`） */
const norm = (c: string) => c.replace(/^[0-9０-９]+[._\-\s]*/, '').replace(/[（(].*?[）)]/g, '').trim()

function decode(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  const utf8 = new TextDecoder('utf-8', { fatal: false }).decode(bytes)
  return utf8.includes('�') ? new TextDecoder('shift_jis').decode(bytes) : utf8
}

function sniff(bytes: Uint8Array): 'zip' | 'pdf' | 'xls' | 'html' | 'text' {
  const b = Array.from(bytes.slice(0, 8))
  if (b[0] === 0x50 && b[1] === 0x4b) return 'zip'
  if (b[0] === 0x25 && b[1] === 0x50 && b[2] === 0x44 && b[3] === 0x46) return 'pdf'
  if (b[0] === 0xd0 && b[1] === 0xcf) return 'xls'
  const head = new TextDecoder('utf-8', { fatal: false }).decode(bytes.slice(0, 200)).trimStart()
  if (/^<(!DOCTYPE|html)/i.test(head)) return 'html'
  return 'text'
}

/** 歳入と歳出はデータセット名かリソース名にしか書かれていない */
function detectDirection(title: string): Direction {
  const hasRev = title.includes('歳入')
  const hasExp = title.includes('歳出')
  if (hasExp && !hasRev) return 'expenditure'
  if (hasRev && !hasExp) return 'revenue'
  return 'unknown'
}

function classify(header: string[]): { granularity: Granularity; hits: string[] } {
  const cols = header.map(norm)
  const joined = cols.join('|')
  const hasAmount = KEY.amount.some((k) => joined.includes(k))
  const exact = KEY.exact.filter((k) => cols.includes(k))
  // 「事業者名」を事業階層と誤判定しない
  const projectCols = cols.filter((c) => KEY.project.some((k) => c.includes(k)) && !KEY.notProject.some((n) => c.includes(n)))

  if (projectCols.length && exact.includes('目') && hasAmount) return { granularity: 'project', hits: [...projectCols, ...exact] }
  if (exact.includes('目') && hasAmount) return { granularity: 'account-item', hits: exact }
  if ((exact.length || KEY.category.some((k) => joined.includes(k))) && hasAmount) return { granularity: 'category', hits: exact }
  const ind = KEY.indicator.filter((k) => joined.includes(k))
  if (ind.length) return { granularity: 'indicator', hits: ind }
  return { granularity: 'unchecked', hits: [] }
}

const m = Manifest.parse(JSON.parse(await Bun.file(MANIFEST).text()))
/** 母集団は manifest の団体コードに限る。都の部局や都外を混ぜない */
const JURISDICTIONS = new Set(Object.keys(m.jurisdictions))

/** result.count を見て最後まで辿る。打ち切ると「無い」の根拠に使えない */
async function search(q: string) {
  const out: any[] = []
  for (let start = 0; ; start += PAGE) {
    const res = await fetch(`${CKAN}?q=${encodeURIComponent(q)}&rows=${PAGE}&start=${start}`, {
      headers: { 'User-Agent': UA },
      signal: AbortSignal.timeout(40_000),
    })
    const j = await res.json()
    out.push(...j.result.results)
    if (out.length >= j.result.count || j.result.results.length === 0) return { rows: out, total: j.result.count }
  }
}

const packages = new Map<string, any>()
const searchStats: Record<string, number> = {}
for (const q of QUERIES) {
  const { rows, total } = await search(q)
  searchStats[q] = total
  for (const p of rows) packages.set(p.name, p)
}

type Candidate = { code: string; dataset: string; resource: string; url: string; direction: Direction }
const candidates: Candidate[] = []
for (const p of packages.values()) {
  const org: string = p.organization?.name ?? ''
  const code = /^t(\d{6})$/.exec(org)?.[1]
  if (!code || !JURISDICTIONS.has(code)) continue
  for (const r of p.resources ?? []) {
    if ((r.format ?? '').toUpperCase() !== 'CSV') continue
    const name = r.name ?? ''
    if (!KEY.relevant.some((k) => `${p.title} ${name}`.includes(k))) continue
    candidates.push({
      code,
      dataset: p.title,
      resource: name,
      url: r.url,
      direction: detectDirection(`${p.title} ${name}`),
    })
  }
}
console.log(`候補 CSV: ${candidates.length} 件 / ${new Set(candidates.map((c) => c.code)).size} 団体（母集団 ${JURISDICTIONS.size}）\n`)

/** 全候補の観測。失敗も残す */
const observations: any[] = []

for (const c of candidates) {
  const base = { ...c, fetchedAt: new Date().toISOString() }
  let bytes: Uint8Array, status: number
  try {
    const res = await fetch(c.url, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(30_000) })
    status = res.status
    const len = Number(res.headers.get('content-length') ?? 0)
    if (len > MAX_BYTES) {
      await res.body?.cancel()
      observations.push({ ...base, status, granularity: 'unchecked', note: `${(len / 1024 / 1024).toFixed(1)}MB で上限超過` })
      continue
    }
    bytes = new Uint8Array(await res.arrayBuffer())
  } catch (e) {
    observations.push({ ...base, status: null, granularity: 'unchecked', note: `取得できない: ${e instanceof Error ? e.message : e}` })
    continue
  }

  const kind = sniff(bytes)
  const sha256 = new Bun.CryptoHasher('sha256').update(bytes).digest('hex')
  if (kind !== 'text') {
    observations.push({ ...base, status, bytes: bytes.length, sha256, detectedFormat: kind, granularity: 'unchecked', note: `${kind} なので列判定できない` })
    continue
  }

  const lines = decode(bytes.buffer as ArrayBuffer).split(/\r?\n/).filter((l) => l.trim())
  const header = splitCsvLine(lines[0] ?? '')
  const { granularity, hits } = classify(header)
  observations.push({
    ...base,
    status,
    bytes: bytes.length,
    sha256,
    detectedFormat: 'csv',
    rows: lines.length - 1,
    columns: header,
    granularity,
    note: hits.length ? `判定根拠の列: ${hits.join(', ')}` : '粒度を示す列が見つからない',
  })
}

/**
 * 団体ごとの最良は派生。歳出を優先し、歳入を歳出の代表にしない。
 * 判定できなかったものは代表にしない — 無関係な CSV を「その団体の結果」として出すと誤読される。
 */
const best = new Map<string, any>()
for (const o of observations) {
  if (o.direction === 'revenue' || o.granularity === 'unchecked') continue
  const prev = best.get(o.code)
  if (prev && RANK[prev.granularity as Granularity] >= RANK[o.granularity as Granularity]) continue
  best.set(o.code, o)
}
const undecided = new Set(observations.filter((o) => !best.has(o.code)).map((o) => o.code))

const tally: Record<string, number> = {}
for (const [code, b] of [...best].sort()) {
  tally[b.granularity] = (tally[b.granularity] ?? 0) + 1
  const mark = b.granularity === 'project' ? '✓' : b.granularity === 'account-item' ? '◎' : '△'
  console.log(`  ${mark} ${code} ${String(b.granularity).padEnd(13)} ${String(b.rows ?? '-').padStart(5)}行  ${b.dataset.slice(0, 32)}`)
}
console.log(`\n${Object.entries(tally).map(([k, v]) => `${k} ${v}`).join(' / ')}  （判定できた ${best.size} 団体 / 候補はあるが判定できない ${undecided.size} 団体 / 母集団 ${JURISDICTIONS.size}）`)
console.log(`取得失敗・判定不能を含む全候補: ${observations.length} 件`)

if (write) {
  await Bun.write(
    OUT,
    JSON.stringify(
      {
        note: '予算・決算系オープンデータの粒度の実測。カタログのタイトルではなく現物の列構成で判定する（原則3）。母集団は manifest の団体コードに限る（原則4）。observations が全候補で SSOT、bestByJurisdiction は歳出のみを対象にした派生。',
        generatedBy: 'scripts/check-budget-granularity.ts',
        queries: searchStats,
        population: JURISDICTIONS.size,
        observations,
        bestByJurisdiction: Object.fromEntries([...best].sort()),
        undecidedJurisdictions: [...undecided].sort(),
      },
      null,
      2,
    ) + '\n',
  )
  console.log(`\n${OUT} へ書き出した`)
}
