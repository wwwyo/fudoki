/**
 * COFOG ツリーで選んだ分類に属する予算の明細行。
 *
 * ⚠️ **全件は取りに行かない。** 狛江市は1万3千行を超える。`pageSize` を絞り、
 * 「続きを読む」で `nextPageToken` を渡して追記する（AGENTS.md タスク仕様）。
 */
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { yen, type Direction } from "@/lib/pipeline"
import type { CofogNodeFilter } from "@/lib/cofog-tree"
import { apiClient } from "@/lib/api-client"

type BudgetLinesResult = Awaited<ReturnType<typeof apiClient.getBudgetLines>>
type BudgetLine = BudgetLinesResult["lines"][number]

/**
 * `view: "FULL"` で取った BudgetLine。contract 側は BASIC と FULL を同じスキーマで
 * 表現しており、hierarchy / amounts / judgments は型の上では常に optional
 * （apps/api/src/contract/budgets.ts の budgetLineSchema）。ここでは FULL しか要求しないので、
 * 「本当に来ているか」を実行時に検査してから型を絞る（?? での握りつぶしはしない。
 * AGENTS.md「型が効かない場所は壊れる場所」）。
 */
type FullBudgetLine = BudgetLine & {
  hierarchy: NonNullable<BudgetLine["hierarchy"]>
  amounts: NonNullable<BudgetLine["amounts"]>
  judgments: NonNullable<BudgetLine["judgments"]>
}

/** view=FULL で要求したのに hierarchy/amounts/judgments が欠けていたら、握りつぶさずに投げる */
function assertFullBudgetLine(line: BudgetLine): FullBudgetLine {
  if (!line.hierarchy || !line.amounts || !line.judgments) {
    throw new Error(
      `expected view=FULL fields (hierarchy/amounts/judgments) on budgetLineId=${line.budgetLineId}, but at least one is missing`,
    )
  }
  return line as FullBudgetLine
}

const PAGE_SIZE = 50

/**
 * ⚠️ **group / class の値はドットを含む（`04.5`）ので必ず引用符で囲む。**
 * AIP-160 サブセット（apps/api/src/lib/filter.ts）の非引用トークンは `[\w-]+` までしか
 * 許さず、ドットが混ざると構文エラーになる（実測: `cofog.group = 05.1` が 400 で弾かれた）。
 */
function filterExpr(filter: CofogNodeFilter, direction: Direction): string {
  const parts = [`direction = "${direction}"`, `cofog.division = "${filter.division}"`]
  if (filter.group !== undefined) parts.push(`cofog.group = "${filter.group}"`)
  if (filter.class !== undefined) parts.push(`cofog.class = "${filter.class}"`)
  return parts.join(" AND ")
}

export function CofogStatement({
  budget,
  direction,
  filter,
  amountPhase,
}: {
  budget: string
  direction: Direction
  filter: CofogNodeFilter
  amountPhase: string
}) {
  const [lines, setLines] = useState<FullBudgetLine[]>([])
  const [nextPageToken, setNextPageToken] = useState<string | undefined>(undefined)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /**
   * 「いま表示している問い合わせ」の世代。分類・年度・歳出歳入を切り替えるたびに進める。
   * ⚠️ 初回取得の stale フラグだけでは足りない — loadMore はエフェクトの外で走るので、
   * 切り替え直後に古い応答が返ると別条件の行が現在の明細に足される。
   */
  const requestId = useRef(0)

  useEffect(() => {
    const id = ++requestId.current
    const isStale = () => requestId.current !== id
    setLines([])
    setNextPageToken(undefined)
    setError(null)
    setLoading(true)
    apiClient
      .getBudgetLines({ budget, view: "FULL", filter: filterExpr(filter, direction), pageSize: PAGE_SIZE })
      .then((res) => {
        if (isStale()) return
        setLines(res.lines.map(assertFullBudgetLine))
        setNextPageToken(res.nextPageToken)
      })
      .catch((e: unknown) => {
        if (!isStale()) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!isStale()) setLoading(false)
      })
    // アンマウントでも世代を進める（外れた画面へ書き戻さない）
    return () => {
      requestId.current++
    }
    // biome-ignore lint/correctness/useExhaustiveDependencies: filter は毎回新しいオブジェクトなので中身で見る
  }, [budget, direction, filter.division, filter.group, filter.class])

  const loadMore = () => {
    if (!nextPageToken) return
    const id = requestId.current
    const isStale = () => requestId.current !== id
    setLoading(true)
    apiClient
      .getBudgetLines({ budget, view: "FULL", filter: filterExpr(filter, direction), pageSize: PAGE_SIZE, pageToken: nextPageToken })
      .then((res) => {
        if (isStale()) return
        setLines((prev) => [...prev, ...res.lines.map(assertFullBudgetLine)])
        setNextPageToken(res.nextPageToken)
      })
      .catch((e: unknown) => {
        if (!isStale()) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!isStale()) setLoading(false)
      })
  }

  if (error) return <p className="text-sm text-destructive">明細を読み込めませんでした: {error}</p>

  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>科目</TableHead>
              <TableHead>事業名</TableHead>
              <TableHead className="text-right">金額（円）</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {lines.map((l) => {
              // FullBudgetLine（assertFullBudgetLine で検査済み）なので hierarchy / judgments / amounts
              // は必ず配列・オブジェクトとして存在する。`?.` は要らない ── 個々の要素が見つからない
              // ケース（この phase の amounts エントリが無い等）だけ undefined になり得る
              const amount = l.amounts.find((a) => a.phase === amountPhase)?.amount
              return (
                <TableRow key={l.budgetLineId}>
                  <TableCell className="whitespace-nowrap text-xs">
                    {l.hierarchy.map((h) => h.label ?? h.code).join(" › ") || "—"}
                  </TableCell>
                  <TableCell className="text-sm">{l.judgments.projectName ?? <span className="text-muted-foreground">—</span>}</TableCell>
                  <TableCell className="text-right tabular-nums">{amount !== undefined ? yen(amount) : "—"}</TableCell>
                </TableRow>
              )
            })}
            {lines.length === 0 && !loading && (
              <TableRow>
                <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                  この分類に属する明細はありません
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      {loading && <p className="text-xs text-muted-foreground">読み込み中…</p>}
      {nextPageToken && !loading && (
        <Button variant="outline" size="sm" className="self-start" onClick={loadMore}>
          続きを読む
        </Button>
      )}
    </div>
  )
}
