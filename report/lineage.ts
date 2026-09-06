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
import { readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { extractedKindOf } from './common'
import type { Check, Node, ProjectNamesExtract, Provenance, RevenueAccountsExtract, Stage, Topology } from './common'

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
export function q<T = Record<string, unknown>>(sql: string, nums: string[] = []): T[] {
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
  config?: { location?: string }; depends_on?: { nodes?: string[] }
  meta?: { role?: 'judgment-rule' | 'external-reference' }
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
 */
/**
 * その証跡が「正本の取り込み」か。取得元ノードと source ノードの行数はこれだけを足す。
 *
 * ⚠️ **direction では見分けられない。** 名称を補う抽出物のうち revenue-accounts は
 * direction を名乗るので、混ざると rows を持たない値が合算に入り NaN になる
 * （狛江市の取得元が空欄で出ていた）。
 * ⚠️ **`extractedKindOf` でも見分けられない。** 事項別明細書 PDF を原典とする団体
 * （千代田区・昭島市）は正本そのものが extracted を持つので、一緒に落ちる。
 * 見分けるのは `rows` の有無 — 正本の取り込みは CSV でも PDF でも必ず行数を持ち、
 * 名称の抽出物は持たない。
 */
function isCanonicalFetch(p: Provenance, direction: string): boolean {
  if (p.direction !== direction) return false
  if (Number.isFinite(p.rows)) return true
  // 捨てる前に、正本らしいのに行数だけ無いものを止める。黙って落とすと
  // 取得元の行数が実際より小さくなり、しかもそれが画面から分からない。
  if (p.resource_name) {
    throw new Error(`${p.jurisdiction_code} の証跡「${p.resource_name}」に rows が無い（${p.fiscal_year}年度）`)
  }
  return false
}

function sourceRows(id: string, name: string, provenance: Provenance[]): Counted | null {
  const code = /\.raw_(\d{6})/.exec(id)?.[1]
  if (!code) throw new Error(`ソース ${id} の名前から団体コードを取れない（raw_<団体コード> の形にすること）`)
  const mine = provenance.filter((p) => p.jurisdiction_code === code)
  // ⚠️ **証跡の形が取得元で違う。** 正本の取り込み（CSV でも事項別明細書の PDF でも）は
  // direction ごとに `rows` を持つが、既収録の団体で欠けている名称を補う抽出物は
  // `rows` を持たず、抽出の要約しか持たない。direction の有無は抽出器によって割れる。
  // ⚠️ **要約の形は抽出器で違う**ので、どちらの抽出器かを `extractedKindOf` で判別する
  // （形で見分けると、項目が増えたときに黙って別の枝へ落ちる）。
  const byDirection = mine.filter((p) => isCanonicalFetch(p, name))
  if (byDirection.length > 0) return countByYear(byDirection.map((p) => [p.fiscal_year, p.rows]))
  // ⚠️ **どの抽出物かは id で決める。** 団体の証跡から抽出物を種類で拾うだけだと、
  // 同じ団体に2つの抽出器があるとき（狛江市の事業名と歳入の科目名称）両方の
  // ソースノードが同じ数字を出す。
  const kind = /\.raw_\d{6}_project_names\./.test(id)
    ? 'project-names'
    : /\.raw_\d{6}_revenue_accounts\./.test(id)
      ? 'revenue-accounts'
      : null
  if (kind === null) return null
  const extracted = mine.filter((p) => extractedKindOf(p) === kind)
  if (extracted.length === 0) return null
  // 抽出器ごとに「何を数えたか」が違う。事業名は事業の数、歳入の科目名称は目の数
  return countByYear(
    extracted.map((p) => [
      p.fiscal_year,
      kind === 'project-names'
        ? (p.extracted as ProjectNamesExtract).projects
        : (p.extracted as RevenueAccountsExtract).moku,
    ]),
  )
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
 * ⚠️ **行数は実データで取れないことがある**（132195 の一部の source/origin。
 * 証跡の `rows` 自体が欠けている取得元と、行数を持つ取得元が同じ direction を
 * 名乗って両方拾われ、`undefined + number` が `NaN` になる）。
 * `NaN` を 0 として足すと（JS の `+` は `null` を 0 に変換するが `NaN` は伝播する）
 * 比較が必ず不一致になり、逆に見なかったことにすると本当の不一致まで見逃す。
 * ここでは「取れていない」を型どおり null 扱いし、`Number.isFinite` で
 * 比較できる（全員が実数の）組だけを見る。
 */
export function assertRowSumsConsistent(nodes: Node[]): void {
  for (const n of nodes) {
    if (n.rowsByJurisdiction === null) continue
    const perJurisdiction = Object.values(n.rowsByJurisdiction)
    if (Number.isFinite(n.rows) && perJurisdiction.every((v) => Number.isFinite(v.total))) {
      const sum = perJurisdiction.reduce((s, v) => s + v.total, 0)
      if (sum !== n.rows) throw new Error(`${n.id}: rows(${n.rows}) !== Σ(rowsByJurisdiction の total)(${sum})`)
    }
    for (const v of perJurisdiction) {
      if (v.byYear === null || !Number.isFinite(v.total)) continue
      const years = Object.values(v.byYear)
      if (years.every((y) => Number.isFinite(y))) {
        const sum = years.reduce((s, y) => s + y, 0)
        if (sum !== v.total) throw new Error(`${n.id}: total(${v.total}) !== Σ(byYear)(${sum})`)
      }
    }
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
  // プレビュー（apps/web/public/preview/<id>.json）が同じ規約で書かれるため
  for (const src of nodes.filter((n) => n.kind === 'source')) {
    // ⚠️ **direction だけで引かない。** 2団体目からは `expenditure` という名前の
    // ソースが団体ごとにあり、direction だけで絞ると三鷹市の取得元ノードに
    // 狛江市の証跡が混ざる（`sourceRows` が同じ理由で団体コードを見ている）。
    const code = /\.raw_(\d{6})/.exec(src.id)?.[1]
    if (!code) continue
    const ps = provenance.filter((p) => p.jurisdiction_code === code && isCanonicalFetch(p, src.label))
    if (ps.length === 0) continue
    // ノードには見出しだけ出す。「※下水道事業会計除く」のような注記は
    // 選んだときのプレビュー（title が正式名）と description に残る。
    // 複数年度あるときは先頭年の名前だけ出すと嘘になる（行数は全年度の合計）ので、範囲にする
    const years = [...new Set(ps.map((p) => p.fiscal_year))].sort()
    const base = ps[0]!.resource_name.split('※')[0]!.trim()
    const label = years.length > 1
      ? `${base.replace(/（\d{4}）$/, '').trim()}（${years[0]}〜${years.at(-1)}）`
      : base
    // 証跡は年度ごとに1件あるので、取得元も年度で切れる（切れないのは規則表だけ）。
    // 1団体ぶんを団体で引ける形へ包むのは `ownCount` と同じ処理なので、それを使う
    const origin = ownCount(countByYear(ps.map((p) => [p.fiscal_year, p.rows])), code)!
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

