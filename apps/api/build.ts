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
import { COFOG_DEPTHS, cofogLabel, type CofogDepth } from '@fudoki/report/budget/detail'
import { BY_JURISDICTION } from '@fudoki/report/budget/static'
import {
  storedBudgetLineSchema,
  budgetSchema,
  cofogConsolidation,
  cofogDecidedAtLevel,
  cofogDepthOf,
  cofogStatus,
  CROSS_JURISDICTION_GROUPINGS,
  storedCrossBudgetLineSchema,
  dimensionName,
  hierarchyChildLevel,
  hierarchyParentPathString,
  JURISDICTION_YEARS_GROUPINGS,
  levelName,
  jurisdictionSchema,
  phaseId,
  SINGLE_BUDGET_GROUPINGS,
  SUPPORTED_GROUPINGS,
  type Budget,
  type BudgetDirectionScope,
  type StoredBudgetLine,
  type BudgetScopes,
  type StoredCrossBudgetLine,
  type HierarchyParentSegment,
  type Jurisdiction,
} from './src/contract'
import { budgetIdOf, direction } from './src/contract'
import {
  paths as assetPaths,
  type AggBudgetsAsset,
  type AggCrossAsset,
  type AggHierarchyAsset,
  type AggHierarchyCofogAsset,
  type AggStat,
  type AggYearsCofogDivisionAsset,
  type AggYearsFundScope,
  type AggYearsTotalAsset,
  type NameIndexEntry,
} from './src/assets'

const ROOT = join(import.meta.dir, '../..')
const DATA_DIR = join(ROOT, 'data/budget/datapackages')
const OUT_DIR = join(import.meta.dir, 'dist/assets')
const CHUNK_SIZE = 1000
/** 1 chunk のサイズ上限（Cloudflare の 25MiB 制限に対する早期警報） */
const CHUNK_BYTES_LIMIT = 20 * 1024 * 1024

/**
 * `provenance.sources` の kind / license の正本（PR #27 レビュー指摘）。
 * datapackage.json の `sources[]` は原典を年度の数だけ複製した生の一覧で、正本かどうか・
 * ライセンスが確定しているかを区別しない ── 狛江市の事業名は決算資料 PDF から起こしており、
 * その PDF の再配布可否は `ingestion/budget/sources.toml` で `review` / `NOASSERTION` と
 * 宣言されているのに、以前の実装は団体の代表ライセンス（CC-BY-4.0）を全出典へ機械的に付けていた。
 * ここで宣言そのもの（取得の入力）を読み、種類ごとに重複排除した出典を組む。
 */
const sourcesToml = Bun.TOML.parse(readFileSync(join(ROOT, 'ingestion/budget/sources.toml'), 'utf8')) as Record<string, unknown>

type ProvenanceSourceDecl = { title: string; path: string | null; license: string; kind: 'canonical' | 'judgment' }

/**
 * jurisdiction の canonical（カタログ由来の一次データ）と judgment（事業名などを起こした二次資料）
 * を、sources.toml の宣言から重複排除して組む。同じ (kind, title, path) は1件にまとめる
 * （狛江市の canonical は年度ごとの `["<団体>:<年度>"]` テーブルに同じ値が6回現れる）。
 */
function provenanceSourcesFromToml(jurisdiction: string): ProvenanceSourceDecl[] {
  const out: ProvenanceSourceDecl[] = []
  const seen = new Set<string>()
  const push = (title: string, path: string | null, license: string, kind: ProvenanceSourceDecl['kind']): void => {
    const key = `${kind}|${title}|${path}`
    if (seen.has(key)) return
    seen.add(key)
    out.push({ title, path, license, kind })
  }
  for (const [key, value] of Object.entries(sourcesToml)) {
    if (!key.startsWith(`${jurisdiction}:`)) continue
    const block = value as { attribution?: string; landing_page?: string; license_id?: string }
    if (block.attribution !== undefined && block.license_id !== undefined) {
      push(block.attribution, block.landing_page ?? null, block.license_id, 'canonical')
    }
  }
  // 事業名（project_names）・歳入科目名（revenue_accounts）は fudoki の判断（事業名・科目名の対応づけ）
  // を作るために参照した二次資料。redistribute/license_id は canonical とは別レイヤーで宣言されている。
  for (const section of ['project_names', 'revenue_accounts'] as const) {
    const table = sourcesToml[section] as Record<string, { document_title?: string; url?: string; license_id?: string }> | undefined
    if (table === undefined) continue
    for (const [key, block] of Object.entries(table)) {
      if (!key.startsWith(`${jurisdiction}:`)) continue
      if (block.document_title !== undefined && block.license_id !== undefined) {
        push(block.document_title, block.url ?? null, block.license_id, 'judgment')
      }
    }
  }
  if (out.filter((s) => s.kind === 'canonical').length === 0) {
    fail(`no canonical source declared in ingestion/budget/sources.toml for jurisdiction ${jurisdiction}`)
  }
  return out
}

/**
 * 分類率の金額ベースに使う予算段階。**団体を足すときは必ずここに書く**
 * （宣言が無ければ build が止まる。既定値で埋めない）。
 * 132047: 当初予算のみの資料なので approved。
 * 132195: 決算の予算現額（流用・充用まで反映した後の額）。
 * 132241: 当初予算のみの資料なので approved（sources.toml の phase_id と同じ）。
 */
const AMOUNT_PHASE: Record<string, StoredBudgetLine['amounts'][number]['phase']> = {
  '132047': 'approved',
  '132195': 'adjusted',
  '132241': 'approved',
}

/**
 * 目より下の「事業階層」を表すレベル名。節・細節・細々節（節以下、経済性分類の深掘り）とは別軸で、
 * moku の直後にこれらのいずれかが現れる団体は、目までしか出さない集計に対して
 * 「もう1段下がれるが出していない」（scopes.nextHierarchyLevel）が生じる。
 * AGENTS.md の「事業階層（大事業、中事業、小事業）」に dbt_project.yml の
 * 「歳出は目の下に細目（事業）が入り」（132241）を合わせた語彙。
 */
const PROJECT_LEVELS = new Set(['jikou', 'daijigyo', 'chujigyo', 'shojigyo', 'saimoku'])

/**
 * 名称の検索（design doc「名称の検索」）で accountLabel の索引対象にする階層。
 * 経済性分類（setsu/saisetsu/saisaisetsu。「報酬」「需用費」のような勘定科目名）と
 * fund は除く ── 名称の検索が指す「名称」は事業・事項・款項目のような分類名で、
 * 会計処理上の経済性分類は対象外という判断（design doc に明記は無い、この実装の判断）。
 */
const ACCOUNT_LABEL_LEVELS = new Set(['kan', 'kou', 'moku', 'jikou', 'daijigyo', 'chujigyo', 'shojigyo', 'saimoku'])
/** kan/kou/moku は原典に無ければ account_names.csv へフォールバックする対象（名称索引用） */
const KAN_KOU_MOKU_LEVELS = new Set(['kan', 'kou', 'moku'])

