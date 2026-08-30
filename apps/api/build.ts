/**
 * 配布物（data/budget/datapackages/）から API 用パーティションを生成する。
 * 出力は dist/assets/（ローカル生成物、commit しない）。
 *
 * **配布物との不整合があれば build を失敗させる。**
 * 検査: 多重集合一致 / 横断 chunk の合計一致 / 分類率の内訳一致 /
 * 注意事項の必須カテゴリ / パススルーの SHA-256 一致。
 *
 * 実行: bun run build.ts [--allow-dirty]
 *   --allow-dirty: 作業ツリーが dirty でも build する（revision に -dirty が付く）。
 *   deploy 経路（build:release）では付けない — どの commit の配布物か言えなくなるため。
 */
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { BY_JURISDICTION } from '@fudoki/report/budget/static'
import {
  budgetLineSchema,
  budgetSchema,
  cofogConsolidation,
  cofogDecidedAtLevel,
  cofogStatus,
  crossBudgetLineSchema,
  dimensionName,
  levelName,
  jurisdictionSchema,
  phaseId,
  type Budget,
  type BudgetLine,
  type CrossBudgetLine,
  type Jurisdiction,
} from './src/contract'
import { budgetIdOf, direction } from './src/contract'
import { paths as assetPaths } from './src/assets'

const ROOT = join(import.meta.dir, '../..')
const DATA_DIR = join(ROOT, 'data/budget/datapackages')
const OUT_DIR = join(import.meta.dir, 'dist/assets')
const CHUNK_SIZE = 1000
/** 1 chunk のサイズ上限（Cloudflare の 25MiB 制限に対する早期警報） */
const CHUNK_BYTES_LIMIT = 20 * 1024 * 1024

/**
 * 分類率の金額ベースに使う予算段階。**団体を足すときは必ずここに書く**
 * （宣言が無ければ build が止まる。既定値で埋めない）。
 * 132047: 当初予算のみの資料なので approved。
 * 132195: 決算の予算現額（流用・充用まで反映した後の額）。
 * 132241: 当初予算のみの資料なので approved（sources.toml の phase_id と同じ）。
 */
const AMOUNT_PHASE: Record<string, BudgetLine['amounts'][number]['phase']> = {
  '132047': 'approved',
  '132195': 'adjusted',
  '132241': 'approved',
}

const REQUIRED_CAVEAT_CATEGORIES = ['coverage', 'phaseSemantics', 'classification', 'sourceAndLicense'] as const

/**
 * 検査: contract の語彙 enum が、配布物側の宣言（fdp/field_types.json の
 * constraints.enum）と過不足なく一致すること。どちらかだけ直すと止まる。
 */
function checkVocabulariesMatchFieldTypes(): void {
  const fieldTypes = (
    JSON.parse(readFileSync(join(ROOT, 'fdp/field_types.json'), 'utf8')) as {
      fields: Record<string, { constraints?: { enum?: string[] } }>
    }
  ).fields
  const pairs: [string, readonly string[]][] = [
    ['direction', direction.options],
    ['cofog_status', cofogStatus.options],
    ['cofog_consolidation', cofogConsolidation.options],
    ['cofog_decided_at_level', cofogDecidedAtLevel.options],
    ['phase_id', phaseId.options],
  ]
  for (const [fieldName, contractValues] of pairs) {
    const declared = fieldTypes[fieldName]?.constraints?.enum
      ?? fail(`fdp/field_types.json の ${fieldName} に constraints.enum が無い（配布物側の語彙宣言）`)
    const a = [...declared].sort().join(' / ')
    const b = [...contractValues].sort().join(' / ')
    if (a !== b) {
      fail(`vocabulary mismatch for ${fieldName}: distribution declares [${a}] but API contract declares [${b}]`)
    }
  }
}

/** 文字列キーの昇順比較（ソートの意図を1箇所に固定する） */
function byKey<T>(key: (v: T) => string): (a: T, b: T) => number {
  return (a, b) => {
    const ka = key(a)
    const kb = key(b)
    return ka < kb ? -1 : ka > kb ? 1 : 0
  }
}

function fail(message: string): never {
  console.error(`\nbuild failed: ${message}`)
  process.exit(1)
}

// ---- git revision -----------------------------------------------------------

