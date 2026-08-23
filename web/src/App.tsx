/**
 * ELT の全体像を見るダッシュボード。
 *
 * 集計はしない。数字はすべて `pipeline.json`（`report/budget/build.ts` の出力）を
 * そのまま出す。画面側でも集計すると、同じ数字が2通りに計算されて、いずれ食い違う。
 */
import { useEffect, useMemo, useState } from 'react'
import { FlowGraph } from '@/components/flow-graph'
import { DetailBrowser } from '@/components/detail-browser'
import { StageDetail } from '@/components/stage-detail'
import { CofogPanel } from '@/components/cofog-panel'
import { ChecksPanel } from '@/components/checks-panel'
import { CaveatsPanel } from '@/components/caveats-panel'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { loadDetail, loadPipeline, toRows, yenShort, type DetailData, type PipelineData } from '@/lib/pipeline'

export default function App() {
  const [data, setData] = useState<PipelineData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  // 明細は報告の 50 倍あるので、タブを開いたときだけ取りに行く
  const [detail, setDetail] = useState<DetailData | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)

  useEffect(() => {
    loadPipeline().then(setData).catch((e: Error) => setError(e.message))
  }, [])

  const rows = useMemo(
    () => (detail ? { expenditure: toRows(detail.expenditure), revenue: toRows(detail.revenue) } : null),
    [detail],
  )

  if (error) {
    return (
      <main className="mx-auto max-w-2xl p-6">
        <Alert variant="destructive">
          <AlertTitle>データを読み込めませんでした</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </main>
    )
  }
  if (!data) {
    return <main className="p-6 text-sm text-muted-foreground">読み込み中…</main>
  }

  const { report } = data
  const m = report.meta
  const t = report.transform
  const total = t.byState.reduce((s, x) => s + x.sum, 0)
  const assigned = t.byState.filter((x) => x.status === 'assigned').reduce((s, x) => s + x.sum, 0)
  const eliminated = t.byState.filter((x) => x.consolidation === 'eliminated').reduce((s, x) => s + x.sum, 0)

  const stats: { label: string; value: string | number; tone?: string; hint?: string }[] = [
    { label: '検査', value: `${report.summary.passed}/${report.summary.total}`, tone: report.summary.failed ? 'bad' : 'good', hint: '1つでも落ちると成果物を書き出さない' },
    { label: '歳出の総額', value: yenShort(total) },
    { label: 'COFOG 割当済み（金額比）', value: `${((assigned / total) * 100).toFixed(1)}%`, hint: 'COFOG は政府支出の機能別分類（教育、保健など10区分）。国際標準' },
    { label: '連結で消去', value: yenShort(eliminated), hint: '会計間の繰出。市の全会計を足すとき二重に数えるので相殺する' },
    { label: '割当規則', value: `${t.ruleCount} 本` },
  ]

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b bg-background/95 px-4 backdrop-blur">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-medium">{m.jurisdictionName}</span>
          <span className="truncate text-sm text-muted-foreground">{m.fiscalYears.join("・")}年度 · {m.phase.label}</span>
        </div>
        <Badge variant={report.summary.failed ? 'destructive' : 'secondary'} className="ml-auto shrink-0">
          検査 {report.summary.passed}/{report.summary.total}
        </Badge>
      </header>

      <main className="mx-auto flex max-w-[1500px] flex-col gap-8 p-4 pb-24">
        <section className="flex flex-col gap-4">
          <div>
            <h1 className="text-xl font-semibold">ELT パイプライン</h1>
          </div>

          <FlowGraph topology={report.topology} report={report} onSelectNode={setSelectedNode} selected={selectedNode} />

          <div className="flex flex-wrap gap-3">
            {stats.map((s) => (
              <Card key={s.label} className="min-w-[9rem] flex-1 gap-1 py-4">
                <CardHeader className="px-4">
                  <CardDescription className="text-xs">{s.label}</CardDescription>
                  <CardTitle
                    className={
                      s.tone === 'good' ? 'text-xl text-[var(--color-chart-2)]'
                        : s.tone === 'bad' ? 'text-xl text-destructive' : 'text-xl'
                    }
                  >
                    {s.value}
                  </CardTitle>
                  {s.hint && <p className="mt-1 text-[11px] leading-tight text-muted-foreground">{s.hint}</p>}
                </CardHeader>
              </Card>
            ))}
          </div>
        </section>

        <Tabs
          defaultValue="stages"
          onValueChange={(v) => {
            if (v === 'detail' && !detail && !detailError) {
              loadDetail().then(setDetail).catch((e: Error) => setDetailError(e.message))
            }
          }}
        >
          <TabsList>
            {/* データの中身はグラフのノード選択が出す。ここに残るのは証跡と階層の実測 */}
            <TabsTrigger value="stages">証跡</TabsTrigger>
            <TabsTrigger value="cofog">COFOG の判断</TabsTrigger>
            <TabsTrigger value="checks">検査</TabsTrigger>
            <TabsTrigger value="detail">明細</TabsTrigger>
            <TabsTrigger value="caveats">未確定のこと</TabsTrigger>
          </TabsList>

          <TabsContent value="stages" className="pt-4">
            <StageDetail report={report} />
          </TabsContent>
          <TabsContent value="cofog" className="pt-4">
            <CofogPanel report={report} />
          </TabsContent>
          <TabsContent value="checks" className="pt-4">
            <ChecksPanel report={report} selectedNode={selectedNode} onClearNode={() => setSelectedNode(null)} />
          </TabsContent>
          <TabsContent value="detail" className="pt-4">
            {detailError ? (
              <Alert variant="destructive">
                <AlertTitle>明細を読み込めませんでした</AlertTitle>
                <AlertDescription>{detailError}</AlertDescription>
              </Alert>
            ) : rows ? (
              <DetailBrowser expenditure={rows.expenditure} revenue={rows.revenue} />
            ) : (
              <p className="text-sm text-muted-foreground">明細を読み込み中…</p>
            )}
          </TabsContent>
          <TabsContent value="caveats" className="pt-4">
            <CaveatsPanel report={report} />
          </TabsContent>
        </Tabs>

        <footer className="border-t pt-6 text-xs leading-relaxed text-muted-foreground">
          正本 <code>data/budget/datapackages/{data.code}/</code> ／ 派生 <code>data/budget/datapackages/derived/</code> ／ 原典 <code>data/budget/raw/</code>
          <br />
          原典: <a className="underline" href={m.landingPage} target="_blank" rel="noreferrer">{m.attribution}</a>
          {' '}／ {m.license.id} ／ 生成 {m.generatedAt.replace('T', ' ').slice(0, 19)}
        </footer>
      </main>
    </div>
  )
}
