/**
 * ①予算の報告を組み立てる。**系統の読み取りは `../lineage` にある**（層に依存しない）。
 *
 * 数値は core への問い合わせで作る。**集計はここ1箇所だけ**で行う
 * （画面側でも集計すると、同じ数字が2通りに計算されていずれ食い違う）。
 *
 * ⚠️ **団体は `sources.toml` の登録から回す。団体コードを直書きしない。**
 * 階層・金額・段階の構造は `dbt/dbt_project.yml` の vars が正本で、
 * dbt のモデルも検査もそこを見ている。ここへ写すと片方だけ直る。
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Check, Provenance, ReportData, Topology } from './schema'
import { ROOT, TARGET, buildChecks, buildTopology, q, readJson, type Manifest, type RunResults } from '../lineage'
import { BY_JURISDICTION, SHARED } from './static'
import {
  COFOG_DIVISIONS, DIRECTIONS, LEVEL_JA, assertDetailColumns,
  type Direction, type DetailTable, type Level,
} from './detail'

const withLabel = <T extends { division: string }>(rows: T[]) =>
  rows.map((r) => ({ ...r, divisionLabel: COFOG_DIVISIONS[r.division] ?? '' }))



/** 階層と金額の宣言。**正本は dbt_project.yml**（dbt のモデルと検査が同じものを見る） */
type Amount = {
  name: string; source: string; unit: string; multiplier: number
  phase: string; phase_label: string; primary: boolean
}
const DBT_VARS = Bun.YAML.parse(
  readFileSync(join(ROOT, 'dbt/dbt_project.yml'), 'utf8'),
) as { vars: {
  budget_levels: Record<string, Record<Direction, Level[]>>
  budget_amounts: Record<string, Record<Direction, Amount[]>>
} }
const levelsOf = (code: string, direction: Direction) => DBT_VARS.vars.budget_levels[code]![direction]

/**
 * 団体に固有の手書きの内容。**既定値で埋めない。**
 * 埋めると、三鷹市について書いた文が狛江市の報告に出たまま気づけない。
 * 以前 `consolidationScope` だけがここを通らず `'（未宣言）'` で素通りし、
 * それが画面の統計カードの説明としてそのまま出る状態だった。
 */
function perJurisdiction(code: string) {
  const hit = BY_JURISDICTION[code]
  if (!hit) throw new Error(`${code} の団体固有の宣言が report/budget/static.ts に無い`)
  return hit
}

/**
 * FDP に無い概念のために自作した ColumnType。**正本は `fdp/field_types.json`。**
 * descriptor（datapackage.json）もそこから作るので、報告へ写すと片方だけ直る。
 */
const CUSTOM_COLUMN_TYPES: ReportData['customColumnTypes'] =
  (JSON.parse(readFileSync(join(ROOT, 'fdp/field_types.json'), 'utf8')) as {
    columnTypes: [string, { name: string; dataType: string; unique?: boolean
                            labelOf?: string; prior?: string; description: string }[]]
  }).columnTypes[1].map(({ description, ...rest }) => ({ ...rest, why: description }))

/**
 * 年度の互換性調査。**団体ごとの観測ファイル**で、無い団体には出さない。
 * 三鷹市は収録が1年度なので他年度が同じ形かを別に調べてある。
 * 狛江市は6年度すべてを収録しているので、この調査にあたるものが要らない。
 */
const YEAR_SURVEY: Record<string, ReportData['yearSurvey']> = {
  '132047': readJson<ReportData['yearSurvey']>(
    join(ROOT, 'data/budget/observations/mitaka-budget-years.json')),
}
const amountsOf = (code: string, direction: Direction) => DBT_VARS.vars.budget_amounts[code]![direction]

/**
 * COFOG の判断。**fudoki が自治体の言っていないことを付け加えた唯一の場所**なので、
 * 何をどこへ割り当て、なぜそう決めたかを根拠まで出す。
 *
 * ⚠️ 分類不能の割合の低さは合否に使わない。成立範囲を正直に調べるのが目的で、
 * 割合を目標にすると分類不能を減らす方向へ判断が歪む。
 *
 * ⚠️ **金額は円で見る**（core_budget_lines の `amount_yen`）。
 * 原典の単位は団体ごとに違うので、source_amount のまま足すと千円と円が混ざる。
 */
