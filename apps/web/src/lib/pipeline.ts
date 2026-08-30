/**
 * ダッシュボードが読むデータの入口。
 *
 * **型の正本は `report/schema.ts`。** 生成側（`report/build.ts`）と画面が同じ型を見るので、
 * 食い違いはコンパイラが捕まえる。型を2箇所で宣言すると、
 * 生成側のキーを変えた瞬間に画面が黙って壊れる（実際にその状態を作った）。
 */
import type { CofogCode, ReportData, Topology, Node, Edge, Stage, Check, NodePreview } from '@fudoki/report/budget/schema'
import type { Direction, DetailRow, DetailTable, Level } from '@fudoki/report/budget/detail'

export type { CofogCode, ReportData, Topology, Node, Edge, Stage, Check, NodePreview }

export type { Direction, DetailColumn, DetailRow, DetailTable, Level } from '@fudoki/report/budget/detail'
export { LEVEL_JA, basisOf, cell, divisionLabelOf, levelCell } from '@fudoki/report/budget/detail'
import { DIRECTIONS, expectedColumns } from '@fudoki/report/budget/detail'

/**
 * ⚠️ **複数団体を運ぶ。**
 * 単一団体の形（`{code, report}`）だった頃は、2団体目を足すと画面が黙って
 * 先頭だけを出す状態になりえた。並びは生成側が団体コード順に固定する。
 */
export type PipelineData = {
  jurisdictions: { code: string; report: ReportData }[]
}

/** 団体で変わらない部分。**団体の数だけ運ばない**ので、生成側が1つに畳んである */
type Shared = Pick<ReportData, 'topology' | 'checks' | 'portability' | 'customColumnTypes'>

/** ファイル上の形。読み込み時に `PipelineData` へ組み直す */
type PipelineFile = {
  shared: Shared
  jurisdictions: { code: string; report: Omit<ReportData, keyof Shared> }[]
}

/** 明細。**報告とは別ファイルで運ぶ** — 報告の 50 倍あり、既定のタブでは使わない */
export type DetailData = {
  expenditure: DetailTable
  revenue: DetailTable
}

/** 報告が渡した階層の並び。**画面は階層名を直書きしない**（団体ごとに違うため） */
export function levelsOf(report: ReportData, direction: Direction): Level[] {
  return report.detailLevels.find((d) => d.direction === direction)?.levels ?? []
}

/**
 * 明細を取りに行く。**明細タブを開いたときだけ**読む。
 * 報告（0.06MB）と一緒に運ぶと、報告しか見ない利用者にも 3.5MB を運ぶことになる。
 * 団体ごとに別ファイル（全団体を1つにすると、1団体だけ見る利用者に全部を運ぶ）。
 */
export async function loadDetail(report: ReportData): Promise<DetailData> {
  const code = report.meta.jurisdictionCode
  const [expenditure, revenue] = await Promise.all(
    DIRECTIONS.map(async (dir) => {
      const res = await fetch(`${import.meta.env.BASE_URL}detail-${code}-${dir}.json`, { cache: 'no-store' })
      if (!res.ok) throw new Error(`detail-${code}-${dir}.json を読めません（HTTP ${res.status}）`)
      const t = (await res.json()) as DetailTable
      const problems: string[] = []
      // ⚠️ **列だけ見ても足りない。** 割当の根拠は行に持たず規則表として1回だけ運んでいるので、
      // `ruleBasis` が欠けた古い明細を掴むと、**列検査を通ったまま根拠の表示だけ黙って空になる**。
      // 型は生成側と画面側に効くが、間に挟まる JSON には効かない — 境界で確かめる。
      if (!Array.isArray(t.columns)) problems.push('columns が配列でない')
      if (t.ruleBasis === null || typeof t.ruleBasis !== 'object') problems.push('ruleBasis が無い')
      problems.push(
        ...expectedColumns(levelsOf(report, dir))
          .filter((c) => !(t.columns as string[])?.includes(c))
          .map((c) => `列が無い: ${c}`),
      )
      if (problems.length > 0) {
        throw new Error(
          `detail-${code}-${dir}.json が宣言と食い違っています（${problems.join(' / ')}）。` +
            `bun run pipeline を回し直してください`,
        )
      }
      return t
    }),
  )
  return { expenditure: expenditure!, revenue: revenue! }
}

/** ノードの中身の先頭数行。**グラフでノードを選んだときだけ**取りに行く */
export async function loadNodePreview(id: string): Promise<NodePreview> {
  const res = await fetch(`${import.meta.env.BASE_URL}preview/${id}.json`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`preview/${id}.json を読めません（HTTP ${res.status}）。bun run report を回し直してください`)
  return (await res.json()) as NodePreview
}

/**
 * 列指向を行指向へ。**列名は `@fudoki/report/budget/detail` の宣言に縛られる** —
 * 宣言に無い列を読むとコンパイルが落ちる。
 * 以前は Record<string, string> だったので、配布物から列を落としても画面が黙って空になった。
 */
export function toRows(t: DetailTable): DetailRow[] {
  return t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i] ?? ''])) as DetailRow)
}

/**
 * 生成物を取りに行く。キャッシュされた古い数字を掴まないようにする。
 * 直したのに古い値が出たままだと、直ったかどうかの判断そのものができない。
 */
