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
import { useEffect, useState } from "react"
import { JurisdictionSelect } from "@/components/jurisdiction-select"
import { Layout } from "@/components/layout"
import { NotCollectedPage } from "@/components/not-collected-page"
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
import { withBase } from "@/lib/utils"
import { DIVISION_COLOR, loadPipeline, pct, senYen, type Direction, type PipelineData, count } from "@/lib/pipeline"
import { apiClient } from "@/lib/api-client"
import type { CofogBreakdown, CofogNodeFilter } from "@/lib/cofog-tree"
import { CofogTree } from "@/components/cofog-tree"
import { CofogStatement } from "@/components/cofog-statement"

/** contract 型を web 側で二重宣言しない。API 呼び出しの戻り値からそのまま導出する */

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
      <NotCollectedPage
        code={urlCode!}
        name={jurisdictionName}
        jurisdictions={data!.jurisdictions.map((j) => ({
          code: j.code,
          name: j.report.meta.jurisdictionName,
        }))}
        basePath="analysis"
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
  const [selected, setSelected] = useState<CofogNodeFilter | null>(null)
  // 明細の金額表示に使う予算段階。direction には依存しない（団体単位の宣言）ので別 effect にする
  const [amountPhase, setAmountPhase] = useState<string | null>(null)

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
    setSelected(null) // 団体・年度・歳出歳入を切り替えたら選択中の分類も捨てる（別の集計に対する古い選択を残さない）
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

  useEffect(() => {
    let stale = false
    setAmountPhase(null)
    apiClient
      .getBudget({ budget: `${code}:${year}` })
      .then((res) => {
        if (!stale) setAmountPhase(res.budget.amountPhase)
      })
      .catch(() => {
        // 明細の金額欄が「—」になるだけなので、ここは静かに諦める（apiError は cofog 取得の失敗用）
      })
    return () => {
      stale = true
    }
  }, [code, year])

  // `cofog.tree` はすでに division → group → class の木として届く（report/budget/cofog.ts の
  // `buildCofogTree()` が組む）。大分類ごとの帯グラフは、その木の最上位ノード（1団体1系列）を
  // そのまま使う ── byDivision を別に取り出して割合を計算し直すと二重集計になる。
  // 割合（`share`）と未分類（`cofog.unclassified`）も生成側が持つので、画面では割り算しない
  // （AGENTS.md「集計は1箇所」）。

  return (
    <Layout>
      <main className="mx-auto flex max-w-[1100px] flex-col gap-8 p-4 pb-24">
        <section className="flex flex-col gap-4">
          <div className="mb-2 flex flex-wrap items-baseline gap-3">
            <h1 className="text-xl font-semibold">支出分析</h1>
            <AnalysisJurisdictionSelect data={data} current={code} />
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
        ) : !cofog ? (
          <p className="text-sm text-muted-foreground">読み込み中…</p>
        ) : (
          <>
            <div className="flex flex-wrap gap-3">
              <Card className="min-w-[9rem] flex-1 gap-1 py-4">
                <CardHeader className="px-4">
                  <CardDescription className="text-xs">合計（{DIRECTIONS.find((d) => d.value === direction)?.label}）・千円</CardDescription>
                  <CardTitle className="text-xl tabular-nums">{senYen(cofog.total.sum)}千円</CardTitle>
                </CardHeader>
              </Card>
              <Card className="min-w-[9rem] flex-1 gap-1 py-4">
                <CardHeader className="px-4">
                  <CardDescription className="text-xs">COFOG 割当済み・千円</CardDescription>
                  <CardTitle className="text-xl tabular-nums">{senYen(cofog.assigned.sum)}千円</CardTitle>
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
                  `合計 ${senYen(cofog.total.sum)} 千円の内訳: ` +
                  cofog.tree.map((v) => `${v.code} ${v.label} ${pct(v.share)}`).join("、") +
                  `、未分類 ${pct(cofog.unclassified.share)}`
                }
              >
                {cofog.tree.map((v) => (
                  <div key={v.code} style={{ width: `${v.share * 100}%`, background: DIVISION_COLOR[v.code] }} />
                ))}
                {cofog.unclassified.sum > 0 && (
                  // ⚠️ 未分類はブランド色でも意味色でもない中立のグレー（DESIGN.md: データを表す面にブランド色を出さない）
                  <div
                    className="bg-muted-foreground/25"
                    style={{ width: `${cofog.unclassified.share * 100}%` }}
                    title="未分類"
                  />
                )}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                {cofog.tree.map((v) => (
                  <span key={v.code} className="inline-flex items-center gap-1.5">
                    <i aria-hidden className="size-2.5 rounded-sm" style={{ background: DIVISION_COLOR[v.code] }} />
                    <span className="font-medium text-foreground">{v.code}</span> {v.label}{" "}
                    <span className="tabular-nums">{pct(v.share)}</span>
                  </span>
                ))}
                {cofog.unclassified.sum > 0 && (
                  <span className="inline-flex items-center gap-1.5">
                    <i aria-hidden className="bg-muted-foreground/25 size-2.5 rounded-sm" />
                    未分類 <span className="tabular-nums">{pct(cofog.unclassified.share)}</span>
                  </span>
                )}
              </div>
              <p className="max-w-[72ch] text-xs leading-relaxed text-muted-foreground">
                割合の分母は{DIRECTIONS.find((d) => d.value === direction)?.label}の合計（{senYen(cofog.total.sum)}千円）。
                COFOG に割り当てられなかった分（分類不能・対象外・歳入は分類の軸なし）も分母に含めて出す
                — 割当済みだけを分母にすると、実際には使途が見えていない分まで「見えている」ことになる。
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-medium">分類ごとの内訳（大分類 → 中分類 → 小分類）</h2>
              <p className="max-w-[72ch] text-xs leading-relaxed text-muted-foreground">
                行を開くとさらに細かい分類へ降りられる。「（〜までで止まった分）」は
                規則がそこより下まで判断していない金額で、割合の高さは分類の質を意味しない。
                行をクリックすると、その分類に属する明細を下に出す。
              </p>
              {cofog.tree.length > 0 && (
                <CofogTree
                  nodes={cofog.tree}
                  selected={selected}
                  onSelect={setSelected}
                  renderDetail={(filter) =>
                    amountPhase ? (
                      <CofogStatement budget={`${code}:${year}`} direction={direction} filter={filter} amountPhase={amountPhase} />
                    ) : null
                  }
                />
              )}
              {cofog.unclassified.sum > 0 && (
                <div className="flex items-center gap-2 rounded-lg border px-2 py-1.5 text-sm text-muted-foreground">
                  <Badge variant="outline">未分類</Badge>
                  {count(cofog.unclassified.count)}件 ・ {senYen(cofog.unclassified.sum)}千円 ・{" "}
                  {pct(cofog.unclassified.share)}
                  <span className="ml-1 text-xs">（分類不能・対象外。明細は下の分類ツリーには出ない）</span>
                </div>
              )}
            </section>

            <p className="max-w-[72ch] text-xs leading-relaxed text-muted-foreground">
              COFOG への割当の根拠（款・項ごとにどの規則で決めたか）は、上部の
              「ELT パイプラインを見る」から開ける「COFOG の判断」タブにある。
            </p>
          </>
        )}
      </main>
    </Layout>
  )
}

/** 団体セレクタ。地図を経由せず隣の団体へ移れるようにする（/pipeline/ と同じ導線） */
function AnalysisJurisdictionSelect({ data, current }: { data: PipelineData; current: string }) {
  const options = data.jurisdictions.map((j) => ({ code: j.code, name: j.report.meta.jurisdictionName }))
  // 団体が1つなら切り替える先が無い。分析はパイプラインと違って見出しに団体名が無いので、名称だけ出す
  if (options.length <= 1) {
    return <span className="shrink-0 text-sm font-medium">{options.find((o) => o.code === current)?.name}</span>
  }
  return <JurisdictionSelect jurisdictions={options} value={current} basePath="analysis" />
}
