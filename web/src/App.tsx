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
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Info } from 'lucide-react'
import { loadDetail, loadPipeline, toRows, type DetailData, type PipelineData } from '@/lib/pipeline'

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

  // 収録範囲（団体・年度）を知っているのは pipeline.json だけ。index.html の title に
  // 写すと、対象を広げた瞬間に静かに嘘になるので、可変の部分だけ実行時に入れる。
  useEffect(() => {
    if (!data) return
    const { jurisdictionName, fiscalYears, phase } = data.report.meta
    document.title = `${jurisdictionName} ${fiscalYears.join('・')}年度 ${phase.label} | fudoki（風土記）`
  }, [data])

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

  // このページの目的は「配布データが正しいか」を判別できることなので、
  // サマリも検証の指標だけを出す（総額のような分析の数字は明細タブが持つ）
  const prov = report.ingestion
  const roundtripOk = prov.filter((p) => p.roundtrip_verified).length
  const rowsOf = (label: string) => report.topology.nodes.find((n) => n.label === label)?.rows
  const rowsIntact = (['expenditure', 'revenue'] as const).every(
    (d) => rowsOf(d) === rowsOf(`stg_${data.code}__${d}`) && rowsOf(d) === rowsOf(`pkg_${data.code}__${d}`),
  )

  const stats: { label: string; value: string | number; tone?: string; hint?: string }[] = [
    { label: '検査', value: `${report.summary.passed}/${report.summary.total}`, tone: report.summary.failed ? 'bad' : 'good', hint: '1つでも落ちると成果物を書き出さない' },
    { label: '原文の復元', value: `${roundtripOk}/${prov.length}`, tone: roundtripOk === prov.length ? 'good' : 'bad', hint: 'cp932 の復号が可逆で、保存した Parquet から原文に戻ること' },
    { label: '行数の一致', value: rowsIntact ? '一致' : '不一致', tone: rowsIntact ? 'good' : 'bad', hint: '取得元 → staging → 配布物で行が増減していないこと' },
    { label: 'COFOG 割当（金額比）', value: `${((assigned / total) * 100).toFixed(1)}%`, hint: 'fudoki の判断が及ぶ範囲。根拠は「COFOG の判断」タブ' },
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
          <h1 className="text-xl font-semibold">ELT パイプライン</h1>

          <FlowGraph topology={report.topology} report={report} onSelectNode={setSelectedNode} selected={selectedNode} />

          <div className="flex flex-wrap gap-3">
            {stats.map((s) => (
              <Card key={s.label} className="min-w-[9rem] flex-1 gap-1 py-4">
                <CardHeader className="px-4">
                  <CardDescription className="flex items-center gap-1 text-xs">
                    {s.label}
                    {s.hint && (
                      <Tooltip>
                        <TooltipTrigger
                          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 rounded-full focus-visible:ring-[3px] focus-visible:outline-none"
                          aria-label={`${s.label} の定義`}
                        >
                          <Info aria-hidden className="size-3" />
                        </TooltipTrigger>
                        <TooltipContent className="max-w-[36ch]">{s.hint}</TooltipContent>
                      </Tooltip>
                    )}
                  </CardDescription>
                  <CardTitle
                    className={
                      s.tone === 'good' ? 'text-xl text-[var(--color-chart-2)]'
                        : s.tone === 'bad' ? 'text-xl text-destructive' : 'text-xl'
                    }
                  >
                    {s.value}
                  </CardTitle>
                </CardHeader>
              </Card>
            ))}
          </div>
        </section>

        <Tabs
          defaultValue="checks"
          onValueChange={(v) => {
            if (v === 'detail' && !detail && !detailError) {
              loadDetail().then(setDetail).catch((e: Error) => setDetailError(e.message))
            }
          }}
        >
          <TabsList>
            {/* 検証の順に並べる: 何を保証しているか（検査）→ どこから来たか（証跡）
                → fudoki は何を足したか（COFOG）→ 1行ずつ確かめる（明細） */}
            <TabsTrigger value="checks">検査</TabsTrigger>
            <TabsTrigger value="stages">証跡</TabsTrigger>
            <TabsTrigger value="cofog">COFOG の判断</TabsTrigger>
            <TabsTrigger value="detail">明細</TabsTrigger>
          </TabsList>

          <TabsContent value="checks" className="pt-4">
            <ChecksPanel report={report} selectedNode={selectedNode} onClearNode={() => setSelectedNode(null)} />
          </TabsContent>
          <TabsContent value="stages" className="pt-4">
            <StageDetail report={report} />
          </TabsContent>
          <TabsContent value="cofog" className="pt-4">
            <CofogPanel report={report} />
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