function resolveRevision(allowDirty: boolean): string {
  const sha = new TextDecoder()
    .decode(Bun.spawnSync(['git', 'rev-parse', 'HEAD'], { cwd: ROOT }).stdout)
    .trim()
  if (!/^[0-9a-f]{40}$/.test(sha)) fail('git rev-parse HEAD failed')
  const dirty = new TextDecoder()
    .decode(Bun.spawnSync(['git', 'status', '--porcelain'], { cwd: ROOT }).stdout)
    .trim()
  if (dirty !== '') {
    if (!allowDirty) {
      fail('working tree is dirty. Commit first, or pass --allow-dirty for local development builds.')
    }
    return `${sha}-dirty`
  }
  return sha
}

// ---- CSV (RFC 4180) ---------------------------------------------------------

function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let inQuotes = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i++
        } else {
          inQuotes = false
        }
      } else {
        field += ch
      }
    } else if (ch === '"') {
      inQuotes = true
    } else if (ch === ',') {
      row.push(field)
      field = ''
    } else if (ch === '\n') {
      row.push(field)
      field = ''
      rows.push(row)
      row = []
    } else if (ch !== '\r') {
      field += ch
    }
  }
  if (field !== '' || row.length > 0) {
    row.push(field)
    rows.push(row)
  }
  return rows
}

type Table = { header: string[]; rows: Record<string, string>[] }

function readCsvTable(path: string): Table {
  const parsed = parseCsv(readFileSync(path, 'utf8'))
  const header = parsed[0] ?? fail(`empty CSV: ${path}`)
  const rows = parsed.slice(1).map((cells) => {
    if (cells.length !== header.length) fail(`ragged CSV row in ${path}: ${JSON.stringify(cells)}`)
    return Object.fromEntries(header.map((h, i) => [h, cells[i]!]))
  })
  return { header, rows }
}

// ---- declarations -----------------------------------------------------------

type Direction = 'expenditure' | 'revenue'
const DIRECTIONS: Direction[] = ['expenditure', 'revenue']

const DBT_VARS = (
  Bun.YAML.parse(readFileSync(join(ROOT, 'dbt/dbt_project.yml'), 'utf8')) as {
    vars: {
      budget_levels: Record<string, Record<Direction, string[]>>
      budget_extra_key_columns: Record<string, Record<Direction, string[]>>
    }
  }
).vars

type Descriptor = {
  resources: {
    name: string
    path: string
    schema: {
      fields: { name: string }[]
      extraFields?: { name: string; constant?: string }[]
    }
  }[]
  licenses: { name: string; title: string; path: string }[]
  sources: { title: string; path?: string }[]
}

// ---- BudgetLine construction ------------------------------------------------

const META_COLUMNS = new Set([
  'budget_line_id', 'fiscal_year', 'phase_id', 'phase_label', 'source_row',
  'value', 'source_amount', 'source_amount_unit',
])

type ResourceContext = {
  jurisdiction: string
  direction: Direction
  levels: string[]
  dimensions: string[]
  header: string[]
  constants: Record<string, string>
}

function resourceContext(jurisdiction: string, direction: Direction, table: Table, descriptor: Descriptor): ResourceContext {
  const levels = DBT_VARS.budget_levels[jurisdiction]?.[direction] ?? fail(`budget_levels missing for ${jurisdiction}/${direction}`)
  const declaredExtra = DBT_VARS.budget_extra_key_columns[jurisdiction]?.[direction] ?? fail(`budget_extra_key_columns missing for ${jurisdiction}/${direction}`)
  const resource = descriptor.resources.find((r) => r.name === direction) ?? fail(`resource ${direction} missing in descriptor of ${jurisdiction}`)
  const constants = Object.fromEntries(
    (resource.schema.extraFields ?? []).filter((f) => f.constant !== undefined).map((f) => [f.name, f.constant!]),
  )

  const dimensions: string[] = []
  for (const col of table.header) {
    if (META_COLUMNS.has(col)) continue
    const m = col.match(/^(.+)_(code|label)$/) ?? fail(`unknown column ${col} in ${jurisdiction}/${direction} (would be silently dropped)`)
    const name = m[1]!
    if (levels.includes(name)) continue
    if (m[2] === 'code' && !dimensions.includes(name)) dimensions.push(name)
  }
  for (const level of levels) {
    if (!table.header.includes(`${level}_code`)) fail(`declared level ${level} has no ${level}_code column in ${jurisdiction}/${direction}`)
  }
  // ヘッダから導いた次元が dbt の宣言と食い違ったら、どちらかが古い
  const sortedA = [...dimensions].sort().join(',')
  const sortedB = [...declaredExtra].sort().join(',')
  if (sortedA !== sortedB) {
    fail(`dimension columns in CSV (${sortedA}) differ from budget_extra_key_columns (${sortedB}) for ${jurisdiction}/${direction}`)
  }
  return { jurisdiction, direction, levels, dimensions, header: table.header, constants }
}

