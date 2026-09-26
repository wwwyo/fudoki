/**
 * 系統（どの段がどの段に依存するか、どの検査がどのノードを守るか）を
 * dbt の成果物から読む。**層に依存しない** — ②調達・③会議録も同じ dbt を通る。
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
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { provenanceForSource } from './common'
import type { CanonicalFetch, Check, CheckAttribution, Node, ProjectNamesExtract, Provenance, RevenueAccountsExtract, Stage, Topology } from './common'

export const ROOT = resolve(import.meta.dirname, '..')
export const TARGET = join(ROOT, 'dbt/target')
const WAREHOUSE = join(ROOT, 'data/fudoki.duckdb')

export const readJson = <T,>(p: string): T => JSON.parse(readFileSync(p, 'utf8')) as T

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
export function q<T = Record<string, unknown>>(sql: string, nums: string[] = [], cwd?: string): T[] {
  const r = Bun.spawnSync(['duckdb', '-json', WAREHOUSE, '-c', sql], cwd ? { cwd } : undefined)
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
export const STAGES: Stage[] = [
  // 取得元だけは dbt の外にある（パイプラインが始まる前の、自治体が配っているファイルそのもの）。
  // ノードは provenance から組む — 手で並べると取得元を変えても図が変わらない
  { id: 'origin', label: '取得元', introducesJudgment: false,
    responsibility: '自治体が公開しているファイルそのもの。fudoki の外にあり、fudoki は変更できない',
    excludes: 'fudoki の関与すべて' },
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
  config?: { location?: string; severity?: string }; depends_on?: { nodes?: string[] }
  meta?: { role?: 'judgment-rule' | 'external-reference' }
  /** テストは定義 SQL（jinja 込み）と compile 済み SQL を持つ */
  raw_code?: string; compiled_code?: string
  /** generic test（schema.yml の unique / not_null 等）はここに種類と対象列が入る */
  test_metadata?: { name?: string; kwargs?: Record<string, unknown> }
}
export type Manifest = { nodes: Record<string, DbtNode>; sources: Record<string, DbtNode> }
export type RunResults = { results: { unique_id: string; status: string; failures: number | null; message: string | null }[] }

/**
 * 段はノードの置き場から決まる。宣言と実装がずれないのはこれが理由。
 *
 * ⚠️ **未知の置き場を core に落とさない。** 落とすと、段を1つ増やしたときに
 * 黙って core に混ざり、判断の境界を誤って表示する。宣言されていなければ止める。
 */
function stageOf(n: DbtNode): Stage['id'] {
  if (n.resource_type === 'source') return 'ingestion'
  if (n.resource_type === 'seed') return 'core'
  const hit = STAGES.find((s) => (n.path ?? '').startsWith(`${s.id}/`))
  if (!hit) throw new Error(`モデル ${n.name}（${n.path}）の置き場が段の宣言に無い`)
  return hit.id
}

/**
 * このノード自身が判断を持ち込むか。
 *
 * **seed は置き場では決まらない。** 規則表（COFOG の割当）は判断そのものだが、
 * 公表資料の書き写しは判断ではない。dbt の meta.role で宣言させ、未宣言なら止める。
 */
function introducesJudgment(n: DbtNode, stage: Stage['id']): boolean {
  if (n.resource_type === 'seed') {
    const role = n.meta?.role
    if (!role) throw new Error(`seed ${n.name} に meta.role の宣言が無い（judgment-rule / external-reference）`)
    return role === 'judgment-rule'
  }
  return stage === 'core'
}

/**
 * 原典（source）の行数を証跡から引く。
 *
 * ⚠️ **direction だけで引かない。** ソースは団体ごとに1つあり、名前はどちらも
 * `expenditure` / `revenue` である。direction だけで突き合わせると、
 * 狛江市の原典ノードに三鷹市の行数が出る（実際にそうなっていた）。
 * ソースの識別子（`source.fudoki.raw_132195.expenditure`）から団体コードを取る。
 * 証跡の拾い方そのものは `common.ts` の `provenanceForSource`（検証画面の
 * ローカル・データ口と共有）。
 */

