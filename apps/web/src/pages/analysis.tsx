/**
 * 団体の支出を COFOG（政府支出の機能別分類）別に見る分析ダッシュボード。
 *
 * `/pipeline/` と違って**静的な生成物を読まない**。COFOG の内訳は
 * `apps/api` の `budgets:aggregate`（`groupBy: ['cofog.class']`、`/rpc`）から取る ──
 * 数字は API 側（`report/budget/cofog.ts` 由来）が持ち、ここでは足し直さない
 * （AGENTS.md の「集計は1箇所」）。木の組み立て（並べ替え）だけを `lib/cofog-tree.ts` で行う。
 *
 * ⚠️ **歳入に COFOG 内訳は無い。** cofog_status が歳入では常に not-applicable なので、
 * `groupBy: ['cofog.class']` は歳入では 400 になる。ただし歳入の「合計」自体は
 * `budgets:aggregate` の別の軸（`groupBy: ['fiscalYear']`、filter は jurisdiction のみ）で
 * 引ける ── COFOG と違い fiscalYear 軸は歳入でも意味を持つ、かつ fund=all を取れる唯一の軸
 * （hierarchy 軸は款・項のコードが会計内でしか一意でないため fund=all を取れない）。
 *
 * 「収録済みか」の判定と団体セレクタだけは `pipeline.json`（`loadPipeline`）を再利用する。
 * ELT パイプラインを通った団体の集合と、budget API が返せる団体の集合は同じ配布物から
 * 生成されるので一致するはずで、ここだけのために別の一覧を持つ理由が無い。
 */