type CofogRow = NonNullable<BudgetLine['judgments']['cofog']>

function buildLines(
  ctx: ResourceContext,
  table: Table,
  cofogByLineId: Map<string, CofogRow>,
  projectNameByKey: Map<string, string> | null,
): BudgetLine[] {
  const byId = new Map<string, BudgetLine>()
  for (const row of table.rows) {
    const id = row['budget_line_id']!
    let line = byId.get(id)
    if (!line) {
      const hierarchy = ctx.levels.map((level) => ({
        level: levelName.parse(level),
        code: row[`${level}_code`]!,
        label: labelOf(row, `${level}_label`),
      }))
      const dimensions = ctx.dimensions.map((name) => ({
        name: dimensionName.parse(name),
        code: row[`${name}_code`]!,
        label: labelOf(row, `${name}_label`),
      }))
      let projectName: string | null = null
      if (projectNameByKey !== null && ctx.direction === 'expenditure') {
        const key = projectKey(row['fiscal_year']!, hierarchy.map((h) => [h.level, h.code]))
        projectName = key === null ? null : (projectNameByKey.get(key) ?? null)
      }
      line = {
        budgetLineId: id,
        fiscalYear: row['fiscal_year']!,
        direction: ctx.direction,
        hierarchy,
        dimensions,
        amounts: [],
        judgments: { cofog: cofogByLineId.get(id) ?? null, projectName },
      }
      byId.set(id, line)
    }
    line.amounts.push({
      phase: phaseId.parse(row['phase_id']),
      phaseLabel: row['phase_label'] ?? ctx.constants['phase_label'] ?? fail(`phase_label is neither a column nor a constant for ${ctx.jurisdiction}/${ctx.direction}`),
      amount: Number(row['value']),
      sourceAmount: Number(row['source_amount']),
      sourceAmountUnit: row['source_amount_unit'] ?? ctx.constants['source_amount_unit'] ?? fail(`source_amount_unit is neither a column nor a constant for ${ctx.jurisdiction}/${ctx.direction}`),
      sourceRow: Number(row['source_row']),
    })
  }
  return [...byId.values()].sort(byKey((l) => l.budgetLineId))
}

function labelOf(row: Record<string, string>, column: string): string | null {
  const v = row[column]
  if (v === undefined) return null
  return v === '' ? null : v
}

/** project_names は (年度, fund..daijigyo) で引く。daijigyo の無い団体は対象外 */
function projectKey(fiscalYear: string, levelCodes: [string, string][]): string | null {
  const wanted = ['fund', 'kan', 'kou', 'moku', 'daijigyo']
  const byLevel = new Map(levelCodes)
  if (!byLevel.has('daijigyo')) return null
  return [fiscalYear, ...wanted.map((l) => byLevel.get(l) ?? '')].join('|')
}

// ---- 検査1: 多重集合一致 -----------------------------------------------------

const NUMERIC_COLUMNS = new Set(['value', 'source_amount', 'source_row'])

function canonicalRow(header: string[], get: (col: string) => string | number): string {
  return JSON.stringify(header.map((col) => {
    const v = get(col)
    return NUMERIC_COLUMNS.has(col) ? Number(v) : String(v)
  }))
}