/** 抽出器ごとに「何を数えたか」が違う。事業名は事業の数、歳入の科目名称は目の数 */
function extractedCount(p: Provenance, kind: 'project-names' | 'revenue-accounts' | 'statement'): number {
  if (!p.extracted) return 0
  return kind === 'project-names'
    ? (p.extracted as ProjectNamesExtract).projects
    : kind === 'revenue-accounts'
      ? (p.extracted as RevenueAccountsExtract).moku
      : (p.extracted as { leaves?: number }).leaves ?? 0
}

function sourceRows(id: string, name: string, provenance: Provenance[]): Counted | null {
  const hit = provenanceForSource(id, name, provenance)
  if (!hit) return null
  // ⚠️ **証跡の形が取得元で違う。** 正本の取り込み（CSV でも事項別明細書の PDF でも）は
  // direction ごとに `rows` を持つが、既収録の団体で欠けている名称を補う抽出物は
  // `rows` を持たず、抽出の要約しか持たない。
  if (hit.kind === 'canonical')
    return countByYear((hit.ps as CanonicalFetch[]).map((p) => [p.fiscal_year, p.rows]))
  const kind = hit.kind
  return countByYear(hit.ps.map((p) => [p.fiscal_year, extractedCount(p, kind)]))
}

/** 年度ごとの行数と、その合計。**合計は生成側で1回だけ足す**（画面では足さない） */
type Counted = { total: number; byYear: Record<string, number> }

function countByYear(pairs: [number, number][]): Counted {
  const byYear: Record<string, number> = {}
  for (const [year, rows] of pairs) byYear[String(year)] = (byYear[String(year)] ?? 0) + rows
  return { total: pairs.reduce((s, [, rows]) => s + rows, 0), byYear }
}

/** ノード1つぶんの行数。`total` は全団体・全年度、`byJurisdiction` は団体で切ったもの */
type NodeCount = { total: number; byJurisdiction: Node['rowsByJurisdiction'] }

/** 1団体しか持たないノード（原典・取得元）を、団体で引ける形へ */
function ownCount(c: Counted | null, code: string): NodeCount | null {
  return c === null ? null : { total: c.total, byJurisdiction: { [code]: { total: c.total, byYear: c.byYear } } }
}

/**
 * 問い合わせの結果を、団体 × 年度の行数へ畳む。
 *
 * ⚠️ **団体を名乗らない表を団体で切らない。** 規則表（`account_master` /
 * `cofog_rules`）は団体にも年度にも依らないので、切ると「その団体の分」という
 * 存在しない概念を画面に出すことになる。null を返して合計だけを見せる。
 */
function tally(rows: CountRow[], hasYear: boolean, hasJurisdiction: boolean, nameCode: string | null): NodeCount {
  const total = rows.reduce((s, r) => s + r.n_rows, 0)
  if (!hasJurisdiction && nameCode === null) return { total, byJurisdiction: null }
  const byJurisdiction: NonNullable<Node['rowsByJurisdiction']> = {}
  for (const r of rows) {
    // 列はあるが値が無い行は、どの団体のページにも出しようがない（合計 `total` には残る）
    const code = hasJurisdiction ? r.jurisdiction_code : nameCode
    if (code === null) continue
    const slot = (byJurisdiction[code] ??= { total: 0, byYear: hasYear ? {} : null })
    slot.total += r.n_rows
    if (slot.byYear !== null && r.fiscal_year !== null)
      slot.byYear[r.fiscal_year] = (slot.byYear[r.fiscal_year] ?? 0) + r.n_rows
  }
  return { total, byJurisdiction }
}

/** ノードの団体。**id か名前のどちらかが名乗る**（`raw_132241` / `pkg_132241__expenditure`） */
function jurisdictionOf(id: string, name: string): string | null {
  return /\.raw_(\d{6})/.exec(id)?.[1] ?? /_(\d{6})__/.exec(name)?.[1] ?? null
}

