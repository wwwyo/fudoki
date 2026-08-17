/**
 * パイプラインの流れ図。
 *
 * **`topology` を描くだけで、段の名前も並びもここに持たない。**
 * 旧ビューアは段を文字列で直書きしていたため、パイプラインを変えても図が変わらなかった。
 *
 * 帯の太さの単位は行数ひとつ。行数と金額を混ぜると、太さが何を表しているのか読めなくなる。
 */
import { useMemo, useState } from 'react'
import type { ReportData, Topology, TopologyNode } from '@/lib/pipeline'
import { STATUS_JA, checksByNode, yen } from '@/lib/pipeline'

/** 色は「fudoki の判断が入っているか」と「分類の状態」を言う。装飾ではない */
const STATUS_FILL: Record<string, string> = {
  assigned: 'var(--color-status-assigned)',
  unclassifiable: 'var(--color-status-unclassifiable)',
  'out-of-scope': 'var(--color-status-out-of-scope)',
}
const fillOf = (n: TopologyNode) =>
  n.kind === 'state' ? (STATUS_FILL[n.status ?? ''] ?? 'var(--color-stage-judgment)')
  : n.kind === 'derived' ? 'var(--color-stage-judgment)'
  : 'var(--color-stage-nojudgment)'
import { cn } from '@/lib/utils'

type Props = { topology: Topology; report: ReportData; onSelectNode?: (id: string | null) => void }

const STAGE_X: Record<string, number> = { extract: 0, load: 1, transform: 2 }
/** 状態ノードは transform の中でもう1列ぶん右へ置く。派生の内訳だと分かるように */
const isState = (n: TopologyNode) => n.kind === 'state'

