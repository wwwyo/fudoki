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
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { FiscalYearSelect } from "@/components/fiscal-year-select"
import { JurisdictionSelect } from "@/components/jurisdiction-select"
import { Layout } from "@/components/layout"
import { NotCollectedPage } from "@/components/not-collected-page"
import { LineageGraph } from "@/components/pipeline/graph"
import { IoPanel } from "@/components/pipeline/io-panel"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { withBase } from "@/lib/utils"
import { type PipelineData, loadPipeline } from "@/lib/pipeline"
import "@/lib/verify.css"
import { nodeLabel, type Pair } from "@/lib/verify"

type Props = {
  /** `/pipeline/<団体コード>/` の団体コード。コードなしの `/pipeline/` では null */
  urlCode?: string | null
  /** 未収録団体でも団体名は出す（jurisdictions.json 由来。ビルド時に埋め込まれる） */
  jurisdictionName?: string
}

/** 誤読の罠の本文に含まれる `**強調**` だけを <strong> にする（記法は md ではない） */
function caveatText(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      <span key={i}>{part}</span>
    ),
  )
}

export function PipelinePage({ urlCode = null, jurisdictionName }: Props = {}) {
  const [data, setData] = useState<PipelineData | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 見ている団体。MPA なので団体は URL（≒ページ）ごとに固定。
  // コードなしの `/pipeline/` はデータを読んだ後に先頭団体の URL へ redirect する
  const code = urlCode

  // 年度は URL に持つ（ブックマーク・共有リンクが同じ状態を指すため）
  const [year, setYear] = useState<number | null>(() => {
    const n = Number(new URLSearchParams(window.location.search).get("y"))
    // `?y=abc` は NaN になって `year=NaN` の問い合わせと「NaN年度」のタイトルを生む
    return Number.isInteger(n) && n > 1900 && n < 2200 ? n : null
  })

  // 選択状態。組 → 行 → PDF 頁の順に下流が上流を従える
  const [pair, setPair] = useState<Pair | null>(null)
  const [nodeCand, setNodeCand] = useState<string | null>(null)
  const [selKey, setSelKey] = useState<string | null>(null)
  const [hovKey, setHovKey] = useState<string | null>(null)
  const [pdfNav, setPdfNav] = useState<{ docId: string | null; page: number | null }>({
    docId: null,
    page: null,
  })
  const [caveats, setCaveats] = useState(false)
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
    const years = year === null ? fiscalYears.join("・") : String(year)
    document.title = `${name} ${years}年度 ${phase.label} 検証 | fudoki（風土記）`
  }, [current, year])

  useEffect(() => {
    if (!notCollected) return
    document.title = `${jurisdictionName ?? urlCode} はまだ収録していません | fudoki（風土記）`
  }, [notCollected, jurisdictionName, urlCode])

  const changeYear = useCallback((y: number | null) => {
    setYear(y)
    // 年度が変わると「その行」の指す実体も文書も変わる — 前年の選択を引きずると
    // 表示年度と文書の年度が食い違う（複数文書の団体は文書ごとに年度が違う）
    setSelKey(null)
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

  // 系統は全団体で1本だが、図は見ている団体の分だけ出す（共有ノードは残す）
  const visibleTopology = useMemo(() => {
    if (!current) return null
    const topo = current.report.topology
    const nodes = topo.nodes.filter((n) => (n.jurisdictionCode ?? current.code) === current.code)
    const ids = new Set(nodes.map((n) => n.id))
    return { ...topo, nodes, edges: topo.edges.filter((e) => ids.has(e.from) && ids.has(e.to)) }
  }, [current])

  const nodeById = useMemo(
    () => new Map((visibleTopology?.nodes ?? []).map((n) => [n.id, n])),
    [visibleTopology],
  )

  // ヘッドラインの検査件数は「この団体に関係するもの」だけに絞る。
  // 共有ノードにぶら下がる検査は全団体の図に出るが、警告が他団体の行にだけ
  // 帰属するときまで件数に混ぜると、自分の団体の警告と誤認させる。
  // 判定は build.ts の summary と同じ系（ok / severity / status）
  const checkTally = useMemo(() => {
    if (!visibleTopology || !current) {
      return { total: 0, passed: 0, failed: 0, warned: 0 }
    }
    const ids = new Set(visibleTopology.nodes.map((n) => n.id))
    const checks = current.report.checks.filter(
      (c) =>
        c.binds.some((b) => ids.has(b)) &&
        (c.ok ||
          c.attribution?.kind === "cross" ||
          !c.attribution?.counts ||
          (c.attribution.counts[current.code] ?? 0) > 0),
    )
    return {
      total: checks.length,
      passed: checks.filter((c) => c.ok).length,
      failed: checks.filter((c) => !c.ok && c.severity === "error").length,
      warned: checks.filter((c) => c.status === "warn").length,
    }
  }, [visibleTopology, current])

  const selectEdge = useCallback((e: Pair) => {
    setPair({ from: e.from, to: e.to })
    setNodeCand(null)
    setSelKey(null)
    setPdfNav({ docId: null, page: null })
  }, [])

  const selectNode = useCallback(
    (id: string) => {
      if (!visibleTopology) return
      const es = visibleTopology.edges.filter((x) => x.from === id || x.to === id)
      if (es.length === 1) {
        selectEdge({ from: es[0]!.from, to: es[0]!.to })
      } else {
        setNodeCand((prev) => (prev === id ? null : id))
      }
      setSelKey(null)
    },
    [visibleTopology, selectEdge],
  )

  const onPdfNavigate = useCallback((docId: string, page: number) => {
    setPdfNav({ docId, page })
  }, [])

  /* ---- 境目ドラッグ ---- */
  const splitRef = useRef<HTMLDivElement>(null)
  const sashRef = useRef<HTMLDivElement>(null)
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
  const cand = nodeCand ? nodeById.get(nodeCand) : null
  const candEdges = nodeCand
    ? visibleTopology.edges.filter((e) => e.from === nodeCand || e.to === nodeCand)
    : []

  return (
    <Layout>
      {/* ヘッダー分（h-14=56px）を引いた残りを上下に割る。ページはスクロールしない */}
      <div
        className="pv vsplit"
        ref={splitRef}
        style={{ height: "calc(100dvh - 3.5rem)" }}
      >
        <div className="headline">
          <h1 style={{ fontSize: 20, fontWeight: 600, lineHeight: "28px", margin: 0 }}>
            {m.jurisdictionName}
          </h1>
          {data.jurisdictions.length > 1 && (
            <JurisdictionSelect
              jurisdictions={data.jurisdictions.map((j) => ({
                code: j.code,
                name: j.report.meta.jurisdictionName,
              }))}
              value={current.code}
              basePath="pipeline"
            />
          )}
          {m.fiscalYears.length > 1 ? (
            <FiscalYearSelect
              years={m.fiscalYears}
              value={year}
              onChange={changeYear}
              allowAll
              className="w-32"
              size="sm"
            />
          ) : (
            <span className="text-sm text-muted-foreground">{m.fiscalYears[0]}年度</span>
          )}
          <span className="text-sm text-muted-foreground">{m.phase.label}</span>
          <span className="text-xs text-muted-foreground">
            検査 {checkTally.passed}/{checkTally.total}
            {checkTally.failed ? `・失敗${checkTally.failed}` : ""}
            {checkTally.warned ? `・警告${checkTally.warned}` : ""}
          </span>
          <button className="linky text-xs" onClick={() => setCaveats((v) => !v)}>
            誤読の罠 {report.caveats.length} 件{caveats ? " ▴" : " ▾"}
          </button>
          <a
            href={withBase(`/analysis/${current.code}/`)}
            className="text-xs"
            style={{ color: "var(--primary)", marginLeft: "auto" }}
          >
            この団体の支出分析を見る
          </a>
        </div>
        {caveats && (
          <div className="caveat-drawer">
            {report.caveats.map((c, i) => (
              <div className="cv" key={i}>
                <div className="t">{caveatText(c.topic)}</div>
                <div className="b">{caveatText(c.body)}</div>
              </div>
            ))}
          </div>
        )}
        <div className="graphwrap-outer" style={{ flex: `0 0 ${splitH}%`, minHeight: 0, position: "relative" }}>
          <LineageGraph
            topology={visibleTopology}
            code={current.code}
            year={year}
            sel={pair}
            nodeCand={nodeCand}
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
        <div className="iowrap">
          <IoPanel
            report={report}
            code={current.code}
            pair={pair}
            year={year}
            selectedKey={selKey}
            onSelectRow={setSelKey}
            hoverKey={hovKey}
            onHoverRow={setHovKey}
            pdfDocId={pdfNav.docId}
            pdfPage={pdfNav.page}
            onPdfNavigate={onPdfNavigate}
          />
        </div>
        {cand && candEdges.length > 0 && (
          <div className="candpop" style={{ position: "fixed", left: 16, bottom: 16 }}>
            <div className="text-xs text-muted-foreground" style={{ padding: "2px 8px 6px" }}>
              {nodeLabel(cand)} に出入りする組（{candEdges.length}件）— 1つ選ぶ:
            </div>
            {candEdges.map((e) => (
              <button key={`${e.from}|${e.to}`} onClick={() => selectEdge(e)}>
                {e.from === nodeCand ? "→ " : "← "}
                {nodeLabel(nodeById.get(e.from)!)} → {nodeLabel(nodeById.get(e.to)!)}
              </button>
            ))}
          </div>
        )}
      </div>
    </Layout>
  )
}