/** 行数の問い合わせの1行 */
type CountRow = {
  node: number
  fiscal_year: string | null
  jurisdiction_code: string | null
  n_rows: number
}

/** スキーマ問い合わせの1行。ノードが年度・団体の列を持つかを、列そのものから判定する */
type SchemaRow = { node: number; column_name: string }

/**
 * 検査: 年度・団体の列を持つと分かっているノードに、その列が NULL の行が無いこと。
 *
 * ⚠️ **これは `tally` が黙って踏んでいた前提。** `tally` は値が NULL の行を
 * `continue` で読み飛ばす（`byJurisdiction` に振り分けようがないため）ので、
 * NULL 行があると `total`（読み飛ばす前の合計）と `Σ(byJurisdiction)`（読み飛ばした後の合計）が
 * 食い違ったまま黙って通る。実データでは起きていないが、起きたらここで止める。
 */
export function assertNoNullKeyRows(counts: CountRow[], hasYear: (node: number) => boolean, hasJurisdiction: (node: number) => boolean): void {
  for (const r of counts) {
    if (hasYear(r.node) && r.fiscal_year === null) throw new Error(`ノード#${r.node}: fiscal_year 列があるのに NULL の行がある`)
    if (hasJurisdiction(r.node) && r.jurisdiction_code === null) throw new Error(`ノード#${r.node}: jurisdiction_code 列があるのに NULL の行がある`)
  }
}

/**
 * 検査: `rows === Σ(rowsByJurisdiction[*].total)` と `total === Σ(byYear)`。
 *
 * ⚠️ **数値でない行数をスキップしない。** `NaN` は比較が必ず不一致になるので、
 * 見なかったことにすると原因が画面から消える（`isCanonicalFetch` を参照）。
 */
export function assertRowSumsConsistent(nodes: Node[]): void {
  // 文言は throw する側でだけ組む。検査のたびに組むと、捨てるだけの文字列を団体 × 年度ぶん作る
  const notANumber = (id: string, what: string, v: unknown) =>
    new Error(`${id}: ${what} が数値でない（${v}）。行数を持たない証跡が合算に混ざっている`)
  for (const n of nodes) {
    if (n.rowsByJurisdiction === null) continue
    let acrossJurisdictions = 0
    for (const [code, v] of Object.entries(n.rowsByJurisdiction)) {
      if (!Number.isFinite(v.total)) throw notANumber(n.id, `${code} の total`, v.total)
      acrossJurisdictions += v.total
      if (v.byYear === null) continue
      let acrossYears = 0
      for (const [year, rows] of Object.entries(v.byYear)) {
        if (!Number.isFinite(rows)) throw notANumber(n.id, `${code} の ${year}年度`, rows)
        acrossYears += rows
      }
      if (acrossYears !== v.total) throw new Error(`${n.id}: total(${v.total}) !== Σ(byYear)(${acrossYears})`)
    }
    // `rows` だけは null を取りうる（行数を数えようが無いノード）
    if (n.rows === null) continue
    if (!Number.isFinite(n.rows)) throw notANumber(n.id, 'rows', n.rows)
    if (acrossJurisdictions !== n.rows)
      throw new Error(`${n.id}: rows(${n.rows}) !== Σ(rowsByJurisdiction の total)(${acrossJurisdictions})`)
  }
}

