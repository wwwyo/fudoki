/**
 * 系統図。原典→取り込み→正規化→判断→配布物を横に並べ、共有リソースは下の別レーン。
 *
 * 選択の単位は「組」（ノード→ノードの線）。線を押すと組が選ばれ、
 * 両端のノードと線が1つに強調される。カーソルを載せたときも組全体が薄く点灯する。
 *
 * ズームは内容を包んだ <g class="vp"> への transform で掛ける。こうすると
 * ブラウザのクリック判定が変換込みで成り立ち、hover 判定も
 * vp.getScreenCTM() の逆行列で同じ変換を辿れる（ズーム/パンしても実位置とズレない）。
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { Edge, Node, Stage, Topology } from "@/lib/pipeline"
import { count, nodeRows } from "@/lib/pipeline"
import { STAGE_JA, isRes, nodeLabel, type Pair } from "@/lib/verify"

const NW = 190
const NH = 44
const CGX = 70
const CGY = 12
const PAD = 10

type Pos = { x: number; y: number; n: Node; small?: boolean }
type Layout = { pos: Record<string, Pos>; W: number; H: number; resY: number; mainH: number }

/** 水平レイアウト: 段 = 列。共有リソースは段の列の下に横一列 */
function layoutH(nodes: Node[], order: Stage["id"][]): Layout {
  const pos: Record<string, Pos> = {}
  const cols: Partial<Record<Node["stage"], Node[]>> = {}
  for (const n of nodes) {
    if (isRes(n)) continue
    ;(cols[n.stage] ||= []).push(n)
  }
  order.forEach((s, i) =>
    (cols[s] ?? []).forEach((n, k) => {
      pos[n.id] = { x: PAD + i * (NW + CGX), y: PAD + k * (NH + CGY), n }
    }),
  )
  const mainW = order.length * (NW + CGX) + PAD
  const mainH = Math.max(1, ...Object.values(cols).map((c) => c.length)) * (NH + CGY) + PAD
  const res = nodes.filter(isRes)
  const resY = mainH + 60
  res.forEach((n, k) => {
    pos[n.id] = { x: PAD + k * (NW + 24), y: resY, n, small: true }
  })
  const W = Math.max(mainW, res.length * (NW + 24) + PAD)
  return { pos, W, H: res.length ? resY + NH + PAD : mainH, resY, mainH }
}

function edgePath(p1: Pos, p2: Pos) {
  const w1 = p1.small ? 120 : NW
  const x1 = p1.x + w1
  const y1 = p1.y + NH / 2
  const x2 = p2.x
  const y2 = p2.y + NH / 2
  const mx = (x1 + x2) / 2
  return { d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, x1, y1, x2, y2 }
}

/** 組 hover 判定用ジオメトリ。辺のベジエを 24 分割でサンプルした点列を持つ */
type PairGeo = {
  pos: Layout["pos"]
  W: number
  H: number
  pairs: { from: string; to: string; pts: [number, number][]; rx0: number; ry0: number; rx1: number; ry1: number }[]
}
function buildPairGeo(edges: Edge[], lay: Layout): PairGeo {
  const pairs: PairGeo["pairs"] = []
  for (const e of edges) {
    const p1 = lay.pos[e.from]
    const p2 = lay.pos[e.to]
    if (!p1 || !p2) continue
    const w1 = p1.small ? 120 : NW
    const w2 = p2.small ? 120 : NW
    const { x1, y1, x2, y2 } = edgePath(p1, p2)
    const mx = (x1 + x2) / 2
    const pts: [number, number][] = []
    for (let i = 0; i <= 24; i++) {
      const t = i / 24
      const u = 1 - t
      pts.push([
        u * u * u * x1 + 3 * u * u * t * mx + 3 * u * t * t * mx + t * t * t * x2,
        u * u * u * y1 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y2,
      ])
    }
    pairs.push({
      from: e.from,
      to: e.to,
      pts,
      rx0: Math.min(p1.x, p2.x),
      ry0: Math.min(p1.y, p2.y),
      rx1: Math.max(p1.x + w1, p2.x + w2),
      ry1: Math.max(p1.y + NH, p2.y + NH),
    })
  }
  return { pos: lay.pos, W: lay.W, H: lay.H, pairs }
}

