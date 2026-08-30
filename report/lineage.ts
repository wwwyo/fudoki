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
import type { Check, Node, ProjectNamesExtract, Provenance, Stage, Topology } from './common'

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
function sourceRows(id: string, name: string, provenance: Provenance[]): number | null {
  const code = /\.raw_(\d{6})/.exec(id)?.[1]
  if (!code) throw new Error(`ソース ${id} の名前から団体コードを取れない（raw_<団体コード> の形にすること）`)
  const mine = provenance.filter((p) => p.jurisdiction_code === code)
  // ⚠️ **証跡の形が取得元で違う。** 正本の取り込み（CSV でも事項別明細書の PDF でも）は
  // direction ごとに `rows` を持つが、既収録の団体で欠けている名称を補う抽出物
  // （事業名）は direction を持たず、抽出の要約（`extracted.projects`）しか持たない。
  // ⚠️ **要約の形は抽出器で違う**ので、どちらの抽出器かを `extractedKindOf` で判別する
  // （形で見分けると、項目が増えたときに黙って別の枝へ落ちる）。
  const byDirection = mine.filter((p) => p.direction === name)
  if (byDirection.length > 0) return byDirection.reduce((s, p) => s + p.rows, 0)
  const extracted = mine.filter((p) => extractedKindOf(p) === 'project-names')
  return extracted.length === 0
    ? null
    : extracted.reduce((s, p) => s + (p.extracted as ProjectNamesExtract).projects, 0)
}

export function buildTopology(m: Manifest, provenance: Provenance[]): Topology {
  const all = { ...m.nodes, ...m.sources }
  const models = Object.entries(all).filter(([, n]) => ['model', 'source', 'seed'].includes(n.resource_type))
  const ids = new Set(models.map(([id]) => id))

  // **行数は1クエリでまとめて数える。** ノードごとに投げると DuckDB CLI の
  // プロセス起動が13回になり、その大半が同じ warehouse を開き直すのに消える。
  // 原典（source）は DuckDB にテーブルとして存在しないので証跡から取る。
  const counted = models.filter(([, n]) => n.resource_type !== 'source')
  const rowCounts = new Map<string, number>(
    counted.length === 0 ? [] :
      Object.entries(
        q<Record<string, number>>(
          `select ${counted
            .map(([, n], i) => {
              const loc = n.config?.location
              // package 段は外部ファイルとして書き出される。DuckDB のビューは dbt の
              // 作業ディレクトリ基準の相対パスなので、実ファイルを直接数える。
              const from = loc
                ? `read_csv('${join(ROOT, 'dbt', loc)}', header = true, all_varchar = true)`
                : `"${n.name}"`
              return `(select count(*) from ${from}) n${i}`
            })
            .join(', ')}`,
          counted.map((_, i) => `n${i}`),
        )[0] ?? {},
      ).map(([k, v]) => [counted[Number(k.slice(1))]![0], v]),
  )

  const nodes: Node[] = models.map(([id, n]) => {
    const loc = n.config?.location
    const rows = n.resource_type === 'source'
      ? sourceRows(id, n.name, provenance)
      : rowCounts.get(id) ?? null
    const stage = stageOf(n)
    return {
      id, label: n.name, kind: n.resource_type as Node['kind'], stage, rows,
      // 団体の帰属はここで1回だけ id / 名前から決める。画面はこのフィールドで絞る
      jurisdictionCode: /\.raw_(\d{6})/.exec(id)?.[1] ?? /_(\d{6})__/.exec(n.name)?.[1] ?? null,
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
    const ps = provenance.filter((p) => p.jurisdiction_code === code && p.direction === src.label)
    if (ps.length === 0) continue
    // ノードには見出しだけ出す。「※下水道事業会計除く」のような注記は
    // 選んだときのプレビュー（title が正式名）と description に残る。
    // 複数年度あるときは先頭年の名前だけ出すと嘘になる（行数は全年度の合計）ので、範囲にする
    const years = [...new Set(ps.map((p) => p.fiscal_year))].sort()
    const base = ps[0]!.resource_name.split('※')[0]!.trim()
    const label = years.length > 1
      ? `${base.replace(/（\d{4}）$/, '').trim()}（${years[0]}〜${years.at(-1)}）`
      : base
    nodes.push({
      id: `${src.id}.origin`, label, kind: 'origin', stage: 'origin',
      jurisdictionCode: code ?? null,
      rows: ps.reduce((s, p) => s + p.rows, 0),
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