import { useEffect, useState } from "react"
import { FiscalYearSelect } from "@/components/fiscal-year-select"
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
import { share } from "@fudoki/report/budget/cofog"
import { apiClient } from "@/lib/api-client"
import { buildCofogTree, type AggregateBudgetsResponse, type CofogNodeFilter, type CofogTreeNode } from "@/lib/cofog-tree"
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
  const [agg, setAgg] = useState<AggregateBudgetsResponse | null>(null)
  // 歳入の合計。budgets:aggregate の fiscalYear 軸（filter=jurisdiction のみ、groupBy=['fiscalYear']）の
  // 応答をそのまま持つ（画面では足し算しない。AGENTS.md「集計は1箇所」）。**全年度ぶんを1回だけ取り**、
  // 選択中の年度のセルは下の `revenueTotal` で都度取り出す ── year を fetch の依存に入れると、
  // 「その団体の全年度」を返す呼び出しを年度を切り替えるたびに丸ごと取り直すことになる。
  const [revenueCells, setRevenueCells] = useState<AggregateBudgetsResponse["cells"] | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [selected, setSelected] = useState<CofogNodeFilter | null>(null)
  // 明細の金額表示に使う予算段階。budgets:aggregate の phase（typed field）にも使う。
  // 団体と年度だけで決まり、歳出・歳入の切り替えには依存しない。
  // 型は getBudget の応答からそのまま導出する（union を web 側で書き直さない）。
  const [amountPhase, setAmountPhase] = useState<Awaited<ReturnType<typeof apiClient.getBudget>>["budget"]["amountPhase"] | null>(null)

  // 団体を切り替えたら年度もその団体の最新年度に戻す（前の団体にしか無い年度を持ち越さない）。
  // 依存は `code` だけにする — `years` を足すと配列の参照が変わるたびに発火し、
  // ユーザーが選んだ年度を勝手に最新へ戻してしまう
  useEffect(() => {
    setYear(years.at(-1)!)
  }, [code])

  // 団体・年度・歳出歳入を切り替えたら選択中の分類も捨てる（別の集計に対する古い選択を残さない）。
  // ネットワークを伴わないので、他の effect と分けても往復は増えない。
  useEffect(() => {
    setSelected(null)
  }, [code, year, direction])

  // amountPhase は団体と年度だけで決まる（procedure/budgets.ts）。歳出・歳入のトグルでは
  // 値が変わらないので、direction を依存に入れない ── 入れるとトグルのたびに取り直すことになる。
  useEffect(() => {
    let stale = false
    setAmountPhase(null)
    setApiError(null)
    apiClient
      .getBudget({ budget: `${code}:${year}` })
      .then((res) => {
        if (!stale) setAmountPhase(res.budget.amountPhase)
      })
      .catch((e: unknown) => {
        if (!stale) setApiError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      stale = true
    }
  }, [code, year])

  // ⚠️ **歳入に COFOG 内訳は無い**（cofog_status が歳入では常に not-applicable）ので、
  // groupBy=['cofog.class'] は歳出だけに使う（fund=all を取れるのはこの軸だけで、hierarchy 軸は
  // 款・項のコードが会計内でしか一意でないため使えない。procedure/budgets.ts の同じ判断）。
  useEffect(() => {
    setAgg(null)
    if (direction !== "expenditure" || !amountPhase) return
    let stale = false
    apiClient
      .aggregateBudgets({
        filter: `jurisdiction = "${code}" AND fiscalYear = ${year}`,
        direction: "expenditure",
        phase: amountPhase,
        groupBy: ["cofog.class"],
      })
      .then((r) => {
        if (!stale) setAgg(r)
      })
      .catch((e: unknown) => {
        if (!stale) setApiError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      stale = true
    }
  }, [code, year, direction, amountPhase])

  // 歳入は fiscalYear 軸（filter=jurisdiction のみ）でその団体の全年度をまとめて取る。
  // 依存に `year` を入れない ── 年度の選び直しは下の `revenueTotal` 側（フェッチ済みの
  // cells から探すだけ）で行い、ここでは取り直さない。
  useEffect(() => {
    setRevenueCells(null)
    if (direction !== "revenue" || !amountPhase) return
    let stale = false
    apiClient
      .aggregateBudgets({
        filter: `jurisdiction = "${code}"`,
        direction: "revenue",
        phase: amountPhase,
        groupBy: ["fiscalYear"],
      })
      .then((r) => {
        if (!stale) setRevenueCells(r.cells)
      })
      .catch((e: unknown) => {
        if (!stale) setApiError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      stale = true
    }
  }, [code, direction, amountPhase])

  // 取得済みの revenueCells から選択中の年度のセルを都度取り出す（ネットワークを伴わない）。
  // 見つからない場合は本来ここに来ないはずの状態（全年度を取っているので必ずあるはず）なので、
  // 元の実装と同じく明示的なエラーとして扱う。
  useEffect(() => {
    if (!revenueCells) return
    const hasCell = revenueCells.some((c) => c.dimensions[0]?.code === String(year))
    if (!hasCell) setApiError(`no fiscalYear=${year} cell in revenue fiscalYear aggregate for ${code}`)
  }, [revenueCells, year, code])

  const revenueTotal = (() => {
    if (!revenueCells) return null
    const cell = revenueCells.find((c) => c.dimensions[0]?.code === String(year))
    return cell ? { lineCount: cell.lineCount, amount: cell.amount } : null
  })()

  // 木の組み立て（並べ替え）は lib/cofog-tree.ts の buildCofogTree が行う。ここでは呼ぶだけ。
  const tree: CofogTreeNode[] = agg ? buildCofogTree(agg) : []
  // `total`/`residual` は budgets:aggregate の応答から来る値のみを使い、画面で割り算しない
  // （AGENTS.md「集計は1箇所」）。足し算・引き算だけで求まる値はここで組む。
  const summary =
    agg?.total && agg.residual
      ? (() => {
          const total = agg.total
          const { unclassifiable, outOfScope } = agg.residual
          const unclassifiedSum = unclassifiable.amount + outOfScope.amount
          const unclassifiedCount = unclassifiable.lineCount + outOfScope.lineCount
          // share は子の和で作らない（cofog-tree.ts と同じ理由）。total.amount から作り直す
          const unclassifiedShare = share(unclassifiedSum, total.amount)
          return {
            total,
            assigned: { sum: total.amount - unclassifiedSum, count: total.lineCount - unclassifiedCount },
            assignedShare: 1 - unclassifiedShare,
            unclassified: { sum: unclassifiedSum, count: unclassifiedCount, share: unclassifiedShare },
          }
        })()
      : null

  return (
    <Layout>
      <main className="mx-auto flex max-w-[1100px] flex-col gap-8 p-4 pb-24">
        <section className="flex flex-col gap-4">
          <div className="mb-2 flex flex-wrap items-baseline gap-3">
            <h1 className="text-xl font-semibold">支出分析</h1>
            <AnalysisJurisdictionSelect data={data} current={code} />
            {years.length > 1 ? (
              // allowAll を渡さないので `y` が null になることはない（「全年度」の選択肢が無い）
              <FiscalYearSelect years={years} value={year} onChange={(y) => setYear(y!)} className="w-28" />
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
              fudoki の API（api.fudoki.dev）から{direction === "expenditure" ? "COFOG 別内訳" : "合計"}
              を取得できませんでした。
              API が止まっているか、この団体・年度の組み合わせがまだ収録されていない可能性があります。
              <br />
              {apiError}
            </AlertDescription>
          </Alert>
        ) : direction !== "expenditure" ? (
          // ⚠️ 歳入は COFOG 軸が無い（procedure/budgets.ts: cofog_status は歳入で常に
          // not-applicable）ので、budgets:aggregate の fiscalYear 軸から合計だけを出す
          // （COFOG が無いことを言うのと、合計を budgets:aggregate から出すことは両立する）。
          !revenueTotal ? (
            <p className="text-sm text-muted-foreground">読み込み中…</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-3">
                <Card className="min-w-[9rem] flex-1 gap-1 py-4">
                  <CardHeader className="px-4">
                    <CardDescription className="text-xs">合計（歳入）・千円</CardDescription>
                    <CardTitle className="text-xl tabular-nums">{senYen(revenueTotal.amount)}千円</CardTitle>
                  </CardHeader>
                </Card>
              </div>
              <Alert>
                <AlertTitle>歳入は COFOG の対象外です</AlertTitle>
                <AlertDescription>
                  COFOG（Classification of the Functions of Government）は政府の支出を機能別に分類する体系で、
                  歳入には分類の軸そのものが無い。この分析ダッシュボードの COFOG 内訳は歳出のみを対象にする
                  （上の合計は{count(revenueTotal.lineCount)}件の歳入明細の合計そのもので、分類は含まない）。
                </AlertDescription>
              </Alert>
            </>
          )
        ) : !summary ? (
          <p className="text-sm text-muted-foreground">読み込み中…</p>
        ) : (
          <>
            <div className="flex flex-wrap gap-3">
              <Card className="min-w-[9rem] flex-1 gap-1 py-4">
                <CardHeader className="px-4">
                  <CardDescription className="text-xs">合計（{DIRECTIONS.find((d) => d.value === direction)?.label}）・千円</CardDescription>
                  <CardTitle className="text-xl tabular-nums">{senYen(summary.total.amount)}千円</CardTitle>
                </CardHeader>
              </Card>
              <Card className="min-w-[9rem] flex-1 gap-1 py-4">
                <CardHeader className="px-4">
                  <CardDescription className="text-xs">COFOG 割当済み・千円</CardDescription>
                  <CardTitle className="text-xl tabular-nums">{senYen(summary.assigned.sum)}千円</CardTitle>
                </CardHeader>
              </Card>
              <Card className="min-w-[9rem] flex-1 gap-1 py-4">
                <CardHeader className="px-4">
                  <CardDescription className="text-xs">割当率（金額比・分母は合計）</CardDescription>
                  <CardTitle className="text-xl tabular-nums">{pct(summary.assignedShare)}</CardTitle>
                </CardHeader>
              </Card>
            </div>

            <section className="flex flex-col gap-2">
              <h2 className="font-medium">大分類別の金額（合計に対する構成比）</h2>
              <div
                className="flex h-6 overflow-hidden rounded-md border"
                role="img"
                aria-label={
                  `合計 ${senYen(summary.total.amount)} 千円の内訳: ` +
                  tree.map((v) => `${v.code} ${v.label} ${pct(v.share)}`).join("、") +
                  `、未分類 ${pct(summary.unclassified.share)}`
                }
              >
                {tree.map((v) => (
                  <div key={v.code} style={{ width: `${v.share * 100}%`, background: DIVISION_COLOR[v.code] }} />
                ))}
                {summary.unclassified.sum > 0 && (
                  // ⚠️ 未分類はブランド色でも意味色でもない中立のグレー（DESIGN.md: データを表す面にブランド色を出さない）
                  <div
                    className="bg-muted-foreground/25"
                    style={{ width: `${summary.unclassified.share * 100}%` }}
                    title="未分類"
                  />
                )}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                {tree.map((v) => (
                  <span key={v.code} className="inline-flex items-center gap-1.5">
                    <i aria-hidden className="size-2.5 rounded-sm" style={{ background: DIVISION_COLOR[v.code] }} />
                    <span className="font-medium text-foreground">{v.code}</span> {v.label}{" "}
                    <span className="tabular-nums">{pct(v.share)}</span>
                  </span>
                ))}
                {summary.unclassified.sum > 0 && (
                  <span className="inline-flex items-center gap-1.5">
                    <i aria-hidden className="bg-muted-foreground/25 size-2.5 rounded-sm" />
                    未分類 <span className="tabular-nums">{pct(summary.unclassified.share)}</span>
                  </span>
                )}
              </div>
              <p className="max-w-[72ch] text-xs leading-relaxed text-muted-foreground">
                割合の分母は{DIRECTIONS.find((d) => d.value === direction)?.label}の合計（{senYen(summary.total.amount)}千円）。
                COFOG に割り当てられなかった分（分類不能・対象外）も分母に含めて出す
                — 割当済みだけを分母にすると、実際には使途が見えていない分まで「見えている」ことになる。
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-medium">分類ごとの内訳（大分類 → 中分類 → 小分類）</h2>
              <p className="max-w-[72ch] text-xs leading-relaxed text-muted-foreground">
                行を開くとさらに細かい分類へ降りられる。「（分類が完全でない分）」は
                規則がそこより下まで判断していない金額で、割合の高さは分類の質を意味しない。
                行をクリックすると、その分類に属する明細を下に出す。
              </p>
              {tree.length > 0 && (
                <CofogTree
                  nodes={tree}
                  selected={selected}
                  onSelect={setSelected}
                  renderDetail={(filter) =>
                    amountPhase ? (
                      <CofogStatement budget={`${code}:${year}`} direction={direction} filter={filter} amountPhase={amountPhase} />
                    ) : null
                  }
                />
              )}
              {summary.unclassified.sum > 0 && (
                <div className="flex items-center gap-2 rounded-lg border px-2 py-1.5 text-sm text-muted-foreground">
                  <Badge variant="outline">未分類</Badge>
                  {count(summary.unclassified.count)}件 ・ {senYen(summary.unclassified.sum)}千円 ・{" "}
                  {pct(summary.unclassified.share)}
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
