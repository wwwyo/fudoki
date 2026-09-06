/** 取得の証跡。URL・SHA-256・復元検査を原典ごとに出す */
import type { ReportData } from '@/lib/pipeline'
import { yen } from '@/lib/pipeline'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export function StageDetail({ report }: { report: ReportData }) {
  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-2">
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>direction</TableHead><TableHead>リソース名</TableHead><TableHead>status</TableHead>
                <TableHead className="text-right">行数</TableHead><TableHead>文字コード</TableHead>
                <TableHead>復元検査</TableHead><TableHead>SHA-256</TableHead><TableHead>取得時刻</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.ingestion.map((p) => (
                <TableRow key={`${p.direction}-${p.fiscal_year}`}>
                  <TableCell>{p.direction}</TableCell>
                  <TableCell>
                    <a className="underline" href={p.request_url} target="_blank" rel="noreferrer">{p.resource_name}</a>
                  </TableCell>
                  <TableCell><Badge variant={p.status === 200 ? 'secondary' : 'destructive'}>{p.status}</Badge></TableCell>
                  <TableCell className="text-right tabular-nums">{yen(p.rows)}</TableCell>
                  <TableCell title="shift_jis ではなく cp932。原典に機種依存文字（Ⅰ = U+2160）が入っている">
                    {p.encoding}
                  </TableCell>
                  <TableCell>
                    <Badge variant={p.roundtrip_verified ? 'secondary' : 'destructive'}>
                      {p.roundtrip_verified ? '一致' : '不一致'}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{p.sha256.slice(0, 16)}…</TableCell>
                  <TableCell className="whitespace-nowrap text-xs">{p.fetched_at.replace('T', ' ').slice(0, 19)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {report.ingestion.map((p) => (
          <p key={`${p.direction}-${p.fiscal_year}-basis`} className="max-w-[70ch] text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{p.direction}</span> の年度: {p.fiscal_year_basis}
          </p>
        ))}
      </section>
    </div>
  )
}
