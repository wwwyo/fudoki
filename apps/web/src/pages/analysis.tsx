/**
 * 団体の支出を COFOG（政府支出の機能別分類）別に見る分析ダッシュボード。
 *
 * `/pipeline/` と違って**静的な生成物を読まない**。COFOG の内訳は
 * `apps/api` の `getCofogBreakdown`（`/rpc`）から取る — 数字は API 側の
 * `report/budget/cofog.ts` が持ち、ここでは足し直さない（AGENTS.md の「集計は1箇所」）。
 *
 * 「収録済みか」の判定と団体セレクタだけは `pipeline.json`（`loadPipeline`）を再利用する。
 * ELT パイプラインを通った団体の集合と、budget API が返せる団体の集合は同じ配布物から
 * 生成されるので一致するはずで、ここだけのために別の一覧を持つ理由が無い。
 */
import { useEffect, useMemo, useState } from "react"
import { Layout } from "@/components/layout"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { withBase } from "@/lib/utils"
import { DIVISION_COLOR, loadPipeline, pct, yen, type Direction, type PipelineData } from "@/lib/pipeline"
import { apiClient } from "@/lib/api-client"

/** contract 型を web 側で二重宣言しない。API 呼び出しの戻り値からそのまま導出する */
type CofogBreakdown = Awaited<ReturnType<typeof apiClient.getCofogBreakdown>>["cofog"]

type Props = {
  /** `/analysis/<団体コード>/` の団体コード。コードなしの `/analysis/` では null */
  urlCode?: string | null
  /** 未収録団体でも団体名は出す（jurisdictions.json 由来。ビルド時に埋め込まれる） */
  jurisdictionName?: string
}

const DIRECTIONS: { value: Direction; label: string }[] = [
  { value: "expenditure", label: "歳出" },
  { value: "revenue", label: "歳入" },
]

export function AnalysisPage({ urlCode = null, jurisdictionName }: Props = {}) {
  const [data, setData] = useState<PipelineData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const code = urlCode

  useEffect(() => {
    loadPipeline()
      .then((d) => {
        setData(d)
        // `/analysis/`（コードなし）は常に収録済みの先頭団体の URL へ送る。地図・パイプラインと同じ向き
        if (!urlCode) {
          const first = d.jurisdictions[0]?.code
          if (first) window.location.replace(withBase(`/analysis/${first}/`))
        }
      })
      .catch((e: Error) => setError(e.message))
  }, [urlCode])

  const found = data?.jurisdictions.find((j) => j.code === code) ?? null
  const notCollected = data !== null && urlCode !== null && found === null

  useEffect(() => {
    if (!found) return
    document.title = `${found.report.meta.jurisdictionName} の支出分析 | fudoki（風土記）`
  }, [found])

  useEffect(() => {
    if (!notCollected) return
    document.title = `${jurisdictionName ?? urlCode} はまだ収録していません | fudoki（風土記）`
  }, [notCollected, jurisdictionName, urlCode])

  if (error) {
    return (
      <Layout>
        <main className="mx-auto max-w-2xl p-6">
          <Alert variant="destructive">
            <AlertTitle>団体一覧を読み込めませんでした</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </main>
      </Layout>
    )
  }

  if (notCollected) {
    return (
      <AnalysisNotCollected
        code={urlCode!}
        name={jurisdictionName}
        jurisdictions={data!.jurisdictions.map((j) => ({
          code: j.code,
          name: j.report.meta.jurisdictionName,
        }))}
      />
    )
  }

  if (!data || !found) {
    return (
      <Layout>
        <main className="p-6 text-sm text-muted-foreground">読み込み中…</main>
      </Layout>
    )
  }

  return <CollectedAnalysis data={data} current={found} />
}

