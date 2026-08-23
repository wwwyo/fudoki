/**
 * パイプラインの流れ図。**実際に線を引く。**
 *
 * 系統は dbt の `manifest.json` から来る。段の名前も並びもノードの依存もここには持たない。
 *
 * ## なぜ SVG で描くか
 *
 * 前はカードを4列に並べただけで、辺を1本も描いていなかった。
 * ノードに名前・行数・成果物・検査を全部載せていたので、**文字の表にしか見えず
 * 「何がどこへ流れるか」が読めなかった**。
 * ノードは名前と行数だけにして、依存は線で見せ、詳細は選んだときに出す。
 */
import { useMemo, useState } from 'react'
import type { Node, ReportData, Topology } from '@/lib/pipeline'
import { STAGE_ORDER, checksByNode, yen } from '@/lib/pipeline'
import { Info } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { NodePreviewPanel } from '@/components/node-preview'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

type Props = { topology: Topology; report: ReportData; onSelectNode?: (id: string | null) => void; selected: string | null }

const COL_W = 210
const COL_GAP = 78
const NODE_H = 46
const NODE_GAP = 14
/** focus ring がはみ出す分の余白。入れないと端のノードで ring が切れる */
const PAD = 8

const KIND_JA: Record<Node['kind'], string> = { origin: '取得元', source: '原典', model: 'モデル', seed: '規則表' }

/**
 * ノード幅に収まるよう表示幅で切り詰める。**文字数で切ると全角で突き抜ける**
 * （取得元ノードのリソース名は全角で、26文字 ≒ 300px になりノードを越えた）。
 * 全角を2、半角を1と数える。上限はノード幅 210px・フォント 11.5px からの実測値
 */
function fitLabel(label: string, maxUnits = 31): string {
  let units = 0
  for (let i = 0; i < label.length; i++) {
    units += label.charCodeAt(i) > 0xff ? 2 : 1
    if (units > maxUnits) return `${label.slice(0, i)}…`
  }
  return label
}