function buildTransform(code: string): ReportData['transform'] {
  const scope = `where c.jurisdiction_code = '${code}'`
  const rules = q<{ n: number; shared: number }>(
    `select count(*) as n, count(*) filter (where coalesce(applies_to, '') = '') as shared
     from cofog_rules where coalesce(applies_to, '') in ('', '${code}')`,
    ['n', 'shared'])[0]!
  return {
    cofogVersion: 'COFOG 1999',
    cofogSource: { name: 'UNSD Classification of the Functions of Government (COFOG)',
                   url: 'https://unstats.un.org/unsd/classifications/Family/Detail/4' },
    ruleCount: rules.n,
    ruleScope: { shared: rules.shared, jurisdictionSpecific: rules.n - rules.shared },
    byState: withLabel(q(`
      select c.cofog_status status, c.cofog_division division, c.cofog_consolidation consolidation,
             count(*) count, sum(s.amount_yen) sum
      from core_budget_cofog c join core_budget_lines s using (budget_line_id) ${scope}
      -- 同点で並びが揺れないよう、決着のつく列まで指定する。
      -- 報告は commit するので、非決定的だと中身が同じでも毎回差分が出る。
      group by all order by sum desc, status, division, consolidation`, ['count', 'sum'])),
    // **規則ごとに分ける。** 併合すると basis が合計に対応しなくなる
    // （国民健康保険への繰出と後期高齢者医療への繰出が1行に潰れ、
    // 片方の根拠だけが両方の金額に付いた状態になっていた）。
    byKan: withLabel(q(`
      select s.fund_code || s.fund_label fund, s.kan_code || s.kan_label kan,
             c.cofog_division division, c.cofog_status status,
             c.cofog_decided_at_level decidedAtLevel, c.cofog_rule_id ruleId,
             sum(s.amount_yen) sum, any_value(r.basis) basis
      from core_budget_cofog c join core_budget_lines s using (budget_line_id)
      left join cofog_rules r on r.rule_id = c.cofog_rule_id ${scope}
      group by 1, 2, 3, 4, 5, 6 order by sum desc, fund, kan, ruleId`, ['sum'])),
    byLevel: q(`
      select c.cofog_decided_at_level "level", count(*) count, sum(s.amount_yen) sum
      from core_budget_cofog c join core_budget_lines s using (budget_line_id) ${scope}
      group by 1 order by sum desc, "level"`, ['count', 'sum']),
    notAssigned: q(`
      select c.cofog_status status, s.fund_code || s.fund_label fund, s.kan_code || s.kan_label kan,
             c.cofog_rule_id ruleId, sum(s.amount_yen) sum, any_value(r.basis) basis
      from core_budget_cofog c join core_budget_lines s using (budget_line_id)
      left join cofog_rules r on r.rule_id = c.cofog_rule_id
      ${scope} and c.cofog_status <> 'assigned' group by 1, 2, 3, 4
      order by sum desc, fund, kan, ruleId`, ['sum']),
    consolidationPairs: q(`
      with paid as (
        select e.fund_label frm, c.cofog_counterpart_fund it, sum(e.amount_yen) amt
        from core_budget_cofog c join core_budget_lines e using (budget_line_id)
        where c.cofog_consolidation = 'eliminated' and c.jurisdiction_code = '${code}' group by 1, 2),
      got as (
        select c.cofog_counterpart_fund frm, r.fund_label it,
               sum(r.amount_yen) amt, count(*) cnt
        from core_revenue_consolidation c join core_revenue_lines r using (budget_line_id)
        where c.cofog_consolidation = 'eliminated' and c.jurisdiction_code = '${code}' group by 1, 2)
      select p.frm "from", p.it "to", p.amt eliminated, g.amt counterpart,
             g.cnt counterpartCount, p.amt = g.amt ok
      from paid p join got g on p.frm = g.frm and p.it = g.it
      order by eliminated desc, "from", "to"`, ['eliminated', 'counterpart', 'counterpartCount']),
    consolidationScope: perJurisdiction(code).consolidationScope,
  }
}

/**
 * 階層ごとのコードの異なり数と完全修飾の異なり数。
 * 完全修飾のほうが大きければ、**同じコードが別の親の下で再利用されている**。
 * 識別子をコードのパスで作れない根拠がこれ。
 */
function buildLevels(code: string): ReportData['levels'] {
  return DIRECTIONS.map((direction) => {
    const levels = levelsOf(code, direction)
    // **direction ごとに1クエリ。** 階層ごとに投げると DuckDB CLI の
    // プロセス起動が 14 回になり、その大半が warehouse の開き直しに消える。
    const select = levels
      .map((lv, i) => {
        const path = levels.slice(0, i + 1).map((p) => `${p}_source`).join(" || chr(31) || ")
        return `count(distinct ${lv}_code) c${i}, count(distinct ${path}) p${i}`
      })
      .join(', ')
    const nums = levels.flatMap((_, i) => [`c${i}`, `p${i}`])
    const r = q<Record<string, number>>(`select ${select} from stg_${code}__${direction}`, nums)[0]!
    return {
      direction,
      items: levels.map((lv, i) => ({
        sourceColumn: LEVEL_JA[lv] ?? lv,
        distinctCodes: r[`c${i}`]!,
        distinctPaths: r[`p${i}`]!,
        codeReusedUnderDifferentParents: r[`p${i}`]! > r[`c${i}`]!,
      })),
    }
  })
}

