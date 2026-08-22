/**
 * ①予算の報告を組み立てる。**系統の読み取りは `../lineage` にある**（層に依存しない）。
 *
 * 数値は core への問い合わせで作る。**集計はここ1箇所だけ**で行う
 * （画面側でも集計すると、同じ数字が2通りに計算されていずれ食い違う）。
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Provenance, ReportData } from './schema'
import { ROOT, TARGET, buildChecks, buildTopology, q, readJson, type Manifest, type RunResults } from '../lineage'
import { STATIC } from './static'

const DIVISIONS: Record<string, string> = {
  '01': '一般公共サービス', '02': '防衛', '03': '公共の秩序及び安全', '04': '経済業務', '05': '環境保護',
  '06': '住宅及び地域アメニティ', '07': '保健', '08': '娯楽、文化及び宗教', '09': '教育', '10': '社会保護',
}
const withLabel = <T extends { division: string }>(rows: T[]) =>
  rows.map((r) => ({ ...r, divisionLabel: DIVISIONS[r.division] ?? '' }))

/**
 * COFOG の判断。**fudoki が自治体の言っていないことを付け加えた唯一の場所**なので、
 * 何をどこへ割り当て、なぜそう決めたかを根拠まで出す。
 *
 * ⚠️ 分類不能の割合の低さは合否に使わない。成立範囲を正直に調べるのが目的で、
 * 割合を目標にすると分類不能を減らす方向へ判断が歪む。
 */
function buildTransform(): ReportData['transform'] {
  const rules = q<{ n: number; shared: number }>(
    `select count(*) as n, count(*) filter (where coalesce(applies_to, '') = '') as shared from cofog_rules`,
    ['n', 'shared'])[0]!
  return {
    cofogVersion: 'COFOG 1999',
    cofogSource: { name: 'UNSD Classification of the Functions of Government (COFOG)',
                   url: 'https://unstats.un.org/unsd/classifications/Family/Detail/4' },
    ruleCount: rules.n,
    ruleScope: { shared: rules.shared, jurisdictionSpecific: rules.n - rules.shared },
    byState: withLabel(q(`
      select c.cofog_status status, c.cofog_division division, c.cofog_consolidation consolidation,
             count(*) count, sum(s.source_amount) * 1000 sum
      from core_budget_cofog c join stg_132047__expenditure s using (budget_line_id)
      -- 同点で並びが揺れないよう、決着のつく列まで指定する。
      -- 報告は commit するので、非決定的だと中身が同じでも毎回差分が出る。
      group by all order by sum desc, status, division, consolidation`, ['count', 'sum'])),
    // **規則ごとに分ける。** 併合すると basis が合計に対応しなくなる
    // （国民健康保険への繰出と後期高齢者医療への繰出が1行に潰れ、
    // 片方の根拠だけが両方の金額に付いた状態になっていた）。
    byKan: withLabel(q(`
      select s.fund_source fund, s.kan_source kan, c.cofog_division division, c.cofog_status status,
             c.cofog_decided_at_level decidedAtLevel, c.cofog_rule_id ruleId,
             sum(s.source_amount) * 1000 sum, any_value(r.basis) basis
      from core_budget_cofog c join stg_132047__expenditure s using (budget_line_id)
      left join cofog_rules r on r.rule_id = c.cofog_rule_id
      group by 1, 2, 3, 4, 5, 6 order by sum desc, fund, kan, ruleId`, ['sum'])),
    byLevel: q(`
      select c.cofog_decided_at_level "level", count(*) count, sum(s.source_amount) * 1000 sum
      from core_budget_cofog c join stg_132047__expenditure s using (budget_line_id)
      group by 1 order by sum desc, "level"`, ['count', 'sum']),
    notAssigned: q(`
      select c.cofog_status status, s.fund_source fund, s.kan_source kan, c.cofog_rule_id ruleId,
             sum(s.source_amount) * 1000 sum, any_value(r.basis) basis
      from core_budget_cofog c join stg_132047__expenditure s using (budget_line_id)
      left join cofog_rules r on r.rule_id = c.cofog_rule_id
      where c.cofog_status <> 'assigned' group by 1, 2, 3, 4
      order by sum desc, fund, kan, ruleId`, ['sum']),
    consolidationPairs: q(`
      with paid as (
        select e.fund_label frm, c.cofog_counterpart_fund it, sum(e.source_amount) * 1000 amt
        from core_budget_cofog c join stg_132047__expenditure e using (budget_line_id)
        where c.cofog_consolidation = 'eliminated' group by 1, 2),
      got as (
        select c.cofog_counterpart_fund frm, r.fund_label it,
               sum(r.source_amount) * 1000 amt, count(*) cnt
        from core_revenue_consolidation c join stg_132047__revenue r using (budget_line_id)
        where c.cofog_consolidation = 'eliminated' group by 1, 2)
      select p.frm "from", p.it "to", p.amt eliminated, g.amt counterpart,
             g.cnt counterpartCount, p.amt = g.amt ok
      from paid p join got g on p.frm = g.frm and p.it = g.it
      order by eliminated desc, "from", "to"`, ['eliminated', 'counterpart', 'counterpartCount']),
    consolidationScope: '三鷹市の全会計（本パッケージ収録分。下水道事業会計を除く）',
  }
}

