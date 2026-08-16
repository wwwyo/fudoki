/**
 * 三鷹市の予算データについて、**令和6年度以外の年度が令和6年度と互換か**を実測する。
 *
 * 収録するのは令和6年度だけで、他年度は調査までが対象（PRD の Non-Goals）。
 * ここで出すのは「収録できるか」の判断材料であって、収録そのものではない。
 *
 * 判定は資料名ではなく**実物の列構成と中身**で行う（パーサ設計の原則3）。
 *
 *   bun run check:budget-years            # 結果を表示
 *   bun run check:budget-years --write    # observations へ書き出す
 */
import { levelsFor } from '../src/budget/columns'
import { splitRows } from '../src/budget/extract'
import { MITAKA_FY2024 } from '../src/budget/source'
import { UA, decodeText, fetchCapped, mapWithConcurrency, sha256, sniffContent } from './lib/source'

const OUT = new URL('../data/observations/mitaka-budget-years.json', import.meta.url).pathname
const CKAN = 'https://catalog.data.metro.tokyo.lg.jp/api/3/action/package_search'
const write = process.argv.includes('--write')
const MAX_BYTES = 20 * 1024 * 1024

const BASE = MITAKA_FY2024
/** 和暦の表記と西暦の対応。リソース名の照合に使う */
const YEARS: { label: string; year: number }[] = [
  { label: '令和６年度', year: 2024 },
  { label: '令和５年度', year: 2023 },
  { label: '令和４年度', year: 2022 },
  { label: '令和３年度', year: 2021 },
  { label: '令和２年度', year: 2020 },
  { label: '令和元年度', year: 2019 },
  { label: '平成30年度', year: 2018 },
  { label: '平成29年度', year: 2017 },
  { label: '平成28年度', year: 2016 },
]

type CkanResource = { format?: string; name?: string; url?: string }
type CkanPackage = { title: string; organization?: { name?: string }; resources?: CkanResource[] }

const res = await fetch(`${CKAN}?q=${encodeURIComponent(BASE.datasetTitle)}&rows=300`, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(40_000) })
const body = (await res.json()) as { result?: { results?: CkanPackage[] } }
const pkg = (body.result?.results ?? []).find((p) => p.organization?.name === `t${BASE.jurisdictionCode}` && p.title === BASE.datasetTitle)
if (!pkg) throw new Error(`データセット「${BASE.datasetTitle}」が見つからない`)

const stripIndex = (c: string) => c.replace(/^[0-9０-９]+[._\-\s]*/, '').trim()
const expected = {
  expenditure: levelsFor(BASE.jurisdictionCode, 'expenditure').map((l) => l.sourceColumn),
  revenue: levelsFor(BASE.jurisdictionCode, 'revenue').map((l) => l.sourceColumn),
}

type Target = { year: number; label: string; direction: 'expenditure' | 'revenue'; resourceName: string; url: string; coverageNote: string | null }
const targets: Target[] = []
for (const { label, year } of YEARS) {
  for (const direction of ['expenditure', 'revenue'] as const) {
    const word = direction === 'expenditure' ? '歳出' : '歳入'
    const r = (pkg.resources ?? []).find((x) => (x.name ?? '').includes(label) && (x.name ?? '').includes(word) && (x.name ?? '').includes('予算データ'))
    if (!r?.url) continue
    const note = /※(.+)$/.exec(r.name ?? '')?.[1]?.trim() ?? null
    targets.push({ year, label, direction, resourceName: r.name!, url: r.url, coverageNote: note })
  }
}
console.log(`対象 ${targets.length} リソース（${YEARS.length} 年度 × 歳出/歳入）\n`)

type Observation = Target & {
  fetchedAt: string
  status: number | null
  bytes?: number
  sha256?: string
  rows?: number
  columns?: string[]
  funds?: string[]
  /** 金額列が整数のみか。単位は原典に書かれていないので推定せず、性質だけ記録する */
  amountAllIntegers?: boolean
  quotedRows?: number
  totalRaw?: number
  compatible: boolean | null
  basis: string
}

