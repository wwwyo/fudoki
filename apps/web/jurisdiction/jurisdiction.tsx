// 自治体の個別ページ（/:都道府県/:名称）の島。サーバーが書いた HTML（検索エンジン向け）を、同じデータでグラフ付きに描き直す。
// 歳出は API の値。人口・将来推計・特色はまだ無いので仮の値（dummy.ts）で、画面にも「仮」と出す
import * as React from 'react'
import { createRoot } from 'react-dom/client'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, XAxis, YAxis } from 'recharts'
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart'
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from '@/components/ui/breadcrumb'
import { StartForm } from '../chat/start-form'
import { DUMMY_TRAITS, dummyPopulation } from './dummy'
import { Flow } from './flow'
import { changePct, formatYen, kanChanges, reiwa, type PageData, type Project, type Setsu } from './types'

const fetchJson = async <T,>(url: string, signal?: AbortSignal): Promise<T> => {
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(String(res.status))
  return (await res.json()) as T
}

const Dummy = () => <span className="ml-1.5 inline-block rounded border border-dashed px-1.5 py-px align-middle text-[11px] leading-none text-muted-foreground">仮</span>

const Card = ({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) => (
  <section className="mt-4 min-w-0 rounded-[20px] border bg-background p-5 sm:p-6">
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="font-sans text-xl font-normal">{title}</h2>
      {aside}
    </div>
    {children}
  </section>
)

const BigNumber = ({ label, dummy, yen, perPerson }: { label: string; dummy?: boolean; yen?: number; perPerson?: number }) => {
  const [n, unit] = yen !== undefined ? formatYen(yen).split(/(?=[億万]円$)/) : [String(perPerson), '万円']
  return (
    <div className="min-w-0 flex-1">
      <div className="text-[13px] text-muted-foreground">
        {label}
        {dummy ? <Dummy /> : null}
      </div>
      <div className="font-sans text-[clamp(2rem,1.5rem+2vw,3.2rem)] leading-tight tabular-nums">
        {n}
        <small className="ml-1 text-[.4em] text-muted-foreground">{unit}</small>
      </div>
    </div>
  )
}

function Trend({ data }: { data: PageData }) {
  const latest = data.years.at(-1)!
  const first = data.years[0]!
  const bars = data.years.map((y) => ({ label: reiwa(y.year).replace('年度', ''), value: y.yen / 1e8 }))
  const changes = kanChanges(data.years)
  const config = { value: { label: '歳出（億円）', color: 'var(--primary)' }, pct: { label: '前年度との増減（%）', color: 'var(--primary)' } } satisfies ChartConfig
  const compared = data.years.length > 1 ? `${reiwa(data.years.at(-2)!.year).replace('年度', '')}→${reiwa(latest.year).replace('年度', '')}` : ''
  return (
    <Card title="歳出の推移" aside={first.year > latest.year - 4 ? <span className="text-xs text-muted-foreground">{reiwa(first.year)}より前は未収録</span> : null}>
      <div className="grid gap-x-8 gap-y-6 md:grid-cols-[5fr_7fr]">
        <div>
          <h3 className="mb-2 text-[13px] font-medium text-muted-foreground">総額</h3>
          <ChartContainer config={config} className="aspect-auto h-[220px] w-full">
            <BarChart data={bars} margin={{ top: 24 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} />
              <ChartTooltip content={<ChartTooltipContent hideLabel />} />
              <Bar dataKey="value" radius={[6, 6, 0, 0]} maxBarSize={72} fill="var(--primary)">
                <LabelList dataKey="value" position="top" className="fill-foreground text-[13px]" formatter={(v) => `${Math.round(Number(v)).toLocaleString('ja-JP')}億円`} />
              </Bar>
            </BarChart>
          </ChartContainer>
        </div>
        <div>
          <h3 className="mb-2 text-[13px] font-medium text-muted-foreground">款ごとの増減{compared ? `（${compared}）` : ''}</h3>
          {changes.length === 0 ? (
            <p className="py-8 text-sm text-muted-foreground">前年度と比べられる款がありません。</p>
          ) : (
            <ChartContainer config={config} className="aspect-auto w-full" style={{ height: 40 + changes.length * 30 }}>
              <BarChart data={changes} layout="vertical" margin={{ left: 8, right: 44 }}>
                <CartesianGrid horizontal={false} />
                <YAxis dataKey="name" type="category" tickLine={false} axisLine={false} width={126} tick={{ fontSize: 12 }} />
                <XAxis type="number" hide domain={['dataMin - 34', 'dataMax + 22']} />
                <ReferenceLine x={0} stroke="var(--border)" />
                <ChartTooltip content={<ChartTooltipContent hideLabel />} />
                <Bar dataKey="pct" radius={4} barSize={14}>
                  {changes.map((c) => (
                    <Cell key={c.name} fill={c.pct >= 0 ? 'var(--primary)' : 'var(--kincha)'} />
                  ))}
                  <LabelList dataKey="pct" position="right" formatter={(v) => `${Number(v) > 0 ? '+' : ''}${v}%`} className="fill-foreground text-xs" />
                </Bar>
              </BarChart>
            </ChartContainer>
          )}
        </div>
      </div>
    </Card>
  )
}

function ProjectRow({ p, rank, max }: { p: Project; rank: number; max: number }) {
  const [setsu, setSetsu] = React.useState<Setsu[]>()
  const [error, setError] = React.useState(false)
  const [attempt, setAttempt] = React.useState(0)
  const pct = changePct(p.yen, p.prevYen)
  // 内訳（節の上位）は開閉せず最初から出す
  React.useEffect(() => {
    const controller = new AbortController()
    setError(false)
    fetchJson<Setsu[]>(`/api/jurisdictions/setsu/${p.id}`, controller.signal).then(
      (value) => { if (!controller.signal.aborted) setSetsu(value) },
      () => { if (!controller.signal.aborted) setError(true) },
    )
    return () => controller.abort()
  }, [p.id, attempt])
  return (
    <li className="border-t">
      <div className="grid grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-x-3.5 gap-y-1 py-3 sm:grid-cols-[22px_minmax(120px,190px)_1fr_110px_90px]">
        <span className="font-sans text-xl text-muted-foreground">{rank}</span>
        <div className="min-w-0">
          <b className="block text-[15px] font-medium leading-snug">{p.name}</b>
          <span className="text-xs text-muted-foreground">{p.kanName}</span>
        </div>
        <div className="order-5 col-span-full sm:order-none sm:col-span-1">
          <div className="h-2.5 overflow-hidden rounded-full bg-foreground/5">
            <div className="h-full rounded-full bg-primary" style={{ width: `${(p.yen / max) * 100}%` }} />
          </div>
        </div>
        <div className="text-right text-[15px] tabular-nums">{p.amountMissing ? '金額未記載' : formatYen(p.yen)}</div>
        <div className={`hidden text-right text-[15px] tabular-nums sm:block ${pct !== null && pct < 0 ? 'text-[#aa5910]' : 'text-primary'}`}>
          {pct === null ? '—' : `${pct >= 0 ? '+' : '−'}${Math.abs(pct).toFixed(1)}%`}
          <i className="block text-[11px] not-italic text-muted-foreground">前年度比</i>
        </div>
      </div>
      {error ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 pb-3 pl-9 text-[13px] text-destructive">
          <span>内訳を読み込めませんでした。</span>
          <button type="button" onClick={() => setAttempt((n) => n + 1)} className="underline underline-offset-2">もう一度読み込む</button>
        </div>
      ) : setsu && setsu.length > 0 ? (
        <ul className="flex flex-wrap gap-x-4 gap-y-0.5 pb-3 pl-9 text-[12.5px] text-muted-foreground">
          {setsu.map((s) => (
            <li key={s.name}>
              {s.name}
              <b className="ml-1.5 font-normal tabular-nums text-foreground">{s.amountMissing ? '金額未記載' : formatYen(s.yen)}</b>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  )
}

function Projects({ data }: { data: PageData }) {
  const max = data.projects[0]?.yen ?? 1
  return (
    <Card title="力を入れている事業" aside={<span className="text-xs text-muted-foreground">支出済額の大きい目（{reiwa(data.years.at(-1)!.year)}）</span>}>
      <ul>
        {data.projects.map((p, i) => (
          <ProjectRow key={p.id} p={p} rank={i + 1} max={max} />
        ))}
      </ul>
    </Card>
  )
}

function Population({ code }: { code: string }) {
  const pop = React.useMemo(() => dummyPopulation(code), [code])
  const rows = [
    ...pop.actual.map((a) => ({ year: a.year, actual: a.value, mid: null as number | null, range: null as [number, number] | null })),
    ...pop.forecast.map((f) => ({ year: f.year, actual: f.year === 2025 ? pop.now : null, mid: f.mid, range: [f.lo, f.hi] as [number, number] })),
  ]
  const config = { actual: { label: '人口（万人）', color: 'var(--primary)' }, mid: { label: '将来推計（万人）', color: 'var(--kincha)' }, range: { label: '推計の幅', color: 'var(--kincha)' } } satisfies ChartConfig
  return (
    <Card title="人口とまちの特色" aside={<Dummy />}>
      <div className="grid items-end gap-6 md:grid-cols-2">
        <div>
          <div className="text-[13px] text-muted-foreground">現在の人口</div>
          <div className="font-sans text-5xl tabular-nums">
            {pop.now}
            <small className="ml-1 text-[.4em] text-muted-foreground">万人</small>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {DUMMY_TRAITS.map((t) => (
              <span key={t} className="rounded-full bg-secondary px-3 py-0.5 text-[13px]">
                {t}
              </span>
            ))}
          </div>
        </div>
        <ChartContainer config={config} className="aspect-auto h-[200px] w-full">
          <AreaChart data={rows} margin={{ left: 4, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="year" type="number" domain={[2016, 2050]} ticks={[2016, 2025, 2035, 2050]} tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
            <YAxis hide domain={['dataMin - 3', 'dataMax + 3']} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Area dataKey="range" type="monotone" stroke="none" fill="var(--color-range)" fillOpacity={0.25} connectNulls />
            <Area dataKey="actual" type="monotone" stroke="var(--color-actual)" strokeWidth={3} fill="var(--color-actual)" fillOpacity={0.15} connectNulls={false} />
            <Area dataKey="mid" type="monotone" stroke="var(--color-mid)" strokeWidth={3} strokeDasharray="2 7" strokeLinecap="round" fill="none" connectNulls />
          </AreaChart>
        </ChartContainer>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">人口・特色・将来推計は仮の値です。</p>
    </Card>
  )
}

function Page({ data, sitekey }: { data: PageData; sitekey: string }) {
  const latest = data.years.at(-1)!
  const pop = React.useMemo(() => dummyPopulation(data.code).now, [data.code])
  const perPerson = Math.round(latest.yen / (pop * 1e4) / 1e4)
  return (
    <div className="mx-auto max-w-[1000px] px-4 pb-48 pt-2 sm:px-6">
      <div className="flex items-center justify-between gap-2 pt-6 text-xs text-muted-foreground">
        <Breadcrumb>
          <BreadcrumbList className="text-xs">
            <BreadcrumbItem>
              <BreadcrumbLink href="/自治体">自治体</BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>{data.prefecture}</BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{data.name}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <span className="rounded-full border px-3 py-1">{reiwa(latest.year)} 決算</span>
      </div>
      <h1 className="mt-3 font-sans text-[clamp(2.4rem,1.5rem+3.4vw,4rem)] font-normal leading-tight">{data.name}</h1>
      <div className="mt-7 flex gap-6 sm:gap-14">
        <BigNumber label="歳出の総額" yen={latest.yen} />
        <div className="border-l pl-6 sm:pl-14 flex-1 min-w-0">
          <BigNumber label="住民一人あたりの歳出" dummy perPerson={perPerson} />
        </div>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">一般会計・{reiwa(latest.year)}決算（支出済額）。一人あたりは、歳出の総額を人数で割った値で、税の負担額ではありません。</p>
      <Trend data={data} />
      <Flow data={data} />
      <Projects data={data} />
      <Population code={data.code} />
      <div className="fixed inset-x-0 bottom-0 z-20 bg-gradient-to-t from-background from-60% to-transparent px-4 pb-[max(14px,env(safe-area-inset-bottom))] pt-3">
        <div className="mx-auto max-w-[720px]">
          <StartForm
            sitekey={sitekey}
            prefix={`${data.name}について：`}
            placeholder={`${data.name}について聞く…`}
            suggestions={[`なぜ${latest.kan[0]?.name ?? '最大の款'}が最大なの？`, '他の自治体と比べると？', 'この数字は出典と合ってる？']}
          />
        </div>
      </div>
    </div>
  )
}

const root = document.getElementById('j-app')
const raw = document.getElementById('j-data')?.textContent
if (root && raw) createRoot(root).render(<Page data={JSON.parse(raw) as PageData} sitekey={root.dataset.turnstileSitekey ?? ''} />)
