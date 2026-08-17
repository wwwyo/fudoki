/**
 * ダッシュボードが読むデータの入口。
 *
 * **型はパイプライン本体から取る**（`@pipeline/report`）。ここで形を手で写すと、
 * `ReportData` のフィールド名を変えた瞬間に画面が黙って壊れる。
 * 実際、旧ビューアは素の JS で 26 箇所を読んでいて、その検査が一切効いていなかった。
 */
import type { ReportData } from '@pipeline/report'
import type { Topology, TopologyNode, TopologyEdge, StageId } from '@pipeline/topology'

export type { ReportData, Topology, TopologyNode, TopologyEdge, StageId }

/** 列指向で運ぶ。行ごとにキーを繰り返すと、ファイルの大半が列名になる */
export type ColumnarTable = { columns: string[]; rows: string[][] }

export type PipelineData = {
  code: string
  year: string
  report: ReportData
  expenditure: ColumnarTable
  revenue: ColumnarTable
}

/** 明細の1行。列は生成側（scripts/build-pipeline-view.ts）が決める */
export type DetailRow = Record<string, string>

export function toRows(t: ColumnarTable): DetailRow[] {
  return t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i] ?? ''])))
}

/**
 * 生成物を取りに行く。`bun run dev` は build:pipeline-view を回してから Vite を上げるので、
 * キャッシュされた古い数字を掴まないようにする。
 * 直したのに古い値が出たままだと、直ったかどうかの判断そのものができない。
 */
export async function loadPipeline(): Promise<PipelineData> {
  const res = await fetch(`${import.meta.env.BASE_URL}pipeline.json`, { cache: 'no-store' })
  if (!res.ok) {
    throw new Error(
      `pipeline.json を読めません（HTTP ${res.status}）。` +
        `bun run build:budget のあと bun run build:pipeline-view を回してください`,
    )
  }
  return (await res.json()) as PipelineData
}

export const yen = (v: number | string) => Number(v).toLocaleString('ja-JP')

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
}

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