/** 図内座標 → 組キー。ノード上では左半分=入る組・右半分=出る組に限定する */
function pairKeyAt(geo: PairGeo, px: number, py: number): string | null {
  for (const id in geo.pos) {
    const p = geo.pos[id]!
    const w = p.small ? 120 : NW
    if (px >= p.x && px <= p.x + w && py >= p.y && py <= p.y + NH) {
      const ins = geo.pairs.filter((q) => q.to === id)
      const outs = geo.pairs.filter((q) => q.from === id)
      const cands = ins.length && outs.length ? (px < p.x + w / 2 ? ins : outs) : ins.length ? ins : outs
      let best: PairGeo["pairs"][number] | null = null
      let bd = Infinity
      for (const q of cands) {
        const o = geo.pos[q.to === id ? q.from : q.to]!
        const d = Math.abs(py - (o.y + NH / 2))
        if (d < bd) {
          bd = d
          best = q
        }
      }
      if (best) return `${best.from}|${best.to}`
      break // 辺を持たないノード上なら組矩形の判定へ
    }
  }
  const cands = geo.pairs.filter((q) => px >= q.rx0 && px <= q.rx1 && py >= q.ry0 && py <= q.ry1)
  if (!cands.length) return null
  let best: PairGeo["pairs"][number] | null = null
  let bd = Infinity
  for (const q of cands) {
    for (const pt of q.pts) {
      const d = (pt[0] - px) * (pt[0] - px) + (pt[1] - py) * (pt[1] - py)
      if (d < bd) {
        bd = d
        best = q
      }
    }
  }
  return best ? `${best.from}|${best.to}` : null
}

/** ラベルを「ユニット幅」で切る（全角=2）。レイアウト幅が字幅基準なので */
function fitText(label: string, maxUnits: number): string {
  let u = 0
  let out = ""
  for (const ch of label) {
    u += (ch.codePointAt(0) ?? 0) > 255 ? 2 : 1
    if (u > maxUnits) return out + "…"
    out += ch
  }
  return out
}

type Zoom = { k: number; tx: number; ty: number; fit: boolean }

