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
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { decodeText, fetchCapped, sha256, splitCsvLine } from '../../ingestion/lib/source'
import { loadJurisdictions } from '../../ingestion/shared/jurisdictions'
import type { Check, CofogCode, CofogReach, NodePreview, Provenance, ReportData, Topology } from './schema'
import { ROOT, TARGET, buildChecks, buildTopology, q, readJson, type Manifest, type RunResults } from '../lineage'
import { BY_JURISDICTION, SHARED } from './static'
import {
  COFOG_DEPTHS, COFOG_DEPTH_JA, DIRECTIONS, LEVEL_JA,
  assertDetailColumns, cofogLabel,
  type CofogDepth, type Direction, type DetailTable, type Level,
} from './detail'

/**
 * COFOG のコードに名称を添える。**名称は行に持たず宣言から引く**（異なり数が少ないため）。
 * ⚠️ 宣言に無いコードは `cofogLabel` が落とす。規則が新しいコードを使ったのに
 * 名称を足し忘れると、画面にコードだけが並ぶ状態になるので、生成で止める。
 */
type Coded = { division: string; group: string; class: string }
const withLabel = <T extends Coded>(rows: T[]): (T & CofogCode)[] =>
  rows.map((r) => ({
    ...r,
    divisionLabel: cofogLabel('division', r.division),
    groupLabel: cofogLabel('group', r.group),
    classLabel: cofogLabel('class', r.class),
  }))

/** COFOG のコード3列。`group` / `class` は SQL の予約語なので引用する */
const CODE_SQL = `c.cofog_division division, c.cofog_group "group", c.cofog_class "class"`



/** 階層と金額の宣言。**正本は dbt_project.yml**（dbt のモデルと検査が同じものを見る） */
type Amount = {
  name: string; source: string; unit: string; multiplier: number
  phase: string; phase_label: string; primary: boolean
  /**
   * その宣言が効く年度。**省略なら全年度。**
   * ⚠️ 同じ団体の同じ資料でも年度をまたぐと列名や単位が割れることがある
   * （多摩市は令和7年度で `予算額` → `合計 / 予算額`、千円 → 円）。
   * 解決の規則は dbt 側（macros/budget_amount_scope.sql）が正本。
   */
  years?: number[]
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

const amountsOf = (code: string, direction: Direction) => DBT_VARS.vars.budget_amounts[code]![direction]

/**
 * COFOG の**到達粒度**と、降りた先そのもの。
 *
 * ⚠️ **`byState` から導出する。問い合わせを増やさない。**
 * どれも同じ join の同じ事実を別の切り方で数えているだけなので、
 * 独立に4本のクエリを投げると、後から片方の絞り込みだけ変えたときに
 * 画面の節どうしが黙って食い違う（合計が一致するのは偶然になる）。
 * 導出なら一致は構造で保たれ、DuckDB CLI の起動も団体あたり4回減る。
 *
 * ⚠️ **`group` / `class` が空なのは「該当が無い」ではなく「まだ降りていない」。**
 * 款の名称だけで決まる規則（総務費 → 01、民生費 → 10）は division 止まりが正しく、
 * group を埋めるには項や目まで下げる判断が要る。したがってここは
 * **達成率ではなく現在地**で、割合の高さを合否に使わない（分類不能の割合と同じ扱い）。
 *
 * ⚠️ **母数は割当済みだけ。** 分類不能・対象外には割当先が無いので深さも無い。
 * 全行を母数にすると「降りていない」と「そもそも割り当てていない」が混ざる。
 *
 * 累積（`reached`）と排他（`deepest`）の両方を持つのは、**画面で足し算させないため**。
 * 集計を画面へ漏らすと、同じ数字が2通りに計算されていずれ食い違う。
 */
type StateRow = CofogCode & { status: string; consolidation: string; count: number; sum: number }

/**
 * 割合。**分母が 0 なら 0 を返す。**
 * 割合は生成側が持つ（画面で割り算しない）ので、丸め規則の置き場もここ1つにする。
 */
const share = (v: number, whole: number) => (whole === 0 ? 0 : v / whole)

/** 順序を SQL と揃える（報告は commit するので、非決定的だと中身が同じでも差分が出る） */
const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)
const ZERO = { count: 0, sum: 0 }
const add = (a: { count: number; sum: number }, b: { count: number; sum: number }) =>
  ({ count: a.count + b.count, sum: a.sum + b.sum })

