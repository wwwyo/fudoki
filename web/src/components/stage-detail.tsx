/** 段ごとの中身。責務と「やらないこと」は dbt の置き場から導いた宣言をそのまま出す */
import type { ReportData } from '@/lib/pipeline'
import { yen } from '@/lib/pipeline'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export function StageDetail({ report }: { report: ReportData }) {
  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-2">
        <h3 className="font-medium">ingestion — 取得の証跡</h3>
        <p className="max-w-[70ch] text-sm leading-relaxed text-muted-foreground">
          原典は <code>data/raw/</code> に Parquet で置く。あわせて URL・status・SHA-256・取得時刻を残すので、
          <span className="font-medium text-foreground">原典から成果物を再生成できること</span>が再現性の意味になる。
          <span className="font-medium text-foreground">「無加工」は主張ではなく検査</span>にしてある — 文字コードの復号が可逆か、
          Parquet からセルを繋いで原文に戻るか、の2つを通してから書き出す。
        </p>
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

      <section className="flex flex-col gap-2">
        <h3 className="font-medium">staging — 階層の切り出し</h3>
        <p className="max-w-[70ch] text-sm leading-relaxed text-muted-foreground">
          「完全修飾」は親までを含めて数えた異なり数。コードの異なり数より大きい階層は、
          <span className="font-medium text-foreground">同じコードが別の親の下で再利用されている</span>ことを意味する。
          識別子をコードのパスではなくセル全文から導いている根拠がこれで、
          細々節はコードのパスだと 5,613 行が 4,708 通りにしかならない。
        </p>
        {report.levels.map((g) => (
          <div key={g.direction} className="flex flex-col gap-1">
            <div className="text-sm font-medium">{g.direction}</div>
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>階層</TableHead>
                    <TableHead className="text-right">コード</TableHead>
                    <TableHead className="text-right">完全修飾</TableHead>
                    <TableHead>コードの再利用</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {g.items.map((i) => (
                    <TableRow key={i.sourceColumn}>
                      <TableCell>{i.sourceColumn}</TableCell>
                      <TableCell className="text-right tabular-nums">{yen(i.distinctCodes)}</TableCell>
                      <TableCell className="text-right tabular-nums">{yen(i.distinctPaths)}</TableCell>
                      <TableCell>
                        {i.codeReusedUnderDifferentParents
                          ? <Badge variant="outline">別の親の下で再利用</Badge>
                          : <span className="text-muted-foreground">—</span>}
                      </TableCell>
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
