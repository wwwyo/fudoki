/**
 * パイプラインの流れ図。node と edge で組む。
 *
 * **`topology` を描くだけで、段の名前も並びもここに持たない。**
 * パイプラインを変えたら図が変わる状態を保つため。
 *
 * ## なぜ Sankey をやめたか
 *
 * 帯の太さという一番高価な視覚チャンネルが、ここではほぼ情報を運んでいなかった。
 * 原典から正本までは設計上ずっと差分0で太さが変わらず、Transform の分岐は
 * 5,586 : 22 : 5 なので比例させると細い側が見えない。
 * そのうえノードが幅 12px の棒で、名前も行数も棒の外に浮いていた。
 * 「ぱっと見て何が何か分からない」のはそのため。
 *
 * node に実体（名前、行数、成果物、検査の結果）を持たせ、
 * edge が「何がどれだけ流れたか」を言う形にした。
 */
import { Fragment, useState } from 'react'
import type { ReportData, Topology, TopologyNode } from '@/lib/pipeline'
import { STATUS_JA, checksByNode, yen } from '@/lib/pipeline'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

type Props = { topology: Topology; report: ReportData; onSelectNode?: (id: string | null) => void }

/** 色は「fudoki の判断が入っているか」と「分類の状態」を言う。装飾ではない */
const TONE: Record<string, { dot: string; ring: string; label: string }> = {
  nojudgment: { dot: 'var(--color-stage-nojudgment)', ring: 'var(--color-stage-nojudgment)', label: '判断なし' },
  judgment: { dot: 'var(--color-stage-judgment)', ring: 'var(--color-stage-judgment)', label: '判断あり' },
  assigned: { dot: 'var(--color-status-assigned)', ring: 'var(--color-status-assigned)', label: '割当済み' },
  unclassifiable: { dot: 'var(--color-status-unclassifiable)', ring: 'var(--color-status-unclassifiable)', label: '分類不能' },
  'out-of-scope': { dot: 'var(--color-status-out-of-scope)', ring: 'var(--color-status-out-of-scope)', label: '対象外' },
}
const toneOf = (n: TopologyNode) =>
  n.kind === 'state' ? (TONE[n.status ?? ''] ?? TONE.judgment!)
  : n.kind === 'derived' ? TONE.judgment!
  : TONE.nojudgment!

/** 段の1語説明。ノードを見た時点で目に入る位置に置く */
const KIND_GLOSS: Record<string, string> = {
  source: '役所が公開したファイルそのまま',
  canonical: '取り込んで検証しただけ。fudoki の判断は入っていない',
  derived: '正本に COFOG を割り当てたもの。ここから fudoki の判断',
  state: '派生の内訳',
}

function NodeCard({
  node, checks, active, onClick,
}: { node: TopologyNode; checks: ReportData['checks']; active: boolean; onClick: () => void }) {
  const tone = toneOf(node)
  const failed = checks.filter((c) => !c.ok).length
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={KIND_GLOSS[node.kind]}
      className={cn(
        'group w-full rounded-lg border bg-card p-3 text-left transition-colors',
        'hover:border-foreground/30',
        active && 'ring-2 ring-offset-1',
      )}
      style={active ? { borderColor: tone.ring, boxShadow: `0 0 0 2px color-mix(in oklab, ${tone.ring} 35%, transparent)` } : undefined}
    >
      <span className="flex items-center gap-2">
        <i aria-hidden className="size-2.5 shrink-0 rounded-sm" style={{ background: tone.dot }} />
        <span className="truncate text-sm font-medium">{node.label}</span>
      </span>
      <span className="mt-1 block text-lg leading-none font-semibold tabular-nums">{yen(node.rows)}<span className="ml-1 text-xs font-normal text-muted-foreground">行</span></span>
      {node.artifact && (
        <span className="mt-1.5 block truncate font-mono text-[11px] text-muted-foreground">{node.artifact}</span>
      )}
      {checks.length > 0 && (
        <span className="mt-1.5 block">
          <Badge variant={failed ? 'destructive' : 'secondary'} className="text-[10px]">
            検査 {checks.length - failed}/{checks.length}
          </Badge>
        </span>
      )}
    </button>
  )
}

/** 辺。何がどれだけ流れたかを矢印の脇に書く */
function Edge({ label, note, dead }: { label?: string; note?: string; dead?: boolean }) {
  return (
    <div className="flex min-w-[92px] flex-col items-center justify-center px-1 text-center">
      <span aria-hidden className={cn('text-lg leading-none', dead ? 'text-muted-foreground/50' : 'text-muted-foreground')}>
        {dead ? '⇥' : '→'}
      </span>
      {label && <span className="mt-0.5 text-[11px] tabular-nums text-muted-foreground">{label}</span>}
      {note && <span className="mt-0.5 max-w-[13ch] text-[10px] leading-tight text-muted-foreground/80">{note}</span>}
    </div>
  )
}

