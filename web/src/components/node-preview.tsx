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
import { Badge } from '@/components/ui/badge'
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
    // 入力・出力を1つずつ独立した card にし、grid の行の高さに stretch させて揃える。
    // 見出しは1行固定（URL は truncate）— 折り返しで高さが割れると表の上端がずれる
    <div className={`grid items-stretch gap-3 ${inputs.length > 0 ? 'lg:grid-cols-2' : ''}`}>
      {inputs.length > 0 && (
        <div className="flex min-w-0 flex-col gap-3">
          {inputs.map((l, i) => (
            <PreviewSection key={i} loaded={l} />
          ))}
        </div>
      )}
      <div className="flex min-w-0 flex-col gap-3">
        {outputs.map((l, i) => (
          <PreviewSection key={i} loaded={l} stretch />
        ))}
      </div>
    </div>
  )
}

function PreviewSection({ loaded: l, stretch }: { loaded: Loaded; stretch?: boolean }) {
  return (
    <section className={`flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-3 ${stretch ? 'flex-1' : ''}`}>
      <div className="flex min-w-0 items-baseline gap-2">
        <Badge variant={l.role === '出力' ? 'secondary' : 'outline'}>{l.role === '入力' ? '入力（データ元）' : '出力（変換後）'}</Badge>
        <span className="shrink-0 truncate font-mono text-xs font-medium">{l.preview.title ?? l.label}</span>
        {l.preview.sourceUrl && (
          <a
            className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground underline"
            href={l.preview.sourceUrl}
            target="_blank"
            rel="noreferrer"
          >
            {l.preview.sourceUrl}
          </a>
        )}
      </div>
      <div className={`overflow-auto rounded-md border bg-background ${stretch ? 'min-h-72 flex-1 basis-72' : 'h-72'}`}>
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
      </div>
    </section>
  )
}
