/**
 * 組（入力→出力）の検査パネル。系統図で辺を選んだ下側ペインに出る。
 *
 * - 両側の行を `/local/rows` から読んで並べ、対応キーのある行にバッジを付ける
 * - 片側で行を押すと反対側の同じ鍵の行が点灯する（行対応は同じ鍵空間のときだけ）
 * - 入力側が PDF 原典なら頁画像ビューアを出し、行選択で該当頁へ飛ぶ
 * - 同じ側を共有する組（例: 1つの入力→複数の出力）はその側を1枚だけ出し、
 *   バラつく側を縦に並べる — 同じ表を組ごとに複写しない
 * - 各側の詳細トグルに 出所（証跡）・取り込みの検証・検査・金額の単位 を畳む
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type {
  Check,
  Direction,
  Node,
  ProjectNamesExtract,
  Provenance,
  ReportData,
  RevenueAccountsExtract,
  StatementExtract,
} from "@/lib/pipeline"
import { DIR_JA, extractedKindOf, isCanonicalFetch } from "@/lib/pipeline"
import {
  colDocsOf,
  edgeDir,
  keysEqual,
  linkSetOf,
  linkSetsByDir,
  loadHitMap,
  loadRows,
  nodeLabel,
  srcIdOf,
  type NodeRows,
  type Pair,
  type PdfHitLoc,
  type PdfRows,
  type TableRows,
} from "@/lib/verify"
import { PdfSide } from "./pdf-side"
import { RowTable, type RowTableHandle } from "./row-table"

/** 行を取りに行く hook。組を替えると両側とも取り直す（verify.ts 側でキャッシュ） */
function useRows(nodeId: string | null, code: string, year: number | null, dir: Direction | null) {
  const [rows, setRows] = useState<NodeRows | null>(null)
  useEffect(() => {
    if (!nodeId) {
      setRows(null)
      return
    }
    let stale = false
    setRows(null)
    loadRows(nodeId, code, year, dir).then((r) => {
      if (!stale) setRows(r)
    })
    return () => {
      stale = true
    }
  }, [nodeId, code, year, dir])
  return rows
}

/** PDF 側が来たとき、hit の対応表を取りに行く hook */
function useHitMap(rows: NodeRows | null, nodeId: string | null, dir: Direction | null = null) {
  const [map, setMap] = useState<Map<string, PdfHitLoc> | null>(null)
  const srcId = nodeId ? srcIdOf(nodeId) : null
  const docs = rows?.kind === "pdf" ? rows.docs : null
  useEffect(() => {
    if (!docs || !srcId) {
      setMap(null)
      return
    }
    let stale = false
    setMap(null)
    loadHitMap(docs, srcId, dir ?? undefined).then((m) => {
      if (!stale) setMap(m)
    })
    return () => {
      stale = true
    }
  }, [docs, srcId, dir])
  return map
}

const fmt = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString("ja-JP"))

/** リード文（SQL コメント・宣言 yml の description）の `**…**` 強調マーカー。画面では太字を使わないので剥がす */
const plain = (text: string) => text.replaceAll("**", "")

/** ノードのリード（表が何であるか）。複数行の説明は先頭行だけを見出しの下に出す */
function nodeLeadOf(n: Node): string | null {
  // 原典の description は URL と取得日時 — 表の意味ではないので定型を出す
  // （出所は従来通り詳細トグルが持つ）
  if (n.kind === "origin") return "自治体が公開した予算・決算の資料そのもの"
  const lead = (n.description ?? "").split("\n")[0]?.trim()
  return lead || null
}

/** 検査の表示名。自然文の説明があればそれを使い、なければテスト名をそのまま出す */
function checkLabel(c: Check): string {
  if (c.description) return c.description
  const lines = (c.explanation ?? "").split("\n").map((s) => s.trim()).filter(Boolean)
  // 先頭行が「警告。」系の severity 断り書きだけのときは説明の見出しではない — 次の行を使う
  const head = lines[0] && /^[警告失敗]{2,3}。/.test(lines[0]) ? lines[1] : lines[0]
  return head || c.name
}

/** 非 pass の検査の帰属表示。「どの団体の行に当たったか」を画面から判別できるようにする */
function attributionNote(c: Check, code: string): string | null {
  const a = c.attribution
  if (!a) return null
  if (a.kind === "cross") return "横断・対象特定不能（どの団体の行かは特定できない）"
  if (!a.counts) return null
  const mine = a.counts[code] ?? 0
  const others = Object.entries(a.counts).filter(([k]) => k !== code)
  const bits: string[] = []
  if (mine > 0) bits.push(`この団体 ${mine} 件`)
  for (const [k, n] of others) bits.push(`${k} ${n} 件`)
  if (!bits.length) return null
  return mine > 0 ? `帰属: ${bits.join("・")}` : `帰属: ${bits.join("・")}（この団体の行ではない）`
}