function checkMultisetEquality(ctx: ResourceContext, table: Table, lines: BudgetLine[]): void {
  const expected = new Map<string, number>()
  for (const row of table.rows) {
    const key = canonicalRow(ctx.header, (col) => row[col]!)
    expected.set(key, (expected.get(key) ?? 0) + 1)
  }
  for (const line of lines) {
    for (const amount of line.amounts) {
      const key = canonicalRow(ctx.header, (col) => {
        if (col === 'budget_line_id') return line.budgetLineId
        if (col === 'fiscal_year') return line.fiscalYear
        if (col === 'phase_id') return amount.phase
        if (col === 'phase_label') return amount.phaseLabel
        if (col === 'source_row') return amount.sourceRow
        if (col === 'value') return amount.amount
        if (col === 'source_amount') return amount.sourceAmount
        if (col === 'source_amount_unit') return amount.sourceAmountUnit
        const m = col.match(/^(.+)_(code|label)$/)!
        const entry = line.hierarchy.find((h) => h.level === m[1]) ?? line.dimensions.find((d) => d.name === m[1])
        if (!entry) fail(`cannot reconstruct column ${col} for ${line.budgetLineId}`)
        return m[2] === 'code' ? entry.code : (entry.label ?? '')
      })
      const n = expected.get(key)
      if (n === undefined || n === 0) {
        fail(`multiset check: partition has a row not in the distribution CSV (${ctx.jurisdiction}/${ctx.direction}, ${line.budgetLineId}, phase ${amount.phase})`)
      }
      expected.set(key, n - 1)
    }
  }
  for (const [key, n] of expected) {
    if (n !== 0) fail(`multiset check: ${n} CSV row(s) missing from partitions (${ctx.jurisdiction}/${ctx.direction}): ${key.slice(0, 200)}`)
  }
}

// ---- main -------------------------------------------------------------------

const allowDirty = process.argv.includes('--allow-dirty')
const revision = resolveRevision(allowDirty)
checkVocabulariesMatchFieldTypes()

rmSync(OUT_DIR, { recursive: true, force: true })
mkdirSync(OUT_DIR, { recursive: true })

const jurisdictionIds = readdirSync(DATA_DIR).filter((d) => existsSync(join(DATA_DIR, d, 'datapackage.json')))
if (jurisdictionIds.length === 0) fail(`no datapackages under ${DATA_DIR}`)

const jurisdictions: Jurisdiction[] = []
/** 収録している全 budget。カバレッジはここから導出する（jurisdiction には持たせない） */
const allBudgets: Budget[] = []
const crossByDivision = new Map<string, CrossBudgetLine[]>()
const filesMeta: Record<string, Record<string, { sha256: string; size: number; contentType: string }>> = {}
/** 検査2の期待値。cofog リソース側から独立に計算する（chunk 側と同じ経路で作らない） */
const expectedCrossCounts = new Map<string, number>()
const expectedCrossAmounts = new Map<string, number>()

