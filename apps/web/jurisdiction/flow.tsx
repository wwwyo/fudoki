// お金の流れ。初期は全款の款→項。横にスクロールすると款が一つずつ（snap）開き、縦にスクロールするとその款の項が一つずつ開く。
// 項まで開くと、その項の目と節の上位を出す（節の金額は目ごとに大きい順、足し上げは作らない）。
import * as React from 'react'
import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Overview } from './sankey'
import { formatYen, type Drill, type Kou, type Moku, type PageData } from './types'

const SETSU_SHOWN = 3
const MOBILE_QUERY = '(max-width: 699px)'

const fetchJson = async <T,>(url: string, signal?: AbortSignal): Promise<T> => {
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(String(res.status))
  return (await res.json()) as T
}

const amountText = (yen: number, missing?: boolean) => (missing ? '金額未記載' : formatYen(yen))
const share = (yen: number, max: number, missing?: boolean) => (missing || max <= 0 ? 0 : (Math.max(0, yen) / max) * 100)

function MokuGroup({ moku, max }: { moku: Moku; max: number }) {
  const shown = moku.setsu.filter((s) => s.amountMissing || s.yen > 0)
  const top = shown.slice(0, SETSU_SHOWN)
  const topMax = Math.max(...top.filter((s) => !s.amountMissing).map((s) => s.yen), 0)
  return (
    <div data-moku data-yen={moku.amountMissing ? 0 : moku.yen} className="grid translate-y-1.5 grid-cols-1 items-start gap-1.5 opacity-30 transition-[opacity,transform] duration-500 group-data-[active=true]/kou:translate-y-0 group-data-[active=true]/kou:opacity-100 sm:grid-cols-[5fr_7fr] sm:gap-4">
      <div className="min-w-0">
        <div className="text-sm leading-snug">{moku.name}</div>
        <div className="text-xs tabular-nums text-muted-foreground">{amountText(moku.yen, moku.amountMissing)}</div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-foreground/5">
          <div className="h-full rounded-full bg-primary" style={{ width: `${share(moku.yen, max, moku.amountMissing)}%` }} />
        </div>
        {shown.length > SETSU_SHOWN ? <div className="mt-1 text-[11.5px] text-muted-foreground">ほか{shown.length - SETSU_SHOWN}節</div> : null}
      </div>
      {top.length > 0 ? (
        <ul className="grid min-w-0 gap-y-0.5 border-l pl-3 text-[12.5px] leading-snug">
          {top.map((s) => (
            <li key={s.name} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-2.5">
              <span className="truncate">{s.name}</span>
              <span className="text-right tabular-nums text-muted-foreground">{amountText(s.yen, s.amountMissing)}</span>
              <span className="col-span-2 mb-0.5 h-[3px] overflow-hidden rounded-full bg-foreground/5">
                <span className="block h-full rounded-full bg-primary/55" style={{ width: `${share(s.yen, topMax, s.amountMissing)}%` }} />
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="border-l pl-3 text-[12.5px] text-muted-foreground">内訳の区分は出典にありません</p>
      )}
    </div>
  )
}

/** 項の帯を目の行へ渡す。狭い画面では出さない */
function KouSection({ kou, active, loading, onBox }: { kou: Kou; active: boolean; loading: boolean; onBox: (el: HTMLElement | null) => void }) {
  const box = React.useRef<HTMLElement | null>(null)
  const rib = React.useRef<HTMLDivElement>(null)
  const [paths, setPaths] = React.useState<{ d: string }[]>([])
  const [bar, setBar] = React.useState({ top: 0, height: 0 })
  const max = Math.max(...kou.moku.filter((m) => !m.amountMissing).map((m) => m.yen), 0)
  React.useLayoutEffect(() => {
    const el = box.current
    const lane = rib.current
    if (!el || !lane) return
    const measure = () => {
      if (window.matchMedia(MOBILE_QUERY).matches) return setPaths([])
      const rows = [...el.querySelectorAll<HTMLElement>('[data-moku]')]
      if (rows.length === 0) return setPaths([])
      const origin = lane.getBoundingClientRect().top
      const first = rows[0]!.getBoundingClientRect()
      const last = rows[rows.length - 1]!.getBoundingClientRect()
      const height = Math.max(last.bottom - first.top, 24)
      const sum = rows.reduce((s, row) => s + Number(row.dataset.yen), 0)
      const width = lane.clientWidth
      let y = first.top - origin
      setBar({ top: first.top - origin, height })
      setPaths(rows.map((row) => {
        const r = row.getBoundingClientRect()
        const ty = r.top - origin
        const th = Math.min(r.height, 26)
        const h = sum > 0 ? Math.max((Number(row.dataset.yen) / sum) * height, 2) : height / rows.length
        const a = y
        y += h
        return { d: `M0 ${a}C${width / 2} ${a},${width / 2} ${ty},${width} ${ty}L${width} ${ty + Math.max(th, 4)}C${width / 2} ${ty + Math.max(th, 4)},${width / 2} ${a + h},0 ${a + h}Z` }
      }))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [kou.moku.length])
  return (
    <section ref={(el) => { box.current = el; onBox(el) }} data-active={active} className="group/kou grid min-h-full snap-start snap-always grid-cols-1 content-start gap-3 px-5 pb-5 pt-3 sm:grid-cols-[150px_10px_64px_minmax(0,1fr)] sm:gap-0 sm:pr-8">
      <div className="min-w-0 border-b pb-2 sm:border-0 sm:pb-0 sm:pr-2">
        <div className="text-[11px] text-muted-foreground">項</div>
        <div className="font-sans text-lg leading-snug">{kou.name}</div>
        <div className="text-[13px] tabular-nums text-muted-foreground">{amountText(kou.yen, kou.amountMissing)}</div>
        {kou.page ? <div className="mt-1.5 text-[11px] text-muted-foreground">決算書 {kou.page}頁</div> : null}
      </div>
      <div className="relative hidden sm:block" aria-hidden="true">
        <i className="absolute left-0 w-2 rounded-sm bg-primary transition-[height] duration-500" style={{ top: bar.top, height: bar.height }} />
      </div>
      <div ref={rib} className="relative hidden sm:block" aria-hidden="true">
        <svg className="absolute inset-0 size-full overflow-visible">
          {paths.map((p, i) => <path key={i} d={p.d} className={`fill-primary/20 transition-opacity duration-500 ${active ? 'opacity-100' : 'opacity-0'}`} />)}
        </svg>
      </div>
      <div className="flex min-w-0 flex-col gap-3">
        {kou.moku.length > 0 ? kou.moku.map((m) => <MokuGroup key={m.id} moku={m} max={max} />) : (
          <p className="text-[12.5px] text-muted-foreground" role={loading ? 'status' : undefined}>{loading ? '内訳を読み込んでいます…' : 'この項に目はありません'}</p>
        )}
      </div>
    </section>
  )
}

function KanPanel({ drill, loading }: { drill: Drill; loading: boolean }) {
  const body = React.useRef<HTMLDivElement>(null)
  const [current, setCurrent] = React.useState(0)
  const sections = React.useRef<(HTMLElement | null)[]>([])
  React.useEffect(() => {
    const root = body.current
    if (!root) return
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) if (entry.isIntersecting) setCurrent(sections.current.indexOf(entry.target as HTMLElement))
    }, { root, rootMargin: '-35% 0px -55% 0px', threshold: 0 })
    for (const el of sections.current) if (el) observer.observe(el)
    return () => observer.disconnect()
  }, [drill.kou.length])
  return (
    <div className="relative h-full w-full shrink-0 snap-start snap-always" data-panel>
      {drill.kou.length > 1 ? (
        <div className="pointer-events-none absolute right-2 top-1/2 z-10 flex -translate-y-1/2 flex-col gap-1.5" aria-hidden="true">
          {drill.kou.map((k, i) => <i key={k.id} className={`block w-[5px] rounded-full transition-all ${i === current ? 'h-4 bg-primary' : 'h-[5px] bg-border'}`} />)}
        </div>
      ) : null}
      <div ref={body} className="h-full snap-y snap-mandatory overflow-y-auto scroll-smooth [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" tabIndex={-1}>
        {drill.kou.map((k, i) => (
          <KouSection key={k.id} kou={k} active={i === current} loading={loading} onBox={(el) => { sections.current[i] = el }} />
        ))}
      </div>
    </div>
  )
}

export function Flow({ data }: { data: PageData }) {
  const latest = data.years.at(-1)!
  const root = React.useRef<HTMLElement>(null)
  const track = React.useRef<HTMLDivElement>(null)
  const [detail, setDetail] = React.useState<Drill[]>()
  const [error, setError] = React.useState(false)
  const [attempt, setAttempt] = React.useState(0)
  const [near, setNear] = React.useState(false)
  const [index, setIndex] = React.useState(0)
  const flows = detail ?? data.flow
  // 項の内訳（目・節）は、図が近づいたら読み込む。クリックは要らない
  React.useEffect(() => {
    const el = root.current
    if (!el) return
    const observer = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) setNear(true) }, { rootMargin: '900px 0px' })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  React.useEffect(() => {
    if (!near || detail) return
    setError(false)
    const controller = new AbortController()
    fetchJson<Drill[]>(`/api/jurisdictions/flow/${data.code}/${latest.year}/setsu`, controller.signal).then(
      (value) => { if (!controller.signal.aborted) setDetail(value) },
      () => { if (!controller.signal.aborted) setError(true) },
    )
    return () => controller.abort()
  }, [near, detail, data.code, latest.year, attempt])
  const onScroll = () => {
    const el = track.current
    if (!el) return
    const next = Math.round(el.scrollLeft / el.clientWidth)
    setIndex((prev) => (prev === next ? prev : next))
  }
  const go = (delta: number) => track.current?.scrollBy({ left: delta * (track.current?.clientWidth ?? 0), behavior: 'smooth' })
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowRight') { go(1); e.preventDefault() }
    else if (e.key === 'ArrowLeft') { go(-1); e.preventDefault() }
  }
  const total = flows.length
  const kan = index > 0 ? flows[index - 1] : undefined
  const sum = flows.reduce((s, f) => s + Math.max(0, f.kan.yen), 0) || 1
  return (
    <section ref={root} className="mt-4 min-w-0 rounded-[20px] border bg-background">
      <div className="px-5 pt-5 sm:px-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-sans text-xl font-normal">お金の流れ</h2>
          {data.originTitle ? <span className="text-xs text-muted-foreground">出典 {data.originTitle}</span> : null}
        </div>
        <div className="mt-3 flex items-baseline justify-between gap-3" aria-live="polite">
          <div className="font-sans text-lg leading-snug">
            {kan ? kan.kan.name : '全体'}
            <span className="ml-2.5 font-sans text-sm tabular-nums text-muted-foreground">{kan ? amountText(kan.kan.yen, kan.kan.amountMissing) : '款と項'}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-xs tabular-nums text-muted-foreground">{kan ? `款 ${index} / ${total}` : ''}</span>
            <Button variant="outline" size="icon-sm" aria-label="前の款" disabled={index === 0} onClick={() => go(-1)} className="rounded-full [@media(hover:none)]:hidden"><ChevronLeftIcon /></Button>
            <Button variant="outline" size="icon-sm" aria-label="次の款" disabled={index >= total} onClick={() => go(1)} className="rounded-full [@media(hover:none)]:hidden"><ChevronRightIcon /></Button>
          </div>
        </div>
        <div className="mt-2.5 flex gap-0.5" aria-hidden="true">
          <i className={`block h-1.5 w-3.5 rounded-sm ${index === 0 ? 'bg-primary' : 'bg-border'}`} />
          {flows.map((f, i) => (
            <i key={f.kan.id} className={`block h-1.5 min-w-[3px] rounded-sm transition-colors ${index === i + 1 ? 'bg-primary' : 'bg-border'}`} style={{ flexGrow: Math.max(f.kan.yen, 0) / sum || 0.01, flexBasis: 0 }} />
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          {index === 0 ? '横にスクロールすると、款が一つずつ開きます。' : <>縦にスクロールすると、款の中の項が一つずつ開きます。{index < total ? '横で次の款へ。' : null}</>}
        </p>
      </div>
      <div className="relative mt-2">
        <div
          ref={track}
          role="region"
          aria-label="お金の流れ（横にスクロールで款を切り替え）"
          tabIndex={0}
          onScroll={onScroll}
          onKeyDown={onKey}
          className="flex h-[clamp(440px,80svh,700px)] snap-x snap-mandatory overflow-x-auto overflow-y-hidden overscroll-x-contain scroll-smooth rounded-b-[20px] [scrollbar-width:none] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring [&::-webkit-scrollbar]:hidden"
        >
          <div className="h-full w-full shrink-0 snap-start snap-always overflow-y-auto px-3 pb-3 pt-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:px-5">
            <Overview flows={flows} height={Math.min(560, typeof window === 'undefined' ? 520 : Math.max(380, window.innerHeight * 0.7))} />
          </div>
          {flows.map((f) => <KanPanel key={f.kan.id} drill={f} loading={!detail && !error} />)}
        </div>
      </div>
      {error ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 px-5 pb-4 text-sm text-destructive">
          <p>内訳を読み込めませんでした。</p>
          <Button variant="outline" onClick={() => { setDetail(undefined); setAttempt((n) => n + 1) }}>もう一度読み込む</Button>
        </div>
      ) : null}
    </section>
  )
}