/**
 * 階層ごとのコードの異なり数と完全修飾の異なり数。
 * 完全修飾のほうが大きければ、**同じコードが別の親の下で再利用されている**。
 * 識別子をコードのパスで作れない根拠がこれ。
 */
function buildLevels(): ReportData['levels'] {
  const specs: [string, [string, string][]][] = [
    ['expenditure', [['fund', '会計'], ['kan', '款'], ['kou', '項'], ['moku', '目'],
                     ['jikou', '事項'], ['setsu', '節'], ['saisaisetsu', '細々節']]],
    ['revenue', [['fund', '会計'], ['kan', '款'], ['kou', '項'], ['moku', '目'],
                 ['setsu', '節'], ['saisetsu', '細節'], ['saisaisetsu', '細々節']]],
  ]
  return specs.map(([direction, levels]) => ({
    direction,
    items: levels.map(([lv, label], i) => {
      const path = levels.slice(0, i + 1).map(([p]) => `${p}_source`).join(' || ')
      const r = q<{ codes: number; paths: number }>(
        `select count(distinct ${lv}_code) codes, count(distinct ${path}) paths from stg_132047__${direction}`,
        ['codes', 'paths'])[0]!
      return {
        sourceColumn: label, distinctCodes: r.codes, distinctPaths: r.paths,
        codeReusedUnderDifferentParents: r.paths > r.codes,
      }
    }),
  }))
}

function build(code = '132047'): ReportData {
  const manifest = readJson<Manifest>(join(TARGET, 'manifest.json'))
  const results = readJson<RunResults>(join(TARGET, 'run_results.json'))
  // 証跡は取得物の隣にある。**この2つは不可分**なので同じ場所から読む。
  const rawDir = join(ROOT, 'data/budget/raw', `jurisdiction=${code}`)
  const provenance = new Bun.Glob('**/provenance.json').scanSync({ cwd: rawDir, absolute: true })
  const prov = [...provenance].sort().map((f) => readJson<Provenance>(f))

  // ⚠️ **TOML を正規表現で読まない。** 最初に一致した key を返すので、
  // 2団体目を足した時点で `code` に関係なく先頭の団体の名称・ライセンスを使う。
  const sources = Bun.TOML.parse(readFileSync(join(ROOT, 'ingestion/budget/sources.toml'), 'utf8')) as
    Record<string, { jurisdiction_name?: string; phase_id?: string; phase_label?: string
                     license_id?: string; attribution?: string; landing_page?: string }>
  const entries = Object.entries(sources).filter(([k]) => k.startsWith(`${code}:`))
  if (entries.length === 0) throw new Error(`取得元 ${code}:* が ingestion/sources.toml に無い`)
  const src = entries[0]![1]
  const pick = (k: keyof typeof src) => src[k] ?? ''

  const checks = buildChecks(manifest, results)
  return {
    meta: {
      jurisdictionCode: code,
      jurisdictionName: pick('jurisdiction_name'),
      fiscalYears: [...new Set(prov.map((p) => p.fiscal_year))].sort(),
      phase: { id: pick('phase_id'), label: pick('phase_label') },
      license: { id: pick('license_id'), url: 'https://creativecommons.org/licenses/by/4.0/' },
      attribution: pick('attribution'),
      landingPage: pick('landing_page'),
      // 実行時刻ではなく原典の取得時刻。回すたびに差分が出ないようにする。
      generatedAt: prov.map((p) => p.fetched_at).sort().at(-1) ?? '',
    },
    summary: {
      total: checks.length,
      passed: checks.filter((c) => c.ok).length,
      failed: checks.filter((c) => !c.ok && c.severity === 'error').length,
      warned: checks.filter((c) => c.status === 'warn').length,
    },
    topology: buildTopology(manifest, prov),
    ingestion: prov,
    levels: buildLevels(),
    transform: buildTransform(),
    checks,
    ...STATIC,
    // 年度調査は観測ファイルを直接読む。**static に写すと、再調査しても画面が変わらない。**
    // 実際 static の generatedBy は削除済みのスクリプト名を指したままになっていた。
    yearSurvey: readJson<ReportData['yearSurvey']>(join(ROOT, 'data/budget/observations/mitaka-budget-years.json')),
  }
}