/** 側ごとの検査一覧（詳細トグルの中身） */
function CheckList({ checks, code }: { checks: Check[]; code: string }) {
  if (!checks.length) return null
  return (
    <>
      <div className="dh">検査（{checks.length}件）</div>
      {checks.map((c) => {
        const att = c.status !== "pass" ? attributionNote(c, code) : null
        return (
          <div className="ck" key={c.name}>
            <span className={`badge ${c.status === "pass" ? "ok" : c.status === "warn" ? "plain" : "bad"}`}>
              {c.status === "pass" ? "成功" : c.status === "warn" ? "警告" : "失敗"}
            </span>{" "}
            <span title={c.name}>{plain(checkLabel(c))}</span>
            {att && <span className="text-muted-foreground">（{att}）</span>}
            {c.status !== "pass" && c.detail && (
              <div className="text-muted-foreground" style={{ paddingLeft: 44 }}>
                {plain(c.detail)}
                {c.failures != null ? ` — ${fmt(c.failures)} 行` : ""}
              </div>
            )}
            {/* 非 pass では説明の全文を出す — 「なぜこの検査があるか」が分からないと
                警告を見ても放置すべきか判断できない */}
            {c.status !== "pass" && c.explanation && (
              <div
                className="text-muted-foreground"
                style={{ paddingLeft: 44, fontSize: 11, whiteSpace: "pre-wrap" }}
              >
                {plain(c.explanation)}
              </div>
            )}
            {c.attribution?.rows?.length ? (
              <div className="mono text-muted-foreground" style={{ paddingLeft: 44, fontSize: 11 }}>
                <div>{c.attribution.columns?.join(" | ")}</div>
                {c.attribution.rows.slice(0, 3).map((r, i) => (
                  <div key={i}>{r.map((v) => String(v ?? "")).join(" | ")}</div>
                ))}
              </div>
            ) : null}
          </div>
        )
      })}
    </>
  )
}

/** 証跡1件の「取り込みの検証」の文言。PDF 抽出は復元が成立しないので内部突合を出す */
function verificationLines(p: Provenance): { ok: boolean; text: string }[] {
  const ex = p.extracted
  // ⚠️ ディスク上の証跡は extracted.kind を持たない — 判別は抽出器のパスから引く
  const kind = extractedKindOf(p)
  if (ex && kind === "statement") {
    const s = ex as StatementExtract
    return [
      {
        ok: (s.leavesReconciled ?? 0) === (s.leaves ?? 0),
        text: `葉の合計と、同じ PDF 内の目の印字額が一致（${fmt(s.leavesReconciled)}/${fmt(s.leaves)} 行）`,
      },
      {
        ok: (s.mokuHeadersFound ?? 0) === (s.moku ?? 0),
        text: `抽出した目すべてに、金額つきの見出しが PDF 内にあった（${fmt(s.mokuHeadersFound)}/${fmt(s.moku)}）`,
      },
      ...(p.verification ? [{ ok: true, text: `方式: ${p.verification}` }] : []),
    ]
  }
  if (ex && kind === "project-names") {
    const x = ex as ProjectNamesExtract
    return [
      {
        ok: x.projectsReconciled === undefined || x.projectsReconciled === x.projects,
        text: `事業名と、同じ PDF 内の印字額が一致（${fmt(x.projectsReconciled)}/${fmt(x.projects)} 事業）`,
      },
      ...(x.moku !== undefined
        ? [
            {
              ok: (x.mokuHeadersFound ?? 0) === x.moku,
              text: `目の見出しが PDF 内にあった（${fmt(x.mokuHeadersFound)}/${fmt(x.moku)}）`,
            },
          ]
        : []),
    ]
  }
  if (ex && kind === "revenue-accounts") {
    const x = ex as RevenueAccountsExtract
    return [
      {
        ok: true,
        text: `科目名を抽出（${fmt(x.named)}/${fmt(x.moku)} 目に名称、うち金額まで取れたのは ${fmt(x.withAmount)}）`,
      },
    ]
  }
  // 正本の取り込み: 復元検査
  return [
    {
      ok: p.roundtrip_verified,
      text: `原典の CSV から同じ表を再構成できる（sha256 ${String(p.sha256 ?? "").slice(0, 12)}…）`,
    },
  ]
}

