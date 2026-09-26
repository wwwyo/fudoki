/**
 * 原典 PDF の閲覧側。実ページの画像に語の文字層を重ねる。
 *
 * - 出力側の行を押すと、その行の記載がある頁へ移動して帯を強調する
 * - 語を押すと、その語の帯が属する行が選ばれる（逆方向）
 * - 対応のある行の帯の左端には、表と同じ番号バッジ（srflag）を重ねる
 * - 文字層の無い原典（OCR のみ）は頁画像だけ出し、押せるものに見せない
 */
import { useEffect, useMemo, useState } from "react"
import type { PdfDocMeta, PdfHitLoc, PdfPageData } from "@/lib/verify"
import { bareKey, loadPdfPage, pdfPagePng } from "@/lib/verify"

type Props = {
  /** 原典ノードが対応する文書（複数年度なら複数） */
  docs: PdfDocMeta[]
  /** 修飾キー → 文書・頁・帯（io-panel が全文書分を畳んだもの） */
  hits: Map<string, PdfHitLoc> | null
  /** 現在の年度（文書の初期選択に使う） */
  year: number | null
  /** 見ている文書・頁。選択行のジャンプ時に親が更新する */
  docId: string | null
  page: number | null
  onNavigate: (docId: string, page: number) => void
  /** 出力側に実在する行キーの集合 — その行だけフラッグを立てる */
  flagKeys: Set<string> | null
  selectedKey: string | null
  hoverKey: string | null
  onSelectRow: (key: string) => void
  onHoverRow: (key: string | null) => void
}

