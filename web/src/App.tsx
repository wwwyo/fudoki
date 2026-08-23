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
import { Button } from '@/components/ui/button'
import { levelsOf, loadDetail, loadPipeline, toRows, type DetailData, type PipelineData } from '@/lib/pipeline'

export default function App() {
  const [data, setData] = useState<PipelineData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  // 見ている団体。**1団体だけを前提にしない** — 以前は pipeline.json が単一団体の形で、
  // 2団体目を足したら生成側が例外で止まるようにしてあった。
  const [code, setCode] = useState<string | null>(null)
  // 明細は報告の 50 倍あるので、タブを開いたときだけ取りに行く。
  // ⚠️ **団体をまたいで溜めない。** 溜めると切り替えるたびに 40,383 行の表が積み上がり、
  // 解放されない（対象は最終的に62団体になる）。見ている団体の分だけ持つ。
  const [detail, setDetail] = useState<{ code: string; data: DetailData } | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  // 開いているタブ。**明細の取得はタブを開いた瞬間だけの出来事ではない** —
  // 明細を見ている最中に団体を切り替えても取りに行く必要がある。
  const [tab, setTab] = useState('checks')

  useEffect(() => {
    loadPipeline()
      .then((d) => { setData(d); setCode(d.jurisdictions[0]?.code ?? null) })
      .catch((e: Error) => setError(e.message))
  }, [])

  const current = data?.jurisdictions.find((j) => j.code === code) ?? data?.jurisdictions[0]
  const loaded = detail?.code === code ? detail.data : undefined

  /**
   * 明細を取りに行く条件は「明細タブを見ていて、その団体の分をまだ持っていない」。
   *
   * ⚠️ **タブを開く操作に紐づけない。** 紐づけると、明細タブを開いたまま団体を切り替えたとき
   * 取得が走らず「明細を読み込み中…」のまま止まる（操作しないと復帰できない）。
   * 見ているものと持っているものの差で決めれば、どちらの順序でも同じ結果になる。
   */
  useEffect(() => {
    if (tab !== 'detail' || !current || loaded || detailError) return
    let stale = false
    const target = current.code
    loadDetail(current.report)
      .then((d) => { if (!stale) setDetail({ code: target, data: d }) })
      .catch((e: Error) => { if (!stale) setDetailError(e.message) })
    // 取得中に団体を切り替えたら、遅れて届いた前の団体の明細を捨てる
    return () => { stale = true }
  }, [tab, current, loaded, detailError])

  // 収録範囲（団体・年度）を知っているのは pipeline.json だけ。index.html の title に
  // 写すと、対象を広げた瞬間に静かに嘘になるので、可変の部分だけ実行時に入れる。
  useEffect(() => {
    if (!current) return
    const { jurisdictionName, fiscalYears, phase } = current.report.meta
    document.title = `${jurisdictionName} ${fiscalYears.join('・')}年度 ${phase.label} | fudoki（風土記）`
  }, [current])

  const rows = useMemo(
    () => (loaded ? { expenditure: toRows(loaded.expenditure), revenue: toRows(loaded.revenue) } : null),
    [loaded],
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
  if (!data || !current) {
    return <main className="p-6 text-sm text-muted-foreground">読み込み中…</main>
  }

  const { report } = current
  const m = report.meta
  const t = report.transform
  const total = t.byState.reduce((s, x) => s + x.sum, 0)
  const assigned = t.byState.filter((x) => x.status === 'assigned').reduce((s, x) => s + x.sum, 0)

  // このページの目的は「配布データが正しいか」を判別できることなので、
  // サマリも検証の指標だけを出す（総額のような分析の数字は明細タブが持つ）。
  // ⚠️ **団体ごとに見る。** ノードは系統1本で共有なので、団体コードで引かないと
  // 別の団体の行数と突き合わせることになる。
  const prov = report.ingestion
  const roundtripOk = prov.filter((p) => p.roundtrip_verified).length
  const rowsOf = (label: string) => report.topology.nodes.find((n) => n.label === label)?.rows
  const rowsIntact = (['expenditure', 'revenue'] as const).every(
    (d) => rowsOf(`stg_${current.code}__${d}`) === rowsOf(`pkg_${current.code}__${d}`),
  )

  const stats: { label: string; value: string | number; tone?: string; hint?: string }[] = [
    { label: '検査', value: `${report.summary.passed}/${report.summary.total}`, tone: report.summary.failed ? 'bad' : 'good', hint: '1つでも落ちると成果物を書き出さない' },
    // ⚠️ 団体で意味が違う。三鷹市は当初予算額、狛江市は決算の予算現額（全会計・全年度の合計）。
    { label: '原文の復元', value: `${roundtripOk}/${prov.length}`, tone: roundtripOk === prov.length ? 'good' : 'bad', hint: '文字コードの復号が可逆で、保存した Parquet から原文に戻ること' },
    { label: '行数の一致', value: rowsIntact ? '一致' : '不一致', tone: rowsIntact ? 'good' : 'bad', hint: 'staging と配布物で行が増減していないこと' },
    { label: 'COFOG 割当済み（金額比）', value: `${((assigned / total) * 100).toFixed(1)}%`, hint: 'COFOG は政府支出の機能別分類（教育、保健など10区分）。国際標準' },
    // ⚠️ 消去が成立しない団体がある（狛江市は相手の会計が原典から決まらない）。
    // 「相殺する」と決め打ちで書くと、消去していない団体で嘘になる。
  ]

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b bg-background/95 px-4 backdrop-blur">
        <div className="flex min-w-0 items-center gap-2">
          {data.jurisdictions.length > 1 && (
            <nav aria-label="団体" className="flex shrink-0 gap-1">
              {data.jurisdictions.map((j) => (
                <Button
                  key={j.code}
                  size="sm"
                  variant={j.code === current.code ? 'default' : 'outline'}
                  onClick={() => { setCode(j.code); setSelectedNode(null); setDetailError(null) }}
                >
                  {j.report.meta.jurisdictionName}
                </Button>
              ))}
            </nav>
          )}
          <span className="truncate text-sm text-muted-foreground">
            {m.fiscalYears.length > 2
              ? `${m.fiscalYears[0]}〜${m.fiscalYears.at(-1)}年度`
              : `${m.fiscalYears.join('・')}年度`} · {m.phase.label}
          </span>
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

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            {/* 検証の順に並べる: 何を保証しているか（検査）→ どこから来たか（証跡）
                → fudoki は何を足したか（COFOG）→ 1行ずつ確かめる（明細） */}
            <TabsTrigger value="checks">検査</TabsTrigger>
            <TabsTrigger value="stages">証跡</TabsTrigger>
            <TabsTrigger value="cofog">COFOG の判断</TabsTrigger>
            <TabsTrigger value="detail">明細</TabsTrigger>
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
              <DetailBrowser
                code={current.code}
                expenditure={rows.expenditure}
                revenue={rows.revenue}
                levels={{
                  expenditure: levelsOf(report, 'expenditure'),
                  revenue: levelsOf(report, 'revenue'),
                }}
                tables={{ expenditure: loaded!.expenditure, revenue: loaded!.revenue }}
              />
            ) : (
              <p className="text-sm text-muted-foreground">明細を読み込み中…</p>
            )}
          </TabsContent>
        </Tabs>

        <footer className="border-t pt-6 text-xs leading-relaxed text-muted-foreground">
          配布物 <code>data/budget/datapackages/{current.code}/</code> ／ 原典 <code>data/budget/raw/</code>
          <br />
          原典: <a className="underline" href={m.landingPage} target="_blank" rel="noreferrer">{m.attribution}</a>
          {' '}／ {m.license.id} ／ 生成 {m.generatedAt.replace('T', ' ').slice(0, 19)}
        </footer>
      </main>
    </div>
  )
}
