/**
 * 明細を辿る。会計から細々節まで階層を降りる。
 *
 * ドリルダウンは**実ボタン**で持つ。行の onClick だけだとキーボードで辿れず、
 * この画面の中心機能がマウス専用になる。
 */
import { useMemo, useState } from 'react'
import type { Direction, DetailRow, DetailTable, Level } from '@/lib/pipeline'
import { LEVEL_JA, basisOf, cell, divisionLabelOf, levelCell } from '@/lib/pipeline'
import { DIVISION_COLOR, STATUS_JA, yen } from '@/lib/pipeline'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

/**
 * ⚠️ **階層の並びは団体ごとにも direction ごとにも違う**
 * （三鷹市の歳出は「事項」、狛江市は「大事業・中事業・小事業」、歳入は「細節」）。
 * 正本は dbt_project.yml の宣言で、報告（`detailLevels`）を通って渡ってくる。
 * **画面は階層名を直書きしない。**
 */
export function DetailBrowser({
  code, expenditure, revenue, levels, tables,
}: {
  code: string
  expenditure: DetailRow[]
  revenue: DetailRow[]
  levels: Record<Direction, Level[]>
  /** 規則表（割当の根拠）を引くために持つ。根拠は行に複製していない */
  tables: Record<Direction, DetailTable>
}) {
  const [dir, setDir] = useState<Direction>('expenditure')
  // key で切り替える。path と query は団体・direction ごとの状態なので、
  // 切り替えたら捨てるのが正しい。
  return (
    <Browser
      key={`${code}:${dir}`}
      dir={dir}
      source={dir === 'expenditure' ? expenditure : revenue}
      levels={levels[dir]}
      table={tables[dir]}
      onSwitch={setDir}
    />
  )
}

