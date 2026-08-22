/**
 * **調査スクリプト**。本番の Extract ではない。
 *
 * 東京都オープンデータカタログに、予算がどの粒度で出ているかを調べる。
 * 本番の取得は市町村ごとに pipeline を作り、最終的には公式サイトの PDF から取る。
 * これはその前段として「CSV で出ている団体はどこか、どこまで届いているか」を測るためのもの。
 *
 * 判定は列構成で行う（データセット名では判定しない。パーサ設計の原則3）。
 * 判定規則は scripts/lib/budget-granularity-profile.ts が持つ。
 *
 * ⚠️ 過去に2度、母集団の取り方で誤った結論を出している。
 * 1度目は `data/budget/opendata.json` の代表1件（団体ごとの代表1件）だけを見て「事業単位のデータは0件」と判定した。
 * 2度目は organization が `t` + 6桁なら何でも団体として数え、東京都の部局や都外まで混ぜた（42件中25件が圏外）。
 * **母集団は団体registry のコードとの積で必ず絞る。**
 *
 * 出力はこのスクリプトの隣 ingestion/budget/observations/（ローカル作業ファイル。commit しない）。
 * **全候補と失敗理由だけを持つ**。団体ごとの最良は観測から導けるので焼き込まない。
 *
 *   bun run scripts/check-budget-granularity.ts            # 結果を表示
 *   bun run scripts/check-budget-granularity.ts --write    # observations へ書き出す
 */
import {
  classifyGranularity,
  detectDirection,
  GRANULARITY_RANK,
  RELEVANT_TITLE_WORDS,
  type Direction,
  type Granularity,
} from './granularity-profile'
import { UA, countDataRows, decodeText, fetchCapped, mapWithConcurrency, sha256, sniffContent, splitCsvLine } from '../lib/source'
import { loadJurisdictions } from '../shared/jurisdictions'

const CKAN = 'https://catalog.data.metro.tokyo.lg.jp/api/3/action/package_search'
const OUT = new URL('./observations/budget-granularity.json', import.meta.url).pathname
const QUERIES = ['歳出', '当初予算', '決算書', '予算データ']
const PAGE = 300
const MAX_BYTES = 20 * 1024 * 1024
/** 相手は自治体のサーバ。ホストは団体ごとに分散しているので、この程度なら同一ホストへ集中しない */
const CONCURRENCY = 3
const write = process.argv.includes('--write')

type CkanResource = { format?: string; name?: string; url: string }
type CkanPackage = { name: string; title: string; organization?: { name?: string }; resources?: CkanResource[] }

/** `result.count` まで辿る。打ち切ると「無い」の根拠に使えない */
async function search(q: string): Promise<{ rows: CkanPackage[]; total: number }> {
  const rows: CkanPackage[] = []
  for (let start = 0; ; start += PAGE) {
    const res = await fetch(`${CKAN}?q=${encodeURIComponent(q)}&rows=${PAGE}&start=${start}`, {
      headers: { 'User-Agent': UA },
      signal: AbortSignal.timeout(40_000),
    })
    const j = (await res.json()) as { result: { count: number; results: CkanPackage[] } }
    rows.push(...j.result.results)
    if (rows.length >= j.result.count || j.result.results.length === 0) return { rows, total: j.result.count }
  }
}

const registry = await loadJurisdictions()
/**
 * 母集団は団体registry のコードに限る。都の部局や都外を混ぜない。
 * **③会議録のゲート判定は読まない** — 根拠が違ううえ、③が落ちたら①も動かなくなる。
 */
const JURISDICTIONS = new Set(Object.keys(registry.jurisdictions))

const found = await Promise.all(QUERIES.map(search))
const searchStats = Object.fromEntries(QUERIES.map((q, i) => [q, found[i]!.total]))
const packages = new Map(found.flatMap((f) => f.rows).map((p) => [p.name, p]))

type Candidate = { code: string; dataset: string; resource: string; url: string; direction: Direction }
const candidates: Candidate[] = []
for (const p of packages.values()) {
  const code = /^t(\d{6})$/.exec(p.organization?.name ?? '')?.[1]
  if (!code || !JURISDICTIONS.has(code)) continue
  for (const r of p.resources ?? []) {
    if ((r.format ?? '').toUpperCase() !== 'CSV') continue
    const title = `${p.title} ${r.name ?? ''}`
    // CKAN の q は説明文まで全文一致するため、無関係なデータセットが大量に混ざる
    if (!RELEVANT_TITLE_WORDS.some((k) => title.includes(k))) continue
    candidates.push({ code, dataset: p.title, resource: r.name ?? '', url: r.url, direction: detectDirection(title) })
  }
}
console.log(`候補 CSV: ${candidates.length} 件 / ${new Set(candidates.map((c) => c.code)).size} 団体（母集団 ${JURISDICTIONS.size}）\n`)

