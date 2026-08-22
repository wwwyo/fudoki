/**
 * ダッシュボードが読むデータの入口。
 *
 * **型の正本は `report/schema.ts`。** 生成側（`report/build.ts`）と画面が同じ型を見るので、
 * 食い違いはコンパイラが捕まえる。型を2箇所で宣言すると、
 * 生成側のキーを変えた瞬間に画面が黙って壊れる（実際にその状態を作った）。
 */
import type { ReportData, Topology, Node, Edge, Stage, Check } from '@report/schema'

export type { ReportData, Topology, Node, Edge, Stage, Check }

/** 列指向で運ぶ。行ごとにキーを繰り返すと、ファイルの大半が列名になる */
export type ColumnarTable = { columns: string[]; rows: string[][] }

export type PipelineData = {
  code: string
  report: ReportData
  expenditure: ColumnarTable
  revenue: ColumnarTable
}

/** 明細の1行。列は配布する CSV のヘッダがそのまま決める */
export type DetailRow = Record<string, string>

export function toRows(t: ColumnarTable): DetailRow[] {
  return t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i] ?? ''])))
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
        `cd dbt && dbt build のあと uv run python -m report.build を回してください`,
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
  // 歳入。COFOG は支出の機能別分類なので分類の軸そのものが無い。
  // 「分類できなかった」と混ぜないために別の状態にしてある。
  'not-applicable': '分類の軸なし',
}

/** 段ごとの並び順。dbt の置き場が段を決めるので、画面はこの順に並べるだけ */
export const STAGE_ORDER: Stage['id'][] = ['ingestion', 'staging', 'core', 'package']

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