/** 側ごとの詳細トグル。原典側は出所・取り込みの検証・証跡、それ以外は検査・金額の単位 */
function SideDetail({
  node,
  srcIds,
  dir,
  year,
  rows,
  report,
  code,
}: {
  node: Node
  /** 原典ノードの場合、その裏にある取り込みソース（検査・証跡の引き当てに使う） */
  srcIds: string[]
  dir: Direction | null
  year: number
  rows: NodeRows | null
  report: ReportData
  code: string
}) {
  // dbt の検査は source ノード（取り込み表）に bind する。原典ノードはその代理として
  // 図に出るので、証跡だけでなく `source.*` に bind した検査もここへ寄せる
  const checks = report.checks.filter(
    (c) => c.binds.includes(node.id) || (node.kind === "origin" && srcIds.some((s) => c.binds.includes(s))),
  )
  const bad = checks.filter((c) => c.status !== "pass" && c.status !== "warn").length
  const warn = checks.filter((c) => c.status === "warn").length
  const ckBad = [bad && `失敗${bad}`, warn && `警告${warn}`].filter(Boolean).join("・")

  // 原典ノードの証跡は /local/rows の応答が持ってくる（団体コードから絞り込み済み）
  const provs: Provenance[] =
    node.kind === "origin" && rows && (rows.kind === "pdf" || rows.kind === "table")
      ? ((rows as PdfRows | TableRows).provs ?? [])
      : []
  const provsShown = provs.filter((p) => p.fiscal_year === year)
  const prov = provsShown[0] ?? provs[0] ?? null

  // 金額の単位の宣言（向きが決まる組だけ。年度が効く団体は年度で絞る）
  const amounts = dir ? (report.amounts[dir] ?? []) : []
  const amountsShown = amounts.filter((a) => a.years === null || a.years.includes(year))

  // 見えている表の列のうち語彙が引けるもの。原典の列は原典自身の見出しなので引かない
  const colDocs = rows?.kind === "table" ? colDocsOf(node, report.columnDocs) : {}
  const docCols = rows?.kind === "table" ? rows.columns.filter((c) => colDocs[c]) : []

  if (!prov && !checks.length && !amountsShown.length && !docCols.length) return null

  const summary = prov
    ? `詳細${checks.length ? `（検査${ckBad ? ` ${ckBad}` : ` ${checks.length}件`}）` : ""}`
    : checks.length
      ? ckBad
        ? `検査 ${checks.length}件（${ckBad}）`
        : `検査 ${checks.length}件：すべて成功`
      : `列の意味 ${docCols.length}列`

  return (
    <details className="fold">
      <summary>{summary}</summary>
      {prov && (
        <>
          {(prov.document_title || prov.dataset_title || prov.resource_name) && (
            <div className="drow">
              <span className="dk">資料名</span>
              <span>{prov.document_title || prov.dataset_title || prov.resource_name}</span>
            </div>
          )}
          <div className="drow">
            <span className="dk">形式</span>
            <span>
              {rows?.kind === "pdf"
                ? "PDF（組版からの抽出）"
                : `CSV（そのまま取り込み${prov.encoding ? `・${prov.encoding}` : ""}）`}
              {prov.layout ? `・${prov.layout}` : ""}
            </span>
          </div>
          <div className="drow">
            <span className="dk">取得元</span>
            <span>
              <a href={prov.request_url} target="_blank" rel="noreferrer">
                {prov.request_url}
              </a>
            </span>
          </div>
          {prov.landing_page && (
            <div className="drow">
              <span className="dk">公開ページ</span>
              <span>
                <a href={prov.landing_page} target="_blank" rel="noreferrer">
                  {prov.landing_page}
                </a>
              </span>
            </div>
          )}
          {prov.pages && (
            <div className="drow">
              <span className="dk">ページ範囲</span>
              <span>
                p.{prov.pages[0]}–{prov.pages[1]}
              </span>
            </div>
          )}
          <div className="drow">
            <span className="dk">取得</span>
            <span className="text-muted-foreground">
              {String(prov.fetched_at ?? "").slice(0, 10)} ・ {fmt(prov.bytes)} B
            </span>
          </div>
          {isCanonicalFetch(prov) && (
            <div className="drow">
              <span className="dk">行数</span>
              <span>{fmt(prov.rows)} 行</span>
            </div>
          )}
          {prov.source_amount_unit && (
            <div className="drow">
              <span className="dk">原典の単位</span>
              <span>{prov.source_amount_unit}</span>
            </div>
          )}
          <div className="dh">取り込みの検証</div>
          {verificationLines(prov).map((v, i) => (
            <div className="ck" key={i}>
              <span className={`badge ${v.ok ? "ok" : "bad"}`}>{v.ok ? "一致" : "不一致"}</span> {v.text}
            </div>
          ))}
          {prov.normalization?.length ? (
            <>
              <div className="dh">抽出時の正規化</div>
              {prov.normalization.map((n, i) => (
                <div className="ck text-muted-foreground" key={i}>
                  {n}
                </div>
              ))}
            </>
          ) : null}
          {(prov.redistribute || prov.license_id || prov.attribution) && (
            <>
              <div className="dh">再配布</div>
              {prov.license_id && (
                <div className="drow">
                  <span className="dk">ライセンス</span>
                  <span>{prov.license_id}</span>
                </div>
              )}
              {prov.attribution && (
                <div className="drow">
                  <span className="dk">帰属表示</span>
                  <span>{prov.attribution}</span>
                </div>
              )}
              {prov.redistribute && (
                <div className="drow">
                  <span className="dk">再配布</span>
                  <span>
                    {prov.redistribute}
                    {prov.redistribute_basis ? ` — ${prov.redistribute_basis}` : ""}
                  </span>
                </div>
              )}
            </>
          )}
        </>
      )}
      {amountsShown.length > 0 && (
        <>
          <div className="dh">金額の単位{dir ? `（${DIR_JA[dir]}）` : ""}</div>
          {amountsShown.map((a, i) => (
            <div className="drow" key={i}>
              <span className="dk mono">{a.name}</span>
              <span>
                {a.unit}（×{a.multiplier.toLocaleString("ja-JP")} → 円）・{a.phaseLabel}
                {a.years ? `・${a.years.join("・")}年度` : "・全年度"}
                {a.source !== "dbt_project" &&
                  `・宣言: ${a.source === "source_amount_unit" ? "証跡" : "注意点"}`}
              </span>
            </div>
          ))}
        </>
      )}
      {docCols.length > 0 && (
        <>
          <div className="dh">列の意味（{docCols.length}/{rows?.kind === "table" ? rows.columns.length : 0}列）</div>
          {docCols.map((c) => {
            const d = colDocs[c]!
            return (
              <div className="drow" key={c}>
                <span className="dk mono">{c}</span>
                <span>{plain([d.title, d.description].filter(Boolean).join(" — "))}</span>
              </div>
            )
          })}
        </>
      )}
      <CheckList checks={checks} code={code} />
    </details>
  )
}

export function IoPanel({
  report,
  code,
  pairs,
  onRemovePair,
  year,
  pdfDocId,
  pdfPage,
  onPdfNavigate,
}: {
  report: ReportData
  code: string
  /** 選択中の組。ノード側面クリックではその側の辺が全部入るので複数 */
  pairs: Pair[]
  onRemovePair: (p: Pair) => void
  year: number
  /** overview の PDF 側が見ている文書・頁（組の PDF は StarPanel 内で持つ） */
  pdfDocId: string | null
  pdfPage: number | null
  onPdfNavigate: (docId: string, page: number) => void
}) {
  if (!pairs.length) {
    return (
      <Overview
        report={report}
        code={code}
        year={year}
        pdfDocId={pdfDocId}
        pdfPage={pdfPage}
        onPdfNavigate={onPdfNavigate}
      />
    )
  }

  // 「同じ側か」の判定は端点ノード id で十分 — 原典ノードは文書単位にまとまっている
  // （歳出・歳入が同じ PDF なら1ノード）ので、これ以上分けると同じ文書が別枚に複写される
  const sameIn = pairs.every((p) => p.from === pairs[0]!.from)
  const sameOut = pairs.every((p) => p.to === pairs[0]!.to)

  if (sameIn || sameOut) {
    return (
      <StarPanel
        report={report}
        code={code}
        pairs={pairs}
        shared={sameIn ? "in" : "out"}
        year={year}
        onRemovePair={onRemovePair}
      />
    )
  }
  // 共通の端点を持たない組み合わせ（側面クリックでは作れない）— 1組ずつの星として並べる
  return (
    <>
      {pairs.map((p) => (
        <StarPanel
          key={`${p.from}|${p.to}`}
          report={report}
          code={code}
          pairs={[p]}
          shared="in"
          year={year}
          onRemovePair={onRemovePair}
        />
      ))}
    </>
  )
}