for (const j of jurisdictionIds.sort()) {
  const dir = join(DATA_DIR, j)
  const descriptor = JSON.parse(readFileSync(join(dir, 'datapackage.json'), 'utf8')) as Descriptor

  const label = descriptor.resources[0]?.schema.extraFields?.find((f) => f.name === 'jurisdiction_label')?.constant
    ?? fail(`jurisdiction_label constant missing for ${j}`)
  const perJurisdiction = BY_JURISDICTION[j]
    ?? fail(`report/budget/static.ts has no BY_JURISDICTION entry for ${j} (declare it; defaults are not allowed)`)
  const amountPhase = AMOUNT_PHASE[j] ?? fail(`AMOUNT_PHASE not declared for ${j} in apps/api/build.ts`)

  // 検査4: 必須カテゴリ
  for (const cat of REQUIRED_CAVEAT_CATEGORIES) {
    if (!perJurisdiction.caveats.some((c) => c.category === cat)) {
      fail(`caveats for ${j} lack required category "${cat}" (report/budget/static.ts)`)
    }
  }

  const cofogTable = readCsvTable(join(dir, 'cofog.csv'))
  const cofogByLineId = new Map<string, CofogRow>()
  for (const row of cofogTable.rows) {
    // 検査: cofog リソースは budget_line_id 単位で1行（重複は黙って上書きせず止める）
    if (cofogByLineId.has(row['budget_line_id']!)) fail(`duplicate budget_line_id in cofog.csv of ${j}: ${row['budget_line_id']}`)
    // 検査: 状態と division・direction の対応（assigned だけが division を持つ / 歳入は not-applicable）
    const st = row['cofog_status']!
    const div = row['cofog_division']!
    if (st === 'assigned' && !/^(0[1-9]|10)$/.test(div)) fail(`assigned cofog row without a valid division (01..10) in ${j}: ${row['budget_line_id']} -> "${div}"`)
    if (st !== 'assigned' && div !== '') fail(`non-assigned cofog row with a division in ${j}: ${row['budget_line_id']} (${st} -> "${div}")`)
    if (row['direction'] === 'revenue' && st !== 'not-applicable') fail(`revenue cofog row must be not-applicable in ${j}: ${row['budget_line_id']} (${st})`)
    if (row['direction'] === 'expenditure' && st === 'not-applicable') fail(`expenditure cofog row must not be not-applicable in ${j}: ${row['budget_line_id']}`)
    cofogByLineId.set(row['budget_line_id']!, {
      status: cofogStatus.parse(row['cofog_status']),
      division: row['cofog_division'] === '' ? null : row['cofog_division']!,
      consolidation: cofogConsolidation.parse(row['cofog_consolidation']),
      decidedAtLevel: row['cofog_decided_at_level'] === '' ? null : cofogDecidedAtLevel.parse(row['cofog_decided_at_level']),
      ruleId: row['cofog_rule_id'] === '' ? null : row['cofog_rule_id']!,
    })
  }

  let projectNames: Map<string, string> | null = null
  if (existsSync(join(dir, 'project_names.csv'))) {
    projectNames = new Map()
    for (const row of readCsvTable(join(dir, 'project_names.csv')).rows) {
      const key = [row['fiscal_year'], row['fund_code'], row['kan_code'], row['kou_code'], row['moku_code'], row['daijigyo_code']].join('|')
      projectNames.set(key, row['project_name']!)
    }
  }

  const fiscalYears: Record<Direction, string[]> = { expenditure: [], revenue: [] }
  const linesByYearDir = new Map<string, BudgetLine[]>()
  /** 検査2用: 年度 → (budget_line_id → 全予算段階の金額合計)。cofog 行ループを O(1) 参照にする */
  const expenditureSums = new Map<string, Map<string, number>>()

  for (const direction of DIRECTIONS) {
    const table = readCsvTable(join(dir, `${direction}.csv`))
    const ctx = resourceContext(j, direction, table, descriptor)
    const lines = buildLines(ctx, table, cofogByLineId, projectNames)
    checkMultisetEquality(ctx, table, lines)

    const years = [...new Set(lines.map((l) => l.fiscalYear))].sort()
    fiscalYears[direction] = years
    for (const year of years) {
      const yearLines = lines.filter((l) => l.fiscalYear === year)
      linesByYearDir.set(`${year}-${direction}`, yearLines)
      writeChunkSeries(assetPaths.linesFamily(j, year, direction), yearLines)
    }
    if (direction === 'expenditure') {
      for (const year of years) {
        const sums = new Map<string, number>()
        for (const r of table.rows) {
          if (r['fiscal_year'] !== year) continue
          sums.set(r['budget_line_id']!, (sums.get(r['budget_line_id']!) ?? 0) + Number(r['value']))
        }
        expenditureSums.set(year, sums)
      }
      for (const line of lines) {
        const division = line.judgments.cofog?.division
        if (!division) continue
        const cross: CrossBudgetLine = {
          budget: `budgets/${budgetIdOf(j, line.fiscalYear)}`,
          budgetLineId: line.budgetLineId,
          fiscalYear: line.fiscalYear,
          amounts: line.amounts.map((a) => ({ phase: a.phase, amount: a.amount })),
          cofog: {
            status: line.judgments.cofog!.status,
            division,
            consolidation: line.judgments.cofog!.consolidation,
          },
        }
        const bucket = crossByDivision.get(division) ?? []
        bucket.push(cross)
        crossByDivision.set(division, bucket)
      }
    }
  }

  if (projectNames !== null) {
    const joined = [...linesByYearDir.values()].flat().filter((l) => l.judgments.projectName !== null).length
    if (joined === 0) fail(`project_names.csv exists for ${j} but zero lines joined (key mismatch?)`)
  }

  // budgets（年度スコープのメタ。検査3: 分類率の内訳の一致を含む）。分類率は歳出に限定する
  const budgets: Budget[] = []
  const allYears = [...new Set([...fiscalYears.expenditure, ...fiscalYears.revenue])].sort()
  for (const year of allYears) {
    if (!fiscalYears.expenditure.includes(year)) fail(`year ${year} has revenue but no expenditure for ${j} (unexpected)`)
    const yearLines = linesByYearDir.get(`${year}-expenditure`)!
    const statuses = {
      assigned: { lines: 0, amount: 0 },
      unclassifiable: { lines: 0, amount: 0 },
      outOfScope: { lines: 0, amount: 0 },
    }
    let totalAtPhase = 0
    for (const line of yearLines) {
      const status = line.judgments.cofog?.status ?? fail(`expenditure line without cofog row: ${line.budgetLineId}`)
      const key = status === 'assigned' ? 'assigned' : status === 'unclassifiable' ? 'unclassifiable' : status === 'out-of-scope' ? 'outOfScope' : fail(`unknown cofog_status "${status}" on ${line.budgetLineId}`)
      const amountAtPhase = line.amounts.find((a) => a.phase === amountPhase)?.amount
        ?? fail(`line ${line.budgetLineId} has no amount at declared phase "${amountPhase}"`)
      statuses[key].lines += 1
      statuses[key].amount += amountAtPhase
      totalAtPhase += amountAtPhase
    }
    const denominator = yearLines.length
    const sumLines = statuses.assigned.lines + statuses.unclassifiable.lines + statuses.outOfScope.lines
    if (sumLines !== denominator) fail(`classification rate line counts (${sumLines}) != distinct expenditure budget lines (${denominator}) for ${j}/${year}`)
    const sumAmount = statuses.assigned.amount + statuses.unclassifiable.amount + statuses.outOfScope.amount
    if (sumAmount !== totalAtPhase) fail(`classification rate amounts do not add up for ${j}/${year}`)
    budgets.push(budgetSchema.parse({
      name: `budgets/${budgetIdOf(j, year)}`,
      id: budgetIdOf(j, year),
      jurisdictionId: j,
      fiscalYear: year,
      directions: DIRECTIONS.filter((d) => fiscalYears[d].includes(year)),
      amountPhase,
      classificationRate: statuses,
    } satisfies Budget))
  }
  allBudgets.push(...budgets)

  // パススルー（検査5: SHA-256 一致）
  const passthroughFiles = ['datapackage.json', ...descriptor.resources.map((r) => r.path)]
  filesMeta[j] = {}
  for (const file of passthroughFiles) {
    const source = readFileSync(join(dir, file))
    const outPath = join(OUT_DIR, assetPaths.passthrough(j, file))
    mkdirSync(join(outPath, '..'), { recursive: true })
    writeFileSync(outPath, source)
    const sha256 = createHash('sha256').update(source).digest('hex')
    const copied = createHash('sha256').update(readFileSync(outPath)).digest('hex')
    if (sha256 !== copied) fail(`passthrough copy of ${j}/${file} does not match the distribution (SHA-256)`)
    filesMeta[j][file] = {
      sha256,
      size: source.byteLength,
      contentType: file.endsWith('.json') ? 'application/json; charset=utf-8' : 'text/csv; charset=utf-8',
    }
  }

  jurisdictions.push(jurisdictionSchema.parse({
    name: `jurisdictions/${j}`,
    id: j,
    label,
    datapackagePath: `/v0/datapackages/${j}/datapackage.json`,
    resources: passthroughFiles,
    licenses: descriptor.licenses,
    sources: descriptor.sources.map((s) => ({ title: s.title, path: s.path ?? null })),
    consolidationScope: perJurisdiction.consolidationScope,
    // API に載せるのは `api: true` の caveat だけ（基準は report/budget/schema.ts）。
    // 必須カテゴリの検査は全量（報告側）に対して行っているので、ここで絞っても落ちない
    caveats: perJurisdiction.caveats.filter((c) => c.api).map((c) => ({ category: c.category, topic: c.topic, body: c.body })),
  } satisfies Jurisdiction))

  // 検査2の材料: cofog リソース側から division ごとの期待値を計算する
  for (const row of cofogTable.rows) {
    if (row['direction'] !== 'expenditure' || row['cofog_division'] === '') continue
    expectedCrossCounts.set(row['cofog_division']!, (expectedCrossCounts.get(row['cofog_division']!) ?? 0) + 1)
    const yearSums = expenditureSums.get(row['fiscal_year']!) ?? fail(`cofog row references unknown year ${row['fiscal_year']} for ${j}`)
    const amountSum = yearSums.get(row['budget_line_id']!) ?? fail(`cofog row references unknown budget_line_id ${row['budget_line_id']}`)
    expectedCrossAmounts.set(row['cofog_division']!, (expectedCrossAmounts.get(row['cofog_division']!) ?? 0) + amountSum)
  }
}