export function FlowGraph({ topology, report, onSelectNode, selected }: Props) {
  const [hover, setHover] = useState<string | null>(null)
  const checks = checksByNode(report)

  /** 段が列、段の中の並びが行。位置はここで決まるので、辺は座標を引くだけでよい */
  const layout = useMemo(() => {
    const pos = new Map<string, { x: number; y: number; node: Node }>()
    STAGE_ORDER.forEach((sid, col) => {
      topology.nodes
        .filter((n) => n.stage === sid)
        .forEach((n, row) => {
          pos.set(n.id, { x: PAD + col * (COL_W + COL_GAP), y: PAD + row * (NODE_H + NODE_GAP), node: n })
        })
    })
    const rows = Math.max(...STAGE_ORDER.map((s) => topology.nodes.filter((n) => n.stage === s).length))
    return {
      pos,
      width: PAD * 2 + STAGE_ORDER.length * COL_W + (STAGE_ORDER.length - 1) * COL_GAP,
      height: PAD * 2 + rows * (NODE_H + NODE_GAP),
    }
  }, [topology])

  const active = selected ?? hover
  /** 選んだノードに繋がる辺だけを強調する。12本を同じ濃さで描くと結局読めない */
  const related = useMemo(() => {
    if (!active) return null
    const s = new Set<string>([active])
    for (const e of topology.edges) {
      if (e.from === active) s.add(e.to)
      if (e.to === active) s.add(e.from)
    }
    return s
  }, [active, topology.edges])

  const detail = selected ? layout.pos.get(selected)?.node : null

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        {/* 段の見出しは HTML で出す。SVG の中だと tooltip を素直に置けない。
            列幅を SVG と揃えるため、どちらも固定幅で横スクロールさせる */}
        <div
          className="grid pb-2"
          style={{
            width: layout.width,
            paddingLeft: PAD,
            gridTemplateColumns: `repeat(${STAGE_ORDER.length}, ${COL_W}px)`,
            columnGap: COL_GAP,
          }}
        >
          {STAGE_ORDER.map((sid, col) => {
            const stage = topology.stages.find((s) => s.id === sid)
            return (
              <div key={sid} className="flex items-center gap-1.5">
                {/* 取得元が 0。fudoki のパイプラインは 1 から始まる */}
                <span className="text-xs text-muted-foreground tabular-nums">{col}</span>
                <span className="text-[13px] font-medium">{stage?.label}</span>
                <Tooltip>
                  <TooltipTrigger
                    className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 rounded-full focus-visible:ring-[3px] focus-visible:outline-none"
                    aria-label={`${stage?.label} の説明`}
                  >
                    <Info aria-hidden className="size-3.5" />
                  </TooltipTrigger>
                  <TooltipContent className="max-w-[36ch]">{stage?.responsibility}</TooltipContent>
                </Tooltip>
              </div>
            )
          })}
        </div>
        <svg
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          role="img"
          aria-label={`パイプラインの依存グラフ。${topology.nodes.length} ノード、${topology.edges.length} 辺`}
        >
          <defs>
            <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" fill="currentColor" />
            </marker>
          </defs>

          {/* 辺。ベジェで引く */}
          <g className="text-muted-foreground">
            {topology.edges.map((e, i) => {
              const a = layout.pos.get(e.from)
              const b = layout.pos.get(e.to)
              if (!a || !b) return null
              const x1 = a.x + COL_W
              const y1 = a.y + NODE_H / 2
              const x2 = b.x - 6
              const y2 = b.y + NODE_H / 2
              const dim = related ? !(related.has(e.from) && related.has(e.to)) : false
              return (
                <path
                  key={i}
                  d={`M${x1},${y1} C${x1 + COL_GAP * 0.55},${y1} ${x2 - COL_GAP * 0.55},${y2} ${x2},${y2}`}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={dim ? 1 : related ? 2.2 : 1.6}
                  opacity={dim ? 0.12 : related ? 0.85 : 0.55}
                  markerEnd="url(#arrow)"
                />
              )
            })}
          </g>

          {/* ノード。名前と行数だけ。詳細は選んだときに下へ出す */}
          {[...layout.pos.values()].map(({ x, y, node }) => {
            const cs = checks.get(node.id) ?? []
            const failed = cs.filter((c) => !c.ok && c.severity === 'error').length
            const warned = cs.filter((c) => !c.ok && c.severity === 'warn').length
            const dim = related ? !related.has(node.id) : false
            const focused = active === node.id
            // **「含む」で色を塗る。** 派生の配布物はそれ自身が規則を適用していなくても
            // 判断を含む。持ち込むかどうかで塗ると、配布物が「判断なし」に見える。
            const on = node.containsJudgment
            const accent = on ? 'var(--color-stage-judgment)' : 'var(--color-stage-nojudgment)'
            // 色が何を言っているかは凡例を置かず、hover と選択で文字にして読ませる
            const hint = [
              on ? 'fudoki の判断を含む' : '判断を含まない（原典と突き合わせて検証できる）',
              cs.length > 0 ? `このノードを守っている検査 ${cs.length} 件` : null,
            ].filter(Boolean).join(' / ')
            return (
              <g
                key={node.id}
                transform={`translate(${x}, ${y})`}
                opacity={dim ? 0.3 : 1}
                onMouseEnter={() => setHover(node.id)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelectNode?.(selected === node.id ? null : node.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelectNode?.(selected === node.id ? null : node.id)
                  }
                }}
                onFocus={() => setHover(node.id)}
                onBlur={() => setHover(null)}
                tabIndex={0}
                role="button"
                aria-pressed={selected === node.id}
                aria-label={`${node.label} — ${hint}`}
                className="cursor-pointer focus:outline-none"
              >
                <title>{`${node.label} — ${hint}`}</title>
                <rect
                  width={COL_W} height={NODE_H} rx={7}
                  className="fill-card"
                  stroke={on ? 'var(--color-stage-judgment)' : 'var(--color-border)'}
                  strokeWidth={1.2}
                />
                {/* 選択は focus ring で示す。ノード自体の太さや色を変えると、
                    その太さ・色が持っている意味（判断を含むか）と混ざる。
                    間隔と太さは shadcn の ring-offset-2 / ring-[3px] に合わせる */}
                {focused && (
                  <rect
                    x={-5} y={-5} width={COL_W + 10} height={NODE_H + 10} rx={11}
                    fill="none" stroke="var(--color-ring)" strokeWidth={3}
                  />
                )}
                <rect width={4} height={NODE_H} rx={2} fill={accent} />
                <text x={16} y={19} className="fill-foreground text-[11.5px] font-medium">
                  {fitLabel(node.label)}
                </text>
                <text x={16} y={35} className="fill-muted-foreground text-[11px] tabular-nums">
                  {node.rows === null ? '—' : yen(node.rows)} 行 · {KIND_JA[node.kind]}
                </text>
                {cs.length > 0 && (
                  <>
                    <circle
                      cx={COL_W - 16} cy={NODE_H / 2} r={7}
                      fill={failed ? 'var(--color-destructive)' : warned ? 'var(--color-status-unclassifiable)' : 'var(--color-chart-2)'}
                      opacity={0.9}
                    />
                    <text x={COL_W - 16} y={NODE_H / 2 + 3.5} textAnchor="middle" className="fill-background text-[9px] font-semibold">
                      {cs.length}
                    </text>
                  </>
                )}
              </g>
            )
          })}
        </svg>
      </div>

      {/* 選んだノードの中身。ノード上に置くと図が文字の表に戻る */}
      {detail && (
        <div className="rounded-lg border bg-muted/30 p-3 text-sm">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-mono font-medium">{detail.label}</span>
            <Badge variant="outline">{KIND_JA[detail.kind]}</Badge>
            <Badge variant={detail.containsJudgment ? 'destructive' : 'secondary'}>
              {detail.containsJudgment ? '判断を含む' : '判断を含まない'}
            </Badge>
            {detail.introducesJudgment && <Badge variant="outline">ここで判断が入る</Badge>}
            {detail.artifact && (
              <code className="text-[11px] text-muted-foreground">{detail.artifact.replace('../data/', 'data/')}</code>
            )}
          </div>
          {detail.description && (
            <p className="mt-1.5 max-w-[80ch] whitespace-pre-line text-muted-foreground">{detail.description}</p>
          )}
          <NodePreviewPanel nodeId={detail.id} topology={topology} />
        </div>
      )}
    </div>
  )
}
