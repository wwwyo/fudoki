/**
 * ダッシュボードが読む報告を組み立てる。
 *
 * **系統（どの段がどの段に依存するか、どの検査がどのノードを守るか）は
 * dbt の `manifest.json` から取る。手で書かない。**
 * 以前は `topology.ts` が段・ノード・辺を宣言しており、パイプラインを変えても
 * 図が変わらない状態を2度作った。系統はツールが持っている情報なので、そこから引く。
 *
 * 数値は core への問い合わせで作る。**集計はここ1箇所だけ**で行う
 * （画面側でも集計すると、同じ数字が2通りに計算されていずれ食い違う）。
 *
 * ## なぜ画面と同じ言語で書くか
 *
 * 出力の型を `ReportData` に固定してあるので、**生成側と画面側の食い違いを
 * コンパイラが捕まえる**。以前は生成が Python、型が TypeScript にあり、
 * 形が2箇所で宣言されてどこでも検査されていなかった。
 * このプロジェクトが繰り返し踏んでいる「宣言はあるが誰も検査していない」と同じ形だった。
 *
 * DuckDB へは CLI（mise で入っている）に `-json` で問い合わせる。
 * npm の binding を足さずに済む。
 */
import { readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import type { Check, Node, Provenance, ReportData, Stage, Topology } from './schema'
import { STATIC } from './static'

const ROOT = resolve(import.meta.dirname, '..')
const TARGET = join(ROOT, 'dbt/target')
const WAREHOUSE = join(ROOT, 'data/fudoki.duckdb')

const readJson = <T,>(p: string): T => JSON.parse(readFileSync(p, 'utf8')) as T

/**
 * DuckDB へ問い合わせる。CLI を使うので npm の依存が増えない。
 *
 * ⚠️ **CLI の `-json` は BIGINT を文字列で返す**（JS の精度落ちを避けるため）。
 * 画面は金額で足し算するので、文字列のままだと `+` が連結になる。
 * 数値として使う列を `nums` に挙げて、ここで明示的に変換する。
 * 全部を自動変換しないのは、コード（`01`）まで数値になってしまうため。
 *
 * 金額は最大でも 1.2×10^11 で Number.MAX_SAFE_INTEGER（9×10^15）に収まる。
 */
function q<T = Record<string, unknown>>(sql: string, nums: string[] = []): T[] {
  const r = Bun.spawnSync(['duckdb', '-json', WAREHOUSE, '-c', sql])
  if (r.exitCode !== 0) throw new Error(`DuckDB: ${r.stderr.toString()}\n--- SQL ---\n${sql}`)
  const out = r.stdout.toString().trim()
  if (!out) return []
  const rows = JSON.parse(out) as Record<string, unknown>[]
  for (const row of rows) {
    for (const k of nums) {
      if (row[k] !== null && row[k] !== undefined) row[k] = Number(row[k])
    }
  }
  return rows as T[]
}

/** 段。**dbt のディレクトリがそのまま段になる。** 名前も並びもここでしか宣言しない */
const STAGES: Stage[] = [
  { id: 'ingestion', label: 'ingestion', introducesJudgment: false,
    responsibility: '取得元から取り、無加工のまま Parquet で置く。取得 URL・status・SHA-256・取得時刻を添える',
    excludes: '解釈・整形・結合' },
  { id: 'staging', label: 'staging', introducesJudgment: false,
    responsibility: '原典と1対1。列名の付け替えと型付けだけ',
    excludes: '判断（分類・名寄せ・推定）。行を増減させること' },
  { id: 'core', label: 'core', introducesJudgment: true,
    responsibility: '判断が入る段。COFOG 写像、連結の消去', excludes: '取得' },
  { id: 'package', label: 'package', introducesJudgment: false,
    responsibility: '配布物へ。Fiscal Data Package の形にする', excludes: '判断' },
]

type DbtNode = {
  name: string; resource_type: string; path?: string; description?: string
  config?: { location?: string }; depends_on?: { nodes?: string[] }
}
type Manifest = { nodes: Record<string, DbtNode>; sources: Record<string, DbtNode> }
type RunResults = { results: { unique_id: string; status: string; failures: number | null; message: string | null }[] }

/** 段はノードの置き場から決まる。宣言と実装がずれないのはこれが理由 */
function stageOf(n: DbtNode): Stage['id'] {
  if (n.resource_type === 'source') return 'ingestion'
  if (n.resource_type === 'seed') return 'core'
  const hit = STAGES.find((s) => (n.path ?? '').startsWith(`${s.id}/`))
  return hit?.id ?? 'core'
}

function buildTopology(m: Manifest, provenance: Provenance[]): Topology {
  const all = { ...m.nodes, ...m.sources }
  const models = Object.entries(all).filter(([, n]) => ['model', 'source', 'seed'].includes(n.resource_type))
  const ids = new Set(models.map(([id]) => id))

  const nodes: Node[] = models.map(([id, n]) => {
    const loc = n.config?.location
    let rows: number | null = null
    if (n.resource_type === 'source') {
      rows = provenance.filter((p) => p.direction === n.name).reduce((s, p) => s + p.rows, 0)
    } else if (loc) {
      // package 段は外部ファイルとして書き出される。DuckDB のビューは dbt の
      // 作業ディレクトリ基準の相対パスなので、実ファイルを直接数える。
      const csv = join(ROOT, 'dbt', loc)
      rows = (q<{ n: number }>(`select count(*) n from read_csv('${csv}', header = true, all_varchar = true)`, ['n'])[0]?.n) ?? null
    } else {
      rows = (q<{ n: number }>(`select count(*) n from "${n.name}"`, ['n'])[0]?.n) ?? null
    }
    const stage = stageOf(n)
    return {
      id, label: n.name, kind: n.resource_type as Node['kind'], stage, rows,
      description: (n.description ?? '').trim(), introducesJudgment: stage === 'core',
      artifact: loc ?? null,
    }
  })

  const edges = models.flatMap(([id, n]) =>
    (n.depends_on?.nodes ?? []).filter((d) => ids.has(d)).map((from) => ({ from, to: id, kind: 'flow' })))

  const order = STAGES.map((s) => s.id)
  nodes.sort((a, b) => order.indexOf(a.stage) - order.indexOf(b.stage) || a.label.localeCompare(b.label))
  return { stages: STAGES, nodes, edges, source: 'dbt/target/manifest.json（手書きではない）' }
}

/**
 * 検査とその紐づけを run_results.json から取る。
 * **どの検査がどのノードを守っているかも dbt が知っている**（test の depends_on）。
 * 以前は手で書いており、書き忘れても誰も気づかなかった。
 */
function buildChecks(m: Manifest, r: RunResults): Check[] {
  const byId = new Map(r.results.map((x) => [x.unique_id, x]))
  return Object.entries(m.nodes)
    .filter(([, n]) => n.resource_type === 'test')
    .map(([id, n]) => {
      const res = byId.get(id)
      const status = res?.status ?? '未実行'
      return {
        name: n.name,
        description: (n.description ?? '').trim(),
        binds: n.depends_on?.nodes ?? [],
        ok: status === 'pass',
        severity: status === 'warn' ? ('warn' as const) : ('error' as const),
        status,
        failures: res?.failures ?? null,
        detail: res?.message ?? '',
      }
    })
    .sort((a, b) => Number(a.ok) - Number(b.ok) || a.name.localeCompare(b.name))
}

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
      from core_budget_cofog c join stg_132047__expenditure s using (source_row)
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
      from core_budget_cofog c join stg_132047__expenditure s using (source_row)
      left join cofog_rules r on r.rule_id = c.cofog_rule_id
      group by 1, 2, 3, 4, 5, 6 order by sum desc, fund, kan, ruleId`, ['sum'])),
    byLevel: q(`
      select c.cofog_decided_at_level "level", count(*) count, sum(s.source_amount) * 1000 sum
      from core_budget_cofog c join stg_132047__expenditure s using (source_row)
      group by 1 order by sum desc, "level"`, ['count', 'sum']),
    notAssigned: q(`
      select c.cofog_status status, s.fund_source fund, s.kan_source kan, c.cofog_rule_id ruleId,
             sum(s.source_amount) * 1000 sum, any_value(r.basis) basis
      from core_budget_cofog c join stg_132047__expenditure s using (source_row)
      left join cofog_rules r on r.rule_id = c.cofog_rule_id
      where c.cofog_status <> 'assigned' group by 1, 2, 3, 4
      order by sum desc, fund, kan, ruleId`, ['sum']),
    consolidationPairs: q(`
      with paid as (
        select e.fund_label frm, c.cofog_counterpart_fund it, sum(e.source_amount) * 1000 amt
        from core_budget_cofog c join stg_132047__expenditure e using (source_row)
        where c.cofog_consolidation = 'eliminated' group by 1, 2),
      got as (
        select c.cofog_counterpart_fund frm, r.fund_label it,
               sum(r.source_amount) * 1000 amt, count(*) cnt
        from core_revenue_consolidation c join stg_132047__revenue r using (source_row)
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
  const provDir = join(ROOT, 'data/provenance')
  const provenance = readdirSync(provDir)
    .filter((f) => f.startsWith(`${code}-`) && f.endsWith('.json'))
    .sort()
    .map((f) => readJson<Provenance>(join(provDir, f)))

  const sources = Bun.YAML === undefined ? null : null // TOML は下で読む
  void sources
  const toml = readFileSync(join(ROOT, 'ingestion/sources.toml'), 'utf8')
  const pick = (k: string) => toml.match(new RegExp(`^${k} = "(.*)"$`, 'm'))?.[1] ?? ''

  const checks = buildChecks(manifest, results)
  return {
    meta: {
      jurisdictionCode: code,
      jurisdictionName: pick('jurisdiction_name'),
      fiscalYears: [...new Set(provenance.map((p) => p.fiscal_year))].sort(),
      phase: { id: pick('phase_id'), label: pick('phase_label') },
      license: { id: pick('license_id'), url: 'https://creativecommons.org/licenses/by/4.0/' },
      attribution: pick('attribution'),
      landingPage: pick('landing_page'),
      // 実行時刻ではなく原典の取得時刻。回すたびに差分が出ないようにする。
      generatedAt: provenance.map((p) => p.fetched_at).sort().at(-1) ?? '',
    },
    summary: {
      total: checks.length,
      passed: checks.filter((c) => c.ok).length,
      failed: checks.filter((c) => !c.ok && c.severity === 'error').length,
      warned: checks.filter((c) => c.status === 'warn').length,
    },
    topology: buildTopology(manifest, provenance),
    ingestion: provenance,
    levels: buildLevels(),
    transform: buildTransform(),
    checks,
    ...STATIC,
  }
}

/** 明細。**配布する CSV そのものを読む** — テーブル経由だと画面と配布物がずれうる */
function columnar(csv: string) {
  const rows = q<Record<string, unknown>>(`select * from read_csv('${csv}', header = true, all_varchar = true)`)
  const columns = rows.length ? Object.keys(rows[0]!) : []
  return { columns, rows: rows.map((r) => columns.map((c) => String(r[c] ?? ''))) }
}

const report = build()
writeFileSync(join(ROOT, 'data/reports/132047.json'), `${JSON.stringify(report, null, 2)}\n`)
writeFileSync(join(ROOT, 'web/public/pipeline.json'), `${JSON.stringify({
  code: '132047',
  report,
  expenditure: columnar(join(ROOT, 'data/packages/132047/expenditure.csv')),
  revenue: columnar(join(ROOT, 'data/packages/132047/revenue.csv')),
  cofog: columnar(join(ROOT, 'data/packages/derived/cofog.csv')),
})}\n`)
const s = report.summary
console.log(`ok  検査 ${s.passed}/${s.total}（警告 ${s.warned}）  ノード ${report.topology.nodes.length}  辺 ${report.topology.edges.length}`)