// 横断 chunk の書き出しと検査2
function writeCrossChunks(): void {
  // 検査: 期待値側（cofog リソース由来）と chunk 側の division 集合が双方向に一致する
  const expectedDivisions = [...expectedCrossCounts.keys()].sort().join(',')
  const actualDivisions = [...crossByDivision.keys()].sort().join(',')
  if (expectedDivisions !== actualDivisions) {
    fail(`division sets differ: cofog resource has [${expectedDivisions}] but chunks have [${actualDivisions}]`)
  }
  for (const [division, lines] of crossByDivision) {
    lines.sort(byKey((l) => l.budgetLineId))
    for (const line of lines) crossBudgetLineSchema.parse(line)

    const count = expectedCrossCounts.get(division) ?? 0
    if (lines.length !== count) fail(`cross chunk count for division ${division} (${lines.length}) != cofog resource rows (${count})`)
    const amountSum = lines.reduce((s, l) => s + l.amounts.reduce((x, a) => x + a.amount, 0), 0)
    const expectedSum = expectedCrossAmounts.get(division) ?? 0
    if (amountSum !== expectedSum) fail(`cross chunk amount sum for division ${division} (${amountSum}) != expected (${expectedSum})`)

    writeChunkSeries(assetPaths.cofogFamily(division, undefined), lines)
    const years = [...new Set(lines.map((l) => l.fiscalYear))]
    for (const year of years) {
      writeChunkSeries(assetPaths.cofogFamily(division, year), lines.filter((l) => l.fiscalYear === year))
    }
  }
}