/** levels 内で moku の直後が事業階層なら、そのレベル名を返す（無ければ null） */
function nextProjectLevel(levels: string[]): string | null {
  const mokuIndex = levels.indexOf('moku')
  if (mokuIndex === -1) fail(`levels has no "moku": ${levels.join(',')}`)
  const next = levels[mokuIndex + 1]
  return next !== undefined && PROJECT_LEVELS.has(next) ? next : null
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

// ---- StoredBudgetLine construction ------------------------------------------------

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

type CofogRow = NonNullable<StoredBudgetLine['judgments']['cofog']>

function buildLines(
  ctx: ResourceContext,
  table: Table,
  cofogByLineId: Map<string, CofogRow>,
  projectNameByKey: Map<string, string> | null,
): StoredBudgetLine[] {
  const byId = new Map<string, StoredBudgetLine>()
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

function checkMultisetEquality(ctx: ResourceContext, table: Table, lines: StoredBudgetLine[]): void {
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

// ---- scopes（budget の direction ごとの収録範囲） ---------------------------

type PhaseIdT = StoredBudgetLine['amounts'][number]['phase']
type CofogAux = { division: string; group: string; klass: string; status: string; consolidation: string }

/** cofog.csv を budget_line_id で引けるようにした素の行。判断（judgments）の型とは別に、group/class 込みで持つ */
function buildCofogAux(cofogTable: Table): Map<string, CofogAux> {
  const map = new Map<string, CofogAux>()
  for (const row of cofogTable.rows) {
    map.set(row['budget_line_id']!, {
      division: row['cofog_division']!,
      group: row['cofog_group']!,
      klass: row['cofog_class']!,
      status: row['cofog_status']!,
      consolidation: row['cofog_consolidation']!,
    })
  }
  return map
}

function amountAtPhase(line: StoredBudgetLine, phase: PhaseIdT): number {
  return line.amounts.find((a) => a.phase === phase)?.amount ?? fail(`line ${line.budgetLineId} has no amount at phase "${phase}"`)
}

function phasesScopeFor(yearLines: StoredBudgetLine[], amountPhase: PhaseIdT): BudgetDirectionScope['phases'] {
  const labelByPhase = new Map<string, string>()
  for (const line of yearLines) {
    for (const a of line.amounts) {
      const existing = labelByPhase.get(a.phase)
      if (existing !== undefined && existing !== a.phaseLabel) {
        fail(`inconsistent phaseLabel for phase "${a.phase}": "${existing}" vs "${a.phaseLabel}"`)
      }
      labelByPhase.set(a.phase, a.phaseLabel)
    }
  }
  // phaseId.options の宣言順に揃える（見た目の安定性のため。集合としての一致は検査側が見る）
  return phaseId.options
    .filter((p) => labelByPhase.has(p))
    .map((p) => ({ id: p, label: labelByPhase.get(p)!, isPrimary: p === amountPhase }))
}

function fundsScopeFor(yearLines: StoredBudgetLine[]): BudgetDirectionScope['funds'] {
  const labelByCode = new Map<string, string | null>()
  for (const line of yearLines) {
    const fund = line.hierarchy.find((h) => h.level === 'fund') ?? fail(`line without a fund level: ${line.budgetLineId}`)
    const existing = labelByCode.get(fund.code)
    if (existing !== undefined && existing !== fund.label) fail(`inconsistent fund label for code "${fund.code}"`)
    labelByCode.set(fund.code, fund.label)
  }
  return [...labelByCode.entries()].sort(byKey(([code]) => code)).map(([code, label]) => ({ code, label }))
}

function consolidationScopeFor(yearLines: StoredBudgetLine[], amountPhase: PhaseIdT, cofogAux: Map<string, CofogAux>): BudgetDirectionScope['consolidation'] {
  const stats = { retained: { lineCount: 0, amount: 0 }, eliminated: { lineCount: 0, amount: 0 } }
  for (const line of yearLines) {
    const aux = cofogAux.get(line.budgetLineId) ?? fail(`line without a cofog row: ${line.budgetLineId}`)
    const amount = amountAtPhase(line, amountPhase)
    const bucket = aux.consolidation === 'retained' ? stats.retained : aux.consolidation === 'eliminated' ? stats.eliminated : fail(`unknown cofog_consolidation "${aux.consolidation}" for ${line.budgetLineId}`)
    bucket.lineCount += 1
    bucket.amount += amount
  }
  return stats
}

function cofogDepthScopeFor(
  direction: Direction,
  yearLines: StoredBudgetLine[],
  amountPhase: PhaseIdT,
  cofogAux: Map<string, CofogAux>,
): BudgetDirectionScope['cofogDepth'] {
  if (direction === 'revenue') return { applicable: false }
  let divisionCount = 0, divisionAmount = 0
  let groupCount = 0, groupAmount = 0
  let classCount = 0, classAmount = 0
  for (const line of yearLines) {
    const aux = cofogAux.get(line.budgetLineId) ?? fail(`line without a cofog row: ${line.budgetLineId}`)
    if (aux.status !== 'assigned') continue
    const amount = amountAtPhase(line, amountPhase)
    divisionCount += 1
    divisionAmount += amount
    if (aux.group !== '') { groupCount += 1; groupAmount += amount }
    if (aux.klass !== '') { classCount += 1; classAmount += amount }
  }
  if (divisionCount === 0) fail('cofogDepth: no assigned expenditure lines (unexpected — expenditure lines must not all be unclassifiable/out-of-scope)')
  return {
    applicable: true,
    division: { lineCount: divisionCount, amount: divisionAmount, rate: 1 },
    group: { lineCount: groupCount, amount: groupAmount, rate: groupCount / divisionCount },
    class: { lineCount: classCount, amount: classAmount, rate: classCount / divisionCount },
  }
}

/**
 * 款・項・目の名称の収録状況。まず原典の {level}_label（budgetLine.hierarchy）を見る。
 * 1行でも名称があれば canonical。原典が名称の列を持たない団体（狛江市など）は
 * account_names.csv（判断のリソース、name_source で出所を区別する）にフォールバックする。
 * ⚠️ hasName は「全行に付いている」ではなく「この年度・direction のどこかに付いている」。
 * 狛江市は同じ年度でも会計（fund）で割れる ── 一般会計は決算資料 PDF があるが、
 * 特別会計には無い（実測: 2020年度 168 行中 settlement-pdf は 103 行）。
 * 全行一致を条件にすると、この団体差そのものを「宣言漏れ」と誤判定してしまう。
 * 詳細な到達率が要る場面は nextHierarchyLevel.namedAmountRate 側で表す。
 */
function hierarchyNameScopeFor(
  level: 'kan' | 'kou' | 'moku',
  yearLines: StoredBudgetLine[],
  accountNameRows: Record<string, string>[],
): { level: 'kan' | 'kou' | 'moku'; hasName: boolean; source: 'canonical' | 'judgment' | null } {
  if (yearLines.length === 0) fail(`hierarchyNameScope: no lines for level "${level}"`)
  const hasCanonicalLabel = yearLines.some((l) => l.hierarchy.find((h) => h.level === level)?.label !== null)
  if (hasCanonicalLabel) return { level, hasName: true, source: 'canonical' }

  if (accountNameRows.length === 0) fail(`cannot resolve ${level} name: raw label column is empty and no account_names.csv rows for this year/direction`)
  const nameColumn = `${level}_name`
  const namedRows = accountNameRows.filter((r) => r[nameColumn] !== '')
  if (namedRows.length === 0) return { level, hasName: false, source: null }
  const sources = new Set(namedRows.map((r) => r['name_source']!))
  if (sources.size !== 1) fail(`mixed name_source for ${level} in account_names.csv: ${[...sources].join(',')}`)
  const source = [...sources][0]!
  if (source === 'source-csv') return { level, hasName: true, source: 'canonical' }
  if (source === 'settlement-pdf') return { level, hasName: true, source: 'judgment' }
  fail(`unknown name_source in account_names.csv: "${source}"`)
}

/**
 * moku より下の事業階層（jikou/daijigyo/saimoku 等）の収録状況。団体×direction 全体で1つ
 * （levels の宣言が年度で変わらないのと同じく、この判定も年度に依存しない）。
 * 名称は「原典の {level}_label に直接ある」（三鷹市・多摩市）か
 * 「project_names.csv による判断」（狛江市の daijigyo）のどちらか。
 */
function nextHierarchyLevelScopeFor(
  direction: Direction,
  levels: string[],
  table: Table,
  amountPhase: PhaseIdT,
  projectNames: Map<string, string> | null,
): BudgetDirectionScope['nextHierarchyLevel'] {
  const level = nextProjectLevel(levels)
  if (level === null) return null
  const rows = table.rows.filter((r) => r['phase_id'] === amountPhase)
  let total = 0
  let named = 0
  for (const row of rows) {
    const amount = Number(row['value'])
    total += amount
    const canonicalLabel = row[`${level}_label`]
    let hasName = canonicalLabel !== undefined && canonicalLabel !== ''
    if (!hasName && projectNames !== null && direction === 'expenditure') {
      const levelCodes = levels.map((l) => [l, row[`${l}_code`]!] as [string, string])
      const key = projectKey(row['fiscal_year']!, levelCodes)
      hasName = key !== null && projectNames.has(key)
    }
    if (hasName) named += amount
  }
  if (total === 0) fail(`nextHierarchyLevel: total amount at phase "${amountPhase}" is 0 for level "${level}" (unexpected)`)
  return {
    level: levelName.parse(level),
    available: true,
    aggregateSupported: false,
    namedAmountRate: named / total,
    alternative: 'budgetLines:search',
  }
}

/** project_names.csv が事業名を付けている範囲（団体×direction 全体。年度ごとに絞らない） */
function projectNameScopeFor(direction: Direction, levels: string[], projectNames: Map<string, string> | null): BudgetDirectionScope['names']['projectName'] {
  if (projectNames === null || direction !== 'expenditure' || !levels.includes('daijigyo')) return null
  const funds = new Set<string>()
  const fiscalYears = new Set<string>()
  for (const key of projectNames.keys()) {
    const [year, fund] = key.split('|')
    fiscalYears.add(year!)
    funds.add(fund!)
  }
  return { hasName: true, source: 'judgment', funds: [...funds].sort(), fiscalYears: [...fiscalYears].sort() }
}

// ---- 検査: scopes を配布物から独立に再計算して突き合わせる ----------------------
// ⚠️ ここは `lines`（buildLines の出力）を再利用しない。上の生成側と同じバグを
// 共有してしまうと、生成側が間違っていても検査が黙って一致してしまう。

function checkPhasesAndFundsMatchSource(
  jurisdiction: string, direction: Direction, year: string, table: Table,
  scopePhases: BudgetDirectionScope['phases'], scopeFunds: BudgetDirectionScope['funds'],
): void {
  const rows = table.rows.filter((r) => r['fiscal_year'] === year)
  const expectedPhases = [...new Set(rows.map((r) => r['phase_id']!))].sort().join(',')
  const actualPhases = [...new Set(scopePhases.map((p) => p.id as string))].sort().join(',')
  if (expectedPhases !== actualPhases) {
    fail(`scopes.phases mismatch for ${jurisdiction}/${year}/${direction}: source=[${expectedPhases}] scopes=[${actualPhases}]`)
  }
  const expectedFunds = [...new Set(rows.map((r) => r['fund_code']!))].sort().join('\0')
  const actualFunds = [...new Set(scopeFunds.map((f) => f.code))].sort().join('\0')
  if (expectedFunds !== actualFunds) {
    fail(`scopes.funds mismatch for ${jurisdiction}/${year}/${direction}: source=[${expectedFunds}] scopes=[${actualFunds}]`)
  }
}

function checkConsolidationMatchesSource(
  jurisdiction: string, direction: Direction, year: string, table: Table, cofogTable: Table, amountPhase: PhaseIdT,
  scope: BudgetDirectionScope['consolidation'],
): void {
  const consolidationByLineId = new Map<string, string>()
  for (const row of cofogTable.rows) {
    if (row['fiscal_year'] !== year || row['direction'] !== direction) continue
    consolidationByLineId.set(row['budget_line_id']!, row['cofog_consolidation']!)
  }
  let retainedCount = 0, retainedAmount = 0, eliminatedCount = 0, eliminatedAmount = 0
  for (const row of table.rows) {
    if (row['fiscal_year'] !== year || row['phase_id'] !== amountPhase) continue
    const c = consolidationByLineId.get(row['budget_line_id']!) ?? fail(`no cofog row for ${row['budget_line_id']} (${jurisdiction}/${year}/${direction})`)
    const amount = Number(row['value'])
    if (c === 'retained') { retainedCount += 1; retainedAmount += amount } else if (c === 'eliminated') { eliminatedCount += 1; eliminatedAmount += amount } else fail(`unexpected cofog_consolidation "${c}"`)
  }
  if (retainedCount !== scope.retained.lineCount || retainedAmount !== scope.retained.amount || eliminatedCount !== scope.eliminated.lineCount || eliminatedAmount !== scope.eliminated.amount) {
    fail(`scopes.consolidation mismatch for ${jurisdiction}/${year}/${direction}: independent count = retained(${retainedCount},${retainedAmount}) eliminated(${eliminatedCount},${eliminatedAmount})`)
  }
}

function checkCofogDepthMatchesSource(
  jurisdiction: string, year: string, table: Table, cofogTable: Table, amountPhase: PhaseIdT,
  scope: BudgetDirectionScope['cofogDepth'],
): void {
  if (scope.applicable !== true) return
  const amountByLineId = new Map<string, number>()
  for (const row of table.rows) {
    if (row['fiscal_year'] !== year || row['phase_id'] !== amountPhase) continue
    amountByLineId.set(row['budget_line_id']!, (amountByLineId.get(row['budget_line_id']!) ?? 0) + Number(row['value']))
  }
  let divisionCount = 0, divisionAmount = 0, groupCount = 0, groupAmount = 0, classCount = 0, classAmount = 0
  for (const row of cofogTable.rows) {
    if (row['fiscal_year'] !== year || row['direction'] !== 'expenditure' || row['cofog_status'] !== 'assigned') continue
    const amount = amountByLineId.get(row['budget_line_id']!) ?? fail(`cofog row references unknown budget_line_id for ${jurisdiction}/${year}: ${row['budget_line_id']}`)
    divisionCount += 1
    divisionAmount += amount
    if (row['cofog_group'] !== '') { groupCount += 1; groupAmount += amount }
    if (row['cofog_class'] !== '') { classCount += 1; classAmount += amount }
  }
  const expected = {
    division: { lineCount: divisionCount, amount: divisionAmount, rate: divisionCount === 0 ? 0 : 1 },
    group: { lineCount: groupCount, amount: groupAmount, rate: divisionCount === 0 ? 0 : groupCount / divisionCount },
    class: { lineCount: classCount, amount: classAmount, rate: divisionCount === 0 ? 0 : classCount / divisionCount },
  } as const
  for (const depth of ['division', 'group', 'class'] as const) {
    const e = expected[depth]
    const a = scope[depth]
    if (e.lineCount !== a.lineCount || e.amount !== a.amount || Math.abs(e.rate - a.rate) > 1e-9) {
      fail(`scopes.cofogDepth.${depth} mismatch for ${jurisdiction}/${year}: expected ${JSON.stringify(e)}, got ${JSON.stringify(a)}`)
    }
  }
}

// ---- 規模の実測（前計算アセットは作らない。exploratory measurement） -------------

/**
 * ある1グループ（fund 単位の行の集合）を parentKeyOf でグルーピングし、
 * 親ごとの (childKeyOf の異なり数) × (cofog.division の異なり数) の最大値を返す。
 * 対象は割当済み（cofog_status=assigned）行だけ（design doc Caveats 5 の測り方に合わせる）。
 */
function maxCellsAcrossParents(
  lines: StoredBudgetLine[],
  cofogAux: Map<string, CofogAux>,
  parentKeyOf: (l: StoredBudgetLine) => string,
  childKeyOf: (l: StoredBudgetLine) => string,
): number {
  const byParent = new Map<string, { children: Set<string>; divisions: Set<string> }>()
  for (const line of lines) {
    const aux = cofogAux.get(line.budgetLineId)
    if (aux?.status !== 'assigned') continue
    const parent = parentKeyOf(line)
    const entry = byParent.get(parent) ?? { children: new Set<string>(), divisions: new Set<string>() }
    entry.children.add(childKeyOf(line))
    entry.divisions.add(aux.division)
    byParent.set(parent, entry)
  }
  let max = 0
  for (const { children, divisions } of byParent.values()) max = Math.max(max, children.size * divisions.size)
  return max
}

function codeAt(line: StoredBudgetLine, level: string): string {
  return line.hierarchy.find((h) => h.level === level)?.code ?? fail(`line ${line.budgetLineId} has no "${level}" level`)
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
const crossByDivision = new Map<string, StoredCrossBudgetLine[]>()
const filesMeta: Record<string, Record<string, { sha256: string; size: number; contentType: string }>> = {}
/** 検査2の期待値。cofog リソース側から独立に計算する（chunk 側と同じ経路で作らない） */
const expectedCrossCounts = new Map<string, number>()
const expectedCrossAmounts = new Map<string, number>()

/**
 * 名称索引のエントリを (field, level, value, nameSource) で束ねる Map（design doc「名称の検索」）。
 * **索引の単位は名称**なので、同じ名称を持つ明細を1エントリの refs へ積み、
 * hierarchy・amounts を明細ごとに複製しない（NameIndexEntry のコメント参照）。
 * 全団体を横断する1系列に積んでから、最後にまとめて chunk 書き出しする。
 */
const nameIndexByKey = new Map<string, NameIndexEntry>()

/** nameIndexByKey の1件を引くか無ければ作る */
function getOrCreateNameIndexEntry(field: NameIndexEntry['field'], level: string, value: string, nameSource: NameIndexEntry['nameSource']): NameIndexEntry {
  const key = `${field}|${level}|${value}|${nameSource}`
  let entry = nameIndexByKey.get(key)
  if (entry === undefined) {
    entry = { field, level, value, nameSource, refs: [] }
    nameIndexByKey.set(key, entry)
  }
  return entry
}
/**
 * 検査7の期待値: 索引が指す明細識別子が実在すること。cofog.csv（budget_line_id を
 * direction 問わず持つ）から独立に集める ── 索引の生成ロジック（buildLines の出力）を
 * 再利用しない。
 */
const allValidBudgetLineIds = new Set<string>()

// 規模の実測用カウンタ（design doc Caveats 5: 62団体への外挿はしないが、
// 今収録している団体では実測する。前計算アセットは生成しない — 数えるだけ）
const hierarchyAssetKeyCount: Record<Direction, number> = { expenditure: 0, revenue: 0 }
let cofogDepthAssetComboCount = 0
let maxHierarchyCofogCells = 0

// ---- COFOG 集計アセット（design doc「引ける集計の一覧」。この段は COFOG 軸のみ） --------
// build がセル単位で突き合わせる（design doc 検査1・2・6）。期待値は生成結果を再利用せず、
// CSV（table.rows / cofogTable.rows）から独立に再計算する ── 生成側は cofogAux（Map）を、
// 検査側はここで新しく組んだ Map を使い、同じバグを共有しないようにする。

function newAggStat(): AggStat {
  return { amount: 0, lineCount: 0 }
}

type CofogClassification =
  | { kind: 'unclassifiable' }
  | { kind: 'out-of-scope' }
  | { kind: 'not-descended' }
  | { kind: 'assigned'; code: string }

/**
 * cofog_status（+ 割当済みなら division/group/class のどれか1つ）から、金額をどの残余バケツへ
 * 足すか・どのセルへ積むかを1つに決める。生成4箇所・検査4箇所で同じ4分岐を読み方だけ変えて
 * 書いていたので、判断だけをここへ抜く（行の取得・cofogAux か cofogTable かの選び方はそれぞれの
 * 呼び出し元に残す。設計方針「生成と検査がデータの取得経路を共有してはいけない」はこの関数の外側の話）。
 */
function classifyCofogAmount(status: string, code: string | undefined, unexpectedStatusMessage: string): CofogClassification {
  if (status === 'unclassifiable') return { kind: 'unclassifiable' }
  if (status === 'out-of-scope') return { kind: 'out-of-scope' }
  if (status !== 'assigned') fail(unexpectedStatusMessage)
  if (!code) return { kind: 'not-descended' }
  return { kind: 'assigned', code }
}

/** 単一 budget（団体×年度×phase×fund）の COFOG 集計を生成し、アセットへ書く */
function writeAggBudgetAsset(
  jurisdiction: string,
  year: string,
  phase: string,
  fund: string,
  depth: CofogDepth,
  rows: Record<string, string>[],
  cofogAux: Map<string, CofogAux>,
): void {
  const cellsByCode = new Map<string, AggStat>()
  const unclassifiable = newAggStat()
  const outOfScope = newAggStat()
  const notDescended = newAggStat()
  const { retained, eliminated } = consolidationAt(rows, cofogAux)
  const total = newAggStat()
  for (const row of rows) {
    const id = row['budget_line_id']!
    const aux = cofogAux.get(id) ?? fail(`agg: no cofog row for ${id} (${jurisdiction}/${year})`)
    const amount = Number(row['value'])
    total.amount += amount
    total.lineCount += 1
    const code = depth === 'division' ? aux.division : depth === 'group' ? aux.group : aux.klass
    const cls = classifyCofogAmount(aux.status, code, `agg: unexpected cofog_status "${aux.status}" for expenditure row ${id}`)
    if (cls.kind === 'unclassifiable') {
      unclassifiable.amount += amount
      unclassifiable.lineCount += 1
      continue
    }
    if (cls.kind === 'out-of-scope') {
      outOfScope.amount += amount
      outOfScope.lineCount += 1
      continue
    }
    if (cls.kind === 'not-descended') {
      notDescended.amount += amount
      notDescended.lineCount += 1
      continue
    }
    const cell = cellsByCode.get(cls.code) ?? newAggStat()
    cell.amount += amount
    cell.lineCount += 1
    cellsByCode.set(cls.code, cell)
  }
  const cells = [...cellsByCode.entries()]
    .sort(byKey(([code]) => code))
    .map(([code, stat]) => ({ code, label: cofogLabel(depth, code), amount: stat.amount, lineCount: stat.lineCount }))
  const asset: AggBudgetsAsset = {
    revision,
    cells,
    residual: { unclassifiable, outOfScope, notDescended },
    total,
    consolidation: { retained, eliminated },
  }
  writeJson(join(OUT_DIR, assetPaths.aggBudget(jurisdiction, year, 'expenditure', phase, fund, depth)), asset)
}

/**
 * 検査1・2: 単一 budget の集計アセットが、cofog.csv + expenditure.csv から独立に数えた値と一致し、
 * かつ cells + residual = total が成り立つこと。**生成に使った cofogAux を再利用しない**
 * （ここだけの Map を cofogTable.rows から新しく組む）。
 *
 * ⚠️ `yearRows` は phase・fund で絞る前の生の行（年度だけで絞ったもの）を受け取り、
 * phase・fund の範囲選択は生成側の `fundRows` を再利用せずこの関数自身が行う（PR #27 レビュー指摘）。
 * セルの再集計の経路が別でも、範囲選択（yearRows → phaseRows → fundRows）を共有していると、
 * その選択自体を誤ったときに生成と検査が同時に同じ誤りを通してしまうため。
 */
function checkAggBudgetAssetMatchesSource(
  jurisdiction: string,
  year: string,
  phase: string,
  fund: string,
  depth: CofogDepth,
  yearRows: Record<string, string>[],
  cofogRowsForYear: Record<string, string>[],
): void {
  const byId = new Map(cofogRowsForYear.map((r) => [r['budget_line_id']!, r]))
  const relevantRows = yearRows.filter((r) => r['phase_id'] === phase && (fund === 'all' || r['fund_code'] === fund))
  // consolidationAt は cofogAux（Map<string, CofogAux>）を取るが、この検査は生成側の buildCofogAux は
  // 呼ばず、ここだけで cofogRowsForYear から独立に組む（生成と検査でデータの取得経路を共有しない）。
  const cofogAuxForCheck = new Map(
    cofogRowsForYear.map((r) => [
      r['budget_line_id']!,
      {
        division: r['cofog_division']!,
        group: r['cofog_group']!,
        klass: r['cofog_class']!,
        status: r['cofog_status']!,
        consolidation: r['cofog_consolidation']!,
      },
    ]),
  )
  const cellsByCode = new Map<string, AggStat>()
  const unclassifiable = newAggStat()
  const outOfScope = newAggStat()
  const notDescended = newAggStat()
  const { retained, eliminated } = consolidationAt(relevantRows, cofogAuxForCheck)
  const total = newAggStat()
  for (const row of relevantRows) {
    const id = row['budget_line_id']!
    const cofogRow = byId.get(id) ?? fail(`agg check: no cofog row for ${id}`)
    const amount = Number(row['value'])
    total.amount += amount
    total.lineCount += 1
    const status = cofogRow['cofog_status']!
    const code = depth === 'division' ? cofogRow['cofog_division']! : depth === 'group' ? cofogRow['cofog_group']! : cofogRow['cofog_class']!
    const cls = classifyCofogAmount(status, code, `agg check: unexpected cofog_status "${status}" for ${id}`)
    if (cls.kind === 'unclassifiable') {
      unclassifiable.amount += amount
      unclassifiable.lineCount += 1
      continue
    }
    if (cls.kind === 'out-of-scope') {
      outOfScope.amount += amount
      outOfScope.lineCount += 1
      continue
    }
    if (cls.kind === 'not-descended') {
      notDescended.amount += amount
      notDescended.lineCount += 1
      continue
    }
    const cell = cellsByCode.get(cls.code) ?? newAggStat()
    cell.amount += amount
    cell.lineCount += 1
    cellsByCode.set(cls.code, cell)
  }

  const assetPath = join(OUT_DIR, assetPaths.aggBudget(jurisdiction, year, 'expenditure', phase, fund, depth))
  const written = JSON.parse(readFileSync(assetPath, 'utf8')) as AggBudgetsAsset
  const writtenByCode = new Map(written.cells.map((c) => [c.code, c]))
  if (writtenByCode.size !== cellsByCode.size) {
    fail(`agg check: cell count mismatch for ${assetPath}: expected ${cellsByCode.size} got ${writtenByCode.size}`)
  }
  for (const [code, expected] of cellsByCode) {
    const w = writtenByCode.get(code) ?? fail(`agg check: missing cell "${code}" in ${assetPath}`)
    if (w.amount !== expected.amount || w.lineCount !== expected.lineCount) {
      fail(`agg check: cell "${code}" mismatch in ${assetPath}: expected ${JSON.stringify(expected)} got ${JSON.stringify({ amount: w.amount, lineCount: w.lineCount })}`)
    }
  }
  const pairs: [string, AggStat, AggStat][] = [
    ['residual.unclassifiable', unclassifiable, written.residual.unclassifiable],
    ['residual.outOfScope', outOfScope, written.residual.outOfScope],
    ['residual.notDescended', notDescended, written.residual.notDescended],
    ['total', total, written.total],
    ['consolidation.retained', retained, written.consolidation.retained],
    ['consolidation.eliminated', eliminated, written.consolidation.eliminated],
  ]
  for (const [name, expected, actual] of pairs) {
    if (expected.amount !== actual.amount || expected.lineCount !== actual.lineCount) {
      fail(`agg check: ${name} mismatch for ${assetPath}: expected ${JSON.stringify(expected)} got ${JSON.stringify(actual)}`)
    }
  }
  // 検査2: cells + residual = total
  const cellsSum = [...cellsByCode.values()].reduce((s, c) => ({ amount: s.amount + c.amount, lineCount: s.lineCount + c.lineCount }), newAggStat())
  const residualAmount = unclassifiable.amount + outOfScope.amount + notDescended.amount
  const residualLines = unclassifiable.lineCount + outOfScope.lineCount + notDescended.lineCount
  if (cellsSum.amount + residualAmount !== total.amount || cellsSum.lineCount + residualLines !== total.lineCount) {
    fail(`agg check: cells + residual != total for ${assetPath}`)
  }
}

// ---- hierarchy 集計アセット（design doc「引ける集計の一覧」2・3行目。Tasks 5） --------------
// fund は必ず特定の会計コード（"all" 無し）。款・項のコードは会計内でしか一意でないため
// （procedure/budgets.ts の hierarchyAggregate に同じ判断を書いている）。

type ChildLevel = 'kan' | 'kou' | 'moku'

/** fund に閉じた行から、根・各款・各(款,項) の parent path を列挙する（design doc Caveats 2: 目は親にしない） */
function hierarchyParentPaths(fundRows: Record<string, string>[]): HierarchyParentSegment[][] {
  const paths: HierarchyParentSegment[][] = [[]]
  const kanCodes = [...new Set(fundRows.map((r) => r['kan_code']!))].sort()
  for (const kan of kanCodes) {
    paths.push([{ level: 'kan', code: kan }])
    const kouCodes = [...new Set(fundRows.filter((r) => r['kan_code'] === kan).map((r) => r['kou_code']!))].sort()
    for (const kou of kouCodes) {
      paths.push([{ level: 'kan', code: kan }, { level: 'kou', code: kou }])
    }
  }
  return paths
}

function scopedRowsFor(fundRows: Record<string, string>[], segments: HierarchyParentSegment[]): Record<string, string>[] {
  return fundRows.filter((r) => segments.every((s) => r[`${s.level}_code`] === s.code))
}

/** child レベルの label。同じコードで label が割れていたら止める（fundsScopeFor などと同じ規律） */
function childLabelOf(rows: Record<string, string>[], childLevel: ChildLevel, code: string): string | null {
  const labels = new Set(rows.filter((r) => r[`${childLevel}_code`] === code).map((r) => labelOf(r, `${childLevel}_label`)))
  if (labels.size > 1) fail(`inconsistent ${childLevel} label for code "${code}": ${[...labels].join(' / ')}`)
  return [...labels][0] ?? null
}

function writeHierarchyAsset(
  jurisdiction: string,
  year: string,
  phase: string,
  fund: string,
  segments: HierarchyParentSegment[],
  childLevel: ChildLevel,
  scoped: Record<string, string>[],
): void {
  const cellsByCode = new Map<string, AggStat>()
  const total = newAggStat()
  for (const row of scoped) {
    const code = row[`${childLevel}_code`]!
    const amount = Number(row['value'])
    total.amount += amount
    total.lineCount += 1
    const cell = cellsByCode.get(code) ?? newAggStat()
    cell.amount += amount
    cell.lineCount += 1
    cellsByCode.set(code, cell)
  }
  const cells = [...cellsByCode.entries()]
    .sort(byKey(([code]) => code))
    .map(([code, stat]) => ({ code, label: childLabelOf(scoped, childLevel, code), amount: stat.amount, lineCount: stat.lineCount }))
  const asset: AggHierarchyAsset = { revision, childLevel, cells, total }
  writeJson(join(OUT_DIR, assetPaths.aggHierarchy(jurisdiction, year, 'expenditure', phase, fund, hierarchyParentPathString(segments))), asset)
}

/**
 * 検査1・2（hierarchy 版）。生成側の cellsByCode を再利用せず、独立に数え直す。
 * ⚠️ 引数は phase・fund・hierarchy の範囲で絞る前の `yearRows`。生成側が組んだ `scoped`
 * （fundRows → scopedRowsFor の結果）をそのまま受け取らず、この関数自身が phase・fund・
 * segments で絞る（PR #27 レビュー指摘。範囲選択の共有を断つ）。
 */
function checkHierarchyAssetMatchesSource(
  jurisdiction: string,
  year: string,
  phase: string,
  fund: string,
  segments: HierarchyParentSegment[],
  childLevel: ChildLevel,
  yearRows: Record<string, string>[],
): void {
  // hierarchy 集計は fund === 'all' を対象にしない（呼び出し側の判断。書き込み側と同じ前提）ので、
  // ここでは fund を会計コードの等値比較で使ってよい
  const scoped = yearRows.filter(
    (r) => r['phase_id'] === phase && r['fund_code'] === fund && segments.every((s) => r[`${s.level}_code`] === s.code),
  )
  const expectedByCode = new Map<string, AggStat>()
  const expectedTotal = newAggStat()
  for (const row of scoped) {
    const code = row[`${childLevel}_code`]!
    const amount = Number(row['value'])
    expectedTotal.amount += amount
    expectedTotal.lineCount += 1
    const cell = expectedByCode.get(code) ?? newAggStat()
    cell.amount += amount
    cell.lineCount += 1
    expectedByCode.set(code, cell)
  }
  const assetPath = join(OUT_DIR, assetPaths.aggHierarchy(jurisdiction, year, 'expenditure', phase, fund, hierarchyParentPathString(segments)))
  const written = JSON.parse(readFileSync(assetPath, 'utf8')) as AggHierarchyAsset
  if (written.cells.length !== expectedByCode.size) fail(`hierarchy check: cell count mismatch for ${assetPath}`)
  for (const [code, expected] of expectedByCode) {
    const w = written.cells.find((c) => c.code === code) ?? fail(`hierarchy check: missing cell "${code}" in ${assetPath}`)
    if (w.amount !== expected.amount || w.lineCount !== expected.lineCount) fail(`hierarchy check: cell "${code}" mismatch in ${assetPath}`)
  }
  if (written.total.amount !== expectedTotal.amount || written.total.lineCount !== expectedTotal.lineCount) {
    fail(`hierarchy check: total mismatch for ${assetPath}`)
  }
  // 検査2: cells の合計 = total（このアセットに COFOG の残余は無い）
  const cellsSum = [...expectedByCode.values()].reduce((s, c) => ({ amount: s.amount + c.amount, lineCount: s.lineCount + c.lineCount }), newAggStat())
  if (cellsSum.amount !== expectedTotal.amount || cellsSum.lineCount !== expectedTotal.lineCount) {
    fail(`hierarchy check: cells != total for ${assetPath}`)
  }
}

function writeHierarchyCofogAsset(
  jurisdiction: string,
  year: string,
  phase: string,
  fund: string,
  segments: HierarchyParentSegment[],
  childLevel: ChildLevel,
  scoped: Record<string, string>[],
  cofogAux: Map<string, CofogAux>,
): void {
  const cellsByKey = new Map<string, { childCode: string; division: string; stat: AggStat }>()
  const unclassifiable = newAggStat()
  const outOfScope = newAggStat()
  const notDescended = newAggStat()
  const total = newAggStat()
  for (const row of scoped) {
    const id = row['budget_line_id']!
    const aux = cofogAux.get(id) ?? fail(`hierarchy-cofog: no cofog row for ${id}`)
    const amount = Number(row['value'])
    total.amount += amount
    total.lineCount += 1
    const childCode = row[`${childLevel}_code`]!
    const cls = classifyCofogAmount(aux.status, aux.division, `hierarchy-cofog: unexpected cofog_status "${aux.status}" for ${id}`)
    if (cls.kind === 'unclassifiable') {
      unclassifiable.amount += amount
      unclassifiable.lineCount += 1
      continue
    }
    if (cls.kind === 'out-of-scope') {
      outOfScope.amount += amount
      outOfScope.lineCount += 1
      continue
    }
    if (cls.kind === 'not-descended') {
      notDescended.amount += amount
      notDescended.lineCount += 1
      continue
    }
    const key = `${childCode}|${cls.code}`
    const cell = cellsByKey.get(key) ?? { childCode, division: cls.code, stat: newAggStat() }
    cell.stat.amount += amount
    cell.stat.lineCount += 1
    cellsByKey.set(key, cell)
  }
  const cells = [...cellsByKey.values()]
    .sort(byKey((c) => `${c.childCode}:${c.division}`))
    .map((c) => ({
      code: c.childCode,
      label: childLabelOf(scoped, childLevel, c.childCode),
      cofogDivision: c.division,
      cofogLabel: cofogLabel('division', c.division),
      amount: c.stat.amount,
      lineCount: c.stat.lineCount,
    }))
  const asset: AggHierarchyCofogAsset = { revision, childLevel, cells, residual: { unclassifiable, outOfScope, notDescended }, total }
  writeJson(
    join(OUT_DIR, assetPaths.aggHierarchyCofog(jurisdiction, year, 'expenditure', phase, fund, hierarchyParentPathString(segments))),
    asset,
  )
}

/**
 * 検査1・2（hierarchy-cofog 版）。cofogRowsForYear（cofog リソース）から独立に数え直す。
 * ⚠️ こちらも `yearRows`（phase・fund・hierarchy で絞る前）を受け取り、範囲選択を自前で行う
 * （checkHierarchyAssetMatchesSource と同じ理由。PR #27 レビュー指摘）。
 */
function checkHierarchyCofogAssetMatchesSource(
  jurisdiction: string,
  year: string,
  phase: string,
  fund: string,
  segments: HierarchyParentSegment[],
  childLevel: ChildLevel,
  yearRows: Record<string, string>[],
  cofogRowsForYear: Record<string, string>[],
): void {
  const scoped = yearRows.filter(
    (r) => r['phase_id'] === phase && r['fund_code'] === fund && segments.every((s) => r[`${s.level}_code`] === s.code),
  )
  const byId = new Map(cofogRowsForYear.map((r) => [r['budget_line_id']!, r]))
  const cellsByKey = new Map<string, AggStat>()
  const unclassifiable = newAggStat()
  const outOfScope = newAggStat()
  const notDescended = newAggStat()
  const total = newAggStat()
  for (const row of scoped) {
    const id = row['budget_line_id']!
    const cofogRow = byId.get(id) ?? fail(`hierarchy-cofog check: no cofog row for ${id}`)
    const amount = Number(row['value'])
    total.amount += amount
    total.lineCount += 1
    const childCode = row[`${childLevel}_code`]!
    const status = cofogRow['cofog_status']!
    const division = cofogRow['cofog_division']!
    const cls = classifyCofogAmount(status, division, `hierarchy-cofog check: unexpected cofog_status "${status}" for ${id}`)
    if (cls.kind === 'unclassifiable') {
      unclassifiable.amount += amount
      unclassifiable.lineCount += 1
      continue
    }
    if (cls.kind === 'out-of-scope') {
      outOfScope.amount += amount
      outOfScope.lineCount += 1
      continue
    }
    if (cls.kind === 'not-descended') {
      notDescended.amount += amount
      notDescended.lineCount += 1
      continue
    }
    const key = `${childCode}|${cls.code}`
    const cell = cellsByKey.get(key) ?? newAggStat()
    cell.amount += amount
    cell.lineCount += 1
    cellsByKey.set(key, cell)
  }
  const assetPath = join(
    OUT_DIR,
    assetPaths.aggHierarchyCofog(jurisdiction, year, 'expenditure', phase, fund, hierarchyParentPathString(segments)),
  )
  const written = JSON.parse(readFileSync(assetPath, 'utf8')) as AggHierarchyCofogAsset
  if (written.cells.length !== cellsByKey.size) fail(`hierarchy-cofog check: cell count mismatch for ${assetPath}`)
  for (const [key, expected] of cellsByKey) {
    const [childCode, division] = key.split('|') as [string, string]
    const w = written.cells.find((c) => c.code === childCode && c.cofogDivision === division)
      ?? fail(`hierarchy-cofog check: missing cell ${key} in ${assetPath}`)
    if (w.amount !== expected.amount || w.lineCount !== expected.lineCount) fail(`hierarchy-cofog check: cell ${key} mismatch in ${assetPath}`)
  }
  const pairs: [string, AggStat, AggStat][] = [
    ['residual.unclassifiable', unclassifiable, written.residual.unclassifiable],
    ['residual.outOfScope', outOfScope, written.residual.outOfScope],
    ['residual.notDescended', notDescended, written.residual.notDescended],
    ['total', total, written.total],
  ]
  for (const [name, expected, actual] of pairs) {
    if (expected.amount !== actual.amount || expected.lineCount !== actual.lineCount) fail(`hierarchy-cofog check: ${name} mismatch for ${assetPath}`)
  }
  // 検査2
  const cellsSum = [...cellsByKey.values()].reduce((s, c) => ({ amount: s.amount + c.amount, lineCount: s.lineCount + c.lineCount }), newAggStat())
  const residualAmount = unclassifiable.amount + outOfScope.amount + notDescended.amount
  const residualLines = unclassifiable.lineCount + outOfScope.lineCount + notDescended.lineCount
  if (cellsSum.amount + residualAmount !== total.amount || cellsSum.lineCount + residualLines !== total.lineCount) {
    fail(`hierarchy-cofog check: cells + residual != total for ${assetPath}`)
  }
}

// ⚠️ 残余（unclassifiable / out-of-scope / notDescended）は団体ごとに持つ（Map<jurisdiction, AggStat>）。
// `cells` が jurisdiction を軸に必須にしているのに、以前は残余だけ全団体で1つの AggStat に
// 合算しており、団体をまたいで足さないという設計を残余だけが破っていた（PR #27 レビュー指摘）。
type CrossDepthBucket = {
  cellsByJC: Map<string, AggStat>
  unclassifiableByJ: Map<string, AggStat>
  outOfScopeByJ: Map<string, AggStat>
  notDescendedByJ: Map<string, AggStat>
}
type CrossAccum = {
  perDepth: Record<CofogDepth, CrossDepthBucket>
  retained: AggStat
  eliminated: AggStat
  includedBudgets: Set<string>
}

/** 年度横断（design doc「引ける集計の一覧」最終行）の材料。key は `${年度}|${phase}` */
const crossByKey = new Map<string, CrossAccum>()
const crossJurisdictionLabel = new Map<string, string>()
/** 検査（cross）用に団体ごとの table/cofogTable を残す（検査側の独立な再集計に使う） */
const perJurisdictionAggSource = new Map<string, { table: Table; cofogTable: Table; cofogAux: Map<string, CofogAux> }>()

function newCrossDepthBucket(): CrossDepthBucket {
  return { cellsByJC: new Map(), unclassifiableByJ: new Map(), outOfScopeByJ: new Map(), notDescendedByJ: new Map() }
}

/** Map<jurisdiction, AggStat> への加算。無ければ 0 から作る */
function addAggStatByJ(map: Map<string, AggStat>, jurisdiction: string, amount: number): void {
  const stat = map.get(jurisdiction) ?? newAggStat()
  stat.amount += amount
  stat.lineCount += 1
  map.set(jurisdiction, stat)
}

function crossAccumFor(key: string): CrossAccum {
  const existing = crossByKey.get(key)
  if (existing) return existing
  const created: CrossAccum = {
    perDepth: { division: newCrossDepthBucket(), group: newCrossDepthBucket(), class: newCrossDepthBucket() },
    retained: newAggStat(),
    eliminated: newAggStat(),
    includedBudgets: new Set(),
  }
  crossByKey.set(key, created)
  return created
}

/** 横断集計の材料を1団体ぶん積む。fund は選べない（design doc: 団体を絞らないと fund を指定できない） */
function accumulateCrossRows(jurisdiction: string, accum: CrossAccum, rows: Record<string, string>[], cofogAux: Map<string, CofogAux>): void {
  const { retained, eliminated } = consolidationAt(rows, cofogAux)
  accum.retained.amount += retained.amount
  accum.retained.lineCount += retained.lineCount
  accum.eliminated.amount += eliminated.amount
  accum.eliminated.lineCount += eliminated.lineCount
  for (const row of rows) {
    const id = row['budget_line_id']!
    const aux = cofogAux.get(id) ?? fail(`agg cross: no cofog row for ${id}`)
    const amount = Number(row['value'])
    for (const depth of COFOG_DEPTHS) {
      const bucket = accum.perDepth[depth]
      const code = depth === 'division' ? aux.division : depth === 'group' ? aux.group : aux.klass
      const cls = classifyCofogAmount(aux.status, code, `agg cross: unexpected cofog_status "${aux.status}" for ${id}`)
      if (cls.kind === 'unclassifiable') {
        addAggStatByJ(bucket.unclassifiableByJ, jurisdiction, amount)
        continue
      }
      if (cls.kind === 'out-of-scope') {
        addAggStatByJ(bucket.outOfScopeByJ, jurisdiction, amount)
        continue
      }
      if (cls.kind === 'not-descended') {
        addAggStatByJ(bucket.notDescendedByJ, jurisdiction, amount)
        continue
      }
      const jcKey = `${jurisdiction}|${cls.code}`
      const cell = bucket.cellsByJC.get(jcKey) ?? newAggStat()
      cell.amount += amount
      cell.lineCount += 1
      bucket.cellsByJC.set(jcKey, cell)
    }
  }
}

/** 蓄積した横断集計をアセットへ書く。omittedBudgets はその年度の全 budget と includedBudgets の差 */
function writeCrossAggAssets(allBudgetsForOmission: Budget[]): void {
  const budgetsByYear = new Map<string, Budget[]>()
  for (const b of allBudgetsForOmission) {
    const arr = budgetsByYear.get(b.fiscalYear) ?? []
    arr.push(b)
    budgetsByYear.set(b.fiscalYear, arr)
  }
  for (const [key, accum] of crossByKey) {
    const [year, phase] = key.split('|') as [string, string]
    const budgetsThisYear = budgetsByYear.get(year) ?? fail(`agg cross: no budgets for year ${year}`)
    const omittedBudgets = budgetsThisYear
      .filter((b) => !accum.includedBudgets.has(b.id))
      .map((b) => ({ budget: `budgets/${b.id}`, code: 'PHASE_NOT_AVAILABLE' as const }))
    // この年度・段階で実在する団体（cells の団体だけでなく、残余しか持たない団体も含む）
    const includedJurisdictions = [...new Set([...accum.includedBudgets].map((id) => id.split(':')[0]!))]
    for (const depth of COFOG_DEPTHS) {
      const bucket = accum.perDepth[depth]
      const cells = [...bucket.cellsByJC.entries()]
        .map(([jc, stat]) => {
          const [jurisdiction, code] = jc.split('|') as [string, string]
          return {
            jurisdiction,
            jurisdictionLabel: crossJurisdictionLabel.get(jurisdiction) ?? fail(`agg cross: no label for jurisdiction ${jurisdiction}`),
            code,
            label: cofogLabel(depth, code),
            amount: stat.amount,
            lineCount: stat.lineCount,
          }
        })
        .sort(byKey((c) => `${c.jurisdiction}:${c.code}`))
      // design doc「団体をまたいで足さない」── cells が jurisdiction を軸に必須なのに、
      // 残余だけ全団体で1つに合算すると団体ごとに cells + residual を復元できなくなる
      // （PR #27 レビュー指摘）。団体ごとの残余にする
      const residualByJurisdiction: AggCrossAsset['residualByJurisdiction'] = {}
      for (const jurisdiction of includedJurisdictions) {
        residualByJurisdiction[jurisdiction] = {
          unclassifiable: bucket.unclassifiableByJ.get(jurisdiction) ?? newAggStat(),
          outOfScope: bucket.outOfScopeByJ.get(jurisdiction) ?? newAggStat(),
          notDescended: bucket.notDescendedByJ.get(jurisdiction) ?? newAggStat(),
        }
      }
      const asset: AggCrossAsset = {
        revision,
        cells,
        residualByJurisdiction,
        consolidation: { retained: accum.retained, eliminated: accum.eliminated },
        includedBudgets: [...accum.includedBudgets].sort().map((id) => `budgets/${id}`),
        omittedBudgets,
      }
      writeJson(join(OUT_DIR, assetPaths.aggCross(year, 'expenditure', phase, depth)), asset)
    }
  }
}

/**
 * 検査1・2（cross 版）。**includedJurisdictions も独立に決める** ── 生成側の
 * accum.includedBudgets をそのまま信じず、table.rows に該当 phase の行が実在するかで判定する。
 */
function checkAggCrossAssetMatchesSource(year: string, phase: string, depth: CofogDepth): void {
  const cellsByJC = new Map<string, AggStat>()
  const unclassifiableByJ = new Map<string, AggStat>()
  const outOfScopeByJ = new Map<string, AggStat>()
  const notDescendedByJ = new Map<string, AggStat>()
  const retained = newAggStat()
  const eliminated = newAggStat()
  const includedJurisdictions: string[] = []
  for (const [jurisdiction, { table, cofogTable }] of perJurisdictionAggSource) {
    const rows = table.rows.filter((r) => r['fiscal_year'] === year && r['phase_id'] === phase)
    if (rows.length === 0) continue
    includedJurisdictions.push(jurisdiction)
    const byId = new Map(
      cofogTable.rows.filter((r) => r['fiscal_year'] === year && r['direction'] === 'expenditure').map((r) => [r['budget_line_id']!, r]),
    )
    // consolidationAt は cofogAux（Map<string, CofogAux>）を取るが、buildCofogAux は呼ばず
    // ここだけで独立に組む（生成と検査でデータの取得経路を共有しない）。
    const cofogAuxForJ = new Map(
      [...byId.entries()].map(([id, r]) => [
        id,
        { division: r['cofog_division']!, group: r['cofog_group']!, klass: r['cofog_class']!, status: r['cofog_status']!, consolidation: r['cofog_consolidation']! },
      ]),
    )
    const consolidationForJ = consolidationAt(rows, cofogAuxForJ)
    retained.amount += consolidationForJ.retained.amount
    retained.lineCount += consolidationForJ.retained.lineCount
    eliminated.amount += consolidationForJ.eliminated.amount
    eliminated.lineCount += consolidationForJ.eliminated.lineCount
    for (const row of rows) {
      const id = row['budget_line_id']!
      const cofogRow = byId.get(id) ?? fail(`agg cross check: no cofog row for ${id}`)
      const amount = Number(row['value'])
      const status = cofogRow['cofog_status']!
      const code = depth === 'division' ? cofogRow['cofog_division']! : depth === 'group' ? cofogRow['cofog_group']! : cofogRow['cofog_class']!
      const cls = classifyCofogAmount(status, code, `agg cross check: unexpected cofog_status "${status}" for ${id}`)
      if (cls.kind === 'unclassifiable') {
        addAggStatByJ(unclassifiableByJ, jurisdiction, amount)
        continue
      }
      if (cls.kind === 'out-of-scope') {
        addAggStatByJ(outOfScopeByJ, jurisdiction, amount)
        continue
      }
      if (cls.kind === 'not-descended') {
        addAggStatByJ(notDescendedByJ, jurisdiction, amount)
        continue
      }
      const jcKey = `${jurisdiction}|${cls.code}`
      const cell = cellsByJC.get(jcKey) ?? newAggStat()
      cell.amount += amount
      cell.lineCount += 1
      cellsByJC.set(jcKey, cell)
    }
  }

  const assetPath = join(OUT_DIR, assetPaths.aggCross(year, 'expenditure', phase, depth))
  const written = JSON.parse(readFileSync(assetPath, 'utf8')) as AggCrossAsset
  const writtenByJC = new Map(written.cells.map((c) => [`${c.jurisdiction}|${c.code}`, c]))
  if (writtenByJC.size !== cellsByJC.size) fail(`agg cross check: cell count mismatch for ${assetPath}`)
  for (const [key, expected] of cellsByJC) {
    const w = writtenByJC.get(key) ?? fail(`agg cross check: missing cell ${key} in ${assetPath}`)
    if (w.amount !== expected.amount || w.lineCount !== expected.lineCount) fail(`agg cross check: cell ${key} mismatch in ${assetPath}`)
  }
  const pairs: [string, AggStat, AggStat][] = [
    ['consolidation.retained', retained, written.consolidation.retained],
    ['consolidation.eliminated', eliminated, written.consolidation.eliminated],
  ]
  for (const [name, expected, actual] of pairs) {
    if (expected.amount !== actual.amount || expected.lineCount !== actual.lineCount) {
      fail(`agg cross check: ${name} mismatch for ${assetPath}`)
    }
  }
  // 残余は団体ごと（design doc「団体をまたいで足さない」）。3種×団体で突き合わせる
  const residualMaps: [string, Map<string, AggStat>, (r: AggCrossAsset['residualByJurisdiction'][string]) => AggStat][] = [
    ['unclassifiable', unclassifiableByJ, (r) => r.unclassifiable],
    ['outOfScope', outOfScopeByJ, (r) => r.outOfScope],
    ['notDescended', notDescendedByJ, (r) => r.notDescended],
  ]
  const allJurisdictionsWithResidual = new Set([...unclassifiableByJ.keys(), ...outOfScopeByJ.keys(), ...notDescendedByJ.keys()])
  if (new Set(Object.keys(written.residualByJurisdiction)).size < allJurisdictionsWithResidual.size) {
    fail(`agg cross check: residualByJurisdiction is missing jurisdictions for ${assetPath}`)
  }
  for (const [name, expectedMap, pick] of residualMaps) {
    for (const [jurisdiction, expected] of expectedMap) {
      const writtenResidual = written.residualByJurisdiction[jurisdiction] ?? fail(`agg cross check: missing residualByJurisdiction[${jurisdiction}] in ${assetPath}`)
      const actual = pick(writtenResidual)
      if (expected.amount !== actual.amount || expected.lineCount !== actual.lineCount) {
        fail(`agg cross check: residualByJurisdiction[${jurisdiction}].${name} mismatch for ${assetPath}`)
      }
    }
  }
  const expectedIncluded = [...includedJurisdictions].sort().map((j) => `budgets/${j}:${year}`)
  const actualIncluded = [...written.includedBudgets].sort()
  if (expectedIncluded.join(',') !== actualIncluded.join(',')) {
    fail(`agg cross check: includedBudgets mismatch for ${assetPath}: expected [${expectedIncluded}] got [${actualIncluded}]`)
  }
}


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
  // 検査7の期待値（索引が指す明細識別子が実在すること）。cofog.csv は direction を
  // 問わず budget_line_id を持つので、ここが独立な母集団になる
  for (const row of cofogTable.rows) allValidBudgetLineIds.add(row['budget_line_id']!)

  // scopes.cofogDepth / scopes.consolidation で group/class/consolidation も要るので、
  // judgments 用の cofogByLineId（division までしか持たない）とは別に持つ
  const cofogAux = buildCofogAux(cofogTable)
  // 款・項・目の名称の出所（scopes.names.hierarchy）。原典に列が無い団体はここへフォールバックする
  const accountNamesTable = readCsvTable(join(dir, 'account_names.csv'))

  let projectNames: Map<string, string> | null = null
  if (existsSync(join(dir, 'project_names.csv'))) {
    projectNames = new Map()
    for (const row of readCsvTable(join(dir, 'project_names.csv')).rows) {
      const key = [row['fiscal_year'], row['fund_code'], row['kan_code'], row['kou_code'], row['moku_code'], row['daijigyo_code']].join('|')
      projectNames.set(key, row['project_name']!)
    }
  }

  const fiscalYears: Record<Direction, string[]> = { expenditure: [], revenue: [] }
  const linesByYearDir = new Map<string, StoredBudgetLine[]>()
  /** 検査2用: 年度 → (budget_line_id → 全予算段階の金額合計)。cofog 行ループを O(1) 参照にする */
  const expenditureSums = new Map<string, Map<string, number>>()
  /** scopes の生成・検査で直接 CSV を読み直せるように、direction ごとの table/ctx を残す */
  const tableByDirection = new Map<Direction, Table>()
  const ctxByDirection = new Map<Direction, ResourceContext>()

  for (const direction of DIRECTIONS) {
    const table = readCsvTable(join(dir, `${direction}.csv`))
    const ctx = resourceContext(j, direction, table, descriptor)
    tableByDirection.set(direction, table)
    ctxByDirection.set(direction, ctx)
    const lines = buildLines(ctx, table, cofogByLineId, projectNames)
    checkMultisetEquality(ctx, table, lines)
    accumulateNameIndexEntries(direction, lines, accountNamesTable.rows.filter((r) => r['direction'] === direction))

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
        const cross: StoredCrossBudgetLine = {
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

  // scopes.names.projectName / scopes.nextHierarchyLevel は団体×direction 全体で1つ
  // （levels の宣言も project_names.csv の収録範囲も年度に依存しないため）
  const staticScopeByDirection = new Map<
    Direction,
    { nextHierarchyLevel: BudgetDirectionScope['nextHierarchyLevel']; projectName: BudgetDirectionScope['names']['projectName'] }
  >()
  for (const direction of DIRECTIONS) {
    if (fiscalYears[direction].length === 0) continue
    const ctx = ctxByDirection.get(direction)!
    const table = tableByDirection.get(direction)!
    staticScopeByDirection.set(direction, {
      nextHierarchyLevel: nextHierarchyLevelScopeFor(direction, ctx.levels, table, amountPhase, projectNames),
      projectName: projectNameScopeFor(direction, ctx.levels, projectNames),
    })
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

    const directionsThisYear = DIRECTIONS.filter((d) => fiscalYears[d].includes(year))
    const scopes: BudgetScopes = {}
    for (const direction of directionsThisYear) {
      const yl = linesByYearDir.get(`${year}-${direction}`) ?? fail(`missing lines for ${j}/${year}/${direction}`)
      const table = tableByDirection.get(direction)!

      const phases = phasesScopeFor(yl, amountPhase)
      const funds = fundsScopeFor(yl)
      checkPhasesAndFundsMatchSource(j, direction, year, table, phases, funds)

      const consolidation = consolidationScopeFor(yl, amountPhase, cofogAux)
      checkConsolidationMatchesSource(j, direction, year, table, cofogTable, amountPhase, consolidation)

      const cofogDepth = cofogDepthScopeFor(direction, yl, amountPhase, cofogAux)
      checkCofogDepthMatchesSource(j, year, table, cofogTable, amountPhase, cofogDepth)

      const accountRowsThisYear = accountNamesTable.rows.filter((r) => r['fiscal_year'] === year && r['direction'] === direction)
      const hierarchy = (['kan', 'kou', 'moku'] as const).map((level) => hierarchyNameScopeFor(level, yl, accountRowsThisYear))

      // 検査: amountPhase は phases[].isPrimary と同じ値でなければならない（値と条件の二重宣言を許さない）
      const primaryPhase = phases.find((p) => p.isPrimary)?.id ?? fail(`no isPrimary phase in scopes.phases for ${j}/${year}/${direction}`)
      if (primaryPhase !== amountPhase) fail(`scopes.amountPhase mismatch for ${j}/${year}/${direction}: phases marks "${primaryPhase}" as primary but amountPhase is "${amountPhase}"`)

      const staticScope = staticScopeByDirection.get(direction)
      scopes[direction] = {
        amountPhase,
        phases,
        funds,
        consolidation,
        cofogDepth,
        names: { hierarchy, projectName: staticScope?.projectName ?? null },
        nextHierarchyLevel: staticScope?.nextHierarchyLevel ?? null,
      }

      // 規模の実測（前計算アセットは作らない）
      for (const fund of funds) {
        const linesForFund = yl.filter((l) => codeAt(l, 'fund') === fund.code)
        const kanCodes = new Set(linesForFund.map((l) => codeAt(l, 'kan')))
        const kanKouPairs = new Set(linesForFund.map((l) => `${codeAt(l, 'kan')}:${codeAt(l, 'kou')}`))
        const parentCount = 1 + kanCodes.size + kanKouPairs.size // root, 各款, 各(款,項)
        hierarchyAssetKeyCount[direction] += parentCount * phases.length
      }
      if (direction === 'expenditure') {
        cofogDepthAssetComboCount += funds.length * phases.length * 3 // division/group/class
        for (const fund of funds) {
          const linesForFund = yl.filter((l) => codeAt(l, 'fund') === fund.code)
          const root = maxCellsAcrossParents(linesForFund, cofogAux, () => 'root', (l) => codeAt(l, 'kan'))
          const byKan = maxCellsAcrossParents(linesForFund, cofogAux, (l) => codeAt(l, 'kan'), (l) => codeAt(l, 'kou'))
          const byKanKou = maxCellsAcrossParents(linesForFund, cofogAux, (l) => `${codeAt(l, 'kan')}:${codeAt(l, 'kou')}`, (l) => codeAt(l, 'moku'))
          maxHierarchyCofogCells = Math.max(maxHierarchyCofogCells, root, byKan, byKanKou)
        }

        // ---- COFOG 集計アセットの生成と検査（design doc「引ける集計の一覧」1行目: 団体+年度） ----
        const yearRows = table.rows.filter((r) => r['fiscal_year'] === year)
        const cofogRowsForYear = cofogTable.rows.filter((r) => r['fiscal_year'] === year && r['direction'] === 'expenditure')
        const fundOptions = ['all', ...funds.map((f) => f.code)]
        for (const phase of phases.map((p) => p.id)) {
          const phaseRows = yearRows.filter((r) => r['phase_id'] === phase)
          for (const fundOption of fundOptions) {
            const fundRows = fundOption === 'all' ? phaseRows : phaseRows.filter((r) => r['fund_code'] === fundOption)
            for (const depth of COFOG_DEPTHS) {
              writeAggBudgetAsset(j, year, phase, fundOption, depth, fundRows, cofogAux)
              // ⚠️ 検査へは範囲選択前の yearRows を渡す（fundRows を渡さない）。範囲選択
              // （yearRows → phaseRows → fundRows）自体は検査関数が独立に行う（PR #27 レビュー指摘）
              checkAggBudgetAssetMatchesSource(j, year, phase, fundOption, depth, yearRows, cofogRowsForYear)
            }
            // hierarchy 集計は "all" を対象にしない（design doc に明記は無い。procedure/budgets.ts の
            // hierarchyAggregate に書いたとおり、款・項のコードは会計内でしか一意でないための判断）
            if (fundOption !== 'all') {
              for (const segments of hierarchyParentPaths(fundRows)) {
                const childLevel = hierarchyChildLevel(segments)
                const scoped = scopedRowsFor(fundRows, segments)
                writeHierarchyAsset(j, year, phase, fundOption, segments, childLevel, scoped)
                checkHierarchyAssetMatchesSource(j, year, phase, fundOption, segments, childLevel, yearRows)
                writeHierarchyCofogAsset(j, year, phase, fundOption, segments, childLevel, scoped, cofogAux)
                checkHierarchyCofogAssetMatchesSource(j, year, phase, fundOption, segments, childLevel, yearRows, cofogRowsForYear)
              }
            }
          }

          // 年度横断（design doc「引ける集計の一覧」最終行）の材料を蓄積。fund は選べない（全会計合算）
          const crossKey = `${year}|${phase}`
          const crossAccum = crossAccumFor(crossKey)
          crossAccum.includedBudgets.add(budgetIdOf(j, year))
          accumulateCrossRows(j, crossAccum, phaseRows, cofogAux)
        }
        crossJurisdictionLabel.set(j, label)
      }
    }

    budgets.push(budgetSchema.parse({
      name: `budgets/${budgetIdOf(j, year)}`,
      id: budgetIdOf(j, year),
      jurisdictionId: j,
      fiscalYear: year,
      directions: directionsThisYear,
      amountPhase,
      classificationRate: statuses,
      scopes,
    } satisfies Budget))
  }
  perJurisdictionAggSource.set(j, { table: tableByDirection.get('expenditure')!, cofogTable, cofogAux })
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
    provenanceSources: provenanceSourcesFromToml(j),
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
    for (const line of lines) storedCrossBudgetLineSchema.parse(line)

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

// ---- 名称索引（design doc「名称の検索」）。索引の単位は名称。全団体を横断する1系列に積む ----

/**
 * account_names.csv の name_source を accountLabel の nameSource へ写す。
 * hierarchyNameScopeFor の判定（source-csv=canonical, settlement-pdf=judgment）と同じ対応。
 */
function accountNameSourceToNameSource(nameSource: string): 'canonical' | 'judgment' {
  if (nameSource === 'source-csv') return 'canonical'
  if (nameSource === 'settlement-pdf') return 'judgment'
  fail(`unknown name_source in account_names.csv: "${nameSource}"`)
}

/** kan/kou/moku を account_names.csv で引くための複合キー（hierarchyNameScopeFor と同じ粒度） */
function accountNameKey(fiscalYear: string, dir: Direction, fundCode: string, kanCode: string, kouCode: string, mokuCode: string): string {
  return [fiscalYear, dir, fundCode, kanCode, kouCode, mokuCode].join('|')
}

function buildAccountNameLookup(rows: Record<string, string>[]): Map<string, Record<string, string>> {
  const map = new Map<string, Record<string, string>>()
  for (const row of rows) {
    const key = accountNameKey(row['fiscal_year']!, row['direction'] as Direction, row['fund_code']!, row['kan_code']!, row['kou_code']!, row['moku_code']!)
    if (!map.has(key)) map.set(key, row)
  }
  return map
}


/**
 * 1団体・1direction ぶんの StoredBudgetLine 群から名称索引エントリを作り、
 * nameIndexByKey（モジュールスコープ、(field,level,value,nameSource) 単位）へ積む。
 * accountLabel は ACCOUNT_LABEL_LEVELS のうち非空ラベルを持つレベルごとに1件、
 * その明細を refs へ足す（hierarchy・amounts は積まない ── 索引は名称の単位であって
 * 明細の単位ではない。resolveLineByRef が budgetLineId から引き直す）。
 * kan/kou/moku は原典（StoredBudgetLine.hierarchy）に無ければ account_names.csv（判断。
 * name_source が nameSource を決める）にフォールバックする ── scopes.names.hierarchy の
 * hasName/source と同じ情報源にしないと、level の検索可否（procedure 側の 400 判定）と
 * 索引の実際の中身が食い違う（design doc は明記していない、この実装の判断）。
 * projectName は judgments.projectName が非 null のときだけ daijigyo で1件。
 */
function accumulateNameIndexEntries(dir: Direction, lines: StoredBudgetLine[], accountNameRowsForDirection: Record<string, string>[]): void {
  const accountNameLookup = buildAccountNameLookup(accountNameRowsForDirection)
  for (const line of lines) {
    const fundEntry = line.hierarchy.find((h) => h.level === 'fund') ?? fail(`name index: line without a fund level: ${line.budgetLineId}`)
    const fund = { code: fundEntry.code, label: fundEntry.label }
    const ref = { budgetLineId: line.budgetLineId, fund }

    for (const h of line.hierarchy) {
      if (!ACCOUNT_LABEL_LEVELS.has(h.level)) continue
      if (h.label !== null && h.label !== '') {
        getOrCreateNameIndexEntry('accountLabel', h.level, h.label, 'canonical').refs.push(ref)
        continue
      }
      if (!KAN_KOU_MOKU_LEVELS.has(h.level)) continue
      const key = accountNameKey(
        line.fiscalYear,
        dir,
        codeAt(line, 'fund'),
        codeAt(line, 'kan'),
        codeAt(line, 'kou'),
        codeAt(line, 'moku'),
      )
      const row = accountNameLookup.get(key)
      const fallbackName = row?.[`${h.level}_name`]
      if (row === undefined || fallbackName === undefined || fallbackName === '') continue
      const nameSource = accountNameSourceToNameSource(row['name_source']!)
      getOrCreateNameIndexEntry('accountLabel', h.level, fallbackName, nameSource).refs.push(ref)
    }
    if (line.judgments.projectName !== null) {
      getOrCreateNameIndexEntry('projectName', 'daijigyo', line.judgments.projectName, 'judgment').refs.push(ref)
    }
  }
}

/**
 * 名称索引を (field, level, value, nameSource) 昇順にソートし、refs を budgetLineId 昇順に
 * 整えてから、明細チャンクと同じ chunk 分割で書き出す（design doc「索引は団体ごとの単一
 * ファイルにせず、明細のチャンクと同じく分割」）。並び順は procedure 側が応答を組むときに
 * budgetLineId 昇順へ作り直すので、ここでの順序は chunk 分割を安定させるためだけのもの。
 * 検査7: 索引が指す明細識別子が実在すること。allValidBudgetLineIds は cofog.csv から
 * 独立に集めた集合（accumulateNameIndexEntries とは別経路）。
 */
function writeNameIndex(): void {
  const entries = [...nameIndexByKey.values()]
  for (const entry of entries) {
    entry.refs.sort(byKey((r) => r.budgetLineId))
    for (const ref of entry.refs) {
      if (!allValidBudgetLineIds.has(ref.budgetLineId)) {
        fail(`name index check: entry references a budget_line_id absent from any cofog.csv: ${ref.budgetLineId}`)
      }
    }
  }
  entries.sort((a, b) => {
    if (a.field !== b.field) return a.field < b.field ? -1 : 1
    if (a.level !== b.level) return a.level < b.level ? -1 : 1
    if (a.value !== b.value) return a.value < b.value ? -1 : 1
    return a.nameSource < b.nameSource ? -1 : a.nameSource > b.nameSource ? 1 : 0
  })
  writeChunkSeries(assetPaths.searchAll, entries)
}

/**
 * ⚠️ チャンク系列（writeChunkSeries）は CHUNK_BYTES_LIMIT を検査するが、集計アセット
 * （aggBudget / aggHierarchy / aggCross / aggYearsTotal / aggYearsCofogDivision など）は
 * 同じ Cloudflare Workers の応答上限を共有するのに検査が無かった（PR #27 レビュー指摘）。
 * 集計アセットは1ファイル1レスポンスなので、チャンクと同じ上限をここでも適用する。
 */
function writeJson(path: string, value: unknown): void {
  const body = JSON.stringify(value)
  if (Buffer.byteLength(body) > CHUNK_BYTES_LIMIT) fail(`asset ${path} exceeds ${CHUNK_BYTES_LIMIT} bytes`)
  writeText(path, body)
}

function writeText(path: string, body: string): void {
  mkdirSync(join(path, '..'), { recursive: true })
  writeFileSync(path, body)
}

// ---- fiscalYear 集計アセット（design doc「引ける集計の一覧」4・5行目。Tasks 6） ------------------
// 単一団体・年度横断。COFOG と違い直接 CSV から独立に数え直す（生成側のアキュムレータは再利用しない）。

type YearsSource = { table: Table; cofogTable: Table; cofogAux: Map<string, CofogAux> }

function consolidationAt(rows: Record<string, string>[], cofogAux: Map<string, CofogAux>): { retained: AggStat; eliminated: AggStat } {
  const retained = newAggStat()
  const eliminated = newAggStat()
  for (const row of rows) {
    const aux = cofogAux.get(row['budget_line_id']!) ?? fail(`years agg: no cofog row for ${row['budget_line_id']}`)
    const amount = Number(row['value'])
    if (aux.consolidation === 'retained') {
      retained.amount += amount
      retained.lineCount += 1
    } else if (aux.consolidation === 'eliminated') {
      eliminated.amount += amount
      eliminated.lineCount += 1
    } else {
      fail(`years agg: unknown cofog_consolidation "${aux.consolidation}"`)
    }
  }
  return { retained, eliminated }
}

/** その (phase, fund) を年度 b が持つか。持たなければ omit する理由を返す */
function yearOmissionFor(scope: BudgetDirectionScope, phase: string, fund: string): 'PHASE_NOT_AVAILABLE' | 'FUND_NOT_AVAILABLE' | null {
  if (!scope.phases.some((p) => p.id === phase)) return 'PHASE_NOT_AVAILABLE'
  if (fund !== 'all' && !scope.funds.some((f) => f.code === fund)) return 'FUND_NOT_AVAILABLE'
  return null
}

/**
 * 年度ごとの `fundScope` を1回ずつだけ足し込んで union する（procedure 側が旧実装で
 * 行っていた「ページ後の cells を足す」と同じ計算を、ここでは年度単位・全件で1回だけ行う）。
 * ⚠️ 呼び出し側は「年度1つにつき1個」の fundScope を渡すこと。cofog セルのように同じ年度の
 * fundScope が複数セルに複製されている配列をそのまま渡すと、division の数だけ二重に数える
 * （PR #27 レビュー指摘の再発）。
 */
function unionFundScope(perYearFundScopes: readonly AggYearsFundScope[]): AggYearsFundScope {
  const fundsUnion = new Map<string, string | null>()
  const retained = newAggStat()
  const eliminated = newAggStat()
  for (const fs of perYearFundScopes) {
    for (const f of fs.funds) if (!fundsUnion.has(f.code)) fundsUnion.set(f.code, f.label)
    retained.amount += fs.consolidation.retained.amount
    retained.lineCount += fs.consolidation.retained.lineCount
    eliminated.amount += fs.consolidation.eliminated.amount
    eliminated.lineCount += fs.consolidation.eliminated.lineCount
  }
  return {
    funds: [...fundsUnion.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([code, label]) => ({ code, label })),
    consolidation: { retained, eliminated },
  }
}

function writeYearsTotalAsset(jurisdiction: string, phase: string, fund: string, budgetsForJ: Budget[], source: YearsSource): void {
  const cells: AggYearsTotalAsset['cells'] = []
  const omittedYears: AggYearsTotalAsset['omittedYears'] = []
  for (const b of [...budgetsForJ].sort(byKey((x) => x.fiscalYear))) {
    const scope = b.scopes.expenditure!
    const omission = yearOmissionFor(scope, phase, fund)
    if (omission !== null) {
      omittedYears.push({ fiscalYear: b.fiscalYear, code: omission })
      continue
    }
    const rows = source.table.rows.filter(
      (r) => r['fiscal_year'] === b.fiscalYear && r['phase_id'] === phase && (fund === 'all' || r['fund_code'] === fund),
    )
    const stat = newAggStat()
    for (const row of rows) {
      stat.amount += Number(row['value'])
      stat.lineCount += 1
    }
    const fundsThisYear = fund === 'all' ? scope.funds : scope.funds.filter((f) => f.code === fund)
    const fundScope: AggYearsFundScope = { funds: fundsThisYear, consolidation: consolidationAt(rows, source.cofogAux) }
    cells.push({ fiscalYear: b.fiscalYear, amount: stat.amount, lineCount: stat.lineCount, fundScope })
  }
  // design doc「範囲全体の要約はアセットに一度だけ持つ」── ページング後の cells から
  // procedure が作り直すと pageSize で値が変わる（PR #27 レビュー指摘）ので、ここで確定させる。
  const total = cells.reduce((s, c) => ({ amount: s.amount + c.amount, lineCount: s.lineCount + c.lineCount }), newAggStat())
  const fundScope = unionFundScope(cells.map((c) => c.fundScope))
  const asset: AggYearsTotalAsset = { revision, cells, total, fundScope, omittedYears }
  writeJson(join(OUT_DIR, assetPaths.aggYearsTotal(jurisdiction, 'expenditure', phase, fund)), asset)
}

/**
 * 検査1・2（years-total 版）。生成側の YearsSource（cofogAux も含む束）は取らず、
 * 必要な table だけを受け取って自分で絞り込む（他の write/check ペアと同じ独立再計算の形に
 * 揃える。この検査は COFOG を見ないので cofogAux はそもそも不要）。
 */
function checkYearsTotalAssetMatchesSource(jurisdiction: string, phase: string, fund: string, budgetsForJ: Budget[], table: Table): void {
  const assetPath = join(OUT_DIR, assetPaths.aggYearsTotal(jurisdiction, 'expenditure', phase, fund))
  const written = JSON.parse(readFileSync(assetPath, 'utf8')) as AggYearsTotalAsset
  const expectedCells: { fiscalYear: string; amount: number; lineCount: number }[] = []
  const expectedOmitted: { fiscalYear: string; code: string }[] = []
  for (const b of budgetsForJ) {
    const scope = b.scopes.expenditure!
    const omission = yearOmissionFor(scope, phase, fund)
    if (omission !== null) {
      expectedOmitted.push({ fiscalYear: b.fiscalYear, code: omission })
      continue
    }
    const rows = table.rows.filter(
      (r) => r['fiscal_year'] === b.fiscalYear && r['phase_id'] === phase && (fund === 'all' || r['fund_code'] === fund),
    )
    let amount = 0
    for (const row of rows) amount += Number(row['value'])
    expectedCells.push({ fiscalYear: b.fiscalYear, amount, lineCount: rows.length })
  }
  const writtenByYear = new Map(written.cells.map((c) => [c.fiscalYear, c]))
  if (writtenByYear.size !== expectedCells.length) fail(`years-total check: cell count mismatch for ${assetPath}`)
  for (const expected of expectedCells) {
    const w = writtenByYear.get(expected.fiscalYear) ?? fail(`years-total check: missing year ${expected.fiscalYear} in ${assetPath}`)
    if (w.amount !== expected.amount || w.lineCount !== expected.lineCount) fail(`years-total check: year ${expected.fiscalYear} mismatch in ${assetPath}`)
  }
  const expectedOmittedKey = expectedOmitted.map((o) => `${o.fiscalYear}:${o.code}`).sort().join(',')
  const actualOmittedKey = written.omittedYears.map((o) => `${o.fiscalYear}:${o.code}`).sort().join(',')
  if (expectedOmittedKey !== actualOmittedKey) {
    fail(`years-total check: omittedYears mismatch for ${assetPath}: expected [${expectedOmittedKey}] got [${actualOmittedKey}]`)
  }
  const expectedTotal = expectedCells.reduce((s, c) => ({ amount: s.amount + c.amount, lineCount: s.lineCount + c.lineCount }), newAggStat())
  if (written.total.amount !== expectedTotal.amount || written.total.lineCount !== expectedTotal.lineCount) {
    fail(`years-total check: total mismatch for ${assetPath}: expected ${JSON.stringify(expectedTotal)} got ${JSON.stringify(written.total)}`)
  }
  const expectedFundScope = unionFundScope(written.cells.map((c) => c.fundScope))
  if (JSON.stringify(written.fundScope) !== JSON.stringify(expectedFundScope)) {
    fail(`years-total check: fundScope is not the union of cells for ${assetPath}`)
  }
}

function writeYearsCofogDivisionAsset(jurisdiction: string, phase: string, fund: string, budgetsForJ: Budget[], source: YearsSource): void {
  const cells: AggYearsCofogDivisionAsset['cells'] = []
  const residualByYear: AggYearsCofogDivisionAsset['residualByYear'] = {}
  const omittedYears: AggYearsCofogDivisionAsset['omittedYears'] = []
  // ⚠️ fundScope は年度単位で1個決まるが、cells は年度×division で複数行に分かれる（同じ
  // fundScope オブジェクトを全 division セルへ複製している）。union は cells からではなく
  // ここへ年度1個につき1回だけ積んだ配列から取る（cells から取ると division の数だけ二重に数える）。
  const perYearFundScopes: AggYearsFundScope[] = []
  for (const b of [...budgetsForJ].sort(byKey((x) => x.fiscalYear))) {
    const scope = b.scopes.expenditure!
    const omission = yearOmissionFor(scope, phase, fund)
    if (omission !== null) {
      omittedYears.push({ fiscalYear: b.fiscalYear, code: omission })
      continue
    }
    const rows = source.table.rows.filter(
      (r) => r['fiscal_year'] === b.fiscalYear && r['phase_id'] === phase && (fund === 'all' || r['fund_code'] === fund),
    )
    const byDivision = new Map<string, AggStat>()
    const unclassifiable = newAggStat()
    const outOfScope = newAggStat()
    const notDescended = newAggStat()
    for (const row of rows) {
      const aux = source.cofogAux.get(row['budget_line_id']!) ?? fail(`years cofog: no cofog row for ${row['budget_line_id']}`)
      const amount = Number(row['value'])
      const cls = classifyCofogAmount(aux.status, aux.division, `years cofog: unexpected cofog_status "${aux.status}"`)
      if (cls.kind === 'unclassifiable') {
        unclassifiable.amount += amount
        unclassifiable.lineCount += 1
        continue
      }
      if (cls.kind === 'out-of-scope') {
        outOfScope.amount += amount
        outOfScope.lineCount += 1
        continue
      }
      if (cls.kind === 'not-descended') {
        notDescended.amount += amount
        notDescended.lineCount += 1
        continue
      }
      const cell = byDivision.get(cls.code) ?? newAggStat()
      cell.amount += amount
      cell.lineCount += 1
      byDivision.set(cls.code, cell)
    }
    const fundsThisYear = fund === 'all' ? scope.funds : scope.funds.filter((f) => f.code === fund)
    const fundScope: AggYearsFundScope = { funds: fundsThisYear, consolidation: consolidationAt(rows, source.cofogAux) }
    perYearFundScopes.push(fundScope)
    for (const [division, stat] of [...byDivision.entries()].sort(byKey(([d]) => d))) {
      cells.push({
        fiscalYear: b.fiscalYear,
        cofogDivision: division,
        cofogLabel: cofogLabel('division', division),
        amount: stat.amount,
        lineCount: stat.lineCount,
        fundScope,
      })
    }
    residualByYear[b.fiscalYear] = { unclassifiable, outOfScope, notDescended }
  }
  // design doc「範囲全体の要約はアセットに一度だけ持つ」。total は cells（division 別）と
  // residualByYear（unclassifiable / out-of-scope / notDescended）の両方を足した全年度合計。
  const cellsTotal = cells.reduce((s, c) => ({ amount: s.amount + c.amount, lineCount: s.lineCount + c.lineCount }), newAggStat())
  const residualTotal = Object.values(residualByYear).reduce(
    (s, r) => ({
      amount: s.amount + r.unclassifiable.amount + r.outOfScope.amount + r.notDescended.amount,
      lineCount: s.lineCount + r.unclassifiable.lineCount + r.outOfScope.lineCount + r.notDescended.lineCount,
    }),
    newAggStat(),
  )
  const total = { amount: cellsTotal.amount + residualTotal.amount, lineCount: cellsTotal.lineCount + residualTotal.lineCount }
  const fundScope = unionFundScope(perYearFundScopes)
  const asset: AggYearsCofogDivisionAsset = { revision, cells, residualByYear, total, fundScope, omittedYears }
  writeJson(join(OUT_DIR, assetPaths.aggYearsCofogDivision(jurisdiction, 'expenditure', phase, fund)), asset)
}

/** 検査1・2（years-cofog-division 版） */
/**
 * 検査1・2（years-cofog-division 版）。生成側の YearsSource（cofogAux も含む束）は取らず、
 * 必要な table・cofogTable だけを受け取り、cofogByLineId も自分で組む（他の write/check ペアと
 * 同じ独立再計算の形に揃える）。
 */
function checkYearsCofogDivisionAssetMatchesSource(
  jurisdiction: string,
  phase: string,
  fund: string,
  budgetsForJ: Budget[],
  table: Table,
  cofogTable: Table,
): void {
  const assetPath = join(OUT_DIR, assetPaths.aggYearsCofogDivision(jurisdiction, 'expenditure', phase, fund))
  const written = JSON.parse(readFileSync(assetPath, 'utf8')) as AggYearsCofogDivisionAsset
  const expectedCells: { fiscalYear: string; division: string; amount: number; lineCount: number }[] = []
  const expectedResidualByYear: Record<string, { unclassifiable: AggStat; outOfScope: AggStat; notDescended: AggStat }> = {}
  const expectedOmitted: { fiscalYear: string; code: string }[] = []
  for (const b of budgetsForJ) {
    const scope = b.scopes.expenditure!
    const omission = yearOmissionFor(scope, phase, fund)
    if (omission !== null) {
      expectedOmitted.push({ fiscalYear: b.fiscalYear, code: omission })
      continue
    }
    const rows = table.rows.filter(
      (r) => r['fiscal_year'] === b.fiscalYear && r['phase_id'] === phase && (fund === 'all' || r['fund_code'] === fund),
    )
    const cofogByLineId = new Map(
      cofogTable.rows
        .filter((r) => r['fiscal_year'] === b.fiscalYear && r['direction'] === 'expenditure')
        .map((r) => [r['budget_line_id']!, r]),
    )
    const byDivision = new Map<string, AggStat>()
    const unclassifiable = newAggStat()
    const outOfScope = newAggStat()
    const notDescended = newAggStat()
    for (const row of rows) {
      const cofogRow = cofogByLineId.get(row['budget_line_id']!) ?? fail(`years-cofog check: no cofog row for ${row['budget_line_id']}`)
      const amount = Number(row['value'])
      const status = cofogRow['cofog_status']!
      const division = cofogRow['cofog_division']!
      const cls = classifyCofogAmount(status, division, `years-cofog check: unexpected cofog_status "${status}"`)
      if (cls.kind === 'unclassifiable') {
        unclassifiable.amount += amount
        unclassifiable.lineCount += 1
        continue
      }
      if (cls.kind === 'out-of-scope') {
        outOfScope.amount += amount
        outOfScope.lineCount += 1
        continue
      }
      if (cls.kind === 'not-descended') {
        notDescended.amount += amount
        notDescended.lineCount += 1
        continue
      }
      const cell = byDivision.get(cls.code) ?? newAggStat()
      cell.amount += amount
      cell.lineCount += 1
      byDivision.set(cls.code, cell)
    }
    for (const [division, stat] of byDivision) expectedCells.push({ fiscalYear: b.fiscalYear, division, amount: stat.amount, lineCount: stat.lineCount })
    expectedResidualByYear[b.fiscalYear] = { unclassifiable, outOfScope, notDescended }
  }
  const writtenByKey = new Map(written.cells.map((c) => [`${c.fiscalYear}|${c.cofogDivision}`, c]))
  if (writtenByKey.size !== expectedCells.length) fail(`years-cofog check: cell count mismatch for ${assetPath}`)
  for (const expected of expectedCells) {
    const key = `${expected.fiscalYear}|${expected.division}`
    const w = writtenByKey.get(key) ?? fail(`years-cofog check: missing cell ${key} in ${assetPath}`)
    if (w.amount !== expected.amount || w.lineCount !== expected.lineCount) fail(`years-cofog check: cell ${key} mismatch in ${assetPath}`)
  }
  for (const [year, expected] of Object.entries(expectedResidualByYear)) {
    const actual = written.residualByYear[year] ?? fail(`years-cofog check: missing residualByYear[${year}] in ${assetPath}`)
    const pairs: [string, AggStat, AggStat][] = [
      ['unclassifiable', expected.unclassifiable, actual.unclassifiable],
      ['outOfScope', expected.outOfScope, actual.outOfScope],
      ['notDescended', expected.notDescended, actual.notDescended],
    ]
    for (const [name, e, a] of pairs) {
      if (e.amount !== a.amount || e.lineCount !== a.lineCount) fail(`years-cofog check: residualByYear[${year}].${name} mismatch for ${assetPath}`)
    }
  }
  const expectedOmittedKey = expectedOmitted.map((o) => `${o.fiscalYear}:${o.code}`).sort().join(',')
  const actualOmittedKey = written.omittedYears.map((o) => `${o.fiscalYear}:${o.code}`).sort().join(',')
  if (expectedOmittedKey !== actualOmittedKey) {
    fail(`years-cofog check: omittedYears mismatch for ${assetPath}: expected [${expectedOmittedKey}] got [${actualOmittedKey}]`)
  }
  const expectedCellsTotal = expectedCells.reduce((s, c) => ({ amount: s.amount + c.amount, lineCount: s.lineCount + c.lineCount }), newAggStat())
  const expectedResidualTotal = Object.values(expectedResidualByYear).reduce(
    (s, r) => ({
      amount: s.amount + r.unclassifiable.amount + r.outOfScope.amount + r.notDescended.amount,
      lineCount: s.lineCount + r.unclassifiable.lineCount + r.outOfScope.lineCount + r.notDescended.lineCount,
    }),
    newAggStat(),
  )
  const expectedTotal = { amount: expectedCellsTotal.amount + expectedResidualTotal.amount, lineCount: expectedCellsTotal.lineCount + expectedResidualTotal.lineCount }
  if (written.total.amount !== expectedTotal.amount || written.total.lineCount !== expectedTotal.lineCount) {
    fail(`years-cofog check: total mismatch for ${assetPath}: expected ${JSON.stringify(expectedTotal)} got ${JSON.stringify(written.total)}`)
  }
  // fundScope は年度単位（cells は年度×division に複製されている）ので、年度ごとに1個だけ拾って union する
  const perYearFundScopes = [...new Map(written.cells.map((c) => [c.fiscalYear, c.fundScope])).values()]
  const expectedFundScope = unionFundScope(perYearFundScopes)
  if (JSON.stringify(written.fundScope) !== JSON.stringify(expectedFundScope)) {
    fail(`years-cofog check: fundScope is not the union of per-year fundScope for ${assetPath}`)
  }
}

/** 団体ごとに、どこかの年度に実在する (phase, fund) の組をすべて洗い出して years アセットを作る */
function writeYearsAggAssets(allBudgetsForYears: Budget[]): void {
  const budgetsByJurisdiction = new Map<string, Budget[]>()
  for (const b of allBudgetsForYears) {
    if (!b.directions.includes('expenditure')) continue
    const arr = budgetsByJurisdiction.get(b.jurisdictionId) ?? []
    arr.push(b)
    budgetsByJurisdiction.set(b.jurisdictionId, arr)
  }
  for (const [jurisdiction, budgetsForJ] of budgetsByJurisdiction) {
    const source = perJurisdictionAggSource.get(jurisdiction) ?? fail(`years agg: no source rows cached for ${jurisdiction}`)
    const phaseFundPairs = new Set<string>()
    for (const b of budgetsForJ) {
      const scope = b.scopes.expenditure!
      for (const phase of scope.phases.map((p) => p.id)) {
        for (const fund of ['all', ...scope.funds.map((f) => f.code)]) phaseFundPairs.add(`${phase}|${fund}`)
      }
    }
    for (const pf of phaseFundPairs) {
      const [phase, fund] = pf.split('|') as [string, string]
      writeYearsTotalAsset(jurisdiction, phase, fund, budgetsForJ, source)
      checkYearsTotalAssetMatchesSource(jurisdiction, phase, fund, budgetsForJ, source.table)
      writeYearsCofogDivisionAsset(jurisdiction, phase, fund, budgetsForJ, source)
      checkYearsCofogDivisionAssetMatchesSource(jurisdiction, phase, fund, budgetsForJ, source.table, source.cofogTable)
    }
  }
}

writeCrossChunks()
allBudgets.sort(byKey((b) => b.id))
writeCrossAggAssets(allBudgets)
for (const key of crossByKey.keys()) {
  const [year, phase] = key.split('|') as [string, string]
  for (const depth of COFOG_DEPTHS) checkAggCrossAssetMatchesSource(year, phase, depth)
}
writeYearsAggAssets(allBudgets)
writeNameIndex()

// 検査6: supportedGroupings が列挙する組み合わせは、すべて前計算アセットが存在する（空の結果を含む）。
// 母集団は SUPPORTED_GROUPINGS そのもの ── 軸を1つ足してアセット生成を足し忘れたら、
// その軸がどの既知の集計種別（single budget / cross / hierarchy / fiscalYear）にも
// 属さないところで最後の else が落ちる（4本の手書き nested loop を1本にまとめた）。
const budgetsByJurisdictionFor6 = new Map<string, Budget[]>()
for (const b of allBudgets) {
  if (!b.directions.includes('expenditure')) continue
  const arr = budgetsByJurisdictionFor6.get(b.jurisdictionId) ?? []
  arr.push(b)
  budgetsByJurisdictionFor6.set(b.jurisdictionId, arr)
}
for (const grouping of SUPPORTED_GROUPINGS) {
  const key = grouping.join(',')
  if (SINGLE_BUDGET_GROUPINGS.some((g) => g.join(',') === key)) {
    if (grouping[0] === 'hierarchy') {
      // 根のアセットは fund ごとに必ず存在する（深い親は原典に実在するものしか作らないので、
      // 根の存在だけを縛る。個々の親パスは生成直後に checkHierarchyAssetMatchesSource が見ている）
      const includesCofog = grouping.length === 2
      for (const b of allBudgets) {
        if (!b.directions.includes('expenditure')) continue
        const scope = b.scopes.expenditure!
        for (const phase of scope.phases.map((p) => p.id)) {
          for (const fund of scope.funds.map((f) => f.code)) {
            const p = includesCofog
              ? join(OUT_DIR, assetPaths.aggHierarchyCofog(b.jurisdictionId, b.fiscalYear, 'expenditure', phase, fund, 'root'))
              : join(OUT_DIR, assetPaths.aggHierarchy(b.jurisdictionId, b.fiscalYear, 'expenditure', phase, fund, 'root'))
            if (!existsSync(p)) fail(`検査6: groupBy [${key}] の根アセットが無い: ${p}`)
          }
        }
      }
    } else {
      const depth = cofogDepthOf(grouping)
      for (const b of allBudgets) {
        if (!b.directions.includes('expenditure')) continue
        const scope = b.scopes.expenditure ?? fail(`budget ${b.id} has expenditure direction but no scopes.expenditure`)
        const fundOptions = ['all', ...scope.funds.map((f) => f.code)]
        for (const phase of scope.phases.map((p) => p.id)) {
          for (const fundOption of fundOptions) {
            const p = join(OUT_DIR, assetPaths.aggBudget(b.jurisdictionId, b.fiscalYear, 'expenditure', phase, fundOption, depth))
            if (!existsSync(p)) fail(`検査6: groupBy [${key}] の組み合わせに対応するアセットが無い: ${p}`)
          }
        }
      }
    }
  } else if (CROSS_JURISDICTION_GROUPINGS.some((g) => g.join(',') === key)) {
    const depth = cofogDepthOf(grouping)
    for (const ck of crossByKey.keys()) {
      const [year, phase] = ck.split('|') as [string, string]
      const p = join(OUT_DIR, assetPaths.aggCross(year, 'expenditure', phase, depth))
      if (!existsSync(p)) fail(`検査6: groupBy [${key}] の横断アセットが無い: ${p}`)
    }
  } else if (JURISDICTION_YEARS_GROUPINGS.some((g) => g.join(',') === key)) {
    // 団体ごとに、どこかの年度に実在する (phase, fund) の組すべてでアセットが存在する
    const includesCofog = grouping.length === 2
    for (const [jurisdiction, budgetsForJ] of budgetsByJurisdictionFor6) {
      const phaseFundPairs = new Set<string>()
      for (const b of budgetsForJ) {
        const scope = b.scopes.expenditure!
        for (const phase of scope.phases.map((p) => p.id)) {
          for (const fund of ['all', ...scope.funds.map((f) => f.code)]) phaseFundPairs.add(`${phase}|${fund}`)
        }
      }
      for (const pf of phaseFundPairs) {
        const [phase, fund] = pf.split('|') as [string, string]
        const p = includesCofog
          ? join(OUT_DIR, assetPaths.aggYearsCofogDivision(jurisdiction, 'expenditure', phase, fund))
          : join(OUT_DIR, assetPaths.aggYearsTotal(jurisdiction, 'expenditure', phase, fund))
        if (!existsSync(p)) fail(`検査6: groupBy [${key}] の fiscalYear 軸アセットが無い: ${p}`)
      }
    }
  } else {
    fail(
      `検査6: groupBy [${key}] はどの既知の集計種別（single budget / cross jurisdiction / hierarchy / fiscalYear）にも属さない。` +
        'SUPPORTED_GROUPINGS に新しい軸を足したら、この検査にもその軸の population を足すこと',
    )
  }
}
writeJson(join(OUT_DIR, assetPaths.jurisdictions), { revision, jurisdictions, budgets: allBudgets })
writeJson(join(OUT_DIR, assetPaths.files), { revision, files: filesMeta })

// 出力の総点検: contract のスキーマに全 StoredBudgetLine を通す（型のずれを deploy 前に落とす）
for (const j of jurisdictionIds) {
  const linesDir = join(OUT_DIR, 'lines', j)
  for (const familyDir of readdirSync(linesDir)) {
    for (const file of readdirSync(join(linesDir, familyDir))) {
      const parsed = JSON.parse(readFileSync(join(linesDir, familyDir, file), 'utf8')) as { lines: unknown[] }
      for (const line of parsed.lines) storedBudgetLineSchema.parse(line)
    }
  }
}

console.log(`built ${jurisdictionIds.length} jurisdiction(s) at revision ${revision} -> ${OUT_DIR}`)

// ---- 規模の実測（前計算アセットは作らない。design doc Caveats 5 が要求する測定） ----
console.log('\nscale measurement (exploratory; no assets generated for these):')
console.log(
  `  hierarchy-asset keys (jurisdiction, fiscal_year, direction, phase, fund, parent-path): ` +
    `${hierarchyAssetKeyCount.expenditure + hierarchyAssetKeyCount.revenue} ` +
    `(expenditure ${hierarchyAssetKeyCount.expenditure}, revenue ${hierarchyAssetKeyCount.revenue})`,
)
console.log(
  `  cofog-depth asset combinations (jurisdiction, fiscal_year, direction=expenditure, phase, fund) x 3 depths: ${cofogDepthAssetComboCount}`,
)
console.log(
  `  max cells in the 2-axis cross (hierarchy-parent x cofog.division), across all (jurisdiction, fiscal_year, phase, fund): ${maxHierarchyCofogCells}`,
)