type Observation = Candidate & {
  fetchedAt: string
  status: number | null
  granularity: Granularity
  note: string
  bytes?: number
  sha256?: string
  detectedFormat?: string
  rows?: number
  columns?: string[]
  basis?: string
}

const observations = await mapWithConcurrency(candidates, CONCURRENCY, async (c): Promise<Observation> => {
  const base = { ...c, fetchedAt: new Date().toISOString() }
  const got = await fetchCapped(c.url, MAX_BYTES)
  if (!got.ok) return { ...base, status: got.status, granularity: 'unchecked', note: got.reason }

  const kind = sniffContent(got.bytes)
  if (kind !== 'text') {
    return { ...base, status: got.status, bytes: got.bytes.length, detectedFormat: kind, granularity: 'unchecked', note: `${kind} なので列判定できない` }
  }

  const text = decodeText(got.bytes)
  const nl = text.indexOf('\n')
  const header = splitCsvLine(nl < 0 ? text : text.slice(0, nl))
  const { granularity, basis, hits } = classifyGranularity(header, c.code)
  return {
    ...base,
    status: got.status,
    bytes: got.bytes.length,
    sha256: sha256(got.bytes),
    detectedFormat: 'csv',
    // 行数は判定に使わない参考値。空行を除き、全行を配列化せずに数える
    rows: countDataRows(text),
    columns: header,
    granularity,
    basis,
    note: hits.length ? `判定根拠の列: ${hits.join(', ')}` : '粒度を示す列が見つからない',
  }
})

/**
 * 団体ごとの最良は観測から導く。ファイルには焼き込まない。
 * 歳出の粒度が目的なので歳入は代表にせず、判定できなかったものも代表にしない
 * （無関係な CSV を「その団体の結果」として出すと誤読される）。
 */
function bestByJurisdiction(obs: readonly Observation[]) {
  const best = new Map<string, Observation>()
  for (const o of obs) {
    if (o.direction === 'revenue' || o.granularity === 'unchecked') continue
    const prev = best.get(o.code)
    const rank = GRANULARITY_RANK[o.granularity]
    if (prev && GRANULARITY_RANK[prev.granularity as Exclude<Granularity, 'unchecked'>] >= rank) continue
    best.set(o.code, o)
  }
  return best
}

const best = bestByJurisdiction(observations)
const tally: Record<string, number> = {}
for (const [code, b] of [...best].sort()) {
  tally[b.granularity] = (tally[b.granularity] ?? 0) + 1
  const mark = b.granularity === 'project' ? '✓' : b.granularity === 'account-item' ? '◎' : '△'
  console.log(`  ${mark} ${code} ${b.granularity.padEnd(13)} ${String(b.rows ?? '-').padStart(5)}行  ${b.basis === 'declared' ? '宣言' : '推定'}  ${b.dataset.slice(0, 30)}`)
}
const undecided = new Set(observations.filter((o) => !best.has(o.code)).map((o) => o.code))
console.log(`\n${Object.entries(tally).map(([k, v]) => `${k} ${v}`).join(' / ')}  （判定できた ${best.size} 団体 / 候補はあるが判定できない ${undecided.size} 団体 / 母集団 ${JURISDICTIONS.size}）`)
console.log(`全候補: ${observations.length} 件`)

if (write) {
  await Bun.write(
    OUT,
    JSON.stringify(
      {
        note: 'カタログに予算がどの粒度で出ているかの調査。本番の取得は市町村ごとの pipeline で行い、最終的には公式サイトの PDF から取る。判定はデータセット名ではなく列構成で行う（原則3）。母集団は団体registry のコードに限る（原則4）。団体ごとの最良はこの観測から導けるので焼き込まない。',
        generatedBy: 'scripts/check-budget-granularity.ts',
        queries: searchStats,
        population: JURISDICTIONS.size,
        observations,
      },
      null,
      2,
    ) + '\n',
  )
  console.log(`\n${OUT} へ書き出した`)
}