export function buildTopology(m: Manifest, provenance: Provenance[]): Topology {
  const all = { ...m.nodes, ...m.sources }
  const models = Object.entries(all).filter(([, n]) => ['model', 'source', 'seed'].includes(n.resource_type))
  const ids = new Set(models.map(([id]) => id))

  // **行数は2クエリでまとめて数える。** ノードごとに投げると DuckDB CLI の
  // プロセス起動がノード数だけ増える。原典（source）は DuckDB にテーブルとして
  // 存在しないので証跡から取る。
  //
  // ⚠️ **どのモデルが年度・団体の列を持つかをここで宣言しない。** core と staging は
  // 両方持ち、package は団体をモデル名で名乗って列を持たず、規則表はどちらも持たない。
  // 宣言すると、モデルに列を足した日に古い数え方が黙って残る。**実物に名乗らせる**。
  //
  // ⚠️ **全行を `to_json` する方式は避ける。** 実測で 200万行のテーブルにおいて
  // 素の `count(*)`（user 0.02s）に対し `to_json` 経由は約45倍の CPU 時間だった。
  // さらに行から列の有無を見る方式は、空のテーブルで「列が無い」と「列はあるが0行」を
  // 区別できない（行が1つも返らないため）。**列の有無はスキーマから判定する**
  // （`DESCRIBE` はサブクエリにできる）。この1本目のクエリは行を1つも読まない。
  const counted = models.filter(([, n]) => n.resource_type !== 'source')
  const from = (n: DbtNode) => {
    const loc = n.config?.location
    // package 段は外部ファイルとして書き出される。DuckDB のビューは dbt の
    // 作業ディレクトリ基準の相対パスなので、実ファイルを直接数える。
    return loc
      ? `read_csv('${join(ROOT, 'dbt', loc)}', header = true, all_varchar = true)`
      : `"${n.name}"`
  }
  const schemaRows = counted.length === 0 ? [] : q<SchemaRow>(
    counted
      .map(([, n], i) => `select ${i} as node, column_name from (describe select * from ${from(n)} limit 0)`)
      .join('\nunion all\n'),
    ['node'],
  )
  const columnsOf = new Map<number, Set<string>>()
  for (const r of schemaRows) columnsOf.set(r.node, (columnsOf.get(r.node) ?? new Set()).add(r.column_name))

  // 2本目で実際に数える。列が無いノードは `count(*)` 一発（group by だと
  // 空テーブルで0行返り、値が取れないことと0件であることを区別できなくなる）。
  // 列があるノードは通常どおり group by で年度 × 団体へ畳む
  // （空テーブルなら0グループ＝合計0になり、こちらは「0行」を正しく表せる）。
  const counts = counted.length === 0 ? [] : q<CountRow>(
    counted
      .map(([, n], i) => {
        const cols = columnsOf.get(i) ?? new Set<string>()
        const hasYear = cols.has('fiscal_year')
        const hasJurisdiction = cols.has('jurisdiction_code')
        if (!hasYear && !hasJurisdiction)
          return `select ${i} as node, cast(null as varchar) as fiscal_year, cast(null as varchar) as jurisdiction_code, count(*) as n_rows from ${from(n)}`
        const yearExpr = hasYear ? 'fiscal_year' : 'cast(null as varchar)'
        const jurExpr = hasJurisdiction ? 'jurisdiction_code' : 'cast(null as varchar)'
        return `select ${i} as node, ${yearExpr} as fiscal_year, ${jurExpr} as jurisdiction_code, count(*) as n_rows
        from ${from(n)} group by 1, 2, 3`
      })
      .join('\nunion all\n'),
    ['node', 'n_rows'],
  )
  assertNoNullKeyRows(counts, (i) => (columnsOf.get(i) ?? new Set()).has('fiscal_year'), (i) => (columnsOf.get(i) ?? new Set()).has('jurisdiction_code'))

  // ノードごとに `counts` を走査すると ノード数 × 集計行数 になる。索引は先に1回だけ作る
  const idxOf = new Map(counted.map(([cid], i) => [cid, i]))
  const countsByNode = new Map<number, CountRow[]>()
  for (const c of counts) {
    const bucket = countsByNode.get(c.node)
    if (bucket) bucket.push(c)
    else countsByNode.set(c.node, [c])
  }

  const nodes: Node[] = models.map(([id, n]) => {
    const loc = n.config?.location
    const jurisdictionCode = jurisdictionOf(id, n.name)
    const nodeIdx = idxOf.get(id) ?? -1
    const cols = columnsOf.get(nodeIdx) ?? new Set<string>()
    const count = n.resource_type === 'source'
      ? ownCount(sourceRows(id, n.name, provenance), jurisdictionCode!)
      : tally(
          countsByNode.get(nodeIdx) ?? [],
          cols.has('fiscal_year'),
          cols.has('jurisdiction_code'),
          jurisdictionCode,
        )
    const stage = stageOf(n)
    return {
      id, label: n.name, kind: n.resource_type as Node['kind'], stage,
      rows: count?.total ?? null,
      rowsByJurisdiction: count?.byJurisdiction ?? null,
      // 団体の帰属はここで1回だけ id / 名前から決める。画面はこのフィールドで絞る
      jurisdictionCode,
      description: (n.description ?? '').trim(),
      introducesJudgment: introducesJudgment(n, stage),
      containsJudgment: false, // 下で上流から伝播させる
      artifact: loc ?? null,
    }
  })

  // 取得元。dbt は知らないので証跡から組む。id を「source ノードid + .origin」にしてあるのは
  // ローカル画面の行取り出し（apps/web/vite-plugins/local-data.ts）が同じ規約で引くため。
  // ⚠️ **抽出物（PDF から起こした表）にも取得元ノードを付ける。** CSV の団体と同じ
  // 「原典 → 取り込み」の形にしないと、PDF の団体だけ系統が1段浅い図になる。
  for (const src of nodes.filter((n) => n.kind === 'source')) {
    // ⚠️ **direction だけで引かない。** 2団体目からは `expenditure` という名前の
    // ソースが団体ごとにあり、direction だけで絞ると三鷹市の取得元ノードに
    // 狛江市の証跡が混ざる（`sourceRows` が同じ理由で団体コードを見ている）。
    const code = /\.raw_(\d{6})/.exec(src.id)?.[1]
    if (!code) continue
    const hit = provenanceForSource(src.id, src.label, provenance)
    if (!hit) continue
    const { ps, kind } = hit
    // ノードには見出しだけ出す。「※下水道事業会計除く」のような注記は
    // 詳細（title が正式名）と description に残る。
    // 複数年度あるときは先頭年の名前だけ出すと嘘になる（行数は全年度の合計）ので、範囲にする。
    // 名は正本の取り込みがリソース名、抽出物が文書名を持つ（resource_name を持たないため）。
    const years = [...new Set(ps.map((p) => p.fiscal_year))].sort()
    const base = (ps[0]!.resource_name ?? ps[0]!.document_title ?? src.label).split('※')[0]!.trim()
    const label = years.length > 1
      ? `${base.replace(/（\d{4}）$/, '').trim()}（${years[0]}〜${years.at(-1)}）`
      : base
    // 証跡は年度ごとに1件あるので、取得元も年度で切れる（切れないのは規則表だけ）。
    // 1団体ぶんを団体で引ける形へ包むのは `ownCount` と同じ処理なので、それを使う。
    // 抽出物は行数を持たないので、取得元ノードの「行数」は抽出した項目の数で代用する
    // （原典の内訳がその数だけある、という意味で）。
    const counted = kind === 'canonical'
      ? countByYear((ps as CanonicalFetch[]).map((p) => [p.fiscal_year, p.rows]))
      : countByYear(ps.map((p) => [p.fiscal_year, extractedCount(p, kind)]))
    const origin = ownCount(counted, code)!
    nodes.push({
      id: `${src.id}.origin`, label, kind: 'origin', stage: 'origin',
      jurisdictionCode: code,
      rows: origin.total,
      rowsByJurisdiction: origin.byJurisdiction,
      description: `${ps[0]!.request_url}${ps.length > 1 ? `\nほか ${ps.length - 1} リソース` : ''}\n取得: ${ps[0]!.fetched_at}`,
      introducesJudgment: false, containsJudgment: false, artifact: null,
    })
  }

  const edges = models.flatMap(([id, n]) =>
    (n.depends_on?.nodes ?? []).filter((d) => ids.has(d)).map((from) => ({ from, to: id, kind: 'flow' })))
  for (const n of nodes) if (n.kind === 'origin') edges.push({ from: n.id, to: n.id.replace(/\.origin$/, ''), kind: 'flow' })

  // **判断は下流へ伝播する。** COFOG を含む派生の配布物は、それ自身が規則を
  // 適用していなくても判断を含む。ここを伝播させないと、配布物が「判断なし」と
  // 表示され、正本と派生を分けている意味が画面から消える。
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const upstream = new Map<string, string[]>()
  for (const e of edges) upstream.set(e.to, [...(upstream.get(e.to) ?? []), e.from])
  const resolve = (id: string, seen = new Set<string>()): boolean => {
    const n = byId.get(id)
    if (!n || seen.has(id)) return false
    seen.add(id)
    return n.introducesJudgment || (upstream.get(id) ?? []).some((u) => resolve(u, seen))
  }
  for (const n of nodes) n.containsJudgment = resolve(n.id)

  const order = STAGES.map((s) => s.id)
  nodes.sort((a, b) => order.indexOf(a.stage) - order.indexOf(b.stage) || a.label.localeCompare(b.label))
  // **辺も並べる。** dbt の manifest はノードの順序が実行ごとに変わりうるので、
  // そのまま出すと中身が同じでも報告に差分が出る（CI の決定性検査がこれで落ちた）。
  edges.sort((a, b) => a.from.localeCompare(b.from) || a.to.localeCompare(b.to))
  assertRowSumsConsistent(nodes)
  return { stages: STAGES, nodes, edges, source: 'dbt/target/manifest.json（手書きではない）' }
}

