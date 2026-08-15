/**
 * 予算・決算系オープンデータを**カタログ横断で探して**取得し、中身の粒度を測る。
 *
 * パーサ設計の原則3「資料名ではなく中身の粒度で判定する」の実装。
 *
 * ⚠️ 初版は manifest の `openData.budget`（団体ごとに代表1件）だけを見ており、
 * 「東京都カタログに事業単位の歳出データは存在しない」という**誤った結論**を出した。
 * 実際には狛江市が28件・多摩市が20件のデータセットを持ち、その中に事業単位のものがある。
 * **代表1件は母集団ではない**（原則4）。だからここでは CKAN を検索して候補を総ざらいする。
 *
 * 結果は data/observations/budget-granularity.json が single source of truth。
 *
 *   bun run scripts/check-budget-granularity.ts            # 結果を表示
 *   bun run scripts/check-budget-granularity.ts --write    # observations へ書き出す
 */
const UA = 'fudoki/0.1 (+https://github.com/wwwyo/fudoki)'
const CKAN = 'https://catalog.data.metro.tokyo.lg.jp/api/3/action/package_search'
const OUT = new URL('../data/observations/budget-granularity.json', import.meta.url).pathname
/** 検索語。件数が跳ねる曖昧語（「事業別」等）は入れない — CKAN の q は部分一致で効きすぎる */
const QUERIES = ['歳出', '当初予算', '決算書', '予算データ']
const MAX_BYTES = 20 * 1024 * 1024
const write = process.argv.includes('--write')

/** 到達した粒度。① が「目まで届いているか」だけが本質的な区別 */
type Granularity =
  | 'project' // 事業（大事業/中事業/事項…）× 金額。目レベルに到達している
  | 'account-item' // 目・節の科目列はあるが事業列が無い
  | 'category' // 款・項どまりの集計
  | 'indicator' // 財政指標。使途ではない
  | 'unchecked' // CSV でない等で列判定できていない

const RANK: Record<Granularity, number> = {
  project: 4,
  'account-item': 3,
  category: 2,
  indicator: 1,
  unchecked: 0,
}

const KEY = {
  /** 「事項」は三鷹、「大事業/中事業/小事業」は狛江の実列名 */
  project: ['事業', '事項', '施策'],
  item: ['目', '節'],
  category: ['款', '項', '目的別', '性質別'],
  indicator: ['比率', '指標', '財政力', '経常収支', '将来負担'],
  amount: ['予算額', '決算額', '金額', '予算計', '執行', '額'],
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

/** 列名の連番プレフィックスを外す（三鷹は `04目` `05事項` のように番号付き） */
const norm = (c: string) => c.replace(/^[0-9０-９]+[._\-\s]*/, '')

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

function classify(header: string[]): { granularity: Granularity; hits: string[] } {
  const cols = header.map(norm)
  const joined = cols.join('|')
  const hasAmount = KEY.amount.some((k) => joined.includes(k))
  const has = (ks: readonly string[]) => ks.filter((k) => joined.includes(k))
  // 「目」「節」は1文字なので列名の完全一致で見る（"科目名称" を拾わないため）
  const item = KEY.item.filter((k) => cols.includes(k))

  const project = has(KEY.project)
  if (project.length && item.length && hasAmount) return { granularity: 'project', hits: [...project, ...item] }
  if (item.length && hasAmount) return { granularity: 'account-item', hits: item }
  const category = has(KEY.category)
  if (category.length && hasAmount) return { granularity: 'category', hits: category }
  const indicator = has(KEY.indicator)
  if (indicator.length) return { granularity: 'indicator', hits: indicator }
  return { granularity: 'unchecked', hits: [] }
}

type Candidate = { code: string; dataset: string; resource: string; url: string }

const packages = new Map<string, any>()
for (const q of QUERIES) {
  const res = await fetch(`${CKAN}?q=${encodeURIComponent(q)}&rows=300`, {
    headers: { 'User-Agent': UA },
    signal: AbortSignal.timeout(40_000),
  })
  for (const p of (await res.json()).result.results) packages.set(p.name, p)
}

const candidates: Candidate[] = []
for (const p of packages.values()) {
  const org: string = p.organization?.name ?? ''
  // 区市町村の org は t + 6桁団体コード。都本体（t130001）は対象外
  const m = /^t(\d{6})$/.exec(org)
  if (!m || m[1] === '130001') continue
  for (const r of p.resources ?? []) {
    if ((r.format ?? '').toUpperCase() !== 'CSV') continue
    candidates.push({ code: m[1]!, dataset: p.title, resource: r.name ?? '', url: r.url })
  }
}
console.log(`候補 CSV リソース: ${candidates.length} 件 / ${new Set(candidates.map((c) => c.code)).size} 団体\n`)

/** 団体ごとに「最も深い粒度に到達した1本」を残す */
const best = new Map<string, any>()

for (const c of candidates) {
  let bytes: Uint8Array, status: number
  try {
    const res = await fetch(c.url, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(30_000) })
    status = res.status
    if (Number(res.headers.get('content-length') ?? 0) > MAX_BYTES) {
      await res.body?.cancel()
      continue
    }
    bytes = new Uint8Array(await res.arrayBuffer())
  } catch {
    continue
  }
  if (sniff(bytes) !== 'text') continue

  const lines = decode(bytes.buffer as ArrayBuffer).split(/\r?\n/).filter((l) => l.trim())
  const header = splitCsvLine(lines[0] ?? '')
  const { granularity, hits } = classify(header)
  const prev = best.get(c.code)
  if (prev && RANK[prev.granularity as Granularity] >= RANK[granularity]) continue

  best.set(c.code, {
    dataset: c.dataset,
    resource: c.resource,
    requestUrl: c.url,
    status,
    bytes: bytes.length,
    sha256: new Bun.CryptoHasher('sha256').update(bytes).digest('hex'),
    rows: lines.length - 1,
    columns: header,
    granularity,
    note: hits.length ? `判定根拠の列: ${hits.join(', ')}` : '粒度を示す列が見つからない',
    fetchedAt: new Date().toISOString(),
  })
}

const tally: Record<string, number> = {}
for (const [code, b] of [...best].sort()) {
  tally[b.granularity] = (tally[b.granularity] ?? 0) + 1
  const mark = b.granularity === 'project' ? '✓' : b.granularity === 'account-item' ? '◎' : '△'
  console.log(`  ${mark} ${code} ${b.granularity.padEnd(13)} ${String(b.rows).padStart(5)}行  ${b.dataset.slice(0, 34)}`)
}
console.log(`\n${Object.entries(tally).map(([k, v]) => `${k} ${v}`).join(' / ')}  （計 ${best.size} 団体）`)
console.log('\n⚠️ 母集団は CKAN の検索語にヒットした団体であって東京62団体ではない（原則4）')

if (write) {
  await Bun.write(
    OUT,
    JSON.stringify(
      {
        note: '予算・決算系オープンデータの粒度の実測。カタログのタイトルではなく現物の列構成で判定する（原則3）。団体ごとに最も深い粒度に到達した1本だけを残す。',
        generatedBy: 'scripts/check-budget-granularity.ts',
        queries: QUERIES,
        jurisdictions: Object.fromEntries([...best].sort()),
      },
      null,
      2,
    ) + '\n',
  )
  console.log(`\n${OUT} へ書き出した`)
}