const observations = await mapWithConcurrency(targets, 3, async (t): Promise<Observation> => {
  const base = { ...t, fetchedAt: new Date().toISOString() }
  const got = await fetchCapped(t.url, MAX_BYTES)
  if (!got.ok) return { ...base, status: got.status, compatible: null, basis: `取得できない: ${got.reason}` }
  if (sniffContent(got.bytes) !== 'text') return { ...base, status: got.status, bytes: got.bytes.length, compatible: null, basis: 'CSV ではないものが返った' }

  const all = splitRows(decodeText(got.bytes))
  const header = all[0] ?? []
  const rows = all.slice(1)
  const columns = header.map(stripIndex)
  const want = [...expected[t.direction], '予算額']

  const sameColumns = columns.length === want.length && want.every((w, i) => w === columns[i])
  const funds = [...new Set(rows.map((r) => (r[0] ?? '').replace(/^"|"$/g, '')))].sort()
  const amounts = rows.map((r) => r[r.length - 1] ?? '')
  const amountAllIntegers = amounts.every((a) => /^-?\d+$/.test(a))
  const totalRaw = amountAllIntegers ? amounts.reduce((s, a) => s + Number(a), 0) : undefined

  // 引用符が混ざると素朴なカンマ分割では壊れる。Load は引用符を見つけたら生成を止めるので、
  // 「列構成が同じ」だけで互換と判定してはいけない
  const quotedRows = rows.filter((r) => r.some((c) => c.includes('"'))).length

  const reasons: string[] = []
  if (!sameColumns) reasons.push(`列構成が違う（令和6年度: ${want.join('/')} / この年度: ${columns.join('/')}）`)
  if (!amountAllIntegers) reasons.push('金額列に整数でない値がある')
  if (quotedRows > 0) reasons.push(`${quotedRows} 行に引用符付きのセルがある。現在の Load は引用符を見つけたら生成を止めるので、収録には引用符を解釈するパーサが要る`)

  return {
    ...base,
    status: got.status,
    bytes: got.bytes.length,
    sha256: sha256(got.bytes),
    rows: rows.length,
    columns,
    funds,
    amountAllIntegers,
    quotedRows,
    totalRaw,
    compatible: reasons.length === 0,
    basis:
      reasons.length === 0
        ? `列構成が令和6年度と一致（${want.join('/')}）。金額列は全て整数。引用符なし。会計 ${funds.length} 件`
        : reasons.join(' / '),
  }
})

for (const o of observations) {
  const m = o.compatible === null ? '?' : o.compatible ? '✓' : '✗'
  console.log(`  ${m} ${o.label} ${o.direction === 'expenditure' ? '歳出' : '歳入'}  ${String(o.rows ?? '-').padStart(5)}行  会計${String(o.funds?.length ?? '-').padStart(2)}  注記=${o.coverageNote ?? 'なし'}`)
}

// 会計範囲が年度で変わることを、注記だけでなく実際の会計一覧の差でも見る
const byYear = new Map<number, Set<string>>()
for (const o of observations) if (o.funds) byYear.set(o.year, new Set([...(byYear.get(o.year) ?? []), ...o.funds]))
console.log('\n会計の範囲')
for (const { year, label } of YEARS) {
  const f = byYear.get(year)
  if (f) console.log(`  ${label}: ${[...f].sort().join(' / ')}`)
}

// 歳出と歳入の合計一致が他年度でも成り立つか（三鷹市に固有の検算がどこまで効くか）
console.log('\n歳出と歳入の合計一致')
for (const { year, label } of YEARS) {
  const e = observations.find((o) => o.year === year && o.direction === 'expenditure')?.totalRaw
  const r = observations.find((o) => o.year === year && o.direction === 'revenue')?.totalRaw
  if (e === undefined || r === undefined) continue
  console.log(`  ${e === r ? '✓' : '✗'} ${label}: 歳出 ${e.toLocaleString()} / 歳入 ${r.toLocaleString()}`)
}

const compatible = observations.filter((o) => o.compatible === true).length
console.log(`\n互換 ${compatible} / ${observations.length} リソース`)
console.log('⚠️ 互換なのは列構成と金額の型まで。**予算段階は原典にもリソース名にも書かれていない**ため、')
console.log('   令和6年度以外を収録するには予算段階の確認が別途要る（確認できない年度は収録しない）。')

if (write) {
  await Bun.write(
    OUT,
    JSON.stringify(
      {
        note: '三鷹市の予算データについて、令和6年度以外の年度が令和6年度と互換かを実測したもの。収録するのは令和6年度だけで、他年度は調査までが対象。判定は資料名ではなく実物の列構成と中身で行う。',
        generatedBy: 'scripts/check-budget-years.ts',
        baseline: { fiscalYear: BASE.fiscalYear, columns: expected },
        caveat: '互換と判定したのは列構成と金額の型まで。予算段階は原典にもリソース名にも現れないため、この観測だけでは収録可否は決まらない。',
        observations,
      },
      null,
      2,
    ) + '\n',
  )
  console.log(`\n${OUT} へ書き出した`)
}