/**
 * 検査とその紐づけを run_results.json から取る。
 * **どの検査がどのノードを守っているかも dbt が知っている**（test の depends_on）。
 * 以前は手で書いており、書き忘れても誰も気づかなかった。
 */
export function buildChecks(m: Manifest, r: RunResults): Check[] {
  const byId = new Map(r.results.map((x) => [x.unique_id, x]))
  const bindable = new Set([...Object.keys(m.nodes), ...Object.keys(m.sources)])
  return Object.entries(m.nodes)
    .filter(([, n]) => n.resource_type === 'test')
    .map(([id, n]) => {
      const res = byId.get(id)
      const status = res?.status ?? '未実行'
      const check: Check = {
        name: n.name,
        description: (n.description ?? '').trim(),
        explanation: checkExplanation(n),
        // マクロ等の依存はノードではないので落とす（画面が存在しないノードを引かないように）
        binds: (n.depends_on?.nodes ?? []).filter((b) => bindable.has(b)),
        ok: status === 'pass',
        // ⚠️ severity は宣言から読む。status から逆算すると、実行前・通過済みの
        // warn 検査が全部「失敗の検査」に見える
        severity: n.config?.severity === 'warn' ? 'warn' : 'error',
        status,
        failures: res?.failures ?? null,
        detail: checkDetail(res?.message ?? ''),
      }
      // 非 pass ではどの団体の行に当たったかを読み直して添える。
      // dbt の結果文（"Got N results"）は件数しか言わず、画面の「この団体の分か」には答えられない
      if (!check.ok && n.compiled_code) {
        check.attribution = attributeCheck(n.compiled_code)
      }
      return check
    })
    .sort((a, b) => Number(a.ok) - Number(b.ok) || a.name.localeCompare(b.name))
}