type SourceEntry = {
  jurisdiction_name?: string; phase_id?: string; phase_label?: string
  license_id?: string; attribution?: string; landing_page?: string
}

/**
 * 取得元の定義。**団体コードを直書きしない** — `sources.toml` が正本。
 *
 * ⚠️ TOML を正規表現で読まない。最初に一致した key を返すので、
 * 2団体目を足した時点で先頭の団体の名称・ライセンスを使ってしまう。
 */
const SOURCES = Bun.TOML.parse(
  readFileSync(join(ROOT, 'ingestion/budget/sources.toml'), 'utf8'),
) as Record<string, SourceEntry>

/** `sources.toml` に登録された団体コード */
const CODES = [...new Set(
  Object.keys(SOURCES).filter((k) => /^\d{6}:/.test(k)).map((k) => k.split(':')[0]!),
)].sort()

/** 証跡は取得物の隣にある。**この2つは不可分**なので同じ場所から読む */
function provenanceOf(dir: string): Provenance[] {
  return [...new Bun.Glob('**/provenance.json').scanSync({ cwd: dir, absolute: true })]
    .sort().map((f) => readJson<Provenance>(f))
}

/**
 * 全団体の証跡。**系統の図は団体で切らない**（パイプラインは1本で、
 * どの団体のノードも同じ図に出る）ので、原典ノードの行数も全団体から引く。
 */
const ALL_PROVENANCE = provenanceOf(join(ROOT, 'data/budget/raw'))

/**
 * 系統と検査は**団体で変わらない**（パイプラインは1本で、どの団体のノードも同じ図に出る）。
 * ⚠️ 団体ごとに呼ぶと、入力が同じなのに DuckDB を起こし直して全配布物を数え直す。
 * 62団体だと配布物の走査が O(N²) になり、出力も同じ 8.9 KB を N 回書くことになる。
 */