export function FlowGraph({ topology, report, onSelectNode }: Props) {
  const [active, setActive] = useState<string | null>(null)
  const checks = useMemo(() => checksByNode(report), [report])

  const layout = useMemo(() => {
    const W = 1040
    const PAD = { top: 30, bottom: 34, left: 96, right: 176 }
    const NODE_W = 12
    const GAP = 16

    const columns: TopologyNode[][] = [[], [], [], []]
    for (const n of topology.nodes) {
      const col = isState(n) ? 3 : STAGE_X[n.stage]!
      columns[col]!.push(n)
    }

    // 高さは「1列に載る行数の最大」で決める。全列を同じ縮尺にしないと太さが比較できない
    const colTotal = columns.map((c) => c.reduce((s, n) => s + n.rows, 0))
    const maxRows = Math.max(...colTotal)
    const maxNodes = Math.max(...columns.map((c) => c.length))
    const H = 380
    const usable = H - PAD.top - PAD.bottom - GAP * (maxNodes - 1)
    const scale = usable / maxRows

    const innerW = W - PAD.left - PAD.right
    const xOf = (col: number) => PAD.left + (innerW / 3) * col

    const placed = new Map<string, { x: number; y: number; h: number; labelY: number }>()
    // 小さい帯はラベルが重なるので、ラベルだけ最小間隔まで押し下げて引き出し線で結ぶ。
    // 比率を曲げて読みやすくすると、図が嘘をつく側に倒れる
    const LABEL_GAP = 34
    columns.forEach((col, ci) => {
      let y = PAD.top
      let lastLabel = -Infinity
      for (const n of col) {
        const h = Math.max(1.5, n.rows * scale)
        const labelY = Math.max(y + 12, lastLabel + LABEL_GAP)
        lastLabel = labelY
        placed.set(n.id, { x: xOf(ci), y, h, labelY })
        y += h + GAP
      }
    })
    return { W, H, NODE_W, placed, xOf, PAD }
  }, [topology])

  const { W, H, NODE_W, placed } = layout
  const nodeById = useMemo(() => new Map(topology.nodes.map((n) => [n.id, n])), [topology])

  const select = (id: string | null) => {
    setActive(id)
    onSelectNode?.(id)
  }

  const ribbon = (x1: number, y1: number, x2: number, y2: number, t: number) => {
    const mx = (x1 + x2) / 2
    return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2} l0,${t} C${mx},${y2 + t} ${mx},${y1 + t} ${x1},${y1 + t} Z`
  }

  // 出入りの累積。1つのノードから複数へ割れるとき、帯を積み上げる
  const outOffset = new Map<string, number>()
  const inOffset = new Map<string, number>()

  const summary =
    `原典 ${yen(topology.nodes.filter((n) => n.kind === 'source').reduce((s, n) => s + n.rows, 0))} 行が正本へ移り、` +
    topology.edges
      .filter((e) => e.kind === 'split')
      .map((e) => `${nodeById.get(e.to!)?.label} ${yen(e.rows)} 行`)
      .join('、') +
    `へ分かれた。` +
    topology.edges.filter((e) => e.kind === 'terminate').map((e) => e.note).join('')

  return (
    <figure className="m-0">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={summary}
        className="hidden w-full md:block">
        {/* 判断の境界。Load と Transform のあいだに立つ */}
        {(() => {
          const load = topology.nodes.find((n) => n.stage === 'load')
          const tf = topology.nodes.find((n) => n.stage === 'transform' && !isState(n))
          if (!load || !tf) return null
          const bx = ((placed.get(load.id)!.x + NODE_W) + placed.get(tf.id)!.x) / 2
          return (
            <g>
              <line x1={bx} y1={8} x2={bx} y2={H - 18} stroke="var(--color-judgment-boundary)" strokeWidth={1.5} strokeDasharray="4 4" />
              <text x={bx + 6} y={14} className="fill-[var(--color-judgment-boundary)] text-[11px] font-semibold">ここから判断</text>
            </g>
          )
        })()}

        {topology.edges.map((e) => {
          const from = placed.get(e.from)
          const fromNode = nodeById.get(e.from)
          if (!from || !fromNode) return null
          const t = Math.max(1.5, e.rows * (from.h / fromNode.rows))
          const oy = outOffset.get(e.from) ?? 0
          outOffset.set(e.from, oy + t)

          if (e.kind === 'terminate' || !e.to) {
            const y = from.y + from.h / 2
            return (
              <g key={e.id}>
                <line x1={from.x + NODE_W} y1={y} x2={from.x + NODE_W + 54} y2={y}
                  stroke="currentColor" strokeWidth={1.5} strokeDasharray="3 3" className="text-border" />
                <text x={from.x + NODE_W + 60} y={y + 4} className="fill-muted-foreground text-[11px]">
                  行き止まり
                </text>
              </g>
            )
          }
          const to = placed.get(e.to)
          if (!to) return null
          const iy = inOffset.get(e.to) ?? 0
          inOffset.set(e.to, iy + t)
          const dim = active && active !== e.from && active !== e.to
          return (
            <path key={e.id} d={ribbon(from.x + NODE_W, from.y + oy, to.x, to.y + iy, t)}
              className={cn('transition-opacity', dim ? 'opacity-10' : 'opacity-40')}
              fill={fillOf(nodeById.get(e.to)!)} />
          )
        })}

        {topology.nodes.map((n) => {
          const p = placed.get(n.id)!
          const right = isState(n)
          const tx = right ? p.x + NODE_W + 10 : p.x - 10
          const anchor = right ? 'start' : 'end'
          const dim = active && active !== n.id
          const bound = checks.get(n.id) ?? []
          const failed = bound.filter((c) => !c.ok).length
          return (
            <g key={n.id} className={cn('cursor-pointer transition-opacity', dim && 'opacity-25')}
              onClick={() => select(active === n.id ? null : n.id)}>
              {Math.abs(p.labelY - (p.y + 12)) > 4 && (
                <line x1={p.x + NODE_W} y1={p.y + p.h / 2} x2={tx - 4} y2={p.labelY - 4}
                  stroke="currentColor" strokeWidth={1} className="text-border" />
              )}
              <rect x={p.x} y={p.y} width={NODE_W} height={p.h} rx={3}
                fill={fillOf(n)} />
              <text x={tx} y={p.labelY} textAnchor={anchor} className="fill-foreground text-[13px]">{n.label}</text>
              <text x={tx} y={p.labelY + 15} textAnchor={anchor} className="fill-muted-foreground text-[11px]">
                {yen(n.rows)} 行{bound.length > 0 && ` · 検査${bound.length}`}{failed > 0 && ` (${failed}失敗)`}
              </text>
            </g>
          )
        })}

        {topology.stages.map((s) => {
          const first = topology.nodes.find((n) => n.stage === s.id && !isState(n))
          if (!first) return null
          return (
            <text key={s.id} x={placed.get(first.id)!.x - 10} y={H - 6} textAnchor="end"
              className="fill-muted-foreground text-[11px] tracking-wider">
              {s.label}{s.introducesJudgment ? ' · 判断あり' : ''}
            </text>
          )
        })}
      </svg>

      {/* 狭い幅では図の文字が潰れるので、同じ数字を一覧で出す */}
      <ul className="grid gap-2 md:hidden">
        {topology.nodes.map((n) => (
          <li key={n.id} className="rounded-lg border bg-card p-3">
            <div className="text-xs tracking-wide text-muted-foreground">
              {topology.stages.find((s) => s.id === n.stage)?.label}
              {n.kind === 'state' && ` · ${STATUS_JA[n.status ?? ''] ?? ''}`}
            </div>
            <div className="font-medium">{n.label}</div>
            <div className="text-xs text-muted-foreground">{yen(n.rows)} 行</div>
          </li>
        ))}
      </ul>

      <figcaption className="mt-3 max-w-[68ch] text-xs leading-relaxed text-muted-foreground">{summary}</figcaption>
    </figure>
  )
}