/**
 * 検査の説明。**`dbt/tests/*.sql` 冒頭のコメントをそのまま出す** —
 * その検査が何を見ているか・なぜあるかはそこに書いてある（書かせる場所にしている）。
 * generic test（schema.yml の unique / not_null 等）はコメントを持たないので
 * `test_metadata` から組み立てる。
 */
function checkExplanation(n: DbtNode): string {
  const out: string[] = []
  for (const line of (n.raw_code ?? '').split('\n')) {
    const t = line.trim()
    if (t.startsWith('--')) {
      out.push(t.replace(/^--\s?/, ''))
      continue
    }
    // 冒頭の jinja（config 宣言）と空行は説明ではないので読み飛ばす。
    // コメントを読み始めた後に SQL の行が来たら説明はそこで終わり
    if (out.length === 0 && (t === '' || t.startsWith('{{') || t.startsWith('{%'))) continue
    break
  }
  const text = out.join('\n').replace(/\*\*/g, '').trim()
  if (text) return text
  const tm = n.test_metadata
  const col = tm?.kwargs?.column_name
  const cols = tm?.kwargs?.combination_of_columns
  const target = (Array.isArray(cols) ? cols.join(' + ') : col) as string | undefined
  const label =
    tm?.name === 'unique' ? `${target ?? 'キー'} が重複しない` :
    tm?.name === 'not_null' ? `${target ?? '列'} が空でない` :
    tm?.name === 'accepted_values' ? `${target ?? '列'} が宣言された値のどれか` :
    tm?.name === 'relationships' ? `${target ?? '列'} が参照先に存在する` :
    tm?.name && target ? `${tm.name}: ${target}` : n.name
  return label
}

