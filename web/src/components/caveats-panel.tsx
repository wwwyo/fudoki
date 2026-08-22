/** 確定できなかったこと。**判断が割れているものを埋もれさせない** */
import type { ReportData } from '@/lib/pipeline'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export function CaveatsPanel({ report }: { report: ReportData }) {
  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3">
        <p className="max-w-[72ch] text-sm text-muted-foreground">
          設計文書と実データが食い違った点、および確定できなかったこと。推測で埋めずに残す。
        </p>
        <div className="grid gap-3 lg:grid-cols-2">
          {report.caveats.map((c, i) => (
            <Card key={i}>
              <CardHeader><CardTitle className="text-sm leading-snug">{c.topic}</CardTitle></CardHeader>
              <CardContent className="text-sm leading-relaxed text-muted-foreground">
                {c.body.replace(/\*\*/g, '')}
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">2団体目へ展開するときに何を確かめるか</h3>
        <p className="max-w-[72ch] text-sm text-muted-foreground">
          「再利用可能と判明した」は1団体では言えない。判定できないものは判定できないと書く。
        </p>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow><TableHead>区分</TableHead><TableHead>要素</TableHead><TableHead>2団体目で確かめること</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {report.portability.map((p, i) => (
                <TableRow key={i}>
                  <TableCell className="whitespace-nowrap"><Badge variant="outline">{p.kind}</Badge></TableCell>
                  <TableCell className="text-sm">{p.element}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">{p.verifyNext}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">独自に定義した ColumnType</h3>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow><TableHead>名前</TableHead><TableHead>dataType</TableHead><TableHead>unique</TableHead><TableHead>なぜ独自定義が要るか</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {report.customColumnTypes.map((c, i) => (
                <TableRow key={i}>
                  <TableCell className="whitespace-nowrap font-mono text-xs">{c.name}</TableCell>
                  <TableCell className="text-xs">{c.dataType}</TableCell>
                  <TableCell className="text-xs">{c.unique ? '必須' : '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{c.why}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  )
}