function writeChunkSeries(family: string, lines: unknown[]): void {
  const chunkCount = Math.max(1, Math.ceil(lines.length / CHUNK_SIZE))
  for (let i = 0; i < chunkCount; i++) {
    const chunkLines = lines.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE)
    const body = JSON.stringify({ revision, hasNext: i + 1 < chunkCount, lines: chunkLines })
    if (Buffer.byteLength(body) > CHUNK_BYTES_LIMIT) fail(`chunk ${family}/${i}.json exceeds ${CHUNK_BYTES_LIMIT} bytes`)
    const chunkPath = join(OUT_DIR, assetPaths.chunk(family, i))
    mkdirSync(join(chunkPath, '..'), { recursive: true })
    writeFileSync(chunkPath, body)
  }
}

function writeJson(path: string, value: unknown): void {
  writeText(path, JSON.stringify(value))
}

function writeText(path: string, body: string): void {
  mkdirSync(join(path, '..'), { recursive: true })
  writeFileSync(path, body)
}

writeCrossChunks()
allBudgets.sort(byKey((b) => b.id))
writeJson(join(OUT_DIR, assetPaths.jurisdictions), { revision, jurisdictions, budgets: allBudgets })
writeJson(join(OUT_DIR, assetPaths.files), { revision, files: filesMeta })

// 出力の総点検: contract のスキーマに全 BudgetLine を通す（型のずれを deploy 前に落とす）
for (const j of jurisdictionIds) {
  const linesDir = join(OUT_DIR, 'lines', j)
  for (const familyDir of readdirSync(linesDir)) {
    for (const file of readdirSync(join(linesDir, familyDir))) {
      const parsed = JSON.parse(readFileSync(join(linesDir, familyDir, file), 'utf8')) as { lines: unknown[] }
      for (const line of parsed.lines) budgetLineSchema.parse(line)
    }
  }
}

console.log(`built ${jurisdictionIds.length} jurisdiction(s) at revision ${revision} -> ${OUT_DIR}`)
