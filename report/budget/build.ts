/**
 * ①予算の報告を組み立てる。**系統の読み取りは `../lineage` にある**（層に依存しない）。
 *
 * 数値は core への問い合わせで作る。**集計はここ1箇所だけ**で行う
 * （画面側でも集計すると、同じ数字が2通りに計算されていずれ食い違う）。
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { decodeText, fetchCapped, sha256, splitCsvLine } from '../../ingestion/lib/source'
import type { NodePreview, Provenance, ReportData } from './schema'
import { ROOT, TARGET, buildChecks, buildTopology, q, readJson, type Manifest, type RunResults } from '../lineage'
import { STATIC } from './static'

/**
 * 自作した ColumnType。**`fdp/field_types.json` が正本**で、配布物の descriptor も
 * そこから作る。
 *
 * ⚠️ 以前は `static.ts` に20件を丸写ししていた（名前・dataType・説明文まで完全一致）。
 * 1件足すたびに2ファイルを直す必要があり、片方だけ直しても型検査もテストも通るので、
 * 配布物と画面の「なぜこの列型を自作したか」が黙ってずれる形だった。
 */
const CUSTOM_COLUMN_TYPES: ReportData['customColumnTypes'] =
  (JSON.parse(readFileSync(join(ROOT, 'fdp/field_types.json'), 'utf8')) as {
    columnTypes: [string, { name: string; dataType: string; unique?: boolean
                            labelOf?: string; prior?: string; description: string }[]]
  }).columnTypes[1].map(({ description, ...rest }) => ({ ...rest, why: description }))
import {
  COFOG_DIVISIONS, LEVELS, LEVEL_JA, assertDetailColumns,
  type Direction, type DetailTable,
} from './detail'

const withLabel = <T extends { division: string }>(rows: T[]) =>
  rows.map((r) => ({ ...r, divisionLabel: COFOG_DIVISIONS[r.division] ?? '' }))