function Browser({
  dir, source, levels, table, onSwitch,
}: {
  dir: Direction; source: DetailRow[]; levels: Level[]
  table: DetailTable; onSwitch: (d: Direction) => void
}) {
  const [path, setPath] = useState<string[]>([])
  const [query, setQuery] = useState('')

  /**
   * 名称を持たない階層。**団体名を直書きしない** — データから分かる。
   * 狛江市は款・項・目・大事業に名称の列が原典に無いが、それは狛江市の性質であって
   * 画面の性質ではない。三鷹市のタブに狛江市の注意書きが出ていた。
   */
  const [named, unnamed] = useMemo(() => {
    const has = (l: Level) => source.some((r) => levelCell(r, l, 'label') !== '')
    return [levels.filter(has), levels.filter((l) => !has(l))]
  }, [source, levels])

  /**
   * ⚠️ **予算段階を混ぜて足さない。**
   * 決算書は原典1行を段階ごとの行へ展開してあるので（狛江市は予算現額・執行済額ほか）、
   * 段階で絞らずに合計すると、同じ金額を段階の数だけ足した意味の無い数字が出る
   * （実際に 3,226 億円の団体で 9,481 億円と表示された）。
   * 段階はデータから取る — 団体ごとに何段階あるかが違う。
   */
  const phases = useMemo(() => {
    const m = new Map<string, string>()
    for (const r of source) m.set(cell(r, 'phase_id'), cell(r, 'phase_label'))
    return [...m.entries()].map(([id, label]) => ({ id, label }))
  }, [source])
  const [phase, setPhase] = useState<string | null>(null)
  const activePhase = phase && phases.some((p) => p.id === phase) ? phase : phases[0]?.id ?? null

  const rows = useMemo(() => {
    let r = source.filter((row) => cell(row, 'phase_id') === activePhase)
    r = r.filter((row) => path.every((v, i) => levelCell(row, levels[i]!, 'source') === v))
    if (query) {
      const q = query.toLowerCase()
      r = r.filter((row) => levels.some((l) => levelCell(row, l, 'label').toLowerCase().includes(q)))
    }
    return r
  }, [source, path, query, levels, activePhase])

  const total = rows.reduce((s, r) => s + Number(cell(r, 'value')), 0)
  const depth = path.length
  const setDirection = onSwitch

  const groups = useMemo(() => {
    if (depth >= levels.length || rows.length <= 1) return null
    const key = levels[depth]!
    const m = new Map<string, { count: number; sum: number; divs: Map<string, number>; statuses: Set<string> }>()
    for (const r of rows) {
      const k = levelCell(r, key, 'source')
      const g = m.get(k) ?? { count: 0, sum: 0, divs: new Map(), statuses: new Set() }
      g.count++
      g.sum += Number(cell(r, 'value'))
      if (dir === 'expenditure') {
        const div = cell(r, 'cofog_division_code')
        if (div) g.divs.set(div, (g.divs.get(div) ?? 0) + Number(cell(r, 'value')))
        g.statuses.add(cell(r, 'cofog_status'))
      }
      m.set(k, g)
    }
    return [...m.entries()].sort((a, b) => b[1].sum - a[1].sum)
  }, [rows, depth, levels, dir])

  const max = groups?.[0]?.[1].sum ?? 1
  const next = levels[depth + 1]
  const nextJa = next ? LEVEL_JA[next] : '明細'

  return (
    <div className="flex flex-col gap-3">
      <p className="max-w-[72ch] text-sm text-muted-foreground">
        行を選ぶと1段深くなる。名称で絞り込むと、その金額がどこに付いているかを直接引ける。
        {unnamed.length > 0 && (
          <>
            {' '}⚠️ この団体の原典は{unnamed.map((l) => LEVEL_JA[l]).join('・')}に名称の列を持たないので、
            絞り込めるのは{named.map((l) => LEVEL_JA[l]).join('・')}だけ。
          </>
        )}
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant={dir === 'expenditure' ? 'default' : 'outline'} onClick={() => setDirection('expenditure')}>歳出</Button>
        <Button size="sm" variant={dir === 'revenue' ? 'default' : 'outline'} onClick={() => setDirection('revenue')}>歳入</Button>
        {phases.length > 1 && (
          <span className="flex flex-wrap items-center gap-1" role="group" aria-label="予算段階">
            {phases.map((p) => (
              <Button key={p.id} size="sm" variant={p.id === activePhase ? 'default' : 'outline'}
                onClick={() => { setPhase(p.id); setPath([]) }}>{p.label}</Button>
            ))}
          </span>
        )}
        <Input className="max-w-xs" type="search" placeholder="科目名で絞り込み" aria-label="科目名で絞り込み"
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
        <LeafCard row={rows[0]!} levels={levels} dir={dir} table={table} />
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

function LeafCard({
  row, levels, dir, table,
}: { row: DetailRow; levels: readonly Level[]; dir: Direction; table: DetailTable }) {
  const items: [string, React.ReactNode][] = [
    ['budget_line_id', <span className="font-mono text-xs">{cell(row, 'budget_line_id')}</span>],
    ...levels.map((l) => [LEVEL_JA[l]!, levelCell(row, l, 'source')] as [string, React.ReactNode]),
    ['金額', <><span className="font-medium">{yen(cell(row, 'value'))} 円</span>（原典 {yen(cell(row, 'source_amount'))} {cell(row, 'source_amount_unit')}）</>],
    ['年度 / 段階', `${cell(row, 'fiscal_year')} / ${cell(row, 'phase_label')}（${cell(row, 'phase_id')}）`],
    ['原典の行', `${cell(row, 'source_row')} 行目`],
  ]
  if (dir === 'expenditure') {
    items.push(
      ['COFOG', cell(row, 'cofog_division_code')
        ? <span className="inline-flex items-center gap-1.5">
            <i aria-hidden className="size-2.5 rounded-sm" style={{ background: DIVISION_COLOR[cell(row, 'cofog_division_code')] }} />
            <span className="font-medium">{cell(row, 'cofog_division_code')}</span> {divisionLabelOf(row)}
            <Badge variant="outline">{STATUS_JA[cell(row, 'cofog_status')] ?? cell(row, 'cofog_status')}</Badge>
          </span>
        : <Badge variant="outline">{STATUS_JA[cell(row, 'cofog_status')] ?? cell(row, 'cofog_status')}</Badge>],
      ['決まった単位', cell(row, 'cofog_decided_at_level')],
      ['割当の根拠', basisOf(table, row)],
      ['適用した規則', <code className="text-xs">{cell(row, 'cofog_rule_id')}</code>],
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
