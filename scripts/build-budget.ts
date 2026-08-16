/**
 * 予算レイヤのパイプラインを回して、正本・派生・証跡・報告を書き出す。
 *
 *   bun run build:budget              # 作業領域のキャッシュを使う（冪等）
 *   bun run build:budget --refetch    # 原典を取り直す。ハッシュが変われば警告する
 *   bun run build:budget --check      # 書き出さず検査だけ回す
 *
 * ネットワークを叩くので CI では回さない。
 * **検査が1つでも落ちたら成果物を書かずに異常終了する**（欠落したまま合計が下がった正本を出さないため）。
 */
import { buildDescriptor, toCsv, type ResourceInput } from '../src/budget/fdp'
import { extractResource } from '../src/budget/extract'
import { load } from '../src/budget/load'
import { buildReport, buildReportData } from '../src/budget/report'
import { MITAKA_FY2024, type BudgetSource } from '../src/budget/source'
import { transform } from '../src/budget/transform'
import { UNIQUE_TYPES, verifyAll } from '../src/budget/verify'
import type { YearSurvey } from '../src/budget/report'

const refetch = process.argv.includes('--refetch')
const checkOnly = process.argv.includes('--check')

const source: BudgetSource = MITAKA_FY2024
const outDir = new URL(`../data/packages/${source.jurisdictionCode}/${source.fiscalYear}/`, import.meta.url).pathname
const provenanceDir = new URL('../data/provenance/', import.meta.url).pathname
const reportDir = new URL('../data/reports/', import.meta.url).pathname

// ── Extract ────────────────────────────────────────────
const [expenditureSpec, revenueSpec] = source.resources
if (!expenditureSpec || !revenueSpec) throw new Error('歳出と歳入の両方が要る')

const extracted = {
  expenditure: await extractResource(source, expenditureSpec, { refetch }),
  revenue: await extractResource(source, revenueSpec, { refetch }),
}
for (const [name, e] of Object.entries(extracted)) {
  console.log(`Extract ${name}: ${e.provenance.rows} 行 / ${e.provenance.bytes} バイト / ${e.provenance.sha256.slice(0, 12)}…`)
  // 自治体側の差し替えは無言で上書きしない
  if (e.changedFrom) console.warn(`  ⚠️ 原典のハッシュが前回と異なる（前回 ${e.changedFrom.slice(0, 12)}…）。差し替えとして記録して再生成する`)
}

// ── Load ───────────────────────────────────────────────
const expenditure = load(source, expenditureSpec, extracted.expenditure)
const revenue = load(source, revenueSpec, extracted.revenue)
console.log(`Load: 歳出 ${expenditure.rows.length} 行 / 歳入 ${revenue.rows.length} 行`)

// ── Transform ──────────────────────────────────────────
const derived = transform(expenditure, revenue)
console.log(`Transform: 派生 ${derived.rows.length} 行 / 連結の対 ${derived.consolidationPairs.length} 件`)

// ── descriptor ─────────────────────────────────────────
const resources: ResourceInput[] = [
  {
    name: 'expenditure',
    title: `${source.fiscalYearLabel}歳出予算（正本）`,
    description: '原典を正規化しただけで、fudoki の判断を含まない。原典1行が1行に対応する。',
    fields: expenditure.fields,
    rows: expenditure.rows,
    provenance: expenditure.provenance,
  },
  {
    name: 'revenue',
    title: `${source.fiscalYearLabel}歳入予算（正本）`,
    description: '原典を正規化しただけで、fudoki の判断を含まない。歳出と階層の意味が違うため別リソースにしてある。',
    fields: revenue.fields,
    rows: revenue.rows,
    provenance: revenue.provenance,
  },
  {
    name: 'expenditure-cofog',
    title: `${source.fiscalYearLabel}歳出予算（COFOG 付き・派生）`,
    description: '正本へ COFOG を割り当てた派生。分類の軸（割当済み / 分類不能 / 対象外）と連結の軸（保持 / 消去）を別々に持つ。',
    fields: derived.fields,
    rows: derived.rows,
    provenance: expenditure.provenance,
  },
]
const descriptor = buildDescriptor(source, resources, UNIQUE_TYPES)

// ── 検証 ───────────────────────────────────────────────
const checks = verifyAll({
  source,
  expenditure,
  revenue,
  expenditureText: extracted.expenditure.text,
  revenueText: extracted.revenue.text,
  derived,
  descriptor,
})
const failed = checks.filter((c) => !c.ok)
console.log('')
for (const c of checks) console.log(`  ${c.ok ? '✓' : '✗'} ${c.name}\n      ${c.detail}`)
console.log(`\n検査 ${checks.length} 件中 ${checks.length - failed.length} 件成功 / ${failed.length} 件失敗`)