export function PdfSide({
  docs,
  hits,
  year,
  docId,
  page,
  onNavigate,
  flagKeys,
  selectedKey,
  hoverKey,
  onSelectRow,
  onHoverRow,
}: Props) {
  const doc =
    docs.find((d) => d.id === docId) ??
    docs.find((d) => year !== null && d.years.includes(year)) ??
    docs[0]
  const [pageData, setPageData] = useState<PdfPageData | null>(null)

  const pages = useMemo(() => {
    if (!doc) return [] as number[]
    const out: number[] = []
    for (let p = doc.first; p <= doc.last; p++) out.push(p)
    return out
  }, [doc])

  // この文書に属する hit だけを拾う（畳み込み済みの表は全文書分を持つ）
  const docHits = useMemo(() => {
    if (!hits || !doc) return [] as [string, PdfHitLoc][]
    return [...hits.entries()].filter(([, h]) => h.docId === doc.id)
  }, [hits, doc])

  const cur = page !== null && pages.includes(page) ? page : null
  // 初期表示はこのソースの行が載っている最初の頁。行を選んだときは親が hit の頁に合わせる
  const shown =
    cur ??
    (() => {
      const hp = docHits.map(([, h]) => h.page).filter((p) => pages.includes(p))
      return hp.length ? Math.min(...hp) : (pages[0] ?? null)
    })()

  useEffect(() => {
    if (!doc || shown === null) return
    let stale = false
    loadPdfPage(doc.id, shown).then((d) => {
      if (!stale) setPageData(d)
    })
    return () => {
      stale = true
    }
  }, [doc?.id, shown])

  if (!docs.length) {
    return (
      <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
        PDF レイヤが無い（bun run pdf:layer で生成）
      </p>
    )
  }
  if (!doc) {
    return (
      <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
        PDF レイヤが無い
      </p>
    )
  }

  const idx = shown !== null ? pages.indexOf(shown) : -1
  const selHit = selectedKey !== null && hits ? hits.get(selectedKey) : null

  const hitsHere = useMemo(() => docHits.filter(([, h]) => h.page === shown), [docHits, shown])

  // 語がどの行の帯に入るか（逆方向の選択用）。縦位置が行の帯に入る語は
  // すべてその行に紐づける（行番号など hit 矩形より左の文字も拾える）。
  // 帯は縦位置でソートして二分探索 — 頁の語数（数千）×帯数の全走査を毎 render で避ける
  const bands = useMemo(
    () => hitsHere.map(([k, h]) => ({ y0: h.box[1], y1: h.box[3], k })).sort((a, b) => a.y0 - b.y0),
    [hitsHere],
  )
  const wordKey = (w: [number, number, number, number, string]): string | null => {
    const cy = (w[1] + w[3]) / 2
    // cy が入る帯 = 「y0 <= cy」を満たす最後（最も下から始まる）の帯
    let lo = 0
    let hi = bands.length - 1
    let best: (typeof bands)[number] | null = null
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      if (bands[mid]!.y0 <= cy) {
        best = bands[mid]!
        lo = mid + 1
      } else {
        hi = mid - 1
      }
    }
    return best && cy <= best.y1 ? best.k : null
  }

  return (
    <div className="pdfview">
      <div className="pdfpager" role="group" aria-label="PDF のページ送り">
        <button
          className="pgbtn"
          disabled={idx <= 0}
          aria-label="前の頁"
          onClick={() => idx > 0 && onNavigate(doc.id, pages[idx - 1]!)}
        >
          ◀
        </button>
        <span className="text-xs" style={{ color: "var(--muted-foreground)" }}>
          <span className="mono">
            {shown !== null ? idx + 1 : "-"}/{pages.length}
          </span>{" "}
          頁
        </span>
        <button
          className="pgbtn"
          disabled={idx < 0 || idx >= pages.length - 1}
          aria-label="次の頁"
          onClick={() => idx >= 0 && idx < pages.length - 1 && onNavigate(doc.id, pages[idx + 1]!)}
        >
          ▶
        </button>
        <span className="mono text-xs">p.{shown ?? "-"}</span>
        {/* 文書が年度ごとに分かれているときの切替。頁番号の意味が変わるので必須 */}
        {docs.length > 1 && (
          <select
            className="ctl"
            aria-label="文書"
            value={doc.id}
            onChange={(e) => {
              const d = docs.find((x) => x.id === e.target.value)!
              onNavigate(d.id, d.first)
            }}
          >
            {docs.map((d) => (
              <option key={d.id} value={d.id}>
                {d.years.length ? `${d.years.join("・")}年度 ` : ""}
                {d.title.length > 24 ? `${d.title.slice(0, 24)}…` : d.title}
              </option>
            ))}
          </select>
        )}
        {selHit && selHit.docId === doc.id && selHit.page !== shown && (
          <button className="linky text-xs" onClick={() => onNavigate(doc.id, selHit.page)}>
            選択行は p.{selHit.page} 頁
          </button>
        )}
        {selHit && selHit.docId !== doc.id && (
          <button className="linky text-xs" onClick={() => onNavigate(selHit.docId, selHit.page)}>
            選択行は別文書の p.{selHit.page} 頁
          </button>
        )}
      </div>
      {shown !== null && (
        <div className="pdfpage">
          <img src={pdfPagePng(doc.id, shown)} alt={`PDF p.${shown}`} />
          {pageData &&
            pageData.words.map((w, i) => {
              const k = wordKey(w)
              return (
                <span
                  key={i}
                  className={`wspan${k !== null && k === hoverKey ? " srhov" : ""}`}
                  data-sr={k ?? undefined}
                  style={{
                    left: `${(w[0] / pageData.w) * 100}%`,
                    top: `${(w[1] / pageData.h) * 100}%`,
                    width: `${((w[2] - w[0]) / pageData.w) * 100}%`,
                    height: `${((w[3] - w[1]) / pageData.h) * 100}%`,
                  }}
                  onClick={k !== null ? () => onSelectRow(k) : undefined}
                  onMouseEnter={k !== null ? () => onHoverRow(k) : undefined}
                  onMouseLeave={k !== null ? () => onHoverRow(null) : undefined}
                >
                  {w[4]}
                </span>
              )
            })}
          {pageData &&
            hitsHere
              .filter(([k]) => selectedKey !== null && k === selectedKey)
              .map(([k, h]) => (
                <div
                  key={k}
                  className="hit"
                  style={{
                    left: `${(h.box[0] / pageData.w) * 100}%`,
                    top: `${(h.box[1] / pageData.h) * 100}%`,
                    width: `${((h.box[2] - h.box[0]) / pageData.w) * 100}%`,
                    height: `${((h.box[3] - h.box[1]) / pageData.h) * 100}%`,
                  }}
                />
              ))}
          {pageData &&
            flagKeys &&
            hitsHere
              .filter(([k]) => flagKeys.has(k))
              .map(([k, h]) => (
                <div
                  key={k}
                  className={`srflag${selectedKey !== null && k === selectedKey ? " sel" : ""}${hoverKey !== null && k === hoverKey ? " flaghov" : ""}`}
                  data-sr={k}
                  style={{
                    left: `${(h.box[0] / pageData.w) * 100}%`,
                    top: `${(((h.box[1] + h.box[3]) / 2) / pageData.h) * 100}%`,
                  }}
                >
                  {bareKey(k)}
                </div>
              ))}
        </div>
      )}
      {doc.textLayer === false && (
        <p className="text-xs" style={{ color: "var(--muted-foreground)", padding: "6px 8px" }}>
          この文書は文字層を持たない（OCR のみ）。語の選択・行との対応はできない。
        </p>
      )}
    </div>
  )
}