/** 鍵ごとに畳む。**鍵に含めない列は先頭行のもの**（同じ鍵なら同じ値である列しか残さない） */
function foldBy<T extends { count: number; sum: number }>(rows: T[], key: (r: T) => string): T[] {
  const m = new Map<string, T>()
  for (const r of rows) {
    const hit = m.get(key(r))
    if (hit) { hit.count += r.count; hit.sum += r.sum } else m.set(key(r), { ...r })
  }
  return [...m.values()]
}

/** その行がどこまで降りているか。**空は「まだ降りていない」** */
const depthOf = (r: CofogCode): CofogDepth => (r.class ? 'class' : r.group ? 'group' : 'division')

function cofogGranularity(byState: StateRow[]):
  Pick<ReportData['transform'],
    'byCode' | 'byDivision' | 'cofogReach' | 'assigned' | 'total' | 'assignedShare'> {
  const total = byState.reduce(add, ZERO)
  const assignedRows = byState.filter((r) => r.status === 'assigned')
  const assigned = assignedRows.reduce(add, ZERO)
  const byCode = foldBy(
    assignedRows.map(({ status: _s, consolidation: _c, ...code }) => code),
    (r) => [r.division, r.group, r.class].join('\u001f'),
  ).sort((a, b) => b.sum - a.sum || cmp(a.division, b.division)
    || cmp(a.group, b.group) || cmp(a.class, b.class))
  const byDivision = foldBy(
    byCode.map(({ division, divisionLabel, count, sum }) => ({ division, divisionLabel, count, sum })),
    (r) => r.division,
  ).sort((a, b) => cmp(a.division, b.division))

  const at = (d: CofogDepth) => byCode.filter((r) => depthOf(r) === d).reduce(add, ZERO)
  const cofogReach: CofogReach[] = COFOG_DEPTHS.map((depth, i) => {
    // その深さ「以上」= 自分より深い段も数える（04.5.1 は group にも届いている）
    const reached = COFOG_DEPTHS.slice(i).map(at).reduce(add, ZERO)
    return {
      depth, label: COFOG_DEPTH_JA[depth],
      deepest: at(depth),
      reached,
      share: { count: share(reached.count, assigned.count), sum: share(reached.sum, assigned.sum) },
    }
  })
  return {
    byCode, byDivision, cofogReach, assigned, total,
    assignedShare: { count: share(assigned.count, total.count), sum: share(assigned.sum, total.sum) },
  }
}

/**
 * そのリソースに現れる予算段階。**行を段階ごとに展開したかはこれで決まる。**
 * ⚠️ **宣言の件数で決めない。** 多摩市は同じ approved の宣言が年度で2件に割れているが、
 * 原典1行は1行のままである（件数で見ると配布物の行数が2倍だと思い込む）。
 */
const phaseIdsOf = (code: string, direction: Direction) =>
  new Set(amountsOf(code, direction).map((a) => a.phase))

/** 年度つきの状態行。**年度を落とすかどうかは受け取る側が決める** */
type YearStateRow = StateRow & { fy: number }

/**
 * COFOG の状態を**年度つきで1回だけ引く。**
 *
 * ⚠️ **同じ事実を2つのクエリから作らない。** 統計カード（`transform`）と
 * 年度ごとの収録（`coverage`）は同じ割当を別の切り方で見ているだけなので、
 * 独立に引くと「割当済みとは何か」の定義を片方だけ変えたときに
 * **画面の節どうしが黙って食い違う**（`cofogGranularity` が問い合わせを増やさない理由と同じ）。
 * 年度は呼ぶ側が畳むか、年度ごとに分けるかを決める。
 */
