/**
 * 年度ごとの収録状況。
 *
 * ⚠️ **団体で1つに畳んだ数字は、年度の主張には使えない。**
 * 統計カードや COFOG の節はどれも全年度の合算で、名称や事業名が
 * 一部の年度にしか無いことがそこには現れない（実際、狛江市は
 * 2018〜2019年度に科目の名称も事業名もゼロだが、合算では 90% 台に見える）。
 * ここは**年度を軸に置いた唯一の面**で、収録範囲を年度ごとに読む場所。
 *
 * 集計はしない。割合はすべて生成側（`report/budget/build.ts`）が持つ。
 */
import type { ReportData } from "@/lib/pipeline"
import { pct, yenShort } from "@/lib/pipeline"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

const DIRECTION_JA = { expenditure: "歳出", revenue: "歳入" } as const

/** 該当が無い欄。**0% と区別する** — 「無い」と「取れていない」は別の事実 */
const NONE = <span className="text-muted-foreground">—</span>

/**
 * 割合のセル。**低いことを失敗として色付けしない。**
 * 名称も COFOG の深さも、達成率ではなく現在地である（原典に無いものは取れない）。
 * ゼロだけは「その年度は1件も無い」という別種の事実なので、目に入るようにする。
 */
function Share({ value, title }: { value: number; title?: string }) {
  return (
    <span
      className={value === 0 ? "text-muted-foreground" : undefined}
      title={title}
    >
      {pct(value)}
    </span>
  )
}

export function CoveragePanel({ report }: { report: ReportData }) {
  // 年度 → direction の順。**同じ年度の歳出と歳入を隣に置く**
  // （原典が別の資料なので、片方だけ名称が取れている年度がある）
  const rows = [...report.coverage].sort(
    (a, b) => a.fiscalYear - b.fiscalYear || (a.direction === "expenditure" ? -1 : 1),
  )

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-[80ch] text-sm text-muted-foreground">
        年度ごとに、何がどこまで取れているか。原典は年度で割れる
        （名称の載った資料がある年度と無い年度があり、列の構成や単位も変わる）ので、
        収録範囲は年度ごとにしか正しく書けない。
        割合の低さは失敗ではなく、原典に無いものはここでも無い、という現在地を表す。
      </p>

      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>年度</TableHead>
              <TableHead></TableHead>
              <TableHead className="text-right">行</TableHead>
              <TableHead className="text-right">金額</TableHead>
              <TableHead className="text-right">
                <WithHint hint="科目（款・項・目）の名称がある行の割合。原典に名称の列が無い団体は、決算書 PDF から解決できた年度にだけ付く">
                  款 / 項 / 目の名称
                </WithHint>
              </TableHead>
              <TableHead className="text-right">
                <WithHint hint="COFOG を割り当てられた金額の割合。歳入に COFOG の割当は無い">
                  COFOG 割当
                </WithHint>
              </TableHead>
              <TableHead className="text-right">
                <WithHint hint="割当済みの金額のうち、group（2桁目）/ class（3桁目）まで降りているもの。分母は割当済みだけ">
                  group / class 到達
                </WithHint>
              </TableHead>
              <TableHead className="text-right">
                <WithHint hint="大事業に名前が付いた割合。分母は全会計の大事業で、括弧内は名称の出所（決算書 PDF の事項別明細）が覆う範囲に対する割合">
                  事業名
                </WithHint>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((c) => (
              <TableRow key={`${c.fiscalYear}-${c.direction}`}>
                <TableCell className="whitespace-nowrap tabular-nums">
                  {c.fiscalYear}年度
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">{DIRECTION_JA[c.direction]}</Badge>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {c.rows.toLocaleString("ja-JP")}
                </TableCell>
                <TableCell className="text-right tabular-nums" title={`${c.sum.toLocaleString("ja-JP")} 円`}>
                  {yenShort(c.sum)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {/* 階層ごとに出す。**款だけ解決した年度がありうる**ので1つに畳まない */}
                  <Share value={c.named.kan} /> / <Share value={c.named.kou} /> /{" "}
                  <Share value={c.named.moku} />
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {c.cofog ? <Share value={c.cofog.assignedShare.sum} /> : NONE}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {c.cofog ? (
                    <>
                      <Share value={c.cofog.groupShare} /> /{" "}
                      <Share value={c.cofog.classShare} />
                    </>
                  ) : (
                    NONE
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {c.projectNames ? (
                    <span
                      title={`${c.projectNames.named} / ${c.projectNames.total} 大事業（出所が覆う範囲 ${c.projectNames.inSourceScope}）`}
                    >
                      <Share value={c.projectNames.share} /> (
                      <Share value={c.projectNames.shareInScope} />)
                    </span>
                  ) : (
                    NONE
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

/** 見出しの語義。列名だけでは分母が分からないので、定義をその場に置く */
function WithHint({ hint, children }: { hint: string; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger className="focus-visible:ring-ring/50 rounded-sm underline decoration-dotted underline-offset-4 focus-visible:ring-[3px] focus-visible:outline-none">
        {children}
      </TooltipTrigger>
      <TooltipContent className="max-w-[40ch]">{hint}</TooltipContent>
    </Tooltip>
  )
}
