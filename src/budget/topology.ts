/**
 * # パイプラインの形（topology）
 *
 * 段・ノード・辺を**実行結果から導く**。
 *
 * ## なぜ要るか
 *
 * 報告 JSON が持っていたのは「1団体・1年度・1回の実行の数値」だけで、
 * 「段がいくつあるか」「何が何に流れるか」「どの検査がどこを守るか」は入っていなかった。
 * その結果、画面側が段の名前と並びを直書きすることになり、
 * **パイプラインを変えても図が変わらない**状態になっていた。
 *
 * それは「実装と表示が食い違っても誰も気づかない」ということで、
 * ELT の全体像を把握する道具としては致命的である。だから形のほうをデータにする。
 *
 * ## 単位は行数ひとつに固定する
 *
 * 辺の太さに使うのは行数だけ。行数と金額を同じ図に混ぜると、
 * 太さが何を表しているのか読めなくなる。金額は別の図が持つ。
 */
import type { CanonicalTable } from './load'
import type { DerivedTable } from './transform'
import type { Direction } from './source'

export type StageId = 'extract' | 'load' | 'transform'

export type TopologyStage = {
  id: StageId
  label: string
  responsibility: string
  /** **やらないこと。** 段の境界は責務よりも、やらないことの側で決まる */
  excludes: string
  /** この段で fudoki の判断が入るか。ELT の切れ目はここで引いている */
  introducesJudgment: boolean
}

/**
 * 段の宣言。**ここが段の定義の唯一の出所**で、画面はこれを描くだけにする。
 * 責務と「やらないこと」は AGENTS.md のパイプライン節と同じ内容を持つ。
 *
 * ⚠️ **ELT という語の一般的な意味とはずれる。** 一般には Load が生のまま置き Transform で整形するが、
 * この PJ で守りたい境界は整形の有無ではなく**判断の有無**である。
 * だから標準（FDP）への正規化まで Load が持ち、Transform には判断だけが残る。
 * Load の出力（正本）が標準に適合していながら原文と突き合わせて検証できるのは、この切り方による。
 */
export const STAGES: TopologyStage[] = [
  {
    id: 'extract',
    label: 'Extract',
    responsibility: '取得元からの取得。レスポンスを無加工で保存し、取得 URL・HTTP status・SHA-256・取得時刻を添える',
    excludes: '解釈・整形・結合',
    introducesJudgment: false,
  },
  {
    id: 'load',
    label: 'Load',
    responsibility: '原典1行を1行のまま標準（FDP）の形へ。コードと名称の分離、単位の正規化、識別子の付与、列の意味づけ',
    excludes: 'fudoki の判断を足すこと（分類、名寄せ、推定）。階層を潰すこと',
    introducesJudgment: false,
  },
  {
    id: 'transform',
    label: 'Transform',
    responsibility: '判断が入る段。COFOG 写像、表記揺れの吸収',
    excludes: '取得',
    introducesJudgment: true,
  },
]

export type NodeKind = 'source' | 'canonical' | 'derived' | 'state'

export type TopologyNode = {
  id: string
  stage: StageId
  kind: NodeKind
  label: string
  /** 辺の太さの単位。ここだけが行数 */
  rows: number
  direction?: Direction
  /** 配布する成果物のパス。作業領域どまりのものは持たない */
  artifact?: string
  bytes?: number
  sha256?: string
  /** state ノードだけが持つ。分類の軸の値 */
  status?: string
}

export type TopologyEdge = {
  id: string
  from: string
  /** `null` は行き止まり。そこで流れが止まる理由を `note` に書く */
  to: string | null
  rows: number
  /** copy = 差分なしの写し / split = 分岐 / terminate = ここで止まる */
  kind: 'copy' | 'split' | 'terminate'
  note?: string
}

export type Topology = {
  stages: TopologyStage[]
  nodes: TopologyNode[]
  edges: TopologyEdge[]
  /** 検査が1つでも落ちたら成果物を書かない、という性質を画面へ渡す */
  writeGate: { blocksOnFailure: true; description: string }
}