if (failed.length > 0) {
  console.error('\n✗ 検査が落ちたので成果物を書き出さない。欠落や重複を含んだまま配布しないため。')
  process.exit(1)
}
if (checkOnly) {
  console.log('\n--check なので書き出さずに終了')
  process.exit(0)
}

// ── 書き出し ────────────────────────────────────────────
const outputs: { path: string; description: string; bytes: number }[] = []
const write = async (path: string, content: string, description: string) => {
  await Bun.write(path, content)
  outputs.push({ path: path.replace(new URL('../', import.meta.url).pathname, ''), description, bytes: new TextEncoder().encode(content).length })
}

for (const r of resources) await write(`${outDir}${r.name}.csv`, toCsv(r.fields, r.rows), r.description)
await write(`${outDir}datapackage.json`, JSON.stringify(descriptor, null, 2) + '\n', 'Fiscal Data Package 1.0.0 の descriptor')

await write(
  `${provenanceDir}${source.jurisdictionCode}-${source.fiscalYear}.json`,
  JSON.stringify(
    {
      note: '原典は保全しない。取得元の URL・取得日時・SHA-256 だけを証跡として残す。原典が取得できなくなった時点の正本を、その時点の正としてそのまま残す。',
      jurisdictionCode: source.jurisdictionCode,
      jurisdictionName: source.jurisdictionName,
      fiscalYear: source.fiscalYear,
      phase: source.phase,
      coverageNote: source.coverageNote,
      license: source.license,
      attribution: source.attribution,
      landingPage: source.landingPage,
      resources: [expenditure.provenance, revenue.provenance],
    },
    null,
    2,
  ) + '\n',
  '取得証跡（URL・取得日時・SHA-256・列構成・行数）',
)

/**
 * 再生成の一致をどう判定するかを、**作業前に一つへ固定して成果物に同梱する。**
 *
 * 判定規則: 生成日時を含まない部分、すなわち3つの CSV と、`created` を除いた descriptor の
 * SHA-256 が一致すること。報告と `created` は生成のたびに変わるので対象にしない。
 */
const sha = (s: string) => new Bun.CryptoHasher('sha256').update(s).digest('hex')
const { created: _created, ...descriptorWithoutCreated } = descriptor as Record<string, unknown>
await write(
  `${outDir}checksums.json`,
  JSON.stringify(
    {
      rule: '生成日時などの可変部分を除いたハッシュの一致で判定する。対象は下記のファイル。datapackage.json は `created` を除いてから正規化して数える。パイプライン報告と `created` は対象外',
      algorithm: 'sha256',
      files: Object.fromEntries([
        ...resources.map((r) => [`${r.name}.csv`, sha(toCsv(r.fields, r.rows))] as const),
        ['datapackage.json (created を除く)', sha(JSON.stringify(descriptorWithoutCreated, null, 2))] as const,
      ]),
      /** 原典が差し替わったかは、これが変わったかで見る */
      sourceSha256: { expenditure: expenditure.provenance.sha256, revenue: revenue.provenance.sha256 },
    },
    null,
    2,
  ) + '\n',
  '再生成の一致判定に使うハッシュ（判定規則を同梱）',
)

// 他年度の互換性は別スクリプトの観測を読み込む。無ければ報告からその節を落とす
const surveyPath = new URL('../data/observations/mitaka-budget-years.json', import.meta.url).pathname
const yearSurvey: YearSurvey | null = (await Bun.file(surveyPath).exists()) ? ((await Bun.file(surveyPath).json()) as YearSurvey) : null
if (!yearSurvey) console.warn('  ⚠️ 他年度の互換性調査が無い。bun run check:budget-years --write を先に回すと報告に載る')

// 集計は buildReportData だけが行い、Markdown（人が読む）と JSON（画面が読む）は同じ結果を整形する。
// 二重に集計すると、同じ数字が2通りに計算されて、いずれ食い違ったまま気づかなくなる。
const reportData = buildReportData({ source, expenditure, revenue, derived, checks, outputs, yearSurvey })
await write(`${reportDir}${source.jurisdictionCode}-${source.fiscalYear}.json`, JSON.stringify(reportData, null, 2) + '\n', 'パイプライン報告（機械可読。画面はこれを読む）')
await write(`${reportDir}${source.jurisdictionCode}-${source.fiscalYear}.md`, buildReport(reportData), 'パイプライン報告（人が読む）')

console.log('')
for (const o of outputs) console.log(`  書き出し ${o.path}（${o.bytes.toLocaleString()} バイト）`)