/**
 * dbt の結果文を画面の言葉にする。"Got 3 results, configured to warn if != 0" は
 * ツールの内部語なので「検出 3 件」とだけ言う（閾値の細部は severity が担う）。
 */
function checkDetail(message: string): string {
  const hit = /^Got (\d+) results?/.exec(message)
  return hit ? `検出 ${hit[1]} 件` : message
}

/** dbt コンパイル済み SQL の相対パスは dbt/ 基準なので、そこを cwd にして読み直す */
const DBT_CWD = join(ROOT, 'dbt')

/**
 * 非 pass の検査がどの団体の行に当たったかを、compiled SQL を読み直して確かめる。
 * 結果行が団体コードの列（`jurisdiction` / `jurisdiction_code`）を持てば団体ごとの
 * 件数まで言える。持たなければ全団体を束ねる検査なので「横断・対象特定不能」とだけ付ける
 * （どの団体の画面にも同じ警告が出るが、それはその団体の原典が原因とは限らない）。
 */
function attributeCheck(compiled: string): CheckAttribution | undefined {
  const inner = compiled.trim().replace(/;+\s*$/, '')
  try {
    const SAMPLE = 8
    const sample = q<Record<string, unknown>>(
      `select * from (\n${inner}\n) t limit ${SAMPLE}`, [], DBT_CWD,
    )
    // 列名は行のキーから取れる（json 出力は全列をキーに持つ）。行が0のときだけ
    // describe に頼る — それ以外で列の取得に問い合わせをもう1本立てない
    const columns = sample.length
      ? Object.keys(sample[0]!)
      : q<{ column_name: string }>(`describe select * from (\n${inner}\n) t`, [], DBT_CWD)
          .map((r) => r.column_name)
    const rows = sample.map((r) => columns.map((c) => (r[c] === undefined ? null : r[c]) as string | number | null))
    const jcol = columns.find((c) => c === 'jurisdiction_code' || c === 'jurisdiction')
    if (!jcol) return { kind: 'cross', columns, rows }
    const counts = Object.fromEntries(
      q<{ j: string; c: number }>(
        `select ${jcol} as j, count(*) as c from (\n${inner}\n) t group by 1 order by 2 desc`,
        ['c'], DBT_CWD,
      ).map((r) => [r.j, r.c]),
    )
    return { kind: 'jurisdiction', counts, columns, rows }
  } catch (e) {
    // 再実行に失敗しても帰属を欠くだけにする — 検査の失敗で報告の生成自体を止めない
    console.warn(`warn  検査の再実行に失敗: ${e instanceof Error ? e.message.split('\n')[0] : e}`)
    return undefined
  }
}