function CollectedAnalysis({
  data,
  current,
}: {
  data: PipelineData
  current: PipelineData["jurisdictions"][number]
}) {
  const code = current.code
  const m = current.report.meta
  // fiscalYears は生成側が団体コード順・年度昇順で持つ（AGENTS.md）。既定は最新年度
  const years = m.fiscalYears
  const [year, setYear] = useState<number>(years.at(-1)!)
  const [direction, setDirection] = useState<Direction>("expenditure")
  const [cofog, setCofog] = useState<CofogBreakdown | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)

  // 団体を切り替えたら年度もその団体の最新年度に戻す（前の団体にしか無い年度を持ち越さない）。
  // 依存は `code` だけにする — `years` を足すと配列の参照が変わるたびに発火し、
  // ユーザーが選んだ年度を勝手に最新へ戻してしまう
  useEffect(() => {
    setYear(years.at(-1)!)
  }, [code])

  useEffect(() => {
    let stale = false
    setCofog(null)
    setApiError(null)
    apiClient
      .getCofogBreakdown({ budget: `${code}:${year}`, direction })
      .then((res) => {
        if (!stale) setCofog(res.cofog)
      })
      .catch((e: unknown) => {
        if (stale) return
        setApiError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      stale = true
    }
  }, [code, year, direction])

  const breakdown = useMemo(() => {
    if (!cofog) return null
    const total = cofog.total.sum
    const unclassifiedSum = cofog.total.sum - cofog.assigned.sum
    const unclassifiedCount = cofog.total.count - cofog.assigned.count
    return {
      // ⚠️ **分母は total（未分類を含む）。** cofog-panel.tsx の帯は「割当済みの中での構成比」だが、
      // ここは ELT パイプラインと違い「事業に使うといくら見えるか」を見せる分析なので、
      // 分類できなかった分を隠さず分母に残す（AGENTS.md タスク仕様）。
      byDivision: cofog.byDivision.map((d) => ({ ...d, share: total > 0 ? d.sum / total : 0 })),
      unclassifiedSum,
      unclassifiedCount,
      unclassifiedShare: total > 0 ? unclassifiedSum / total : 0,
    }
  }, [cofog])

  return (
    <Layout>
      <main className="mx-auto flex max-w-[1100px] flex-col gap-8 p-4 pb-24">
        <section className="flex flex-col gap-4">
          <div className="mb-2 flex flex-wrap items-baseline gap-3">
            <h1 className="text-xl font-semibold">支出分析</h1>
            <JurisdictionSelect data={data} current={code} />
            {years.length > 1 ? (
              <Select
                items={years.map((y) => ({ value: String(y), label: `${y}年度` }))}
                value={String(year)}
                onValueChange={(v) => setYear(Number(v))}
              >
                <SelectTrigger aria-label="年度" className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {years.map((y) => (
                      <SelectItem key={y} value={String(y)}>
                        {y}年度
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            ) : (
              <span className="text-sm text-muted-foreground">{years[0]}年度</span>
            )}
            <Select
              items={DIRECTIONS}
              value={direction}
              onValueChange={(v) => setDirection(v as Direction)}
            >
              <SelectTrigger aria-label="歳出・歳入" className="w-24">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {DIRECTIONS.map((d) => (
                    <SelectItem key={d.value} value={d.value}>
                      {d.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            {/* この団体の ELT パイプラインへの導線。分析は数字を見る場所、パイプラインは
                その数字の根拠（集計・COFOG 割当）を検証する場所で目的が違う。pipeline.tsx 側の
                「支出分析を見る」ボタンと対になる導線なので、扱いを揃える */}
            <Button
              variant="outline"
              size="sm"
              nativeButton={false}
              className="ml-auto shrink-0"
              render={<a href={withBase(`/pipeline/${code}/`)}>ELT パイプラインを見る</a>}
            />
          </div>
          <p className="max-w-[72ch] text-sm leading-relaxed text-muted-foreground">
            {m.jurisdictionName} の{DIRECTIONS.find((d) => d.value === direction)?.label}を、
            <span className="font-medium text-foreground">COFOG</span>
            （Classification of the Functions of Government。政府支出の機能別分類）の
            10区分ごとに集計する。
          </p>
        </section>

        {apiError ? (
          <Alert variant="destructive">
            <AlertTitle>分析データを読み込めませんでした</AlertTitle>
            <AlertDescription>
              fudoki の API（api.fudoki.dev）から COFOG 別内訳を取得できませんでした。
              API が止まっているか、この団体・年度・方向の組み合わせがまだ収録されていない可能性があります。
              <br />
              {apiError}
            </AlertDescription>
          </Alert>
        ) : !cofog || !breakdown ? (
          <p className="text-sm text-muted-foreground">読み込み中…</p>
        ) : (
          <>
            <div className="flex flex-wrap gap-3">
              <Card className="min-w-[9rem] flex-1 gap-1 py-4">
                <CardHeader className="px-4">
                  <CardDescription className="text-xs">合計（{DIRECTIONS.find((d) => d.value === direction)?.label}）</CardDescription>
                  <CardTitle className="text-xl tabular-nums">{yen(cofog.total.sum)}円</CardTitle>
                </CardHeader>
              </Card>
              <Card className="min-w-[9rem] flex-1 gap-1 py-4">
                <CardHeader className="px-4">
                  <CardDescription className="text-xs">COFOG 割当済み</CardDescription>
                  <CardTitle className="text-xl tabular-nums">{yen(cofog.assigned.sum)}円</CardTitle>
                </CardHeader>
              </Card>
              <Card className="min-w-[9rem] flex-1 gap-1 py-4">
                <CardHeader className="px-4">
                  <CardDescription className="text-xs">割当率（金額比・分母は合計）</CardDescription>
                  <CardTitle className="text-xl tabular-nums">{pct(cofog.assignedShare.sum)}</CardTitle>
                </CardHeader>
              </Card>
            </div>

            <section className="flex flex-col gap-2">
              <h2 className="font-medium">大分類別の金額（合計に対する構成比）</h2>
              <div
                className="flex h-6 overflow-hidden rounded-md border"
                role="img"
                aria-label={
                  `合計 ${yen(cofog.total.sum)} 円の内訳: ` +
                  breakdown.byDivision.map((v) => `${v.division} ${v.divisionLabel} ${pct(v.share)}`).join("、") +
                  `、未分類 ${pct(breakdown.unclassifiedShare)}`
                }
              >
                {breakdown.byDivision.map((v) => (
                  <div key={v.division} style={{ width: `${v.share * 100}%`, background: DIVISION_COLOR[v.division] }} />
                ))}
                {breakdown.unclassifiedSum > 0 && (
                  // ⚠️ 未分類はブランド色でも意味色でもない中立のグレー（DESIGN.md: データを表す面にブランド色を出さない）
                  <div
                    className="bg-muted-foreground/25"
                    style={{ width: `${breakdown.unclassifiedShare * 100}%` }}
                    title="未分類"
                  />
                )}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                {breakdown.byDivision.map((v) => (
                  <span key={v.division} className="inline-flex items-center gap-1.5">
                    <i aria-hidden className="size-2.5 rounded-sm" style={{ background: DIVISION_COLOR[v.division] }} />
                    <span className="font-medium text-foreground">{v.division}</span> {v.divisionLabel}{" "}
                    <span className="tabular-nums">{pct(v.share)}</span>
                  </span>
                ))}
                {breakdown.unclassifiedSum > 0 && (
                  <span className="inline-flex items-center gap-1.5">
                    <i aria-hidden className="bg-muted-foreground/25 size-2.5 rounded-sm" />
                    未分類 <span className="tabular-nums">{pct(breakdown.unclassifiedShare)}</span>
                  </span>
                )}
              </div>
              <p className="max-w-[72ch] text-xs leading-relaxed text-muted-foreground">
                割合の分母は{DIRECTIONS.find((d) => d.value === direction)?.label}の合計（{yen(cofog.total.sum)}円）。
                COFOG に割り当てられなかった分（分類不能・対象外・歳入は分類の軸なし）も分母に含めて出す
                — 割当済みだけを分母にすると、実際には使途が見えていない分まで「見えている」ことになる。
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-medium">大分類ごとの内訳</h2>
              <div className="overflow-x-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>コード</TableHead>
                      <TableHead>大分類</TableHead>
                      <TableHead className="text-right">明細数</TableHead>
                      <TableHead className="text-right">金額（円）</TableHead>
                      <TableHead className="text-right">合計に対する割合</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {breakdown.byDivision.map((v) => (
                      <TableRow key={v.division}>
                        <TableCell>
                          <span className="inline-flex items-center gap-1.5">
                            <i aria-hidden className="size-2.5 rounded-sm" style={{ background: DIVISION_COLOR[v.division] }} />
                            {v.division}
                          </span>
                        </TableCell>
                        <TableCell>{v.divisionLabel}</TableCell>
                        <TableCell className="text-right tabular-nums">{yen(v.count)}</TableCell>
                        <TableCell className="text-right tabular-nums">{yen(v.sum)}</TableCell>
                        <TableCell className="text-right tabular-nums">{pct(v.share)}</TableCell>
                      </TableRow>
                    ))}
                    {breakdown.unclassifiedSum > 0 && (
                      <TableRow>
                        <TableCell colSpan={2}>
                          <Badge variant="outline">未分類</Badge>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{yen(breakdown.unclassifiedCount)}</TableCell>
                        <TableCell className="text-right tabular-nums">{yen(breakdown.unclassifiedSum)}</TableCell>
                        <TableCell className="text-right tabular-nums">{pct(breakdown.unclassifiedShare)}</TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
              <p className="max-w-[72ch] text-xs leading-relaxed text-muted-foreground">
                COFOG への割当の根拠（款・項ごとにどの規則で決めたか）は、上部の
                「ELT パイプラインを見る」から開ける「COFOG の判断」タブにある。
              </p>
            </section>
          </>
        )}
      </main>
    </Layout>
  )
}

/** 団体セレクタ。地図を経由せず隣の団体へ移れるようにする（/pipeline/ と同じ導線） */
function JurisdictionSelect({ data, current }: { data: PipelineData; current: string }) {
  if (data.jurisdictions.length <= 1) {
    const only = data.jurisdictions.find((j) => j.code === current)
    return <span className="shrink-0 text-sm font-medium">{only?.report.meta.jurisdictionName}</span>
  }
  return (
    <Select
      items={data.jurisdictions.map((j) => ({ value: j.code, label: j.report.meta.jurisdictionName }))}
      value={current}
      onValueChange={(v) => {
        window.location.href = withBase(`/analysis/${v}/`)
      }}
    >
      <SelectTrigger aria-label="団体">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {data.jurisdictions.map((j) => (
            <SelectItem key={j.code} value={j.code}>
              {j.report.meta.jurisdictionName}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

/**
 * 未収録団体のページ（`/analysis/<未収録の団体コード>/`）。
 * `/pipeline/` の `NotCollectedPage` と同じ扱い（AGENTS.md タスク仕様）。
 */
function AnalysisNotCollected({
  code,
  name,
  jurisdictions,
}: {
  code: string
  name?: string
  jurisdictions: { code: string; name: string }[]
}) {
  return (
    <Layout>
      <main className="mx-auto flex max-w-2xl flex-col gap-4 p-6">
        <h1 className="text-xl font-semibold">{name ?? code}</h1>
        <Alert>
          <AlertTitle>この団体はまだ収録していません</AlertTitle>
          <AlertDescription>
            {name ?? code}（団体コード {code}）の予算データは、まだ fudoki のパイプラインを通していません。
          </AlertDescription>
        </Alert>
        {jurisdictions.length > 0 && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">収録済みの団体を見る:</span>
            <Select
              items={jurisdictions.map((j) => ({ value: j.code, label: j.name }))}
              onValueChange={(v) => {
                window.location.href = withBase(`/analysis/${v}/`)
              }}
            >
              <SelectTrigger aria-label="団体">
                <SelectValue placeholder="団体を選ぶ" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {jurisdictions.map((j) => (
                    <SelectItem key={j.code} value={j.code}>
                      {j.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
        )}
      </main>
    </Layout>
  )
}
