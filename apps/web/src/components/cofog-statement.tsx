import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { yen, STATUS_JA } from '@/lib/display'
import type { CofogNodeFilter } from '@/lib/cofog-tree'
import { apiClient } from '@/lib/api-client'

type Result = Awaited<ReturnType<typeof apiClient.getFiscalLines>>
type Versions = Parameters<typeof apiClient.getFiscalLines>[0]['versions']
export function CofogStatement({
  versions,
  datasetId,
  filter,
  fund,
  consolidation,
}: {
  versions: Versions
  datasetId: string
  filter?: CofogNodeFilter
  fund?: string
  consolidation: 'all' | 'retained' | 'eliminated'
}) {
  const [lines, setLines] = useState<Result['lines']>([]),
    [cursor, setCursor] = useState<string>(),
    [loading, setLoading] = useState(false),
    [error, setError] = useState<string | null>(null)
  const generation = useRef(0)
  const query = {
    versions,
    datasetIds: [datasetId],
    cofog: filter,
    fund,
    consolidation,
    pageSize: 50,
  }
  useEffect(() => {
    const id = ++generation.current
    setLines([])
    setCursor(undefined)
    setError(null)
    setLoading(true)
    apiClient
      .getFiscalLines(query)
      .then((result) => {
        if (id !== generation.current) return
        setLines(result.lines)
        setCursor(result.nextCursor)
      })
      .catch((e) => {
        if (id === generation.current)
          setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (id === generation.current) setLoading(false)
      })
    return () => {
      generation.current++
    }
  }, [
    versions,
    datasetId,
    filter?.division,
    filter?.group,
    filter?.class,
    fund,
    consolidation,
  ])
  async function more() {
    if (!cursor || loading) return
    const id = generation.current
    setLoading(true)
    try {
      const result = await apiClient.getFiscalLines({ ...query, cursor })
      if (id !== generation.current) return
      setLines((previous) => [...previous, ...result.lines])
      setCursor(result.nextCursor)
    } catch (e) {
      if (id === generation.current)
        setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (id === generation.current) setLoading(false)
    }
  }
  return (
    <div className="space-y-3 p-4">
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>原典の行</TableHead>
            <TableHead>科目・事業</TableHead>
            <TableHead className="text-right">金額（円）</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {lines.map((line) => (
            <TableRow key={line.id}>
              <TableCell>{line.sourceRow}</TableCell>
              <TableCell>
                <div>
                  {line.hierarchy
                    .map((h) => `${h.code} ${h.label}`)
                    .join(' / ')}
                </div>
                {line.names
                  .filter((n) => n.kind === 'project')
                  .map((n) => (
                    <div
                      key={`${n.kind}:${n.level}`}
                      className="text-muted-foreground"
                    >
                      {n.value}（{n.nameSource}）
                    </div>
                  ))}
                <div className="text-xs text-muted-foreground">
                  {line.cofog &&
                    `${STATUS_JA[line.cofog.status] ?? line.cofog.status} / `}
                  {line.consolidation === 'eliminated'
                    ? '会計間移転'
                    : '合算対象'}
                  {line.cofog?.basis && ` / ${line.cofog.basis}`}
                </div>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {yen(line.amount)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {loading && <p className="text-muted-foreground">読み込み中…</p>}
      {cursor && (
        <Button variant="outline" size="sm" disabled={loading} onClick={more}>
          続きを読む
        </Button>
      )}
    </div>
  )
}
