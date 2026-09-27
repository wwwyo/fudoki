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
  bareKey,
  colDocsOf,
  edgeDir,
  keySpaceOf,
  linkSetOf,
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
function useHitMap(rows: NodeRows | null, nodeId: string | null) {
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
    loadHitMap(docs, srcId).then((m) => {
      if (!stale) setMap(m)
    })
    return () => {
      stale = true
    }
  }, [docs, srcId])
  return map
}

const fmt = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString("ja-JP"))

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
            <span title={c.name}>{checkLabel(c)}</span>
            {att && <span className="text-muted-foreground">（{att}）</span>}
            {c.status !== "pass" && c.detail && (
              <div className="text-muted-foreground" style={{ paddingLeft: 44 }}>
                {c.detail}
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
                {c.explanation}
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
                <span>{[d.title, d.description].filter(Boolean).join(" — ")}</span>
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
  const nodeById = useMemo(
    () => new Map(report.topology.nodes.map((n) => [n.id, n])),
    [report.topology.nodes],
  )
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

  // 原典ノードは文書単位にまとまりうる（歳出・歳入が同じ PDF なら1ノード）ので、
  // 「同じ入力表か」の判定は解決済みのノード id（`<source>.origin` の規約）で比較する。
  // まとめられた原典が歳出・歳入両方の辺を持っても、direction ごとの頁範囲・証跡は別物
  const inIdOf = (p: Pair) =>
    nodeById.get(p.from)?.kind === "origin" ? `${p.to}.origin` : p.from
  const sameIn = pairs.every((p) => inIdOf(p) === inIdOf(pairs[0]!))
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
  selectedKey,
  hoverKey,
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
  selectedKey: string | null
  hoverKey: string | null
  onSelectRow: (key: string) => void
  onHoverRow: (key: string | null) => void
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
        selectedKey={selectedKey}
        hoverKey={hoverKey}
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
        selectedKey={selectedKey}
        hoverKey={hoverKey}
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
  const sharedNodeId =
    shared === "in" && sharedNode?.kind === "origin" ? `${pairs[0]!.to}.origin` : sharedId
  const dir = edgeDir(pairs[0]!.from, pairs[0]!.to)

  // 行選択と共有側の PDF 表示位置はパネルに紐づく。年度が変わると行の実体も文書も変わるので捨てる
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const [pdfNav, setPdfNav] = useState<{ docId: string | null; page: number | null }>({
    docId: null,
    page: null,
  })
  useEffect(() => {
    setSelectedKey(null)
    setPdfNav({ docId: null, page: null })
  }, [year])

  const sharedRows = useRows(sharedNodeId, code, year, dir)
  const sharedHits = useHitMap(sharedRows, sharedNodeId)
  const sharedTable = useRef<RowTableHandle>(null)

  /**
   * 対応バッジの母数 = 反対側に実在する行キーの集合。共有側から見ると反対側は
   * 複数あるので和集合を取る（どれか1つの側に載っていれば「対応あり」）。
   * バラつく側から見た母数は共有側の鍵集合（StarSide が受け取って使う）。
   */
  const sharedKeys = useMemo<Set<string> | null>(() => {
    if (sharedHits) return new Set(sharedHits.keys())
    return sharedRows?.kind === "table" ? linkSetOf(sharedRows) : null
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
  const varJump = useRef(new Map<string, (key: string) => void>())
  const regJump = useCallback((k: string, f: ((key: string) => void) | null) => {
    if (f === null) varJump.current.delete(k)
    else varJump.current.set(k, f)
  }, [])

  // 行選択。どの側で選んでも同じ — 残り全部の表をその鍵へ、hit を持つ PDF をその頁へ
  const pick = (key: string) => {
    const next = selectedKey === key ? null : key
    setSelectedKey(next)
    if (next === null) return
    sharedTable.current?.scrollToKey(next)
    varJump.current.forEach((f) => f(next))
    const h = sharedHits?.get(next)
    if (h) setPdfNav({ docId: h.docId, page: h.page })
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
  const lead =
    shared === "out"
      ? report.topology.stages.find((s) => s.id === sharedNode.stage)?.responsibility
      : null

  const sharedSide = (
    <div className="side">
      <h3>
        {sharedHead}
        {selectedKey != null && (
          <button className="linky text-xs" onClick={() => setSelectedKey(null)}>
            行 {bareKey(selectedKey)} の選択を解除
          </button>
        )}
      </h3>
      {lead && (
        <p className="text-muted-foreground" style={{ fontSize: 12, margin: "-2px 0 8px" }}>
          {lead}
        </p>
      )}
      {sharedRows === null ? (
        <p className="text-xs text-muted-foreground">読み込み中…</p>
      ) : (
        <SideRows
          rows={sharedRows}
          hits={sharedHits}
          linkedKeys={peerKeys}
          selectedKey={selectedKey}
          hoverKey={hoverKey}
          onSelectRow={pick}
          onHoverRow={setHoverKey}
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

  const sharedSpace = sharedRows?.kind === "table" ? keySpaceOf(sharedRows) : null
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
              sharedSpace={sharedSpace}
              sharedKeys={sharedKeys}
              sharedKind={sharedRows?.kind ?? null}
              selectedKey={selectedKey}
              hoverKey={hoverKey}
              onHoverRow={setHoverKey}
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
  sharedSpace,
  sharedKeys,
  sharedKind,
  selectedKey,
  hoverKey,
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
  sharedSpace: ReturnType<typeof keySpaceOf>
  sharedKeys: Set<string> | null
  sharedKind: NodeRows["kind"] | null
  selectedKey: string | null
  hoverKey: string | null
  onHoverRow: (key: string | null) => void
  onPick: (key: string) => void
  reportPeers: (k: string, s: Set<string> | null) => void
  register: (k: string, f: ((key: string) => void) | null) => void
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
  const hits = useHitMap(rows, nodeId)
  const tableRef = useRef<RowTableHandle>(null)
  const [pdfNav, setPdfNav] = useState<{ docId: string | null; page: number | null }>({
    docId: null,
    page: null,
  })
  useEffect(() => {
    setPdfNav({ docId: null, page: null })
  }, [year])
  const pairKey = `${pair.from}|${pair.to}`

  // 表↔表は鍵空間（source_row 系 / ordinal 系）が同じときだけ対応を付ける。
  // hit の鍵は取り込み側と同じ鍵列で `<年度>|<鍵>` に修飾してあるので PDF 側はそのまま比べられる
  const sameSpace =
    rows?.kind === "table" && sharedKind === "table" ? keySpaceOf(rows) === sharedSpace : true
  const myKeys = useMemo<Set<string> | null>(() => {
    if (hits) return new Set(hits.keys())
    if (rows?.kind === "table") return sameSpace ? linkSetOf(rows) : null
    return null
  }, [hits, rows, sameSpace])

  // 共有側の「対応あり」母数に自分の鍵集合を供給（外れたら引く）
  useEffect(() => {
    reportPeers(pairKey, myKeys)
    return () => reportPeers(pairKey, null)
  }, [pairKey, myKeys, reportPeers])

  // 別の側で行が選ばれたら、自分の表をその鍵へ・hit があれば PDF をその頁へ追わせる
  const jump = useCallback(
    (key: string) => {
      tableRef.current?.scrollToKey(key)
      const h = hits?.get(key)
      if (h) setPdfNav({ docId: h.docId, page: h.page })
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
  const lead =
    side === "out"
      ? report.topology.stages.find((s) => s.id === node.stage)?.responsibility
      : null
  const dirShown = dir && (name.includes(DIR_JA[dir]) || sharedName.includes(DIR_JA[dir]))
  const meta = [dir && !dirShown && DIR_JA[dir], `${year}年度`].filter(Boolean).join(" ／ ")

  return (
    <div className="io-node">
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
      {lead && (
        <p className="text-muted-foreground" style={{ fontSize: 12, margin: "-2px 0 8px" }}>
          {lead}
        </p>
      )}
      {rows === null ? (
        <p className="text-xs text-muted-foreground">読み込み中…</p>
      ) : (
        <SideRows
          rows={rows}
          hits={hits}
          linkedKeys={sharedKeys}
          selectedKey={selectedKey}
          hoverKey={hoverKey}
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
 * 行対応は区間（辺）の話なのでここでは付けない — 辺を選ぶと両側の対応が見られる。
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

  return (
    <>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
        <h2 style={{ fontSize: 14, margin: 0 }}>
          原典 <span className="text-muted-foreground">→</span> 配布物
        </h2>
        <span className="text-muted-foreground text-xs">
          図の辺・ノードを選ぶと、その区間の行対応を出します
        </span>
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
              pdfDocId={pdfDocId}
              pdfPage={pdfPage}
              onPdfNavigate={onPdfNavigate}
            />
          ))}
        </div>
        <div className="side">
          {sinks.map((n) => (
            <OverviewNode key={n.id} node={n} srcIds={[]} code={code} year={year} report={report} />
          ))}
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
  pdfDocId = null,
  pdfPage = null,
  onPdfNavigate = () => {},
}: {
  node: Node
  srcIds: string[]
  code: string
  year: number
  report: ReportData
  pdfDocId?: string | null
  pdfPage?: number | null
  onPdfNavigate?: (docId: string, page: number) => void
}) {
  const rows = useRows(node.id, code, year, null)
  const head =
    node.kind === "origin"
      ? `原典${rows?.kind === "pdf" ? "（PDF）" : rows?.kind === "table" ? "（CSV）" : ""} — ${node.label}`
      : nodeLabel(node)
  return (
    <div className="io-node">
      <h3>{head}</h3>
      {rows === null ? (
        <p className="text-xs text-muted-foreground">読み込み中…</p>
      ) : rows.kind === "pdf" ? (
        <PdfSide
          docs={rows.docs}
          hits={null}
          year={year}
          docId={pdfDocId}
          page={pdfPage}
          onNavigate={onPdfNavigate}
          flagKeys={null}
          selectedKey={null}
          hoverKey={null}
          onSelectRow={() => {}}
          onHoverRow={() => {}}
        />
      ) : rows.kind === "table" ? (
        <RowTable
          table={rows}
          linkedKeys={null}
          selectedKey={null}
          hoverKey={null}
          docs={colDocsOf(node, report.columnDocs)}
          onSelectRow={() => {}}
          onHoverRow={() => {}}
        />
      ) : (
        <p className="text-xs text-muted-foreground">行データなし（{rows.reason}）</p>
      )}
      <SideDetail node={node} srcIds={srcIds} dir={null} year={year} rows={rows} report={report} code={code} />
    </div>
  )
}
