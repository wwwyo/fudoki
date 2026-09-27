/**
 * パイプラインの検証画面（ローカル専用）。
 *
 * 「1団体の配布物が正しいか」を運営者が確かめる画面。上ペインに系統図、
 * 下ペインに選んだ組（ノード→ノード）の入力と出力を並べる。
 * 境目はドラッグで比率を変えられる。ページ自体はスクロールしない。
 *
 * 集計はしない。行数・検査・証跡はすべて報告（pipeline.json）と
 * `/local/rows`・`/local/pdf/*` が返す値をそのまま出す。
 */
import { ArrowUpRight } from "lucide-react"
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { FiscalYearSelect } from "@/components/fiscal-year-select"
import { JurisdictionSelect } from "@/components/jurisdiction-select"
import { PhaseSelect } from "@/components/phase-select"
import { Layout } from "@/components/layout"
import { NotCollectedPage } from "@/components/not-collected-page"
import { LineageGraph } from "@/components/pipeline/graph"
import { IoPanel } from "@/components/pipeline/io-panel"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { withBase } from "@/lib/utils"
import { type PipelineData, loadPipeline } from "@/lib/pipeline"
import "@/lib/verify.css"
import { isRes, type Pair } from "@/lib/verify"

type Props = {
  /** `/pipeline/<団体コード>/` の団体コード。コードなしの `/pipeline/` では null */
  urlCode?: string | null
  /** 未収録団体でも団体名は出す（jurisdictions.json 由来。ビルド時に埋め込まれる） */
  jurisdictionName?: string
}

/** 注意点（caveat）の本文に含まれる `**強調**` と `` `コード` `` だけを要素にする（記法は md ではない） */
function caveatText(s: string) {
  return s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : part.startsWith("`") && part.endsWith("`") ? (
      <code key={i} className="mono">{part.slice(1, -1)}</code>
    ) : (
      <span key={i}>{part}</span>
    ),
  )
}

/** 本文を空行でブロックに分け、`- ` 始まりのブロックを箇条書きにする（書式は schema.ts 参照） */
function CaveatBody({ body }: { body: string }) {
  return (
    <>
      {body.split(/\n{2,}/).map((block, i) =>
        block.startsWith("- ") ? (
          <ul key={i}>
            {block.split("\n").map((line, j) => (
              <li key={j}>{caveatText(line.slice(2))}</li>
            ))}
          </ul>
        ) : (
          <p key={i}>{caveatText(block)}</p>
        ),
      )}
    </>
  )
}