export const LineageGraph = memo(function LineageGraph({
  topology,
  code,
  year,
  sel,
  nodeCand,
  onSelectEdge,
  onSelectNode,
}: {
  topology: Topology
  /** 見ている団体。行数の引き当てに使う */
  code: string
  year: number | null
  sel: Pair | null
  /** 候補ポップを出しているノード（その組を破線で予告する） */
  nodeCand: string | null
  onSelectEdge: (e: Pair) => void
  onSelectNode: (id: string) => void
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const vpRef = useRef<SVGGElement>(null)
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 800, h: 400 })
  const [z, setZ] = useState<Zoom>({ k: 1, tx: 0, ty: 0, fit: true })
  const [hov, setHov] = useState<string | null>(null)
  const panning = useRef(false)

  // 段の並びは報告（topology.stages）が正本 — ここで写しを持つと段を足したときに置き場の無いノードが出る
  const stageOrder = useMemo(() => topology.stages.map((s) => s.id), [topology.stages])
  const lay = useMemo(() => layoutH(topology.nodes, stageOrder), [topology.nodes, stageOrder])
  const geo = useMemo(() => buildPairGeo(topology.edges, lay), [topology.edges, lay])
  const candEdges = useMemo(
    () => (nodeCand ? topology.edges.filter((e) => e.from === nodeCand || e.to === nodeCand) : []),
    [topology.edges, nodeCand],
  )
  const fitT = useCallback((): Zoom => {
    const { w, h } = size
    // コンテナの高さが潰れている（sash の下端・レイアウト確定前）と k=0 になり、
    // 以後のズーム計算が z0.k で割って NaN になる。k は必ず正を返す
    const k = w > 0 && h > 0 ? Math.min(w / lay.W, h / lay.H) : 1
    return { k, tx: (w - lay.W * k) / 2, ty: (h - lay.H * k) / 2, fit: true }
  }, [size, lay.W, lay.H])

  // svg をコンテナに合わせる。fit モードなら寸法が変わるたびに合わせ直す
  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap) return
    const ro = new ResizeObserver(() => {
      setSize({ w: wrap.clientWidth, h: wrap.clientHeight })
    })
    ro.observe(wrap)
    setSize({ w: wrap.clientWidth, h: wrap.clientHeight })
    return () => ro.disconnect()
  }, [])

  // サイズ確定後・fit 中だけ追従。手動ズーム/パン中（fit=false）は維持
  useEffect(() => {
    setZ((prev) => (prev.fit ? fitT() : prev))
  }, [size, fitT])

  // （sx,sy）= svg 座標のアンカー点が画面上動かないように k0→k1 へズーム
  const zoomAt = useCallback(
    (sx: number, sy: number, k1: number) => {
      setZ((prev) => {
        const z0 = prev.fit ? fitT() : prev
        const kMin = Math.min(0.3, fitT().k)
        const k = Math.min(3, Math.max(kMin, k1))
        if (k === z0.k) return z0
        return { k, tx: sx - (sx - z0.tx) * (k / z0.k), ty: sy - (sy - z0.ty) * (k / z0.k), fit: false }
      })
    },
    [fitT],
  )

  const zoomAction = useCallback(
    (a: "in" | "out" | "one" | "fit") => {
      const r = svgRef.current?.getBoundingClientRect()
      if (!r) return
      const cx = r.width / 2
      const cy = r.height / 2
      if (a === "fit") setZ(fitT())
      else if (a === "in") zoomAt(cx, cy, (z.fit ? fitT().k : z.k) * 1.3)
      else if (a === "out") zoomAt(cx, cy, (z.fit ? fitT().k : z.k) / 1.3)
      else zoomAt(cx, cy, 1)
    },
    [fitT, zoomAt, z],
  )

  /* ---- ポインタ操作: パン / ピンチ / クリック ---- */
  // ドラッグ・ピンチ直後の click を1回だけ捨てる（辺・ノードの誤選択防止）
  const noClick = useRef(false)
  const drag = useRef<{ id: number; x0: number; y0: number; tx0: number; ty0: number; active: boolean } | null>(null)
  const pts = useRef(new Map<number, { x: number; y: number }>())
  const pinch = useRef<{ d0: number; mx0: number; my0: number; k0: number; tx0: number; ty0: number } | null>(null)

  // クライアント座標 → 図内座標（vp の変換を逆に辿る）
  const toGraph = (cx: number, cy: number): { x: number; y: number } | null => {
    const ctm = vpRef.current?.getScreenCTM()
    if (!ctm) return null
    const p = new DOMPoint(cx, cy).matrixTransform(ctm.inverse())
    return { x: p.x, y: p.y }
  }

  const onPointerDown = (e: React.PointerEvent) => {
    if ((e.target as Element).closest(".zoomctl")) return
    if (e.pointerType === "mouse" && e.button !== 0) return
    const z0 = z.fit ? fitT() : z
    pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (pts.current.size === 2) {
      const [a, b] = [...pts.current.values()]
      const r = svgRef.current!.getBoundingClientRect()
      pinch.current = {
        d0: Math.hypot(a!.x - b!.x, a!.y - b!.y) || 1,
        mx0: (a!.x + b!.x) / 2 - r.left,
        my0: (a!.y + b!.y) / 2 - r.top,
        k0: z0.k,
        tx0: z0.tx,
        ty0: z0.ty,
      }
      drag.current = null // 2本指になった時点でクリック候補は潰す
      setHov(null)
    } else if (pts.current.size === 1) {
      drag.current = { id: e.pointerId, x0: e.clientX, y0: e.clientY, tx0: z0.tx, ty0: z0.ty, active: false }
    }
  }

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (pts.current.has(e.pointerId)) pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
      if (pinch.current && pts.current.size >= 2) {
        const [a, b] = [...pts.current.values()]
        const r = svgRef.current?.getBoundingClientRect()
        if (!r) return
        const mx = (a!.x + b!.x) / 2 - r.left
        const my = (a!.y + b!.y) / 2 - r.top
        const p = pinch.current
        const kMin = Math.min(0.3, fitT().k)
        const k = Math.min(3, Math.max(kMin, p.k0 * (Math.hypot(a!.x - b!.x, a!.y - b!.y) / p.d0)))
        setZ({ k, tx: mx - (p.mx0 - p.tx0) * (k / p.k0), ty: my - (p.my0 - p.ty0) * (k / p.k0), fit: false })
        setHov(null)
        return
      }
      const d = drag.current
      if (!d || e.pointerId !== d.id) return
      const dx = e.clientX - d.x0
      const dy = e.clientY - d.y0
      // 6px 未満はクリックとして扱う（辺選択・ノード候補ポップを壊さない）
      if (!d.active) {
        if (dx * dx + dy * dy < 36) return
        d.active = true
        panning.current = true
        svgRef.current?.classList.add("panning")
        setHov(null)
      }
      setZ((prev) => ({ ...prev, tx: d.tx0 + dx, ty: d.ty0 + dy, fit: false }))
    }
    const onEnd = (e: PointerEvent) => {
      pts.current.delete(e.pointerId)
      if (pinch.current && pts.current.size < 2) {
        pinch.current = null
        drag.current = null
        noClick.current = true
        setTimeout(() => (noClick.current = false), 100)
      }
      if (drag.current && e.pointerId === drag.current.id) {
        if (drag.current.active) {
          noClick.current = true
          setTimeout(() => (noClick.current = false), 100)
        }
        drag.current = null
        panning.current = false
        svgRef.current?.classList.remove("panning")
      }
    }
    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onEnd)
    window.addEventListener("pointercancel", onEnd)
    return () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onEnd)
      window.removeEventListener("pointercancel", onEnd)
    }
  }, [fitT])

  // ホイール（ctrl+wheel のピンチ操作を含む）でポインタ位置をアンカーにズーム。
  // ⚠️ React の onWheel は passive で preventDefault できないのでネイティブに張る
  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = svgRef.current!.getBoundingClientRect()
      const d = e.deltaY * (e.deltaMode === 1 ? 16 : 1)
      setZ((prev) => {
        const z0 = prev.fit ? fitT() : prev
        const kMin = Math.min(0.3, fitT().k)
        const k = Math.min(3, Math.max(kMin, z0.k * Math.exp(-d * (e.ctrlKey ? 0.01 : 0.0022))))
        const sx = e.clientX - r.left
        const sy = e.clientY - r.top
        return { k, tx: sx - (sx - z0.tx) * (k / z0.k), ty: sy - (sy - z0.ty) * (k / z0.k), fit: false }
      })
    }
    wrap.addEventListener("wheel", onWheel, { passive: false })
    return () => wrap.removeEventListener("wheel", onWheel)
  }, [fitT])

  const onPointerMove = (e: React.PointerEvent) => {
    if (drag.current || pinch.current) return
    const g = toGraph(e.clientX, e.clientY)
    if (!g) {
      setHov(null)
      return
    }
    const key = pairKeyAt(geo, g.x, g.y)
    // 選択済みの組は選択スタイルが既に出ているので予告は重ねない
    setHov(key && sel && `${sel.from}|${sel.to}` === key ? null : key)
  }

  const onClick = (e: React.MouseEvent) => {
    if (noClick.current) {
      noClick.current = false
      return
    }
    const hit = (e.target as Element).closest("[data-edge]")
    if (hit) {
      const [from, to] = (hit.getAttribute("data-edge") ?? "").split("|")
      onSelectEdge({ from: from!, to: to! })
      return
    }
    const nd = (e.target as Element).closest("[data-node]")
    if (nd) onSelectNode(nd.getAttribute("data-node")!)
  }

  const selKey = sel ? `${sel.from}|${sel.to}` : null

  return (
    <div ref={wrapRef} className="graphwrap" style={{ flexBasis: "100%", height: "100%" }}>
      <svg
        ref={svgRef}
        className="graphsvg"
        width={size.w}
        height={size.h}
        viewBox={`0 0 ${size.w} ${size.h}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerLeave={() => setHov(null)}
        onClick={onClick}
      >
        <g className="vp" ref={vpRef} transform={`translate(${z.tx} ${z.ty}) scale(${z.k})`}>
          <defs>
            <marker id="arw" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
              <path d="M0,0 L7,3.5 L0,7" fill="none" stroke="var(--muted-foreground)" strokeWidth="1.2" />
            </marker>
            <marker id="arw-sel" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8" fill="none" stroke="var(--primary)" strokeWidth="1.6" />
            </marker>
            <marker id="arw-hov" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8" fill="none" stroke="var(--primary)" strokeWidth="1.6" opacity=".55" />
            </marker>
          </defs>
          {/* 段の見出し。層はデータが流れる下の方へ読むので、見出しは列の下に置く */}
          {stageOrder.map((s, i) =>
            topology.nodes.some((n) => n.stage === s && !isRes(n)) ? (
              <text key={s} x={PAD + i * (NW + CGX)} y={lay.mainH + 30} fontSize="11" fill="var(--muted-foreground)">
                {STAGE_JA[s]}
              </text>
            ) : null,
          )}
          {topology.nodes.some(isRes) && (
            <text x={PAD} y={lay.resY - 8} fontSize="11" fill="var(--muted-foreground)">
              判断のリソース（共有・全団体共通）
            </text>
          )}
          {/* 辺 */}
          {topology.edges.map((e) => {
            const p1 = lay.pos[e.from]
            const p2 = lay.pos[e.to]
            if (!p1 || !p2) return null
            const { d } = edgePath(p1, p2)
            const key = `${e.from}|${e.to}`
            const isSel = selKey === key
            const isCand = candEdges.some((c) => c.from === e.from && c.to === e.to)
            const isHov = hov === key
            return (
              <g key={key} className={isHov ? "hov" : ""}>
                <path className="edge-hov-under" d={d} />
                <path className="edge-hov" d={d} markerEnd="url(#arw-hov)" />
                {isSel ? (
                  <>
                    <path className="edge-sel-under" d={d} />
                    <path className="edge-sel" d={d} markerEnd="url(#arw-sel)" />
                  </>
                ) : (
                  <path className={isCand ? "cand" : "edge"} d={d} markerEnd="url(#arw)" />
                )}
                <path className="edge-hit" d={d} data-edge={key}>
                  <title>
                    {nodeLabel(p1.n)} → {nodeLabel(p2.n)}
                  </title>
                </path>
              </g>
            )
          })}
          {/* ノード */}
          {Object.entries(lay.pos).map(([id, p]) => {
            const w = p.small ? 120 : NW
            const { rows, scopedToYear } = nodeRows(p.n, code, year)
            const isSelN = sel && (sel.from === id || sel.to === id)
            const isHovN = hov ? hov.split("|").includes(id) : false
            const tag = sel && sel.from === id ? "入力" : sel && sel.to === id ? "出力" : null
            const shared = !p.n.jurisdictionCode
            return (
              <g
                key={id}
                className={`gnode${isSelN ? " sel" : ""}${isHovN ? " hov" : ""}`}
                data-kind={isRes(p.n) ? "res" : "main"}
                transform={`translate(${p.x},${p.y})`}
                data-node={id}
                style={{ cursor: "pointer" }}
              >
                {isSelN && <rect className="ring" x={-5} y={-5} width={w + 10} height={NH + 10} rx={11} />}
                <rect className="body" width={w} height={NH} rx={7} />
                <rect className="hring" x={-5} y={-5} width={w + 10} height={NH + 10} rx={11} />
                {tag && (
                  <>
                    <rect className="io-tag-bg" x={w / 2 - 18} y={-9} width={36} height={14} rx={7} />
                    <text className="io-tag" x={w / 2} y={1} textAnchor="middle">
                      {tag}
                    </text>
                  </>
                )}
                <text x={10} y={17} fontSize="11.5" fontWeight={500} fill="var(--foreground)">
                  {fitText(nodeLabel(p.n), p.small ? 16 : 26)}
                </text>
                <text x={10} y={34} fontSize="10.5" fill="var(--muted-foreground)">
                  {fitText(
                    (isRes(p.n) ? "共有リソース" : STAGE_JA[p.n.stage]) +
                      " · " +
                      (rows === null ? "—" : `${count(rows)} 行`) +
                      (shared && !isRes(p.n) ? "（共有・この団体分）" : "") +
                      (year !== null && !scopedToYear && p.n.rowsByJurisdiction ? " · 全年度" : "") +
                      (!p.n.rowsByJurisdiction ? " · 規則表" : ""),
                    p.small ? 20 : 36,
                  )}
                </text>
              </g>
            )
          })}
        </g>
      </svg>
      <div className="zoomctl" aria-label="図のズーム">
        <button onClick={() => zoomAction("in")} title="拡大（ホイールでも可）">
          ＋
        </button>
        <button onClick={() => zoomAction("out")} title="縮小">
          －
        </button>
        <button onClick={() => zoomAction("fit")} title="全体が収まるように表示">
          fit
        </button>
        <button onClick={() => zoomAction("one")} title="等倍（1x）に戻す">
          1x
        </button>
      </div>
    </div>
  )
})