/** 側の行ビュー（表 or PDF or 空）。スクロール用の ref は表のときだけ効く */
function SideRows({
  rows,
  hits,
  linkedKeys,
  selectedKeys,
  hoverKeys,
  keyDir,
  onSelectRow,
  onHoverRow,
  tableRef,
  pdfNav,
  onPdfNavigate,
  year,
  docs,
}: {
  rows: NodeRows
  hits: Map<string, PdfHitLoc> | null
  linkedKeys: Set<string> | null
  selectedKeys: Set<string> | null
  hoverKeys: Set<string> | null
  /** 表側の鍵に載せる向き修飾（'row' = 行自身の direction 列） */
  keyDir?: Direction | "row"
  onSelectRow: (keys: Set<string>) => void
  onHoverRow: (keys: Set<string> | null) => void
  tableRef: React.RefObject<RowTableHandle | null>
  pdfNav: { docId: string | null; page: number | null }
  onPdfNavigate: (docId: string, page: number) => void
  year: number
  docs: ReturnType<typeof colDocsOf>
}) {
  if (rows.kind === "pdf") {
    return (
      <PdfSide
        docs={rows.docs}
        hits={hits}
        year={year}
        docId={pdfNav.docId}
        page={pdfNav.page}
        onNavigate={onPdfNavigate}
        flagKeys={linkedKeys}
        selectedKeys={selectedKeys}
        hoverKeys={hoverKeys}
        onSelectRow={onSelectRow}
        onHoverRow={onHoverRow}
      />
    )
  }
  if (rows.kind === "table") {
    return (
      <RowTable
        ref={tableRef}
        table={rows}
        linkedKeys={linkedKeys}
        selectedKeys={selectedKeys}
        hoverKeys={hoverKeys}
        keyDir={keyDir}
        docs={docs}
        onSelectRow={onSelectRow}
        onHoverRow={onHoverRow}
      />
    )
  }
  return <p className="text-xs text-muted-foreground">行データなし（{rows.reason}）</p>
}

/**
 * 同じ側を共有する組の検査パネル。共有側の表は1枚だけ出し、バラつく側を縦に並べる。
 * 行選択はパネル単位 — 共有側の行を選ぶと、鍵を持つすべての側の対応行が光る。
 * PDF の表示位置は PDF を持つ側ごと（共有側に1つ＋バラつく側それぞれ）。
 */
