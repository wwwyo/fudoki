/** 段ごとの中身。責務と「やらないこと」は topology の宣言をそのまま出す */
import type { ReportData } from '@/lib/pipeline'
import { yen } from '@/lib/pipeline'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export function StageDetail({ report }: { report: ReportData }) {
  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-3 md:grid-cols-3">
        {report.topology.stages.map((s) => (
          <Card key={s.id}>
            <CardHeader>
              <div className="flex items-center gap-2">
                <CardTitle>{s.label}</CardTitle>
                {s.introducesJudgment && <Badge variant="outline">判断あり</Badge>}
              </div>
              <CardDescription>{s.responsibility}</CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              <span className="font-medium text-foreground">やらないこと</span>: {s.excludes}
            </CardContent>
          </Card>
        ))}
      </div>

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">Extract — 取得の証跡</h3>
        <p className="max-w-[68ch] text-sm text-muted-foreground">
          原典は <code>data/raw/</code> に Parquet で置く（取得の単位ごとに partition）。
          あわせて URL・status・SHA-256・取得時刻を証跡として残すので、
          <strong>原典から成果物を再生成できること</strong>が再現性の意味になる。
        </p>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>direction</TableHead><TableHead>リソース名</TableHead><TableHead>status</TableHead>
                <TableHead className="text-right">行数</TableHead><TableHead>文字コード</TableHead>
                <TableHead>SHA-256</TableHead><TableHead>取得時刻</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.extract.map((p) => (
                <TableRow key={p.direction}>
                  <TableCell>{p.direction}</TableCell>
                  <TableCell><a className="underline" href={p.requestUrl} target="_blank" rel="noreferrer">{p.resourceName}</a></TableCell>
                  <TableCell><Badge variant={p.status === 200 ? 'secondary' : 'destructive'}>{p.status}</Badge></TableCell>
                  <TableCell className="text-right tabular-nums">{yen(p.rows)}</TableCell>
                  <TableCell>{p.encoding}</TableCell>
                  <TableCell className="font-mono text-xs">{p.sha256.slice(0, 16)}…</TableCell>
                  <TableCell className="whitespace-nowrap text-xs">{p.fetchedAt.replace('T', ' ').slice(0, 19)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <div className="text-sm text-muted-foreground">
          {report.extract.map((p) => (
            <p key={p.direction} className="max-w-[68ch]">
              <span className="font-medium text-foreground">{p.direction}</span> の年度: {p.fiscalYearBasis}
            </p>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">Load — 原典1行を正本1行へ</h3>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>direction</TableHead><TableHead className="text-right">入力</TableHead>
                <TableHead className="text-right">出力</TableHead><TableHead className="text-right">差分</TableHead>
                <TableHead className="text-right" title="その階層を持たない行を、自治体がプレースホルダで埋めているセルの数（三鷹市の歳入は 0 で埋める）">階層なしのセル</TableHead><TableHead className="text-right" title="コード+名称の形でもプレースホルダでもないセル。0 でなければ原典の想定が外れている">想定外のセル</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.load.map((l) => (
                <TableRow key={l.direction}>
                  <TableCell>{l.direction}</TableCell>
                  <TableCell className="text-right tabular-nums">{yen(l.inputRows)}</TableCell>
                  <TableCell className="text-right tabular-nums">{yen(l.outputRows)}</TableCell>
                  <TableCell className="text-right">
                    <Badge variant={l.diff === 0 ? 'secondary' : 'destructive'}>{l.diff}</Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{yen(l.absentLevelCells)}</TableCell>
                  <TableCell className="text-right tabular-nums">{l.irregularCells}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <h4 className="mt-2 text-sm font-medium">1行がどう変わったか</h4>
        <pre className="overflow-x-auto rounded-lg border bg-muted/40 p-3 text-xs">{report.walkthrough.sourceLine}</pre>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow><TableHead>出力の列</TableHead><TableHead>値</TableHead><TableHead>どこから来たか</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {report.walkthrough.fields.map((f) => (
                <TableRow key={f.column}>
                  <TableCell className="whitespace-nowrap font-mono text-xs">{f.column}</TableCell>
                  <TableCell className="text-xs">{f.value}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{f.origin}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <h4 className="mt-2 text-sm font-medium">階層の切り出し</h4>
        <p className="max-w-[68ch] text-sm text-muted-foreground">
          「完全修飾」は親までを含めて数えた異なり数。コードの異なり数より大きいのは、
          同じコードが別の親の下で再利用されていることを意味する。
        </p>
        {report.levels.map((g) => (
          <div key={g.direction} className="flex flex-col gap-1">
            <div className="text-sm font-medium">{g.direction}</div>
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>階層</TableHead><TableHead>語彙</TableHead>
                    <TableHead className="text-right">コード</TableHead><TableHead className="text-right">完全修飾</TableHead>
                    <TableHead title="FDP が列の意味を与える識別子。コロン区切りの階層で、どの標準のどの概念に対応するかを示す">ColumnType</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {g.items.map((i) => (
                    <TableRow key={i.sourceColumn}>
                      <TableCell>{i.sourceColumn}</TableCell>
                      <TableCell><Badge variant="outline">{i.vocabulary}</Badge></TableCell>
                      <TableCell className="text-right tabular-nums">{yen(i.distinctCodes)}</TableCell>
                      <TableCell className="text-right tabular-nums">{yen(i.distinctPaths)}</TableCell>
                      <TableCell className="font-mono text-xs">{i.columnType}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        ))}
      </section>
    </div>
  )
}