/** ノード id。**verify と report の両方が参照する**ので、文字列を散らさずここに寄せる */
export const nodeId = {
  source: (d: Direction) => `source:${d}`,
  canonical: (d: Direction) => `canonical:${d}`,
  derived: (d: Direction) => `derived:${d}`,
  state: (status: string) => `state:${status}`,
} as const

const DIRECTION_JA: Record<Direction, string> = { expenditure: '歳出', revenue: '歳入' }
const STATUS_JA: Record<string, string> = {
  assigned: '割当済み',
  unclassifiable: '分類不能',
  'out-of-scope': '対象外',
}

/**
 * 実行結果から形を組み立てる。
 *
 * ノードも辺も、渡された表の実測値から作る。ここに数を直書きしない
 * （直書きすると、パイプラインが変わっても図が変わらない状態へ戻る）。
 */
export function buildTopology(args: {
  canonical: CanonicalTable[]
  derived: DerivedTable
  derivedDirection: Direction
  /** 配布パスの解決。正本と派生がどのファイルになるか */
  artifactOf: (kind: NodeKind, direction: Direction) => string | undefined
}): Topology {
  const { canonical, derived, derivedDirection, artifactOf } = args
  const nodes: TopologyNode[] = []
  const edges: TopologyEdge[] = []

  for (const t of canonical) {
    const d = t.direction
    const p = t.provenance
    nodes.push({
      id: nodeId.source(d),
      stage: 'extract',
      kind: 'source',
      label: `${DIRECTION_JA[d]} 原典`,
      rows: p.rows,
      direction: d,
      bytes: p.bytes,
      sha256: p.sha256,
    })
    nodes.push({
      id: nodeId.canonical(d),
      stage: 'load',
      kind: 'canonical',
      label: `${DIRECTION_JA[d]} 正本`,
      rows: t.rows.length,
      direction: d,
      artifact: artifactOf('canonical', d),
    })
    // 差分0が「太さが変わらない」として図に出る。ここが崩れたら一目で分かる
    edges.push({
      id: `extract:${d}`,
      from: nodeId.source(d),
      to: nodeId.canonical(d),
      rows: t.rows.length,
      kind: 'copy',
      note: t.rows.length === p.rows ? '差分 0' : `差分 ${t.rows.length - p.rows}`,
    })
  }

  nodes.push({
    id: nodeId.derived(derivedDirection),
    stage: 'transform',
    kind: 'derived',
    label: `${DIRECTION_JA[derivedDirection]} 派生（COFOG）`,
    rows: derived.rows.length,
    direction: derivedDirection,
    artifact: artifactOf('derived', derivedDirection),
  })
  edges.push({
    id: `transform:${derivedDirection}`,
    from: nodeId.canonical(derivedDirection),
    to: nodeId.derived(derivedDirection),
    rows: derived.rows.length,
    kind: 'copy',
  })

  // 分類の軸ごとの行数。派生の中身がどこへ割れたか
  const byStatus = new Map<string, number>()
  for (const r of derived.rows) {
    const s = String(r.cofog_status)
    byStatus.set(s, (byStatus.get(s) ?? 0) + 1)
  }
  for (const [status, rows] of [...byStatus].sort((a, b) => b[1] - a[1])) {
    nodes.push({
      id: nodeId.state(status),
      stage: 'transform',
      kind: 'state',
      label: STATUS_JA[status] ?? status,
      rows,
      status,
      direction: derivedDirection,
    })
    edges.push({
      id: `state:${status}`,
      from: nodeId.derived(derivedDirection),
      to: nodeId.state(status),
      rows,
      kind: 'split',
    })
  }

  // 派生を作らない direction は行き止まり。理由を持たせる
  for (const t of canonical) {
    if (t.direction === derivedDirection) continue
    edges.push({
      id: `terminate:${t.direction}`,
      from: nodeId.canonical(t.direction),
      to: null,
      rows: t.rows.length,
      kind: 'terminate',
      note: 'COFOG は支出の機能別分類なので歳入には使えない。歳入に分類軸は付けない',
    })
  }

  return {
    stages: STAGES,
    nodes,
    edges,
    writeGate: {
      blocksOnFailure: true,
      description: '検査が1つでも落ちたら成果物を書かずに異常終了する。欠落したまま合計が下がった正本を配らないため',
    },
  }
}