function build(
  code: string, topology: Topology, checks: Check[],
): ReportData {
  const prov = provenanceOf(join(ROOT, 'data/budget/raw', `jurisdiction=${code}`))

  const entries = Object.entries(SOURCES).filter(([k]) => k.startsWith(`${code}:`))
  if (entries.length === 0) throw new Error(`取得元 ${code}:* が ingestion/budget/sources.toml に無い`)
  const src = entries[0]![1]
  const pick = (k: keyof typeof src) => src[k] ?? ''

  return {
    meta: {
      jurisdictionCode: code,
      jurisdictionName: pick('jurisdiction_name'),
      fiscalYears: [...new Set(prov.map((p) => p.fiscal_year))].sort(),
      // **原典の文書の種類**（当初予算 / 決算）。行が持つ予算段階とは別の軸で、
      // 狛江市の決算書は1行が予算現額と執行済額の両方を持つ。
      // 行の段階は配布物の列にあり、画面はデータから拾う（段階の数が団体ごとに違うため）。
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
    topology,
    ingestion: prov,
    detailLevels: DIRECTIONS.map((direction) => ({ direction, levels: levelsOf(code, direction) })),
    levels: buildLevels(code),
    transform: buildTransform(code),
    checks,
    ...SHARED,
    // ⚠️ **団体固有の内容は宣言が無ければ止める。** 既定値で埋めると、
    // 三鷹市について書いた caveats が狛江市の報告に出たまま気づけない。
    ...perJurisdiction(code),
    // FDP に無い概念のために自作した ColumnType。**正本は fdp/field_types.json**
    // （descriptor もそこから作る）。報告へ写すと片方だけ直る。
    customColumnTypes: CUSTOM_COLUMN_TYPES,
    // 年度調査は観測ファイルを直接読む。**static に写すと、再調査しても画面が変わらない。**
    // 実際 static の generatedBy は削除済みのスクリプト名を指したままになっていた。
    // ⚠️ 三鷹市についての調査なので、他団体の報告には載せない。
    ...(YEAR_SURVEY[code] ? { yearSurvey: YEAR_SURVEY[code]! } : {}),
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
 *
 * ⚠️ **単一段階の団体には phase_label / source_amount_unit の列が無い。**
 * 全行同じ値なので配布物から外して descriptor の定数にしてあるが、
 * 画面は列として受け取る。無い側をここで補う。
 */
function detailProjection(code: string, direction: Direction): DetailTable {
  const levels = levelsOf(code, direction)
  const amounts = amountsOf(code, direction)
  const canonical = join(ROOT, `data/budget/packages/${code}/${direction}.csv`)
  const src = levels.map((l) => `${l}_code || ${l}_label as ${l}_source`).join(', ')
  const single = amounts.length === 1
  const constants = single
    ? `, '${amounts[0]!.phase_label}' as phase_label, '${amounts[0]!.unit}' as source_amount_unit`
    : ''
  // ⚠️ **異なり数の少ない列を行へ join しない。** 根拠（basis）は19種類しかないのに
  // 行へ入れると狛江市の歳出だけで 7.0 MB になる（`cofog_rule_id` が全行にあるので情報量ゼロ）。
  // ディビジョン名も画面が宣言として持っている。どちらも規則表・宣言から引く。
  const rows = q<Record<string, unknown>>(`
    select c.*, ${src}${constants},
           d.cofog_status, d.cofog_division as cofog_division_code,
           d.cofog_consolidation, d.cofog_decided_at_level, d.cofog_rule_id
    from read_csv('${canonical}', header = true, all_varchar = true) c
    left join read_csv('${join(ROOT, 'data/budget/packages/derived/cofog.csv')}', header = true, all_varchar = true) d
      using (budget_line_id)
    order by c.fiscal_year, c.source_row, c.phase_id`)
  const columns = rows.length ? Object.keys(rows[0]!) : []
  // **宣言した列が欠けていたら落とす。** 画面が黙って空になるより、生成が止まるほうがよい。
  assertDetailColumns(code, direction, levels, columns)
  return {
    columns: columns as DetailTable['columns'],
    rows: rows.map((x) => columns.map((c) => String(x[c] ?? ''))),
    ruleBasis: RULE_BASIS,
  }
}

/** 割当の根拠。**規則ごとに1つ**なので行に複製せず、明細と一緒に1回だけ運ぶ */
const RULE_BASIS: Record<string, string> = Object.fromEntries(
  q<{ rule_id: string; basis: string }>(
    `select rule_id, basis from read_csv('${join(ROOT, 'data/budget/packages/derived/cofog_rules.csv')}',
     header = true, all_varchar = true)`,
  ).map((r) => [r.rule_id, r.basis]),
)

const manifest = readJson<Manifest>(join(TARGET, 'manifest.json'))
const results = readJson<RunResults>(join(TARGET, 'run_results.json'))

// **団体で変わらないものは1回だけ作る。**
const topology = buildTopology(manifest, ALL_PROVENANCE)
const checks = buildChecks(manifest, results)

const reports = CODES.map((code) => ({ code, report: build(code, topology, checks) }))
for (const { code, report } of reports) {
  writeFileSync(join(ROOT, `data/budget/reports/${code}.json`), `${JSON.stringify(report, null, 2)}\n`)
}
// **報告と明細を分けて書く。** 明細は報告の 50 倍あり（2.4MB 対 0.05MB）、
// 既定のタブは明細を使わない。1つにまとめると、報告だけ見る利用者にも全部を運ぶことになる。
//
// ⚠️ **団体で変わらないものを団体の数だけ運ばない。**
// 系統・検査・移植性の判定・独自 ColumnType はどの団体でも同じ内容で、
// 2団体でも 151.7 KB のうち 29.1 KB（19%）がバイト一致していた。62団体なら系統だけで約 11 MB になる。
// しかも pipeline.json は明細タブを開かなくても読まれる**既定の payload** である。
// 画面側（`loadPipeline`）が読み込み時に組み直すので、下流の型は変わらない。
//
// ⚠️ `data/budget/reports/<団体>.json` のほうは**分けない。**
// あちらは配布する成果物なので、1ファイルで完結しているほうが利用者に要る。
const { portability, customColumnTypes } = reports[0]!.report
writeFileSync(join(ROOT, 'web/public/pipeline.json'), `${JSON.stringify({
  shared: { topology, checks, portability, customColumnTypes },
  jurisdictions: reports.map(({ code, report }) => {
    const { topology: _1, checks: _2, portability: _3, customColumnTypes: _4, ...rest } = report
    return { code, report: rest }
  }),
})}\n`)

for (const { code } of reports) {
  for (const direction of DIRECTIONS) {
    const table = detailProjection(code, direction)
    writeFileSync(
      join(ROOT, `web/public/detail-${code}-${direction}.json`),
      `${JSON.stringify(table)}\n`,
    )
  }
}
for (const { code, report } of reports) {
  const s = report.summary
  console.log(`ok  ${code}  検査 ${s.passed}/${s.total}（警告 ${s.warned}）  `
    + `ノード ${report.topology.nodes.length}  辺 ${report.topology.edges.length}`)
}