function cofogStateRows(code: string): YearStateRow[] {
  return withLabel(q<Coded & {
    fy: number; status: string; consolidation: string; count: number; sum: number
  }>(`
    select s.fiscal_year fy, c.cofog_status status, ${CODE_SQL}, c.cofog_consolidation consolidation,
           count(*) count, sum(s.amount_yen) sum
    from core_budget_cofog c join core_budget_lines s using (budget_line_id)
    where c.jurisdiction_code = '${code}'
    -- 同点で並びが揺れないよう、決着のつく列まで指定する。
    -- 報告は commit するので、非決定的だと中身が同じでも毎回差分が出る。
    group by all
    order by sum desc, status, division, "group", "class", consolidation, fy`, ['fy', 'count', 'sum']))
}

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
function buildTransform(code: string, stateRows: YearStateRow[]): ReportData['transform'] {
  const scope = `where c.jurisdiction_code = '${code}'`
  const rules = q<{ n: number; shared: number }>(
    `select count(*) as n, count(*) filter (where coalesce(applies_to, '') = '') as shared
     from cofog_rules where coalesce(applies_to, '') in ('', '${code}')`,
    ['n', 'shared'])[0]!
  // ⚠️ **年度を落としてから畳む。** 残したまま畳むと、配布する `byState` に
  // 先頭行の年度だけが紛れ込み、全年度の合計に1つの年度が付いた行になる。
  const byState = foldBy(
    stateRows.map(({ fy: _fy, ...r }) => r),
    (r) => [r.status, r.division, r.group, r.class, r.consolidation].join('\u001f'),
  ).sort((a, b) => b.sum - a.sum || cmp(a.status, b.status) || cmp(a.division, b.division)
    || cmp(a.group, b.group) || cmp(a.class, b.class) || cmp(a.consolidation, b.consolidation))
  return {
    cofogVersion: 'COFOG 1999',
    cofogSource: { name: 'UNSD Classification of the Functions of Government (COFOG)',
                   url: 'https://unstats.un.org/unsd/classifications/Family/Detail/4' },
    ruleCount: rules.n,
    ruleScope: { shared: rules.shared, jurisdictionSpecific: rules.n - rules.shared },
    byState,
    // **規則ごとに分ける。** 併合すると basis が合計に対応しなくなる
    // （国民健康保険への繰出と後期高齢者医療への繰出が1行に潰れ、
    // 片方の根拠だけが両方の金額に付いた状態になっていた）。
    byKan: withLabel(q<Coded & {
      fund: string; kan: string; status: string; decidedAtLevel: string
      ruleId: string | null; sum: number; basis: string | null
    }>(`
      select s.fund_code || s.fund_label fund, s.kan_code || s.kan_label kan,
             ${CODE_SQL}, c.cofog_status status,
             c.cofog_decided_at_level decidedAtLevel, c.cofog_rule_id ruleId,
             sum(s.amount_yen) sum, any_value(r.basis) basis
      from core_budget_cofog c join core_budget_lines s using (budget_line_id)
      left join cofog_rules r on r.rule_id = c.cofog_rule_id ${scope}
      -- ⚠️ **規則ごとに分けてあるので行は増えない。** 1本の規則が決める COFOG コードは
      -- 1つで、group / class はそのコードの分解にすぎない。
      group by 1, 2, 3, 4, 5, 6, 7, 8 order by sum desc, fund, kan, ruleId`, ['sum'])),
    ...cofogGranularity(byState),
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

/**
 * 年度 × direction ごとの収録の状況。**年度差は団体単位の集計に現れない。**
 *
 * ⚠️ **団体で畳んだ割合を年度の主張に使わない。** 狛江市は事業名の PDF が
 * 2020〜2023年度にしか無く、2018〜2019年度は科目の名称も事業名もゼロだが、
 * 6年度を合算すると名称のある年度が薄めるだけで、無い年度の存在が消える。
 *
 * ⚠️ **名称は行に持っている値ではなく `core_budget_accounts` から測る。**
 * 名称の解決（原典の列か、決算書 PDF から起こしたものか）はそこが正本で、
 * ここで `coalesce` を書き直すと同じ判断が2箇所に分かれる。
 *
 * ⚠️ **COFOG は引き直さない。** 統計カードと同じ `stateRows` を年度で切って
 * `cofogGranularity` に通す（同じ事実を2つのクエリから作らないため）。
 * 引くのは行数・金額・名称と、事業名（大事業を持つ団体だけ）。
 */
function buildCoverage(code: string, stateRows: YearStateRow[]): ReportData['coverage'] {
  return coverageRows(code, stateRows)
    // **並び順は生成側が決める。** 年度 → direction の順に並べ、同じ年度の歳出と歳入を隣に置く
    // （原典が別の資料なので、片方だけ名称が取れている年度がある）。
    // 画面で並べ替えると、JSON を直接読む利用者と画面で行の順が違うことになる。
    .sort((a, b) => a.fiscalYear - b.fiscalYear
      || (a.direction === b.direction ? 0 : a.direction === 'expenditure' ? -1 : 1))
}

function coverageRows(code: string, stateRows: YearStateRow[]): ReportData['coverage'] {
  const byYear = new Map<number, YearStateRow[]>()
  for (const r of stateRows) byYear.set(r.fy, [...(byYear.get(r.fy) ?? []), r])
  return DIRECTIONS.flatMap((direction) => {
    const lines = direction === 'expenditure' ? 'core_budget_lines' : 'core_revenue_lines'
    const projects = projectNameCoverage(code, direction)
    type Row = {
      fy: number; lineCount: number; sum: number
      namedKan: number; namedKou: number; namedMoku: number
    }
    const rows = q<Row>(`
      -- ⚠️ year と rows はどちらも予約語で、別名に使うと DuckDB のパーサが落ちる
      select l.fiscal_year fy, count(*) lineCount, sum(l.amount_yen) sum,
             count(*) filter (where a.kan_name is not null) namedKan,
             count(*) filter (where a.kou_name is not null) namedKou,
             count(*) filter (where a.moku_name is not null) namedMoku
      from ${lines} l
      left join core_budget_accounts a
        on  a.jurisdiction_code = l.jurisdiction_code and a.fiscal_year = l.fiscal_year
        and a.direction = l.direction and a.fund_code = l.fund_code
        and a.kan_code = l.kan_code and a.kou_code = l.kou_code and a.moku_code = l.moku_code
      where l.jurisdiction_code = '${code}'
      group by 1 order by 1`,
      ['fy', 'lineCount', 'sum', 'namedKan', 'namedKou', 'namedMoku'])
    return rows.map((r) => ({
      fiscalYear: r.fy,
      direction,
      rows: r.lineCount,
      sum: r.sum,
      named: {
        kan: share(r.namedKan, r.lineCount),
        kou: share(r.namedKou, r.lineCount),
        moku: share(r.namedMoku, r.lineCount),
      },
      // COFOG は歳出にしか無い。**判定は cofogGranularity に任せる** —
      // 「割当済みとは何か」「どこまで降りたか」の定義を写すと、統計カードと食い違う
      cofog: direction === 'expenditure' ? cofogOfYear(byYear.get(r.fy) ?? []) : null,
      projectNames: projects.get(r.fy) ?? null,
    }))
  })
}

/**
 * その年度の COFOG。**統計カードと同じ導出（`cofogGranularity`）を通す。**
 * 年度で切ってから畳むだけで、判定条件はここに持たない。
 *
 * ⚠️ **割当済みが 0 円の年度は、到達の割合を 0% と言えない**（降りる先が無い）。
 * 「割り当てたが降りていない」と区別できないので null にして、画面は「該当なし」を出す。
 */
function cofogOfYear(rows: YearStateRow[]): ReportData['coverage'][number]['cofog'] {
  const g = cofogGranularity(rows)
  const reach = (depth: CofogDepth) =>
    g.assigned.sum === 0 ? null : g.cofogReach.find((d) => d.depth === depth)!.share.sum
  return { assignedShare: g.assignedShare, groupShare: reach('group'), classShare: reach('class') }
}

/**
 * 年度ごとの事業名の充足。**歳出の大事業だけ**に掛かる（他は空の Map = 画面では null）。
 *
 * ⚠️ **歳入には掛けない。** `core_budget_project_names` は歳出の事項別明細から起こしており
 * direction を持たないので、歳入に同じ (年度, 会計, 款項目) があれば歳出の事業名が付く。
 * 同じ型の誤結合は会計を落としたときに既に一度起きている（実測199件）。
 *
 * ⚠️ **母集団は全会計の大事業。** 名称の出所（決算書 PDF の事項別明細）は
 * 一般会計しか載せていないので、狭めると「出所が覆っていない」ぶんが見えなくなる。
 * 代わりに出所の範囲（`inSourceScope`）を併記して、**出所が届いていない**のと
 * **届いているが当たらなかった**のを分けられるようにする。
 *
 * ⚠️ **出所がある年度は `sources.toml` の宣言で決める。** 突合できた行から逆算すると、
 * 「PDF が無い年度」と「PDF はあるが1件も当たらなかった年度」が同じ 0 になる。
 */
function projectNameCoverage(
  code: string, direction: Direction,
): Map<number, NonNullable<ReportData['coverage'][number]['projectNames']>> {
  const out = new Map<number, NonNullable<ReportData['coverage'][number]['projectNames']>>()
  if (direction !== 'expenditure') return out
  if (!levelsOf(code, direction).includes('daijigyo' as Level)) return out
  const declaredYears = PROJECT_NAME_YEARS.get(code) ?? new Set<number>()
  const rows = q<{ fy: number; total: number; named: number; inScope: number }>(`
    with d as (
      select distinct fiscal_year, fund_code, kan_code, kou_code, moku_code, daijigyo_code
      from stg_${code}__${direction}
    )
    select d.fiscal_year fy, count(*) total,
           count(p.project_name) named,
           -- 出所が覆う会計。**report で決め打たない** — 対応づけの側が
           -- 一般会計に閉じているので、その宣言（fund_code）を引いて母数にする
           count(*) filter (where d.fund_code in (
             select distinct fund_code from core_budget_project_names
             where jurisdiction_code = '${code}')) inScope
    from d
    left join core_budget_project_names p
      on  p.jurisdiction_code = '${code}' and p.fiscal_year = d.fiscal_year
      and p.fund_code = d.fund_code and p.kan_code = d.kan_code and p.kou_code = d.kou_code
      and p.moku_code = d.moku_code and p.daijigyo_code = d.daijigyo_code
    group by 1 order by 1`, ['fy', 'total', 'named', 'inScope'])
  for (const r of rows) {
    // 出所の宣言が無い年度は、覆う会計も無い（0 件）。割合は 0% ではなく「該当なし」
    const inScope = declaredYears.has(r.fy) ? r.inScope : 0
    out.set(r.fy, {
      total: r.total, named: r.named, inSourceScope: inScope,
      share: share(r.named, r.total),
      shareInScope: inScope === 0 ? null : r.named / inScope,
    })
  }
  return out
}

type SourceEntry = {
  phase_id?: string; phase_label?: string
  license_id?: string; attribution?: string; landing_page?: string
}

/**
 * 取得元の定義。**団体コードを直書きしない** — `sources.toml` が正本。
 *
 * ⚠️ TOML を正規表現で読まない。最初に一致した key を返すので、
 * 2団体目を足した時点で先頭の団体の名称・ライセンスを使ってしまう。
 */
const SOURCES_TOML = Bun.TOML.parse(
  readFileSync(join(ROOT, 'ingestion/budget/sources.toml'), 'utf8'),
) as Record<string, SourceEntry | Record<string, SourceEntry>> & {
  project_names?: Record<string, unknown>
  statement?: Record<string, SourceEntry>
}

/**
 * 取得元。**経路が2つある**（CKAN の CSV と、事項別明細書の PDF）ので両方を束ねる。
 *
 * ⚠️ **CSV の取得元だけを母集団にしない。** 59/62 団体は PDF しか持たないので、
 * トップレベルの `<団体>:<年度>` だけを見ると、それらの団体が報告から丸ごと消える
 * （実際に1団体目が黙って抜けた）。Python 側の `all_sources()` と同じ束ね方をする。
 * ⚠️ `[project_names]` `[revenue_accounts]` は束ねない — あれは既に収録済みの団体で
 * 欠けている名称を補う取得元で、その団体を収録している宣言ではない。
 */
const SOURCES: Record<string, SourceEntry> = {
  ...Object.fromEntries(
    Object.entries(SOURCES_TOML).filter(([k]) => /^\d{6}:/.test(k)),
  ) as Record<string, SourceEntry>,
  ...(SOURCES_TOML.statement ?? {}),
}

/**
 * 事業名の取得元がある (団体, 年度)。**正本は `sources.toml` の `[project_names]`。**
 * 突合できた行から逆算すると、PDF が無い年度と、PDF はあるが1件も当たらなかった年度が
 * 同じ 0 になる。**出所の有無は宣言が言う**（AGENTS.md「年度を宣言で持つ」）。
 */
const PROJECT_NAME_YEARS: Map<string, Set<number>> = (() => {
  const m = new Map<string, Set<number>>()
  for (const key of Object.keys(SOURCES_TOML.project_names ?? {})) {
    const [code, year] = key.split(':')
    if (!code || !year) continue
    m.set(code, (m.get(code) ?? new Set()).add(Number(year)))
  }
  return m
})()

/**
 * 団体の名称。**`sources.toml` には持たせない**（`ingestion/budget/sources.py` が
 * 明示的に禁止している — 以前は団体×年度ごとに反復宣言しており、狛江市だけで6回、
 * 誤記があっても検知されなかった）。正本は `ingestion/shared/jurisdictions.json`
 * （①②③のどの層からも参照される、層に依存しない団体の同一性）。
 *
 * ⚠️ **読む口を自分で作らない。** 既に `ingestion/shared/jurisdictions.ts` の
 * `loadJurisdictions()` が zod で検証して読んでいる。ここで `readFileSync` + 型アサーションを
 * 書き直すと、同じ JSON を読む口が2つになるうえ、実行時の検証が効かない場所を自分で作ることになる。
 * `loadJurisdictions()` は非同期だが、Bun の ESM は top-level await を扱えるので、
 * 同期に寄せる理由にはならない。
 */
const JURISDICTIONS = (await loadJurisdictions()).jurisdictions

/** 団体コードから名称を引く。**登録が無ければ止める**（黙って欠けさせない） */
function jurisdictionNameOf(code: string): string {
  const j = JURISDICTIONS[code]
  if (!j) {
    throw new Error(
      `団体コード「${code}」が ingestion/shared/jurisdictions.json に無い。` +
        `団体の名称と識別子はそこで一元管理している（AGENTS.md 参照）`,
    )
  }
  return j.name
}

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
  // COFOG の状態は**1回だけ引いて2つの節へ渡す**（統計カードと年度ごとの収録が
  // 同じ割当を別の切り方で見ているだけなので、独立に引くと定義がいずれ食い違う）
  const cofogState = cofogStateRows(code)

  return {
    meta: {
      jurisdictionCode: code,
      jurisdictionName: jurisdictionNameOf(code),
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
      rowsPreserved: DIRECTIONS.every((d) => {
        // label（表示名）ではなく id で引く。表示名は変わりうるが、dbt の unique_id は識別子
        const rows = (name: string) => topology.nodes.find((n) => n.id.endsWith(`.${name}`))?.rows
        return rows(`stg_${code}__${d}`)! * phaseIdsOf(code, d).size === rows(`pkg_${code}__${d}`)
      }),
    },
    topology,
    ingestion: prov,
    detailLevels: DIRECTIONS.map((direction) => ({ direction, levels: levelsOf(code, direction) })),
    levels: buildLevels(code),
    coverage: buildCoverage(code, cofogState),
    transform: buildTransform(code, cofogState),
    checks,
    ...SHARED,
    // ⚠️ **団体固有の内容は宣言が無ければ止める。** 既定値で埋めると、
    // 三鷹市について書いた caveats が狛江市の報告に出たまま気づけない。
    ...perJurisdiction(code),
    // FDP に無い概念のために自作した ColumnType。**正本は fdp/field_types.json**
    // （descriptor もそこから作る）。報告へ写すと片方だけ直る。
    customColumnTypes: CUSTOM_COLUMN_TYPES,
  }
}

/**
 * 明細。**配布する CSV を読み、画面用に join した射影を作る。**
 *
 * 配布物は正本（判断なし）と判断のリソースを別ファイルにしてある。
 * 画面はその両方を見せたいので、利用者が `budget_line_id` で join して得るのと
 * 同じものをここで組む。**配布物を太らせて画面に合わせない** —
 * それをやると正本に判断が混ざる。
 *
 * `*_source`（原典のセル全文）は配布物から落としてある（code‖label で復元できるため）。
 * 画面は階層の絞り込みに使うので、ここで組み立て直す。
 *
 * ⚠️ **配布物に phase_label / source_amount_unit の列が無い団体がある。**
 * 全行同じ値なら配布物から外して descriptor の定数にしてあるからで、
 * 画面は列として受け取るので無い側をここで補う。
 * ⚠️ **2つは別々に決まる。** 段階が1つなら phase_label は定数だが、
 * 単位は年度でも割れる（多摩市は令和3〜6年度が千円、令和7年度が円）ので列に残る。
 */
/**
 * 割当の根拠。**規則ごとに1つ**なので行に複製せず、明細と一緒に1回だけ運ぶ。
 * 規則表は団体ごとの配布物にあり、その団体に効く規則だけが入っている。
 */
function ruleBasisOf(code: string): Record<string, string> {
  return Object.fromEntries(
    q<{ rule_id: string; basis: string }>(
      `select rule_id, basis from read_csv('${join(ROOT, 'data/budget/datapackages')}/${code}/cofog_rules.csv',
       header = true, all_varchar = true)`,
    ).map((r) => [r.rule_id, r.basis]),
  )
}

function detailProjection(code: string, direction: Direction): DetailTable {
  const levels = levelsOf(code, direction)
  // 事業名は fudoki の判断（原典に無い）。階層に大事業を持つ団体だけに掛かる。
  const PROJECT_NAMES = levels.includes('daijigyo' as Level)
    ? `left join read_csv('${join(ROOT, `data/budget/datapackages/${code}/project_names.csv`)}',
         header = true, all_varchar = true) pn
       on pn.fiscal_year = c.fiscal_year and pn.fund_code = c.fund_code
       and pn.kan_code = c.kan_code and pn.kou_code = c.kou_code
       and pn.moku_code = c.moku_code and pn.daijigyo_code = c.daijigyo_code`
    : ''
  const amounts = amountsOf(code, direction)
  const canonical = join(ROOT, `data/budget/datapackages/${code}/${direction}.csv`)
  // ⚠️ join 相手にも同名の列があるので c. で明示する（曖昧参照で DuckDB が落ちる）
  const src = levels.map((l) => `c.${l}_code || c.${l}_label as ${l}_source`).join(', ')
  // ⚠️ **段階の数と宣言の数を分けて見る。** 多摩市は段階が1つ（approved）なので
  // phase_label は配布物の定数だが、単位は年度で割れるので配布物の列になっている。
  // 一緒くたにすると、既にある列を二重に select して DuckDB が落ちる。
  const constants = [
    phaseIdsOf(code, direction).size === 1 ? `, '${amounts[0]!.phase_label}' as phase_label` : '',
    amounts.length === 1 ? `, '${amounts[0]!.unit}' as source_amount_unit` : '',
  ].join('')
  // ⚠️ **異なり数の少ない列を行へ join しない。** 根拠（basis）は19種類しかないのに
  // 行へ入れると狛江市の歳出だけで 7.0 MB になる（`cofog_rule_id` が全行にあるので情報量ゼロ）。
  // ディビジョン名も画面が宣言として持っている。どちらも規則表・宣言から引く。
  const rows = q<Record<string, unknown>>(`
    select c.*, ${src}${constants},
           d.cofog_status, d.cofog_division as cofog_division_code,
           d.cofog_consolidation, d.cofog_decided_at_level, d.cofog_rule_id,
           ${levels.includes('daijigyo' as Level) ? "coalesce(pn.project_name, '')" : "''"} as project_name
    from read_csv('${canonical}', header = true, all_varchar = true) c
    left join read_csv('${join(ROOT, `data/budget/datapackages/${code}/cofog.csv`)}', header = true, all_varchar = true) d
      using (budget_line_id)
    ${PROJECT_NAMES}
    order by c.fiscal_year, c.source_row, c.phase_id`)
  const columns = rows.length ? Object.keys(rows[0]!) : []
  // **宣言した列が欠けていたら落とす。** 画面が黙って空になるより、生成が止まるほうがよい。
  assertDetailColumns(code, direction, levels, columns)
  return {
    columns: columns as DetailTable['columns'],
    rows: rows.map((x) => columns.map((c) => String(x[c] ?? ''))),
    ruleBasis: ruleBasisOf(code),
  }
}


const manifest = readJson<Manifest>(join(TARGET, 'manifest.json'))
const results = readJson<RunResults>(join(TARGET, 'run_results.json'))

// **団体で変わらないものは1回だけ作る。**
const topology = buildTopology(manifest, ALL_PROVENANCE)
const checks = buildChecks(manifest, results)

const reports = CODES.map((code) => ({ code, report: build(code, topology, checks) }))

// **報告と明細を分けて書く。** 明細は報告の 50 倍あり（2.4MB 対 0.05MB）、
// 既定のタブは明細を使わない。1つにまとめると、報告だけ見る利用者にも全部を運ぶことになる。
//
// ⚠️ **団体で変わらないものを団体の数だけ運ばない。**
// 系統・検査・移植性の判定・独自 ColumnType はどの団体でも同じ内容で、
// 2団体でも 151.7 KB のうち 29.1 KB（19%）がバイト一致していた。62団体なら系統だけで約 11 MB になる。
// しかも pipeline.json は明細タブを開かなくても読まれる**既定の payload** である。
// 画面側（`loadPipeline`）が読み込み時に組み直すので、下流の型は変わらない。
const { portability, customColumnTypes } = reports[0]!.report
writeFileSync(join(ROOT, 'apps/web/public/pipeline.json'), `${JSON.stringify({
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
      join(ROOT, `apps/web/public/detail-${code}-${direction}.json`),
      `${JSON.stringify(table)}\n`,
    )
  }
}

/**
 * ノードごとの中身の先頭。グラフでノードを選んだときに画面が出す。
 * **原典（source）は raw の Parquet を直接読む** — 加工前の姿を見せるのが目的なので、
 * staging 以降のテーブルで代用しない。
 *
 * ⚠️ **原典ノードは団体ごとにある。** ソースの識別子（`source.fudoki.raw_132195.expenditure`）から
 * 団体コードを取る。1団体を前提に外から `code` を渡すと、狛江市のノードに三鷹市の原典が出る
 * （系統の行数で実際にその壊れ方をした）。
 */
function previewFrom(node: ReportData['topology']['nodes'][number]): string {
  if (node.kind === 'source') {
    const owner = /\.raw_(\d{6})/.exec(node.id)?.[1]
    if (!owner) throw new Error(`ソース ${node.id} の名前から団体コードを取れない`)
    // 事業名・歳入科目名は原典の CSV とは別の場所（PDF から起こした抽出物）にある
    if (node.id.includes('project_names'))
      return `read_parquet('${join(ROOT, 'data/budget/raw/project-names')}/jurisdiction=${owner}/**/data.parquet')`
    if (node.id.includes('revenue_accounts'))
      return `read_parquet('${join(ROOT, 'data/budget/raw/revenue-accounts')}/jurisdiction=${owner}/**/data.parquet')`
    return `read_parquet('${join(ROOT, 'data/budget/raw')}/jurisdiction=${owner}/**/direction=${node.label}/data.parquet')`
  }
  // package 段は外部 CSV。DuckDB のビューは dbt の作業ディレクトリ基準なので実ファイルを読む
  if (node.artifact) return `read_csv('${join(ROOT, 'dbt', node.artifact)}', header = true, all_varchar = true)`
  return `"${node.label}"`
}

// **プレビューは団体で分けない。** 系統が1本なので、ノードの集合も1つ。
const PREVIEW_ROWS = 20
mkdirSync(join(ROOT, 'apps/web/public/preview'), { recursive: true })
// 取得元（origin）は DuckDB に無い。下の「取得元 CSV」節が fetch して書く
for (const node of topology.nodes.filter((n) => n.kind !== 'origin')) {
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
 *
 * ⚠️ **証跡は団体ごとに引く。** 2団体目からは direction だけでは決まらない。
 */
const ORIGIN_CACHE = join(ROOT, '.cache/origin-csv')
mkdirSync(ORIGIN_CACHE, { recursive: true })
const provByCode = new Map(reports.map(({ code, report }) => [code, report.ingestion]))
for (const node of topology.nodes.filter((n) => n.kind === 'source')) {
  const code = /\.raw_(\d{6})/.exec(node.id)?.[1]
  const p = provByCode.get(code ?? '')?.find((x) => x.direction === node.label)
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

for (const { code, report } of reports) {
  const s = report.summary
  console.log(`ok  ${code}  検査 ${s.passed}/${s.total}（警告 ${s.warned}）  `
    + `ノード ${report.topology.nodes.length}  辺 ${report.topology.edges.length}`)
}
console.log(`ok  プレビュー ${topology.nodes.length} 件`)
