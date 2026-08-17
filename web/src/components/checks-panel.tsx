/**
 * 検査。
 *
 * 平らな30件の一覧ではなく、**どの段の何を守っているか**で見せる。
 * 流れ図でノードを選ぶと、その binds を持つ検査だけに絞れる。
 */
import { useState } from 'react'
import type { ReportData } from '@/lib/pipeline'
import { unboundChecks } from '@/lib/pipeline'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

type Props = { report: ReportData; selectedNode: string | null; onClearNode: () => void }

export function ChecksPanel({ report, selectedNode, onClearNode }: Props) {
  const [failOnly, setFailOnly] = useState(false)
  const nodeLabel = report.topology.nodes.find((n) => n.id === selectedNode)?.label

  let rows = report.checks
  if (selectedNode) rows = rows.filter((c) => c.binds.includes(selectedNode))
  if (failOnly) rows = rows.filter((c) => !c.ok)

  const nr = report.notYetReconciled
  const unbound = unboundChecks(report)

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-[72ch] text-sm leading-relaxed text-muted-foreground">
        合計の突合だけに頼らない。<span className="font-medium text-foreground">1行の欠落と同額の行の重複は合計では相殺されて素通りする。</span>
        性質の異なる検査を並べ、どれか1つが通っても他が落ちる状態を作る。
        検査が1つでも落ちると成果物は書き出されない（{report.topology.writeGate.description}）。
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant={failOnly ? 'default' : 'outline'} onClick={() => setFailOnly((v) => !v)}>
          失敗だけ表示
        </Button>
        {selectedNode && (
          <Button size="sm" variant="outline" onClick={onClearNode}>
            {nodeLabel} で絞り込み中 — 解除
          </Button>
        )}
        <span className="text-xs text-muted-foreground">{rows.length} / {report.checks.length} 件</span>
      </div>

      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow><TableHead>結果</TableHead><TableHead>検査</TableHead><TableHead>守っている対象</TableHead><TableHead>詳細</TableHead></TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow><TableCell colSpan={4} className="text-sm text-muted-foreground">該当なし。</TableCell></TableRow>
            ) : rows.map((c, i) => (
              <TableRow key={i}>
                <TableCell><Badge variant={c.ok ? 'secondary' : 'destructive'}>{c.ok ? '成功' : '失敗'}</Badge></TableCell>
                <TableCell className="min-w-[20ch] text-sm">{c.name}</TableCell>
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                  {c.binds.length === 0 ? 'パッケージ全体'
                    : c.binds.map((b) => report.topology.nodes.find((n) => n.id === b)?.label ?? b).join(' / ')}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">{c.detail}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <p className="text-xs text-muted-foreground">
        {unbound.length} 件はどのノードにも紐づかない（descriptor 適合と公表値の内部整合）。
        特定の段ではなくパッケージ全体に掛かるため。
      </p>

      <Alert>
        <AlertTitle>まだ突合していない範囲 — {nr.scope}</AlertTitle>
        <AlertDescription>
          <p>{nr.reason}</p>
          <p>現在の根拠: {nr.currentEvidence}</p>
          <p>出所の候補: <a className="underline" href={nr.wouldComeFrom} target="_blank" rel="noreferrer">{nr.wouldComeFrom}</a></p>
        </AlertDescription>
      </Alert>
    </div>
  )
}