export function PipelinePage({ urlCode = null, jurisdictionName }: Props = {}) {
  const [data, setData] = useState<PipelineData | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 見ている団体。MPA なので団体は URL（≒ページ）ごとに固定。
  // コードなしの `/pipeline/` はデータを読んだ後に先頭団体の URL へ redirect する
  const code = urlCode

  // 年度は URL に持つ（ブックマーク・共有リンクが同じ状態を指すため）。
  // null は「未指定」— 画面側では収録年度の最新に倒す（全年度ビューは持たない。
  // 複数年度を1画面に混ぜると「この行はどの年度か」を行ごとに判別する必要が出る）
  const [year, setYear] = useState<number | null>(() => {
    const n = Number(new URLSearchParams(window.location.search).get("y"))
    // `?y=abc` は NaN になって `year=NaN` の問い合わせと「NaN年度」のタイトルを生む
    return Number.isInteger(n) && n > 1900 && n < 2200 ? n : null
  })

  // 選択状態。組は複数持てる（ノード側面クリックでその側の辺が全部入る）。
  // 組 → 行 → PDF 頁の順に下流が上流を従えるが、行選択と PDF 頁は組ごとの状態なので
  // StarPanel の内側に閉じる。overview の PDF 頁だけはここで持つ
  const [pairs, setPairs] = useState<Pair[]>([])
  const [pdfNav, setPdfNav] = useState<{ docId: string | null; page: number | null }>({
    docId: null,
    page: null,
  })
  const [splitH, setSplitH] = useState(42)

  useEffect(() => {
    loadPipeline()
      .then((d) => {
        setData(d)
        if (!urlCode) {
          const first = d.jurisdictions[0]?.code
          if (first) window.location.replace(withBase(`/pipeline/${first}/`))
        }
      })
      .catch((e: Error) => setError(e.message))
  }, [urlCode])

  const found = data?.jurisdictions.find((j) => j.code === code) ?? null
  const notCollected = data !== null && urlCode !== null && found === null
  const current = found ?? undefined

  // 団体ごとの収録年度・名称を title へ
  useEffect(() => {
    if (!current) return
    const { jurisdictionName: name, fiscalYears, phase } = current.report.meta
    const y = year ?? fiscalYears[fiscalYears.length - 1]
    document.title = `${name} ${y}年度 ${phase.label} 検証 | fudoki（風土記）`
  }, [current, year])

  useEffect(() => {
    if (!notCollected) return
    document.title = `${jurisdictionName ?? urlCode} はまだ収録していません | fudoki（風土記）`
  }, [notCollected, jurisdictionName, urlCode])

  const changeYear = useCallback((y: number | null) => {
    setYear(y)
    // 年度が変わると「その行」の指す実体も文書も変わる — 前年の選択を引きずると
    // 表示年度と文書の年度が食い違う（複数文書の団体は文書ごとに年度が違う）
    setPdfNav({ docId: null, page: null })
    const url = new URL(window.location.href)
    if (y === null) url.searchParams.delete("y")
    else url.searchParams.set("y", String(y))
    window.history.replaceState(null, "", url)
  }, [])

  // URL 直入力で収録外の年度が来たら範囲内に戻す（存在しない年度の空表を見せない）
  useEffect(() => {
    if (!current || year === null) return
    const { fiscalYears } = current.report.meta
    if (!fiscalYears.includes(year)) changeYear(fiscalYears[fiscalYears.length - 1] ?? null)
  }, [current, year, changeYear])

  // 系統は全団体で1本だが、図は見ている団体の分だけ出す。共有の core モデルは
  // 「この団体の行数」が切れるので残すが、規則表（マスタデータ）は検証対象の
  // 流れではないので図から外す
  const visibleTopology = useMemo(() => {
    if (!current) return null
    const topo = current.report.topology
    const nodes = topo.nodes.filter((n) => (n.jurisdictionCode ?? current.code) === current.code && !isRes(n))
    const ids = new Set(nodes.map((n) => n.id))
    return { ...topo, nodes, edges: topo.edges.filter((e) => ids.has(e.from) && ids.has(e.to)) }
  }, [current])

  const selectEdge = useCallback((e: Pair) => {
    setPairs([{ from: e.from, to: e.to }])
    setPdfNav({ docId: null, page: null })
  }, [])

  // ノードの側面クリック。左半分 = そのノードを出力とする辺全部（入ってくる側）、
  // 右半分 = 入力とする辺全部（出ていく側）。その側に辺を持たない端点ノード
  // （原典・配布物）は残っている側の全辺に倒す
  const selectNode = useCallback(
    (id: string, side: "in" | "out") => {
      if (!visibleTopology) return
      const es = visibleTopology.edges.filter((x) =>
        side === "out" ? x.to === id : x.from === id,
      )
      const any = visibleTopology.edges.filter((x) => x.from === id || x.to === id)
      setPairs((es.length ? es : any).map((x) => ({ from: x.from, to: x.to })))
      setPdfNav({ docId: null, page: null })
    },
    [visibleTopology],
  )

  const removePair = useCallback((p: Pair) => {
    setPairs((prev) => prev.filter((x) => !(x.from === p.from && x.to === p.to)))
  }, [])

  const onPdfNavigate = useCallback((docId: string, page: number) => {
    setPdfNav({ docId, page })
  }, [])

  /* ---- 境目ドラッグ ---- */
  const splitRef = useRef<HTMLDivElement>(null)
  const sashRef = useRef<HTMLDivElement>(null)
  const ioWrapRef = useRef<HTMLDivElement>(null)
  const sashDrag = useRef(false)
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!sashDrag.current) return
      const cont = splitRef.current
      const gw = cont?.querySelector<HTMLElement>(".graphwrap-outer")
      if (!cont || !gw) return
      const r = cont.getBoundingClientRect()
      // 図ペインの下端をポインタに合わせる。ペインの高さはコンテナ高に対する % で保持する
      const top = gw.getBoundingClientRect().top - r.top
      setSplitH(Math.min(80, Math.max(12, ((e.clientY - r.top - top) / r.height) * 100)))
    }
    const onEnd = () => {
      sashDrag.current = false
      sashRef.current?.classList.remove("drag")
    }
    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onEnd)
    window.addEventListener("pointercancel", onEnd)
    return () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onEnd)
      window.removeEventListener("pointercancel", onEnd)
    }
  }, [])

  /* ---- I/O の左右で背の低い側を sticky にする ----
     高い側をスクロールしたとき短い側が流れて空の列になるのを防ぐ。
     viewport より高い側は下端アンカー（下端まで辿れる）にして見えない領域を作らない。
     DOM は組の選択・非同期の hit 読み込みで増減するので MutationObserver で追う */
  useLayoutEffect(() => {
    const wrap = ioWrapRef.current
    if (!wrap) return
    // rAF は occluded/バックグラウンドのタブで発火しないことがある。
    // ここは描画同期ではなく「DOM 変化への追従」なので、常に回る microtask で束ねる
    let scheduled = false
    const schedule = () => {
      if (scheduled) return
      scheduled = true
      queueMicrotask(() => {
        scheduled = false
        apply()
      })
    }
    const ro = new ResizeObserver(schedule)
    const apply = () => {
      const vp = wrap.clientHeight
      for (const io of wrap.querySelectorAll<HTMLElement>(".io")) {
        const sides = [...io.children].filter(
          (c): c is HTMLElement => c instanceof HTMLElement && c.classList.contains("side"),
        )
        if (sides.length !== 2) continue
        // 画像の読み込みで側の高さは後から変わる — 高さの変化を拾うため側自体を監視する
        sides.forEach((s) => ro.observe(s))
        const [a, b] = sides as [HTMLElement, HTMLElement]
        for (const s of [a, b]) {
          s.classList.remove("sidestick")
          s.style.top = ""
        }
        // 左右の先頭見出し（見出し＋リード文の塊）の高さを揃える — 片側だけ改行すると
        // 表/PDF の上端がずれる
        const ha = a.querySelector<HTMLElement>(".sidehead")
        const hb = b.querySelector<HTMLElement>(".sidehead")
        if (ha && hb) {
          ha.style.minHeight = ""
          hb.style.minHeight = ""
          const max = Math.max(ha.offsetHeight, hb.offsetHeight)
          ha.style.minHeight = hb.style.minHeight = `${max}px`
        }
        if (a.offsetHeight === b.offsetHeight) continue
        const s = a.offsetHeight < b.offsetHeight ? a : b
        s.classList.add("sidestick")
        s.style.top = `${Math.min(0, vp - s.offsetHeight)}px`
      }
    }
    const mo = new MutationObserver(schedule)
    mo.observe(wrap, { childList: true, subtree: true })
    ro.observe(wrap)
    window.addEventListener("resize", schedule)
    apply()
    return () => {
      mo.disconnect()
      ro.disconnect()
      window.removeEventListener("resize", schedule)
    }
  })

  /* ---- 再描画キー（`r`） ---- */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === "r" || e.key === "R") window.location.reload()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [])

  if (error) {
    return (
      <Layout>
        <main className="mx-auto max-w-2xl p-6">
          <Alert variant="destructive">
            <AlertTitle>データを読み込めませんでした</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </main>
      </Layout>
    )
  }
  if (notCollected) {
    return (
      <NotCollectedPage
        code={urlCode!}
        name={jurisdictionName}
        jurisdictions={data!.jurisdictions.map((j) => ({
          code: j.code,
          name: j.report.meta.jurisdictionName,
        }))}
        basePath="pipeline"
      />
    )
  }
  if (!data || !current || !visibleTopology) {
    return (
      <Layout>
        <main className="p-6 text-sm text-muted-foreground">読み込み中…</main>
      </Layout>
    )
  }

  const report = current.report
  const m = report.meta
  // `?y=` 未指定は最新年度に倒す。年度セレクトは収録年度だけ出す
  const y = year ?? m.fiscalYears[m.fiscalYears.length - 1]!

  return (
    <Layout>
      {/* ヘッダー分（h-14=56px）を引いた残りを上下に割る。ページはスクロールしない */}
      <div
        className="pv vsplit"
        ref={splitRef}
        style={{ height: "calc(100dvh - 3.5rem)" }}
      >
        <div className="headline">
          {/* 団体名はセレクトの表示値が担う（見出しを別に置くと二重になる） */}
          <JurisdictionSelect
            jurisdictions={data.jurisdictions.map((j) => ({
              code: j.code,
              name: j.report.meta.jurisdictionName,
            }))}
            value={current.code}
            basePath="pipeline"
          />
          <FiscalYearSelect
            years={m.fiscalYears}
            value={y}
            onChange={changeYear}
            className="w-32"
            size="sm"
          />
          <PhaseSelect value={m.phase.id} className="w-32" size="sm" />
          <a
            href={withBase(`/analysis/${current.code}/`)}
            className="text-xs"
            style={{
              color: "var(--primary)",
              marginLeft: "auto",
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
            }}
          >
            この団体の支出分析を見る
            <ArrowUpRight size={12} aria-hidden />
          </a>
        </div>
        <div className="graphwrap-outer" style={{ flex: `0 0 ${splitH}%`, minHeight: 0, position: "relative" }}>
          <LineageGraph
            topology={visibleTopology}
            code={current.code}
            year={y}
            sel={pairs}
            onSelectEdge={selectEdge}
            onSelectNode={selectNode}
          />
        </div>
        <div
          className="splitsash"
          ref={sashRef}
          role="separator"
          aria-orientation="horizontal"
          title="ドラッグで上下の比率を変更"
          onPointerDown={(e) => {
            sashDrag.current = true
            e.currentTarget.classList.add("drag")
            e.preventDefault()
          }}
        />
        <div className="iowrap" ref={ioWrapRef}>
          <IoPanel
            report={report}
            code={current.code}
            pairs={pairs}
            onRemovePair={removePair}
            year={y}
            pdfDocId={pdfNav.docId}
            pdfPage={pdfNav.page}
            onPdfNavigate={onPdfNavigate}
          />
          {/* 注意点は組の行検査の後・ペインの末尾 — 見出しの上に置くと読み始めの
              行のすぐ上を塞ぐので、確認を終えた読み終わりに来る位置に置く */}
          <details className="fold caveats">
            <summary>⚠ 注意点 {report.caveats.length} 件</summary>
            {report.caveats.map((c, i) => (
              <div className="cv" key={i}>
                <div className="t">{caveatText(c.topic)}</div>
                <div className="b"><CaveatBody body={c.body} /></div>
              </div>
            ))}
          </details>
        </div>
      </div>
    </Layout>
  )
}