/**
 * 明細。**配布する CSV を読み、画面用に join した射影を作る。**
 *
 * 配布物は正本（判断なし）と派生（判断あり）を別ファイルにしてある。
 * 画面はその両方を見せたいので、利用者が `budget_line_id` で join して得るのと
 * 同じものをここで組む。**配布物を太らせて画面に合わせない** —
 * それをやると正本に判断が混ざる。
 *
 * `*_source`（原典のセル全文）は配布物から落としてある（code‖label で復元できるため）。
 * 画面は階層の絞り込みに使うので、ここで組み立て直す。
 */
function detailProjection(canonical: string, levels: string[], phaseId: string) {
  const src = levels.map((l) => `${l}_code || ${l}_label as ${l}_source`).join(', ')
  const rows = q<Record<string, unknown>>(`
    select c.*, ${src},
           '${phaseId}' as phase_id, '千円' as source_amount_unit,
           d.cofog_status, d.cofog_division as cofog_division_code,
           d.cofog_consolidation, d.cofog_decided_at_level, r.basis as cofog_basis
    from read_csv('${canonical}', header = true, all_varchar = true) c
    left join read_csv('${join(ROOT, 'data/budget/packages/derived/cofog.csv')}', header = true, all_varchar = true) d
      using (budget_line_id)
    left join read_csv('${join(ROOT, 'data/budget/packages/derived/cofog_rules.csv')}', header = true, all_varchar = true) r
      on r.rule_id = d.cofog_rule_id
    order by c.source_row`)
  const columns = rows.length ? Object.keys(rows[0]!) : []
  return { columns, rows: rows.map((x) => columns.map((c) => String(x[c] ?? ''))) }
}

const report = build()
writeFileSync(join(ROOT, 'data/budget/reports/132047.json'), `${JSON.stringify(report, null, 2)}\n`)
writeFileSync(join(ROOT, 'web/public/pipeline.json'), `${JSON.stringify({
  code: '132047',
  report,
  expenditure: detailProjection(join(ROOT, 'data/budget/packages/132047/expenditure.csv'),
    ['fund', 'kan', 'kou', 'moku', 'jikou', 'setsu', 'saisaisetsu'], report.meta.phase.id),
  revenue: detailProjection(join(ROOT, 'data/budget/packages/132047/revenue.csv'),
    ['fund', 'kan', 'kou', 'moku', 'setsu', 'saisetsu', 'saisaisetsu'], report.meta.phase.id),
})}\n`)
const s = report.summary
console.log(`ok  検査 ${s.passed}/${s.total}（警告 ${s.warned}）  ノード ${report.topology.nodes.length}  辺 ${report.topology.edges.length}`)