export async function loadPipeline(): Promise<PipelineData> {
  const res = await fetch(`${import.meta.env.BASE_URL}pipeline.json`, { cache: 'no-store' })
  if (!res.ok) {
    throw new Error(
      `pipeline.json を読めません（HTTP ${res.status}）。` +
        `bun run pipeline を回してください`,
    )
  }
  const file = (await res.json()) as PipelineFile
  assertShape(file)
  // 団体で変わらない部分を各団体へ戻す。**下流は完全な ReportData だけを見る**ので、
  // 運び方（畳んであるか)を画面のあちこちが知らずに済む。
  return {
    jurisdictions: file.jurisdictions.map(({ code, report }) => ({
      code,
      report: { ...report, ...file.shared } as ReportData,
    })),
  }
}

/**
 * 読み込んだ JSON が宣言どおりかを**実行時に**確かめる。
 *
 * 型は生成側と画面側の両方に効くが、**間に挟まる JSON には効かない。**
 * 古い pipeline.json を掴むと、型が「ある」と言っている列が実際には無い状態になり、
 * 画面が黙って空になる（実際に一度そうなった）。
 * 型を信じるのではなく、境界で確かめて、ずれていたら理由を出して止める。
 */
function assertShape(d: PipelineFile): void {
  const problems: string[] = []
  if (!d.shared) problems.push('shared が無い（団体ごとに複製していた古い形かもしれません）')
  else {
    for (const k of ['topology', 'checks', 'portability', 'customColumnTypes'] as const) {
      if (d.shared[k] === undefined) problems.push(`shared.${k} が無い`)
    }
  }
  if (!Array.isArray(d.jurisdictions)) problems.push('jurisdictions が無い（1団体だけの古い形かもしれません）')
  else if (d.jurisdictions.length === 0) problems.push('jurisdictions が空')
  for (const j of d.jurisdictions ?? []) {
    if (j.code === undefined) problems.push('jurisdictions[].code が無い')
    if (!j.report) { problems.push(`${j.code}: report が無い`); continue }
    for (const k of ['meta', 'summary', 'ingestion', 'detailLevels', 'levels', 'transform'] as const) {
      if (j.report[k] === undefined) problems.push(`${j.code}: report.${k} が無い`)
    }
    // ⚠️ **transform の中まで見る。** COFOG の集計は生成側が持っていて画面は表示だけなので、
    // 古い pipeline.json を掴むと**型が「ある」と言っている節が実際には無い**まま画面が落ちる。
    // 到達粒度を足したときに実際にこの穴が開いた（transform があるかしか見ていなかった）。
    for (const k of ['byDivision', 'byCode', 'cofogReach', 'assigned', 'total'] as const) {
      if (j.report?.transform?.[k] === undefined) problems.push(`${j.code}: report.transform.${k} が無い`)
    }
  }
  if (problems.length > 0) {
    throw new Error(
      `pipeline.json が宣言と食い違っています。bun run pipeline を回し直してください。\n` +
        problems.map((p) => `  - ${p}`).join('\n'),
    )
  }
}

export const yen = (v: number | string) => Number(v).toLocaleString('ja-JP')

/** 割合（0〜1）の書式。**割り算は生成側が済ませてある** — ここでは桁の揃え方だけを1箇所で決める */
export const pct = (v: number) => `${(v * 100).toFixed(1)}%`

/** 円は桁が多い。俯瞰する場所では丸め、厳密な値は必ず併記する */
export function yenShort(v: number | string): string {
  const x = Number(v)
  if (Math.abs(x) >= 1e8) return `${(x / 1e8).toFixed(x >= 1e10 ? 0 : 1)}億円`
  if (Math.abs(x) >= 1e4) return `${Math.round(x / 1e4).toLocaleString('ja-JP')}万円`
  return `${yen(x)}円`
}

/** COFOG 1999 のディビジョン。色は識別の補助で、コードは必ず文字でも出す */
export const DIVISION_COLOR: Record<string, string> = {
  '01': 'oklch(62% 0.06 260)',
  '02': 'oklch(58% 0.06 300)',
  '03': 'oklch(58% 0.07 40)',
  '04': 'oklch(69% 0.10 80)',
  '05': 'oklch(64% 0.08 145)',
  '06': 'oklch(60% 0.06 65)',
  '07': 'oklch(63% 0.09 20)',
  '08': 'oklch(63% 0.07 295)',
  '09': 'oklch(60% 0.06 230)',
  '10': 'oklch(64% 0.05 355)',
}

export const STATUS_JA: Record<string, string> = {
  assigned: '割当済み',
  unclassifiable: '分類不能',
  'out-of-scope': '対象外',
  // 歳入。COFOG は支出の機能別分類なので分類の軸そのものが無い。
  // 「分類できなかった」と混ぜないために別の状態にしてある。
  'not-applicable': '分類の軸なし',
}

/** 段ごとの並び順。dbt の置き場が段を決めるので、画面はこの順に並べるだけ */
export const STAGE_ORDER: Stage['id'][] = ['origin', 'ingestion', 'staging', 'core', 'package']

/** 検査をノードごとに引けるようにする。「どの段の何を守っているか」で見せるため */
export function checksByNode(report: ReportData) {
  const m = new Map<string, ReportData['checks']>()
  for (const c of report.checks) {
    for (const b of c.binds) m.set(b, [...(m.get(b) ?? []), c])
  }
  return m
}

/** どのノードにも紐づかない検査。パッケージ全体に掛かるもの */
export function unboundChecks(report: ReportData) {
  return report.checks.filter((c) => c.binds.length === 0)
}