function StarPanel({
  report,
  code,
  pairs,
  shared,
  year,
  onRemovePair,
}: {
  report: ReportData
  code: string
  pairs: Pair[]
  /** どちら側を共有するか。"in" = 同じ入力→複数の出力、"out" = 複数の入力→同じ出力 */
  shared: "in" | "out"
  year: number
  onRemovePair: (p: Pair) => void
}) {
  const nodeById = useMemo(
    () => new Map(report.topology.nodes.map((n) => [n.id, n])),
    [report.topology.nodes],
  )
  const sharedId = shared === "in" ? pairs[0]!.from : pairs[0]!.to
  const sharedNode = nodeById.get(sharedId)
  // `.origin` ノードは文書単位で併合済み（歳出・歳入が同じ PDF なら1ノード）—
  // その id で引くとぶら下がる全 source の行・証跡が返る。向きが混ざるときは
  // 行・金額宣言を方向で絞れないので null に倒す
  const sharedDirs = new Set(pairs.map((p) => edgeDir(p.from, p.to)))
  const dir = sharedDirs.size === 1 ? [...sharedDirs][0]! : null

  // 行選択と共有側の PDF 表示位置はパネルに紐づく。年度が変わると行の実体も文書も変わるので捨てる
  const [selectedKeys, setSelectedKeys] = useState<Set<string> | null>(null)
  const [hoverKeys, setHoverKeys] = useState<Set<string> | null>(null)
  const [pdfNav, setPdfNav] = useState<{ docId: string | null; page: number | null }>({
    docId: null,
    page: null,
  })
  useEffect(() => {
    setSelectedKeys(null)
    setPdfNav({ docId: null, page: null })
  }, [year])

  const sharedRows = useRows(sharedId, code, year, dir)
  // 原典の hit はぶら下がる source ごとに載っている。併合原典（歳出・歳入が同じ
  // 文書に綴じられている）は両方向ぶんを、その辺の向き修飾で畳み込んで1枚にする
  // （overview と同じ形 — 行鍵が向き修飾で衝突しないので共存できる）
  const sharedIsOrigin = sharedNode?.kind === "origin"
  const [sharedHits, setSharedHits] = useState<Map<string, PdfHitLoc> | null>(null)
  const sharedDocs = sharedRows?.kind === "pdf" ? sharedRows.docs : null
  const hitSpecKey = pairs.map((p) => `${p.to}:${edgeDir(p.from, p.to) ?? ""}`).join("|")
  useEffect(() => {
    if (!sharedDocs || !sharedIsOrigin) {
      setSharedHits(null)
      return
    }
    let stale = false
    Promise.all(
      pairs.map((p) => loadHitMap(sharedDocs, p.to, edgeDir(p.from, p.to) ?? undefined)),
    ).then((ms) => {
      if (stale) return
      const m = new Map<string, PdfHitLoc>()
      ms.forEach((x) => x.forEach((v, k) => m.set(k, v)))
      setSharedHits(m)
    })
    return () => {
      stale = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pairs の中身は hitSpecKey で追う
  }, [sharedDocs, sharedIsOrigin, hitSpecKey])
  const sharedTable = useRef<RowTableHandle>(null)

  /**
   * 対応バッジの母数 = 反対側に実在する行キーの集合。共有側から見ると反対側は
   * 複数あるので和集合を取る（どれか1つの側に載っていれば「対応あり」）。
   * バラつく側から見た母数は共有側の鍵集合（StarSide が受け取って使う）。
   *
   * 鍵はバラつく側がその辺の向きで修飾する `<空間>|<年度>|<向き>|<鍵>` と一致するよう、
   * 共有側は行自身の direction 列で修飾する（'row'）。共有表が向き列を持たない
   * ときは無修飾のまま — 向きを持つ側とは一致しなくなる（誤対応より対応なしのほうが正しい）。
   */
  const sharedKeys = useMemo<Set<string> | null>(() => {
    if (sharedHits) return new Set(sharedHits.keys())
    return sharedRows?.kind === "table" ? linkSetOf(sharedRows, "row") : null
  }, [sharedHits, sharedRows])

  const peerMap = useRef(new Map<string, Set<string>>())
  const [peerKeys, setPeerKeys] = useState<Set<string> | null>(null)
  const reportPeers = useCallback((k: string, s: Set<string> | null) => {
    if (s === null) peerMap.current.delete(k)
    else peerMap.current.set(k, s)
    let u: Set<string> | null = null
    peerMap.current.forEach((v) => v.forEach((x) => (u ??= new Set()).add(x)))
    setPeerKeys(u)
  }, [])

  // 行が選ばれたらバラつく側の表・PDF を追わせるため、各側が jump 関数を登録する
  const varJump = useRef(new Map<string, (keys: Set<string>) => void>())
  const regJump = useCallback((k: string, f: ((keys: Set<string>) => void) | null) => {
    if (f === null) varJump.current.delete(k)
    else varJump.current.set(k, f)
  }, [])

  // 行選択。どの側で選んでも同じ — 選んだ行の鍵集合を全部の表へ追わせ、
  // hit を持つ PDF をその頁へ。同じ行を再度選ぶと解除
  const pick = (keys: Set<string>) => {
    const next = keysEqual(selectedKeys, keys) ? null : keys
    setSelectedKeys(next)
    if (next === null) return
    sharedTable.current?.scrollToKeys(next)
    varJump.current.forEach((f) => f(next))
    for (const k of next) {
      const h = sharedHits?.get(k)
      if (h) {
        setPdfNav({ docId: h.docId, page: h.page })
        break
      }
    }
  }

  if (!sharedNode) return null

  const sharedName = sharedNode.kind === "origin" ? "原典" : nodeLabel(sharedNode)
  const sharedHead =
    shared === "in"
      ? sharedNode.kind === "origin"
        ? `原典${sharedRows?.kind === "pdf" ? "（PDF）" : sharedRows?.kind === "table" ? "（CSV）" : ""}`
        : `入力 — ${sharedName}`
      : sharedName
  // 変換の説明 = 出力側ノードの段の責務。共有出力では全組で同じなのでここで1回だけ出す
  // （共有入力では出力ごとに違うので各側の見出しの下に出す）
  const stageLead =
    shared === "out"
      ? report.topology.stages.find((s) => s.id === sharedNode.stage)?.responsibility
      : null
  const nodeLead = sharedNode ? nodeLeadOf(sharedNode) : null

  const sharedSide = (
    <div className="side">
      <div className="sidehead">
        <h3>{sharedHead}</h3>
        {nodeLead && <p className="lead">{plain(nodeLead)}</p>}
        {stageLead && <p className="lead">{plain(stageLead)}</p>}
      </div>
      {sharedRows === null ? (
        <p className="text-xs text-muted-foreground">読み込み中…</p>
      ) : (
        <SideRows
          rows={sharedRows}
          hits={sharedHits}
          linkedKeys={peerKeys}
          selectedKeys={selectedKeys}
          hoverKeys={hoverKeys}
          keyDir="row"
          onSelectRow={pick}
          onHoverRow={setHoverKeys}
          tableRef={sharedTable}
          pdfNav={pdfNav}
          onPdfNavigate={(docId, page) => setPdfNav({ docId, page })}
          year={year}
          docs={colDocsOf(sharedNode, report.columnDocs)}
        />
      )}
      <SideDetail
        node={sharedNode}
        srcIds={sharedNode.kind === "origin" ? pairs.map((p) => p.to) : []}
        dir={dir}
        year={year}
        rows={sharedRows}
        report={report}
        code={code}
      />
    </div>
  )

  const varSide = shared === "in" ? "out" : "in"

  return (
    <div className="io-pair">
      <div className="io">
        {shared === "in" ? sharedSide : null}
        <div className="side">
          {pairs.map((p) => (
            <StarSide
              key={`${p.from}|${p.to}`}
              report={report}
              code={code}
              year={year}
              pair={p}
              side={varSide}
              node={nodeById.get(varSide === "in" ? p.from : p.to) ?? null}
              sharedName={sharedName}
              sharedKeys={sharedKeys}
              keyDir={edgeDir(p.from, p.to)}
              selectedKeys={selectedKeys}
              hoverKeys={hoverKeys}
              onHoverRow={setHoverKeys}
              onPick={pick}
              reportPeers={reportPeers}
              register={regJump}
              onRemovePair={onRemovePair}
            />
          ))}
        </div>
        {shared === "out" ? sharedSide : null}
      </div>
    </div>
  )
}

/**
 * バラつく側1件分（行・PDF・見出し・×）。自分の行選択・PDF 頁はここに閉じ、
 * 自分が持つ鍵集合を共有側のバッジ母数へ供給する。
 */
function StarSide({
  report,
  code,
  year,
  pair,
  side,
  node,
  sharedName,
  sharedKeys,
  keyDir,
  selectedKeys,
  hoverKeys,
  onHoverRow,
  onPick,
  reportPeers,
  register,
  onRemovePair,
}: {
  report: ReportData
  code: string
  year: number
  pair: Pair
  /** この側が入力か出力か */
  side: "in" | "out"
  node: Node | null
  sharedName: string
  sharedKeys: Set<string> | null
  /** この側の辺の向き（鍵の向き修飾に使う） */
  keyDir: Direction | null
  selectedKeys: Set<string> | null
  hoverKeys: Set<string> | null
  onHoverRow: (keys: Set<string> | null) => void
  onPick: (keys: Set<string>) => void
  reportPeers: (k: string, s: Set<string> | null) => void
  register: (k: string, f: ((keys: Set<string>) => void) | null) => void
  onRemovePair: (p: Pair) => void
}) {
  const dir = edgeDir(pair.from, pair.to)
  const nodeId =
    side === "in"
      ? node?.kind === "origin"
        ? `${pair.to}.origin`
        : pair.from
      : pair.to
  const rows = useRows(nodeId, code, year, dir)
  const hits = useHitMap(rows, nodeId, dir)
  const tableRef = useRef<RowTableHandle>(null)
  const [pdfNav, setPdfNav] = useState<{ docId: string | null; page: number | null }>({
    docId: null,
    page: null,
  })
  useEffect(() => {
    setPdfNav({ docId: null, page: null })
  }, [year])
  const pairKey = `${pair.from}|${pair.to}`

  // 対応の判定は鍵集合の交差でするので空間の一致は要らない。行は複数の鍵空間
  // （source_row・ordinal・budget_line_id・rule_id・科目コード…）を同時に持ちうる。
  // hit の鍵は取り込み側と同じ `sr` 空間で `<空間>|<年度>|<向き>|<鍵>` に修飾してある
  const myKeys = useMemo<Set<string> | null>(() => {
    if (hits) return new Set(hits.keys())
    if (rows?.kind === "table") return linkSetOf(rows, dir ?? undefined)
    return null
  }, [hits, rows, dir])

  // 共有側の「対応あり」母数に自分の鍵集合を供給（外れたら引く）
  useEffect(() => {
    reportPeers(pairKey, myKeys)
    return () => reportPeers(pairKey, null)
  }, [pairKey, myKeys, reportPeers])

  // 別の側で行が選ばれたら、自分の表をその鍵集合へ・hit があれば PDF をその頁へ追わせる
  const jump = useCallback(
    (keys: Set<string>) => {
      tableRef.current?.scrollToKeys(keys)
      for (const k of keys) {
        const h = hits?.get(k)
        if (h) {
          setPdfNav({ docId: h.docId, page: h.page })
          break
        }
      }
    },
    [hits],
  )
  useEffect(() => {
    register(pairKey, jump)
    return () => register(pairKey, null)
  }, [pairKey, jump, register])

  if (!node) return null
  const name = node.kind === "origin" ? "原典" : nodeLabel(node)
  // この区間でしている変換 = 出力側ノードの段の責務（topology.stages が正本）
  const stageLead =
    side === "out"
      ? report.topology.stages.find((s) => s.id === node.stage)?.responsibility
      : null
  const nodeLead = nodeLeadOf(node)
  const dirShown = dir && (name.includes(DIR_JA[dir]) || sharedName.includes(DIR_JA[dir]))
  const meta = [dir && !dirShown && DIR_JA[dir], `${year}年度`].filter(Boolean).join(" ／ ")

  return (
    <div className="io-node">
      <div className="sidehead">
        <h3>
          {side === "in" ? `${name} →` : `→ ${name}`}
          {meta && <span className="text-muted-foreground">{meta}</span>}
          <button
            className="pair-x"
            onClick={() => onRemovePair(pair)}
            title="この組を外す"
            aria-label="この組を外す"
          >
            ✕
          </button>
        </h3>
        {nodeLead && <p className="lead">{plain(nodeLead)}</p>}
        {stageLead && <p className="lead">{plain(stageLead)}</p>}
      </div>
      {rows === null ? (
        <p className="text-xs text-muted-foreground">読み込み中…</p>
      ) : (
        <SideRows
          rows={rows}
          hits={hits}
          linkedKeys={sharedKeys}
          selectedKeys={selectedKeys}
          hoverKeys={hoverKeys}
          keyDir={keyDir ?? undefined}
          onSelectRow={onPick}
          onHoverRow={onHoverRow}
          tableRef={tableRef}
          pdfNav={pdfNav}
          onPdfNavigate={(docId, page) => setPdfNav({ docId, page })}
          year={year}
          docs={colDocsOf(node, report.columnDocs)}
        />
      )}
      <SideDetail
        node={node}
        srcIds={node.kind === "origin" ? [pair.to] : []}
        dir={dir}
        year={year}
        rows={rows}
        report={report}
        code={code}
      />
    </div>
  )
}

/**
 * 未選択時の一覧。系統の入口（原典）と出口（配布物）を左右に全部並べる。
 *
 * 行選択はここでも効く: 原典の行・PDF hit と配布物の行は同じ source_row を運ぶので、
 * 入口→出口まで通しの対応を直接見せる。歳出・歳入は別の行番号体系なので、
 * ここでは全ての鍵を `<年度>|<向き>|<鍵>` に修飾して混同を防ぐ。
 */
function Overview({
  report,
  code,
  year,
  pdfDocId,
  pdfPage,
  onPdfNavigate,
}: {
  report: ReportData
  code: string
  year: number
  pdfDocId: string | null
  pdfPage: number | null
  onPdfNavigate: (docId: string, page: number) => void
}) {
  // 入口 = 原典ノード、出口 = 出ていく辺を持たない配布物ノード。共有リソースや
  // 途中のモデルはここでは出さない（区間の中身は辺選択の役割）
  const { origins, sinks } = useMemo(() => {
    const hasOut = new Set(report.topology.edges.map((e) => e.from))
    const nodes = report.topology.nodes.filter((n) => n.jurisdictionCode === code)
    return {
      origins: nodes.filter((n) => n.kind === "origin"),
      sinks: nodes.filter((n) => n.stage === "package" && !hasOut.has(n.id)),
    }
  }, [report.topology, code])
  // 原典 → 取り込み表の辺から、まとめられた原典でも裏の source を全部拾う
  const memberSrcIds = (n: Node) =>
    report.topology.edges.filter((e) => e.from === n.id).map((e) => e.to)

  // 行選択は overview 全体で共有。年度が変わると行の実体も文書も変わるので捨てる
  const [selectedKeys, setSelectedKeys] = useState<Set<string> | null>(null)
  const [hoverKeys, setHoverKeys] = useState<Set<string> | null>(null)
  useEffect(() => setSelectedKeys(null), [year])

  /**
   * 各ノードが自分の鍵を報告する。
   * - 原典: `{ byDir }`（向きごとの鍵集合）+ `{ hits }`（PDF hit の位置表 — 配布物の行を
   *   選んだとき PDF をその頁へ飛ばすために使う）
   * - 配布物: `{ keys }`（自分の鍵集合。原典側の「対応あり」バッジ・フラッグの母数）
   */
  const originInfo = useRef(new Map<string, { byDir: Map<string, Set<string>>; hits: Map<string, PdfHitLoc> | null }>())
  const peerSets = useRef(new Map<string, Set<string>>())
  const [originKeysByDir, setOriginKeysByDir] = useState<Map<string, Set<string>>>(new Map())
  const [sinkKeys, setSinkKeys] = useState<Set<string> | null>(null)
  const reportKeys = useCallback(
    (
      id: string,
      v: { byDir?: Map<string, Set<string>>; hits?: Map<string, PdfHitLoc> | null; keys?: Set<string> } | null,
    ) => {
      if (v?.byDir) originInfo.current.set(id, { byDir: v.byDir, hits: v.hits ?? null })
      else originInfo.current.delete(id)
      if (v?.keys) peerSets.current.set(id, v.keys)
      else peerSets.current.delete(id)
      const u = new Map<string, Set<string>>()
      originInfo.current.forEach(({ byDir }) =>
        byDir.forEach((s, d) => {
          let acc = u.get(d)
          if (!acc) u.set(d, (acc = new Set()))
          s.forEach((k) => acc.add(k))
        }),
      )
      setOriginKeysByDir(u)
      let sink: Set<string> | null = null
      peerSets.current.forEach((s) => s.forEach((k) => (sink ??= new Set()).add(k)))
      setSinkKeys(sink)
    },
    [],
  )

  // 行選択で各表を追わせるため、表を持つノードが jump 関数を登録する
  const jumps = useRef(new Map<string, (keys: Set<string>) => void>())
  const regJump = useCallback((id: string, f: ((keys: Set<string>) => void) | null) => {
    if (f === null) jumps.current.delete(id)
    else jumps.current.set(id, f)
  }, [])

  const pick = (keys: Set<string>) => {
    const next = keysEqual(selectedKeys, keys) ? null : keys
    setSelectedKeys(next)
    if (next === null) return
    jumps.current.forEach((f) => f(next))
    for (const { hits } of originInfo.current.values()) {
      for (const k of next) {
        const h = hits?.get(k)
        if (h) {
          onPdfNavigate(h.docId, h.page)
          return
        }
      }
    }
  }

  return (
    <>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
        <h2 style={{ fontSize: 14, margin: 0 }}>
          原典 <span className="text-muted-foreground">→</span> 配布物
        </h2>
      </div>
      <div className="io">
        <div className="side">
          {origins.map((n) => (
            <OverviewNode
              key={n.id}
              node={n}
              srcIds={memberSrcIds(n)}
              code={code}
              year={year}
              report={report}
              reportKeys={reportKeys}
              linkedKeys={sinkKeys}
              keyDir="row"
              selectedKeys={selectedKeys}
              hoverKeys={hoverKeys}
              onSelectRow={pick}
              onHoverRow={setHoverKeys}
              register={regJump}
              pdfDocId={pdfDocId}
              pdfPage={pdfPage}
              onPdfNavigate={onPdfNavigate}
            />
          ))}
        </div>
        <div className="side">
          {sinks.map((n) => {
            const dir = edgeDir(n.id, "")
            return (
              <OverviewNode
                key={n.id}
                node={n}
                srcIds={[]}
                code={code}
                year={year}
                report={report}
                reportKeys={reportKeys}
                linkedKeys={originKeysByDir.get(dir ?? "") ?? null}
                keyDir={dir}
                selectedKeys={selectedKeys}
                hoverKeys={hoverKeys}
                onSelectRow={pick}
                onHoverRow={setHoverKeys}
                register={regJump}
              />
            )
          })}
        </div>
      </div>
    </>
  )
}

/** overview の1ノード分。原典なら PDF/CSV、配布物なら配布物の表を出す */
function OverviewNode({
  node,
  srcIds,
  code,
  year,
  report,
  reportKeys,
  linkedKeys,
  keyDir,
  selectedKeys,
  hoverKeys,
  onSelectRow,
  onHoverRow,
  register,
  pdfDocId = null,
  pdfPage = null,
  onPdfNavigate = () => {},
}: {
  node: Node
  srcIds: string[]
  code: string
  year: number
  report: ReportData
  /** 鍵の報告先（原典は `{byDir, hits}`、配布物は `{keys}` を渡す） */
  reportKeys: (id: string, v: { byDir?: Map<string, Set<string>>; hits?: Map<string, PdfHitLoc> | null; keys?: Set<string> } | null) => void
  /** 「対応あり」の母数（原典: 配布物の鍵和集合 / 配布物: 自分の向きの原典鍵） */
  linkedKeys: Set<string> | null
  /** 表の鍵に載せる向き修飾（原典は 'row' = 行の direction 列、配布物は自分の向き） */
  keyDir: Direction | "row" | null
  selectedKeys: Set<string> | null
  hoverKeys: Set<string> | null
  onSelectRow: (keys: Set<string>) => void
  onHoverRow: (keys: Set<string> | null) => void
  register: (id: string, f: ((keys: Set<string>) => void) | null) => void
  pdfDocId?: string | null
  pdfPage?: number | null
  onPdfNavigate?: (docId: string, page: number) => void
}) {
  const isOrigin = node.kind === "origin"
  // 配布物ノードの向きは id から（expenditure / revenue のどちらか、または向きなし）
  const dir = isOrigin ? null : edgeDir(node.id, "")
  const rows = useRows(node.id, code, year, null)
  const tableRef = useRef<RowTableHandle>(null)
  const srcKey = srcIds.join("|")

  // PDF 原典はぶら下がる全 source の hit を向き修飾で併合する
  // （歳出・歳入が同じ文書に綴じられている原典は1ノードで両方向を持つ）
  const [hits, setHits] = useState<Map<string, PdfHitLoc> | null>(null)
  useEffect(() => {
    if (!isOrigin) {
      // 配布物: 自分の鍵集合を原典側のフラッグ母数へ供給
      reportKeys(node.id, rows?.kind === "table" ? { keys: linkSetOf(rows, dir ?? undefined) } : null)
      return () => reportKeys(node.id, null)
    }
    let stale = false
    if (rows?.kind === "pdf") {
      const specs = srcIds.map((s) => ({ s, d: edgeDir("", s) }))
      Promise.all(specs.map(({ s, d }) => loadHitMap(rows.docs, s, d ?? undefined))).then((ms) => {
        if (stale) return
        const merged = new Map<string, PdfHitLoc>()
        const byDir = new Map<string, Set<string>>()
        specs.forEach(({ d }, i) => {
          ms[i]!.forEach((v, k) => merged.set(k, v))
          byDir.set(d ?? "", new Set(ms[i]!.keys()))
        })
        setHits(merged)
        reportKeys(node.id, { byDir, hits: merged })
      })
    } else if (rows?.kind === "table") {
      setHits(null)
      reportKeys(node.id, { byDir: linkSetsByDir(rows), hits: null })
    } else {
      setHits(null)
      reportKeys(node.id, null)
    }
    return () => {
      stale = true
      reportKeys(node.id, null)
    }
  }, [isOrigin, rows, srcKey, dir, node.id, reportKeys]) // eslint-disable-line react-hooks/exhaustive-deps -- srcIds は render ごとに新しい配列なので srcKey で追う

  // 別の側で行が選ばれたら自分の表をその鍵集合へ追わせる
  useEffect(() => {
    register(node.id, (keys: Set<string>) => tableRef.current?.scrollToKeys(keys))
    return () => register(node.id, null)
  }, [node.id, register])

  const head =
    isOrigin
      ? `原典${rows?.kind === "pdf" ? "（PDF）" : rows?.kind === "table" ? "（CSV）" : ""} — ${node.label}`
      : nodeLabel(node)
  const nodeLead = nodeLeadOf(node)
  return (
    <div className="io-node">
      <div className="sidehead">
        <h3>{head}</h3>
        {nodeLead && <p className="lead">{plain(nodeLead)}</p>}
      </div>
      {rows === null ? (
        <p className="text-xs text-muted-foreground">読み込み中…</p>
      ) : rows.kind === "pdf" ? (
        <PdfSide
          docs={rows.docs}
          hits={hits}
          year={year}
          docId={pdfDocId}
          page={pdfPage}
          onNavigate={onPdfNavigate}
          flagKeys={linkedKeys}
          selectedKeys={selectedKeys}
          hoverKeys={hoverKeys}
          onSelectRow={onSelectRow}
          onHoverRow={onHoverRow}
        />
      ) : rows.kind === "table" ? (
        <RowTable
          ref={tableRef}
          table={rows}
          linkedKeys={linkedKeys}
          selectedKeys={selectedKeys}
          hoverKeys={hoverKeys}
          keyDir={keyDir ?? undefined}
          docs={colDocsOf(node, report.columnDocs)}
          onSelectRow={onSelectRow}
          onHoverRow={onHoverRow}
        />
      ) : (
        <p className="text-xs text-muted-foreground">行データなし（{rows.reason}）</p>
      )}
      <SideDetail node={node} srcIds={srcIds} dir={null} year={year} rows={rows} report={report} code={code} />
    </div>
  )
}
