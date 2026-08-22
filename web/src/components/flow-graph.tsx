/**
 * パイプラインの流れ図。node と edge で組む。
 *
 * **系統は dbt の `manifest.json` から来る。** 段の名前も並びもノードの依存も
 * ここには持たない。以前は `topology.ts` が宣言しており、パイプラインを変えても
 * 図が変わらない状態を2度作った。いまはモデルの置き場が段を決めるので、
 * ディレクトリを動かせば図も動く。
 *
 * 列が段、列の中のカードがノード。**判断が入る段（core）だけ枠の色を変える** —
 * この図で一番伝えたいのは「どこから先が fudoki の言い分か」なので。
 */
import { Fragment } from 'react'
import type { Node, ReportData, Stage, Topology } from '@/lib/pipeline'
import { STAGE_ORDER, checksByNode, yen } from '@/lib/pipeline'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

type Props = { topology: Topology; report: ReportData; onSelectNode?: (id: string | null) => void; selected: string | null }

const KIND_JA: Record<Node['kind'], string> = { source: '原典', model: 'モデル', seed: '規則表' }

function NodeCard({
  node, checks, active, onClick,
}: { node: Node; checks: ReportData['checks']; active: boolean; onClick: () => void }) {
  const failed = checks.filter((c) => !c.ok && c.severity === 'error').length
  const warned = checks.filter((c) => c.severity === 'warn' && !c.ok).length
  const judged = node.introducesJudgment
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={node.description || undefined}
      className={cn(
        'w-full rounded-lg border bg-card p-2.5 text-left transition-colors hover:border-foreground/30',
        judged && 'border-[var(--color-stage-judgment)]/60',
        active && 'ring-2 ring-offset-1',
      )}
    >
      <span className="flex items-center gap-1.5">
        <i
          aria-hidden
          className="size-2 shrink-0 rounded-sm"
          style={{ background: judged ? 'var(--color-stage-judgment)' : 'var(--color-stage-nojudgment)' }}
        />
        <span className="truncate font-mono text-[11px] font-medium">{node.label}</span>
      </span>
      <span className="mt-1 flex items-baseline gap-1.5">
        <span className="text-base leading-none font-semibold tabular-nums">
          {node.rows === null ? '—' : yen(node.rows)}
        </span>
        <span className="text-[10px] text-muted-foreground">行 · {KIND_JA[node.kind]}</span>
      </span>
      {node.artifact && (
        <span className="mt-1 block truncate font-mono text-[10px] text-muted-foreground">
          {node.artifact.replace('../data/', '')}
        </span>
      )}
      {checks.length > 0 && (
        <span className="mt-1.5 block">
          <Badge variant={failed ? 'destructive' : warned ? 'outline' : 'secondary'} className="text-[10px]">
            検査 {checks.length - failed - warned}/{checks.length}
          </Badge>
        </span>
      )}
    </button>
  )
}

export function FlowGraph({ topology, report, onSelectNode, selected }: Props) {
  const checks = checksByNode(report)
  const stageOf = (id: Stage['id']) => topology.stages.find((s) => s.id === id)
  const select = (id: string) => onSelectNode?.(selected === id ? null : id)

  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-4">
        {STAGE_ORDER.map((sid, i) => {
          const stage = stageOf(sid)
          const nodes = topology.nodes.filter((n) => n.stage === sid)
          return (
            <Fragment key={sid}>
              <section className="flex flex-col gap-2">
                <header className="flex flex-col gap-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-muted-foreground tabular-nums">{i + 1}</span>
                    <h3 className="text-sm font-medium">{stage?.label}</h3>
                    {stage?.introducesJudgment && (
                      <span
                        className="rounded-sm px-1 py-0.5 text-[10px]"
                        style={{
                          background: 'color-mix(in oklab, var(--color-judgment-boundary) 18%, transparent)',
                          color: 'var(--color-judgment-boundary)',
                        }}
                      >
                        ここから判断
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] leading-tight text-muted-foreground">{stage?.responsibility}</p>
                  <p className="text-[11px] leading-tight text-muted-foreground">
                    <span className="font-medium text-foreground">やらないこと</span>: {stage?.excludes}
                  </p>
                </header>
                <div className="flex flex-col gap-1.5">
                  {nodes.map((n) => (
                    <NodeCard
                      key={n.id}
                      node={n}
                      checks={checks.get(n.id) ?? []}
                      active={selected === n.id}
                      onClick={() => select(n.id)}
                    />
                  ))}
                </div>
              </section>
            </Fragment>
          )
        })}
      </div>
      <p className="text-[11px] text-muted-foreground">
        系統の出所: <code>{topology.source}</code> ／ ノード {topology.nodes.length} · 辺 {topology.edges.length}。
        ノードを選ぶと、その段を守っている検査だけに絞れる。
      </p>
    </div>
  )
}