/** SQL に埋めるディビジョン表。**宣言から作る** — 手で書くと片方だけ直る */
const DIVISION_VALUES = Object.entries(COFOG_DIVISIONS)
  .map(([code, label]) => `('${code}','${label}')`)
  .join(',')

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
function buildLevels(code: string): ReportData['levels'] {
  // 階層の定義は `./detail` の LEVELS が正本。ここで書き直すと、
  // 階層が変わったとき明細画面と統計で数と順序が食い違う。
  return (Object.keys(LEVELS) as Direction[]).map((direction) => {
    const levels = LEVELS[direction]
    // **direction ごとに1クエリ。** 階層ごとに投げると DuckDB CLI の
    // プロセス起動が 14 回になり、その大半が warehouse の開き直しに消える。
    const select = levels
      .map((lv, i) => {
        const path = levels.slice(0, i + 1).map((p) => `${p}_source`).join(' || ')
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

function build(code: string): ReportData {
  const manifest = readJson<Manifest>(join(TARGET, 'manifest.json'))
  const results = readJson<RunResults>(join(TARGET, 'run_results.json'))
  // 証跡は取得物の隣にある。**この2つは不可分**なので同じ場所から読む。
  const rawDir = join(ROOT, 'data/budget/raw', `jurisdiction=${code}`)
  const provenance = new Bun.Glob('**/provenance.json').scanSync({ cwd: rawDir, absolute: true })
  const prov = [...provenance].sort().map((f) => readJson<Provenance>(f))

  const entries = Object.entries(SOURCES).filter(([k]) => k.startsWith(`${code}:`))
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
    levels: buildLevels(code),
    transform: buildTransform(),
    checks,
    ...STATIC,
    customColumnTypes: CUSTOM_COLUMN_TYPES,
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
function detailProjection(direction: Direction, canonical: string, phaseId: string): DetailTable {
  const levels = LEVELS[direction]
  const src = levels.map((l) => `${l}_code || ${l}_label as ${l}_source`).join(', ')
  const rows = q<Record<string, unknown>>(`
    select c.*, ${src},
           '${phaseId}' as phase_id, '千円' as source_amount_unit,
           d.cofog_status, d.cofog_division as cofog_division_code,
           d.cofog_consolidation, d.cofog_decided_at_level, d.cofog_rule_id,
           coalesce(v.label, '') as cofog_division_label, r.basis as cofog_basis
    from read_csv('${canonical}', header = true, all_varchar = true) c
    left join read_csv('${join(ROOT, 'data/budget/datapackages/derived/cofog.csv')}', header = true, all_varchar = true) d
      using (budget_line_id)
    left join read_csv('${join(ROOT, 'data/budget/datapackages/derived/cofog_rules.csv')}', header = true, all_varchar = true) r
      on r.rule_id = d.cofog_rule_id
    left join (values ${DIVISION_VALUES}) as v(code, label) on v.code = d.cofog_division
    order by c.source_row`)
  const columns = rows.length ? Object.keys(rows[0]!) : []
  // **宣言した列が欠けていたら落とす。** 画面が黙って空になるより、生成が止まるほうがよい。
  assertDetailColumns(direction, columns)
  return {
    columns: columns as DetailTable['columns'],
    rows: rows.map((x) => columns.map((c) => String(x[c] ?? ''))),
  }
}

/**
 * ⚠️ **画面はまだ1団体しか扱えない。**
 * `pipeline.json` が単一団体の形（`{code, report}`）で、切り替えの導線も無い。
 * 2団体目を足したらここで止まるので、黙って先頭の団体だけ配る事故は起きない。
 * 直すときは dbt の core を団体横断へ一般化するのと同じ回でやる（AGENTS.md の Caveats）。
 */
if (CODES.length !== 1) {
  throw new Error(
    `sources.toml に ${CODES.length} 団体（${CODES.join(', ')}）ある。` +
      `報告と画面は1団体しか扱えないので、複数団体へ広げる実装が要る`,
  )
}
const code = CODES[0]!

const report = build(code)
// **報告と明細を分けて書く。** 明細は報告の 50 倍あり（2.4MB 対 0.05MB）、
// 既定のタブは明細を使わない。1つにまとめると、報告だけ見る利用者にも全部を運ぶことになる。
writeFileSync(join(ROOT, 'apps/web/public/pipeline.json'), `${JSON.stringify({ code, report })}\n`)

for (const direction of ['expenditure', 'revenue'] as const) {
  const table = detailProjection(
    direction,
    join(ROOT, `data/budget/datapackages/${code}/${direction}.csv`),
    report.meta.phase.id,
  )
  writeFileSync(join(ROOT, `apps/web/public/detail-${direction}.json`), `${JSON.stringify(table)}\n`)
}
/**
 * ノードごとの中身の先頭。グラフでノードを選んだときに画面が出す。
 * **原典（source）は raw の Parquet を直接読む** — 加工前の姿を見せるのが目的なので、
 * staging 以降のテーブルで代用しない。
 */
function previewFrom(node: ReportData['topology']['nodes'][number]): string {
  if (node.kind === 'source')
    return `read_parquet('${join(ROOT, 'data/budget/raw')}/jurisdiction=${code}/**/direction=${node.label}/data.parquet')`
  // package 段は外部 CSV。DuckDB のビューは dbt の作業ディレクトリ基準なので実ファイルを読む
  if (node.artifact) return `read_csv('${join(ROOT, 'dbt', node.artifact)}', header = true, all_varchar = true)`
  return `"${node.label}"`
}

const PREVIEW_ROWS = 20
mkdirSync(join(ROOT, 'apps/web/public/preview'), { recursive: true })
// 取得元（origin）は DuckDB に無い。下の「取得元 CSV」節が fetch して書く
for (const node of report.topology.nodes.filter((n) => n.kind !== 'origin')) {
  const rows = q<Record<string, unknown>>(`select * from ${previewFrom(node)} limit ${PREVIEW_ROWS}`)
  const columns = rows.length ? Object.keys(rows[0]!) : []
  const preview: NodePreview = {
    id: node.id,
    columns,
    rows: rows.map((r) => columns.map((c) => (r[c] == null ? '' : String(r[c])))),
    limit: PREVIEW_ROWS,
    totalRows: node.rows,
  }
  writeFileSync(join(ROOT, 'apps/web/public/preview', `${node.id}.json`), `${JSON.stringify(preview)}\n`)
}

/**
 * 原典ノードの「入力」= 取得元の CSV そのもの。**都度取りに行き、SHA-256 が同じ間はキャッシュを使う。**
 * raw（Parquet）は取り込み後の姿なので、その手前＝自治体が配っているファイルの生の姿を左に出す。
 * 取れなくても報告は止めない — オフラインでも報告は原典から作れるのが ELT の建付けで、
 * この節はその上に乗る飾りに過ぎない。
 */
const ORIGIN_CACHE = join(ROOT, '.cache/origin-csv')
mkdirSync(ORIGIN_CACHE, { recursive: true })
for (const node of report.topology.nodes.filter((n) => n.kind === 'source')) {
  const p = report.ingestion.find((x) => x.direction === node.label)
  if (!p) continue
  // キャッシュキーは証跡の SHA-256。上流が差し替えたら証跡も変わり、キャッシュも取り直しになる
  const cached = join(ORIGIN_CACHE, `${p.sha256}.csv`)
  let bytes: Uint8Array | null = existsSync(cached) ? new Uint8Array(readFileSync(cached)) : null
  if (!bytes) {
    const f = await fetchCapped(p.request_url, 20 * 1024 * 1024)
    if (!f.ok) {
      console.warn(`warn  取得元 CSV を取れない（${node.label}: ${f.reason}）。入力プレビューは無しで続ける`)
      continue
    }
    if (sha256(f.bytes) !== p.sha256)
      console.warn(`warn  取得元 CSV が証跡の SHA-256 と一致しない（${node.label}）。上流が差し替えた可能性`)
    bytes = f.bytes
    writeFileSync(cached, bytes)
  }
  const lines = decodeText(bytes).split(/\r?\n/).filter((l) => l.trim())
  const preview: NodePreview = {
    id: `${node.id}.origin`,
    columns: splitCsvLine(lines[0] ?? ''),
    rows: lines.slice(1, 1 + PREVIEW_ROWS).map(splitCsvLine),
    limit: PREVIEW_ROWS,
    totalRows: Math.max(0, lines.length - 1),
    title: p.resource_name,
    sourceUrl: p.request_url,
    fetchedAt: p.fetched_at,
  }
  writeFileSync(join(ROOT, 'apps/web/public/preview', `${node.id}.origin.json`), `${JSON.stringify(preview)}\n`)
}

const s = report.summary
console.log(`ok  検査 ${s.passed}/${s.total}（警告 ${s.warned}）  ノード ${report.topology.nodes.length}  辺 ${report.topology.edges.length}  プレビュー ${report.topology.nodes.length} 件`)
