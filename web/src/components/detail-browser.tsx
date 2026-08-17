/**
 * 明細を辿る。会計から細々節まで階層を降りる。
 *
 * ドリルダウンは**実ボタン**で持つ。行の onClick だけだとキーボードで辿れず、
 * この画面の中心機能がマウス専用になる。
 */
import { useMemo, useState } from 'react'
import type { DetailRow } from '@/lib/pipeline'
import { DIVISION_COLOR, STATUS_JA, yen } from '@/lib/pipeline'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

type Direction = 'expenditure' | 'revenue'

const LEVELS: Record<Direction, string[]> = {
  expenditure: ['fund', 'kan', 'kou', 'moku', 'jikou', 'setsu', 'saisaisetsu'],
  revenue: ['fund', 'kan', 'kou', 'moku', 'setsu', 'saisetsu', 'saisaisetsu'],
}
const LEVEL_JA: Record<string, string> = {
  fund: '会計', kan: '款', kou: '項', moku: '目', jikou: '事項', setsu: '節', saisetsu: '細節', saisaisetsu: '細々節',
}

export function DetailBrowser({ expenditure, revenue }: { expenditure: DetailRow[]; revenue: DetailRow[] }) {
  const [dir, setDir] = useState<Direction>('expenditure')
  const [path, setPath] = useState<string[]>([])
  const [query, setQuery] = useState('')

  const levels = LEVELS[dir]
  const source = dir === 'expenditure' ? expenditure : revenue

  const rows = useMemo(() => {
    let r = source.filter((row) => path.every((v, i) => row[`${levels[i]}_source`] === v))
    if (query) {
      const q = query.toLowerCase()
      r = r.filter((row) => levels.some((l) => (row[`${l}_label`] ?? '').toLowerCase().includes(q)))
    }
    return r
  }, [source, path, query, levels])

  const total = rows.reduce((s, r) => s + Number(r.value), 0)
  const depth = path.length
  const setDirection = (d: Direction) => { setDir(d); setPath([]) }

  const groups = useMemo(() => {
    if (depth >= levels.length || rows.length <= 1) return null
    const key = `${levels[depth]}_source`
    const m = new Map<string, { count: number; sum: number; divs: Map<string, number>; statuses: Set<string> }>()
    for (const r of rows) {
      const g = m.get(r[key]!) ?? { count: 0, sum: 0, divs: new Map(), statuses: new Set() }
      g.count++
      g.sum += Number(r.value)
      if (dir === 'expenditure') {
        if (r.cofog_division_code) g.divs.set(r.cofog_division_code, (g.divs.get(r.cofog_division_code) ?? 0) + Number(r.value))
        g.statuses.add(r.cofog_status!)
      }
      m.set(r[key]!, g)
    }
    return [...m.entries()].sort((a, b) => b[1].sum - a[1].sum)
  }, [rows, depth, levels, dir])

  const max = groups?.[0]?.[1].sum ?? 1
  const nextJa = LEVEL_JA[levels[depth + 1] ?? ''] ?? '明細'

  return (
    <div className="flex flex-col gap-3">
      <p className="max-w-[72ch] text-sm text-muted-foreground">
        行の科目名を選ぶと1段深くなる。事項名（例:「いじめ問題対策協議会関係費」）で絞り込むと、
        その金額がどこに付いているかを直接引ける。
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant={dir === 'expenditure' ? 'default' : 'outline'} onClick={() => setDirection('expenditure')}>歳出</Button>
        <Button size="sm" variant={dir === 'revenue' ? 'default' : 'outline'} onClick={() => setDirection('revenue')}>歳入</Button>
        <Input className="max-w-xs" type="search" placeholder="事項名・科目名で絞り込み" aria-label="科目名で絞り込み"
          value={query} onChange={(e) => { setQuery(e.target.value); setPath([]) }} />
        <span className="text-xs tabular-nums text-muted-foreground">{yen(rows.length)} 行 / {yen(total)} 円</span>
      </div>

      <nav aria-label="階層" className="flex flex-wrap items-center gap-1 text-sm">
        <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => setPath([])}>全体</Button>
        {path.map((v, i) => (
          <span key={i} className="flex items-center gap-1">
            <span aria-hidden className="text-muted-foreground">›</span>
            {i === path.length - 1 ? (
              <span className="max-w-[26ch] truncate font-medium" title={v}>{v}</span>
            ) : (
              <Button size="sm" variant="ghost" className="h-7 max-w-[22ch] truncate px-2"
                title={v} onClick={() => setPath(path.slice(0, i + 1))}>{v}</Button>
            )}
          </span>
        ))}
      </nav>

      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">該当なし。</p>
      ) : groups === null ? (
        <LeafCard row={rows[0]!} levels={levels} dir={dir} />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{LEVEL_JA[levels[depth]!]}</TableHead>
                <TableHead className="text-right">金額（円）</TableHead>
                <TableHead className="w-[120px]">構成</TableHead>
                <TableHead className="text-right">行数</TableHead>
                {dir === 'expenditure' && <TableHead>COFOG</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {groups.map(([k, g]) => {
                const ds = [...g.divs.entries()].sort((a, b) => b[1] - a[1])
                return (
                  <TableRow key={k}>
                    <TableCell>
                      <button type="button" className="w-full cursor-pointer text-left hover:text-primary hover:underline"
                        aria-label={`${k} を開いて${nextJa}を見る（${yen(g.sum)} 円 / ${yen(g.count)} 行）`}
                        onClick={() => setPath([...path, k])}>{k}</button>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{yen(g.sum)}</TableCell>
                    <TableCell>
                      <div className="h-1.5 rounded-full bg-primary/30" style={{ width: `${(g.sum / max) * 100}%` }} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{yen(g.count)}</TableCell>
                    {dir === 'expenditure' && (
                      <TableCell className="whitespace-nowrap text-xs">
                        {ds.length === 0
                          ? [...g.statuses].map((s) => <Badge key={s} variant="outline" className="mr-1">{STATUS_JA[s] ?? s}</Badge>)
                          : (
                            <span className="inline-flex items-center gap-1.5">
                              {ds.slice(0, 4).map(([d]) => (
                                <i key={d} aria-hidden className="size-2.5 rounded-sm" style={{ background: DIVISION_COLOR[d] }} />
                              ))}
                              <span className="font-medium">{ds[0]![0]}</span>
                              {ds.length > 1 && <span className="text-muted-foreground">ほか{ds.length - 1}区分</span>}
                            </span>
                          )}
                      </TableCell>
                    )}
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

function LeafCard({ row, levels, dir }: { row: DetailRow; levels: string[]; dir: Direction }) {
  const items: [string, React.ReactNode][] = [
    ['budget_line_id', <span className="font-mono text-xs">{row.budget_line_id}</span>],
    ...levels.map((l) => [LEVEL_JA[l]!, row[`${l}_source`]] as [string, React.ReactNode]),
    ['金額', <><span className="font-medium">{yen(row.value!)} 円</span>（原典 {yen(row.source_amount!)} {row.source_amount_unit}）</>],
    ['年度 / 段階', `${row.fiscal_year} / ${row.phase_id}`],
    ['原典の行', `${row.source_row} 行目`],
  ]
  if (dir === 'expenditure') {
    items.push(
      ['COFOG', row.cofog_division_code
        ? <span className="inline-flex items-center gap-1.5">
            <i aria-hidden className="size-2.5 rounded-sm" style={{ background: DIVISION_COLOR[row.cofog_division_code] }} />
            <span className="font-medium">{row.cofog_division_code}</span> {row.cofog_division_label}
            <Badge variant="outline">{STATUS_JA[row.cofog_status!] ?? row.cofog_status}</Badge>
          </span>
        : <Badge variant="outline">{STATUS_JA[row.cofog_status!] ?? row.cofog_status}</Badge>],
      ['決まった単位', row.cofog_decided_at_level],
      ['割当の根拠', row.cofog_basis],
      ['適用した規則', <code className="text-xs">{row.cofog_rule_id}</code>],
    )
  }
  return (
    <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 rounded-lg border bg-muted/30 p-4 text-sm">
      {items.map(([k, v], i) => (
        <div key={i} className="col-span-2 grid grid-cols-subgrid">
          <dt className="whitespace-nowrap text-muted-foreground">{k}</dt>
          <dd className="m-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  )
}
