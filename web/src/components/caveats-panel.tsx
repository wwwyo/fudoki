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
        <h3 className="font-medium">他団体へ展開できるか（2団体目を通した結果）</h3>
        <p className="max-w-[72ch] text-sm text-muted-foreground">
          「再利用可能と判明した」は1団体では言えない。2団体目（狛江市）を通して分かったことと、まだ判定できないことを分けて書く。
        </p>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow><TableHead>区分</TableHead><TableHead>要素</TableHead><TableHead>根拠 / 次に確かめること</TableHead></TableRow>
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

      {report.yearSurvey && (
        <section className="flex flex-col gap-2">
          <h3 className="font-medium">他年度との互換性（調査のみ。収録はしない）</h3>
          <p className="max-w-[72ch] text-sm text-muted-foreground">{report.yearSurvey.caveat}</p>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>年度</TableHead><TableHead>direction</TableHead><TableHead className="text-right">行数</TableHead>
                  <TableHead className="text-right">会計</TableHead><TableHead>収録範囲</TableHead>
                  <TableHead>互換</TableHead><TableHead>判定根拠</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {report.yearSurvey.observations.map((o, i) => (
                  <TableRow key={i}>
                    <TableCell className="whitespace-nowrap">{o.label}</TableCell>
                    <TableCell>{o.direction}</TableCell>
                    <TableCell className="text-right tabular-nums">{o.rows ?? '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{o.funds?.length ?? '—'}</TableCell>
                    <TableCell className="text-xs">{o.coverageNote ?? '—'}</TableCell>
                    <TableCell>
                      <Badge variant={o.compatible == null ? 'outline' : o.compatible ? 'secondary' : 'destructive'}>
                        {o.compatible == null ? '未判定' : o.compatible ? '互換' : '非互換'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{o.basis}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </section>
      )}

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
