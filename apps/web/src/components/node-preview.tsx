/**
 * グラフで選んだノードの入力と出力の中身（先頭数行）。
 *
 * 入力は topology の辺から引く（依存の宣言は dbt の manifest が正本で、
 * 画面が独自に「このノードの入力はこれ」と持つと、パイプラインを変えても直らない）。
 * データはノードごとに分けた preview/*.json を選んだときだけ取りに行く
 * （明細と同じ理由 — 常に運ぶと報告が太る）。
 */
import { useEffect, useState } from 'react'
import type { NodePreview, Topology } from '@/lib/pipeline'
import { loadNodePreview } from '@/lib/pipeline'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

type Loaded = { label: string; role: '入力' | '出力'; preview: NodePreview }

export function NodePreviewPanel({ nodeId, topology }: { nodeId: string; topology: Topology }) {
  const [loaded, setLoaded] = useState<Loaded[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoaded(null)
    setError(null)
    const labelOf = (id: string) => topology.nodes.find((n) => n.id === id)?.label ?? id
    const inputs = topology.edges.filter((e) => e.to === nodeId).map((e) => e.from)
    // 取得元（.origin）のプレビューはオンラインで報告を生成したときだけある
    const optional = (id: string) => id.endsWith('.origin')
    const targets: { id: string; label: string; role: '入力' | '出力'; optional?: boolean }[] = [
      ...inputs.map((id) => ({ id, label: labelOf(id), role: '入力' as const, optional: optional(id) })),
      { id: nodeId, label: labelOf(nodeId), role: '出力' as const, optional: optional(nodeId) },
    ]
    Promise.all(
      targets.map(async (t) => {
        try {
          return { label: t.label, role: t.role, preview: await loadNodePreview(t.id) }
        } catch (e) {
          if (t.optional) return null
          throw e
        }
      }),
    )
      .then((r) => alive && setLoaded(r.filter((x): x is Loaded => x !== null)))
      .catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [nodeId, topology])

  if (error) return <p className="mt-2 text-xs text-destructive">{error}</p>
  if (!loaded) return <p className="mt-2 text-xs text-muted-foreground">中身を読み込み中…</p>
  if (loaded.length === 0)
    return (
      <p className="mt-2 text-xs text-muted-foreground">
        取得元 CSV のプレビューが無い。オンラインで bun run report を回すと取得して表示する
      </p>
    )

  const inputs = loaded.filter((l) => l.role === '入力')
  const outputs = loaded.filter((l) => l.role === '出力')

  return (
    // 入力（データ元）と出力（変換後）を左右に並べて、変換の前後を突き合わせて読めるようにする。
    // 入力の無いノード（原典）は出力だけを全幅で出す
    // card は subgrid で親の行トラック（見出し / URL / 表）を共有する。
    // URL 行が片方にしか無くても、両カラムの表の上端が同じトラックに揃う
    <div className={`grid items-stretch gap-3 ${inputs.length > 0 ? 'lg:grid-cols-2' : ''}`}>
      {inputs.map((l, i) => (
        <PreviewSection key={`in-${i}`} loaded={l} className="lg:col-start-1" />
      ))}
      {outputs.map((l, i) => (
        <PreviewSection key={`out-${i}`} loaded={l} className={inputs.length > 0 ? 'lg:col-start-2 lg:row-start-1' : ''} />
      ))}
    </div>
  )
}

function PreviewSection({ loaded: l, className = '' }: { loaded: Loaded; className?: string }) {
  return (
    <Card size="sm" className={`min-w-0 gap-2 lg:grid lg:grid-rows-subgrid lg:row-span-3 ${className}`}>
      <CardHeader>
        <CardTitle className="flex min-w-0 items-baseline gap-2 text-sm">
          <span className="shrink-0 text-xs font-medium text-muted-foreground">{l.role === '入力' ? '入力（データ元）' : '出力（変換後）'}</span>
          <span className="min-w-0 truncate font-mono text-xs">{l.preview.title ?? l.label}</span>
        </CardTitle>
      </CardHeader>
      {l.preview.sourceUrl && (
        <CardDescription className="px-(--card-spacing) lg:row-start-2">
          <a className="break-all text-[11px] underline" href={l.preview.sourceUrl} target="_blank" rel="noreferrer">
            {l.preview.sourceUrl}
          </a>
        </CardDescription>
      )}
      {/* 表は常に3トラック目。URL の無い card は2トラック目が空くが、位置は動かない */}
      <CardContent className="min-h-96 flex-1 basis-96 overflow-auto px-0 lg:row-start-3">
        <Table>
          <TableHeader>
            <TableRow>
              {l.preview.columns.map((c) => (
                <TableHead key={c} className="whitespace-nowrap font-mono text-[11px]">{c}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {l.preview.rows.map((row, ri) => (
              <TableRow key={ri}>
                {row.map((v, ci) => (
                  <TableCell key={ci} className="max-w-[24rem] truncate whitespace-nowrap text-[11px] tabular-nums" title={v}>
                    {v}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