export function FlowGraph({ topology, report, onSelectNode }: Props) {
  const [active, setActive] = useState<string | null>(null)
  const checks = checksByNode(report)
  const byId = new Map(topology.nodes.map((n) => [n.id, n]))
  const edgeFrom = (id: string) => topology.edges.filter((e) => e.from === id)

  const select = (id: string) => {
    const next = active === id ? null : id
    setActive(next)
    onSelectNode?.(next)
  }

  const sources = topology.nodes.filter((n) => n.kind === 'source')
  const states = topology.nodes.filter((n) => n.kind === 'state')
  const stageOf = (id: StageIdLike) => topology.stages.find((s) => s.id === id)

  return (
    <div className="flex flex-col gap-3">
      {/* 3語の定義を、ノードを見る前に置く */}
      <dl className="flex flex-wrap gap-x-5 gap-y-1 rounded-lg border bg-muted/30 px-3 py-2 text-xs">
        {(['source', 'canonical', 'derived'] as const).map((k) => (
          <div key={k} className="flex items-baseline gap-1.5">
            <dt className="font-medium">
              {k === 'source' ? '原典' : k === 'canonical' ? '正本' : '派生'}
            </dt>
            <dd className="m-0 text-muted-foreground">{KIND_GLOSS[k]}</dd>
          </div>
        ))}
      </dl>

      {/* 段の見出し */}
      <div className="hidden grid-cols-[1fr_auto_1fr_auto_1.4fr] items-end gap-2 md:grid">
        {(['extract', 'load', 'transform'] as const).map((id, i) => {
          const s = stageOf(id)
          return (
            <Fragment key={id}>
              {i > 0 && <div />}
              <div className="text-xs">
                <span className="font-medium">{s?.label}</span>
                {s?.introducesJudgment && (
                  <span className="ml-1.5 rounded-sm px-1 py-0.5 text-[10px]"
                    style={{ background: 'color-mix(in oklab, var(--color-judgment-boundary) 18%, transparent)', color: 'var(--color-judgment-boundary)' }}>
                    ここから判断
                  </span>
                )}
                <p className="mt-0.5 text-[11px] leading-tight text-muted-foreground">{s?.responsibility}</p>
              </div>
            </Fragment>
          )
        })}
      </div>

      {/* 本体。1行が1つの direction の経路 */}
      <div className="flex flex-col gap-3">
        {sources.map((src) => {
          const toCanon = edgeFrom(src.id)[0]
          const canon = toCanon?.to ? byId.get(toCanon.to) : undefined
          const fromCanon = canon ? edgeFrom(canon.id)[0] : undefined
          const derived = fromCanon?.to ? byId.get(fromCanon.to) : undefined
          const isDead = fromCanon?.kind === 'terminate'

          return (
            <div key={src.id}
              className="grid items-stretch gap-2 md:grid-cols-[1fr_auto_1fr_auto_1.4fr]">
              <NodeCard node={src} checks={checks.get(src.id) ?? []} active={active === src.id} onClick={() => select(src.id)} />
              <Edge label={`${yen(toCanon?.rows ?? 0)} 行`} note={toCanon?.note} />
              {canon && (
                <NodeCard node={canon} checks={checks.get(canon.id) ?? []} active={active === canon.id} onClick={() => select(canon.id)} />
              )}

              {isDead ? (
                <>
                  <Edge dead note="行き止まり" />
                  <div className="flex items-center rounded-lg border border-dashed bg-muted/20 p-3 text-xs leading-relaxed text-muted-foreground">
                    {fromCanon?.note}
                  </div>
                </>
              ) : (
                <>
                  <Edge label={`${yen(fromCanon?.rows ?? 0)} 行`} />
                  {derived && (
                    <div className="flex flex-col gap-2">
                      <NodeCard node={derived} checks={checks.get(derived.id) ?? []} active={active === derived.id} onClick={() => select(derived.id)} />
                      {/* 派生の内訳。分類の3状態 */}
                      <div className="grid gap-1.5 sm:grid-cols-3">
                        {states.map((st) => {
                          const tone = toneOf(st)
                          const c = checks.get(st.id) ?? []
                          return (
                            <button key={st.id} type="button" onClick={() => select(st.id)} aria-pressed={active === st.id}
                              className={cn('rounded-md border bg-card px-2 py-1.5 text-left transition-colors hover:border-foreground/30',
                                active === st.id && 'ring-1')}
                              style={active === st.id ? { borderColor: tone.ring } : undefined}>
                              <span className="flex items-center gap-1.5">
                                <i aria-hidden className="size-2 shrink-0 rounded-sm" style={{ background: tone.dot }} />
                                <span className="truncate text-[11px]">{STATUS_JA[st.status ?? ''] ?? st.label}</span>
                              </span>
                              <span className="block text-sm font-semibold tabular-nums">{yen(st.rows)}
                                <span className="ml-0.5 text-[10px] font-normal text-muted-foreground">行</span></span>
                              {c.length > 0 && <span className="text-[10px] text-muted-foreground">検査 {c.length}</span>}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )
        })}
      </div>

      {/* 凡例。図の解釈が色に依存しているので必ず出す */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground">色の意味</span>
        {Object.entries(TONE).map(([k, t]) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <i aria-hidden className="size-2.5 rounded-sm" style={{ background: t.dot }} />
            {t.label}
          </span>
        ))}
      </div>
    </div>
  )
}

type StageIdLike = Topology['stages'][number]['id']
