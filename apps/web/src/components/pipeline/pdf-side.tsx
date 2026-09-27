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
  // `at` は読み込んだ頁 — 頁送りの間、前の頁の文字層が新しい画像に残るのを防ぐ
  const [pageData, setPageData] = useState<{ at: number; d: PdfPageData | null } | null>(null)

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
      if (!stale) setPageData({ at: shown, d })
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
  const curData = pageData?.at === shown ? pageData.d : null

  /** 頁送りの入力（取り込み範囲の序数）。範囲外はクランプ、同じ頁は何もしない */
  const jumpToOrdinal = (raw: string) => {
    const n = Number.parseInt(raw, 10)
    if (!doc || Number.isNaN(n) || !pages.length) return
    const p = pages[Math.min(Math.max(n, 1), pages.length) - 1]!
    if (p !== shown) onNavigate(doc.id, p)
  }

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
    // 「y0 <= cy」を満たす最後（最も下から始まる）の帯の index
    let best = -1
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      if (bands[mid]!.y0 <= cy) {
        best = mid
        lo = mid + 1
      } else {
        hi = mid - 1
      }
    }
    // 帯は y0 ではソートできるが高さは揃っていない — 見つかった帯が cy を含まなくても、
    // 上に広い帯（長い行）が残っていることがある。y0 <= cy の帯を上へ遡って、
    // 含むもののうち最も下から始まる（= 行として最も内側の）ものを取る
    for (let j = best; j >= 0; j--) {
      if (cy <= bands[j]!.y1) return bands[j]!.k
    }
    return null
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
        {/* 中央の「序数/総数」は入力で直接移動できる。key で頁が変わったら
            入力値をその頁の序数に戻す */}
        <input
          key={`${doc.id}:${shown}`}
          className="pgnum mono"
          defaultValue={idx + 1}
          inputMode="numeric"
          disabled={!pages.length}
          aria-label="取り込んだ頁の何枚目か（直接入力で移動）"
          title="取り込んだ頁の何枚目か（直接入力で移動）"
          onFocus={(e) => e.currentTarget.select()}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return
            if (e.key === "Enter") e.currentTarget.blur()
            else if (e.key === "Escape") {
              e.currentTarget.value = String(idx + 1)
              e.currentTarget.blur()
            }
          }}
          onBlur={(e) => jumpToOrdinal(e.currentTarget.value)}
        />
        <span
          className="text-xs"
          style={{ color: "var(--muted-foreground)" }}
          title="この文書に取り込んだ頁数"
        >
          / {pages.length}
        </span>
        <button
          className="pgbtn"
          disabled={idx < 0 || idx >= pages.length - 1}
          aria-label="次の頁"
          onClick={() => idx >= 0 && idx < pages.length - 1 && onNavigate(doc.id, pages[idx + 1]!)}
        >
          ▶
        </button>
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

        {/* p.N は PDF の通し頁番号（証跡・hit・頁画像ファイルが指す番号）。
            冊子の印字頁番号とはずれるが、証跡と対応させるためこちらで統一する */}
        <span
          className="mono text-xs"
          style={{ marginLeft: "auto", color: "var(--muted-foreground)" }}
          title="PDF ファイルの通し頁番号"
        >
          p.{shown ?? "-"}
        </span>
      </div>
      {shown !== null && (
        <div className="pdfpage">
          <img src={pdfPagePng(doc.id, shown)} alt={`PDF p.${shown}`} />
          {curData &&
            curData.words.map((w, i) => {
              const k = wordKey(w)
              return (
                <span
                  key={i}
                  className={`wspan${k !== null && k === hoverKey ? " srhov" : ""}`}
                  data-sr={k ?? undefined}
                  style={{
                    left: `${(w[0] / curData.w) * 100}%`,
                    top: `${(w[1] / curData.h) * 100}%`,
                    width: `${((w[2] - w[0]) / curData.w) * 100}%`,
                    height: `${((w[3] - w[1]) / curData.h) * 100}%`,
                  }}
                  onClick={k !== null ? () => onSelectRow(k) : undefined}
                  onMouseEnter={k !== null ? () => onHoverRow(k) : undefined}
                  onMouseLeave={k !== null ? () => onHoverRow(null) : undefined}
                >
                  {w[4]}
                </span>
              )
            })}
          {curData &&
            hitsHere
              .filter(([k]) => selectedKey !== null && k === selectedKey)
              .map(([k, h]) => (
                <div
                  key={k}
                  className="hit"
                  style={{
                    left: `${(h.box[0] / curData.w) * 100}%`,
                    top: `${(h.box[1] / curData.h) * 100}%`,
                    width: `${((h.box[2] - h.box[0]) / curData.w) * 100}%`,
                    height: `${((h.box[3] - h.box[1]) / curData.h) * 100}%`,
                  }}
                />
              ))}
          {curData &&
            flagKeys &&
            hitsHere
              .filter(([k]) => flagKeys.has(k))
              .map(([k, h]) => (
                <div
                  key={k}
                  className={`srflag${selectedKey !== null && k === selectedKey ? " sel" : ""}${hoverKey !== null && k === hoverKey ? " flaghov" : ""}`}
                  data-sr={k}
                  style={{
                    left: `${(h.box[0] / curData.w) * 100}%`,
                    top: `${(((h.box[1] + h.box[3]) / 2) / curData.h) * 100}%`,
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
