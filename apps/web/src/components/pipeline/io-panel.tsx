/**
 * 組（入力→出力）の検査パネル。系統図で辺を選んだ下側ペインに出る。
 *
 * - 両側の行を `/local/rows` から読んで並べ、対応キーのある行にバッジを付ける
 * - 片側で行を押すと反対側の同じ鍵の行が点灯する（行対応は同じ鍵空間のときだけ）
 * - 入力側が PDF 原典なら頁画像ビューアを出し、行選択で該当頁へ飛ぶ
 * - 各側の詳細トグルに 出所（証跡）・取り込みの検証・検査・金額の単位 を畳む
 */
import { useEffect, useMemo, useRef, useState } from "react"
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
import { extractedKindOf, isCanonicalFetch } from "@/lib/pipeline"
import {
  DIR_JA,
  bareKey,
  edgeDir,
  keySpaceOf,
  linkSetOf,
  loadHitMap,
  loadRows,
  nodeLabel,
  type NodeRows,
  type PdfHitLoc,
  type PdfRows,
  type TableRows,
} from "@/lib/verify"
import { PdfSide } from "./pdf-side"
import { RowTable, type RowTableHandle } from "./row-table"

export type Pair = { from: string; to: string }

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
  dir,
  year,
  rows,
  report,
  code,
}: {
  node: Node
  dir: Direction | null
  year: number | null
  rows: NodeRows | null
  report: ReportData
  code: string
}) {
  // dbt の検査は source ノード（取り込み表）に bind する。原典ノードはその代理として
  // 図に出るので、証跡だけでなく `source.*` に bind した検査もここへ寄せる
  const checks = report.checks.filter(
    (c) => c.binds.includes(node.id) || (node.kind === "origin" && c.binds.includes(srcIdOf(node.id))),
  )
  const bad = checks.filter((c) => c.status !== "pass" && c.status !== "warn").length
  const warn = checks.filter((c) => c.status === "warn").length
  const ckBad = [bad && `失敗${bad}`, warn && `警告${warn}`].filter(Boolean).join("・")

  // 原典ノードの証跡は /local/rows の応答が持ってくる（団体コードから絞り込み済み）
  const provs: Provenance[] =
    node.kind === "origin" && rows && (rows.kind === "pdf" || rows.kind === "table")
      ? ((rows as PdfRows | TableRows).provs ?? [])
      : []
  const provsShown = year == null ? provs : provs.filter((p) => p.fiscal_year === year)
  const prov = provsShown[0] ?? provs[0] ?? null

  // 金額の単位の宣言（向きが決まる組だけ。年度が効く団体は年度で絞る）
  const amounts = dir ? (report.amounts[dir] ?? []) : []
  const amountsShown = year == null ? amounts : amounts.filter((a) => a.years === null || a.years.includes(year))

  if (!prov && !checks.length && !amountsShown.length) return null

  const summary = prov
    ? `詳細${checks.length ? `（検査${ckBad ? ` ${ckBad}` : ` ${checks.length}件`}）` : ""}`
    : ckBad
      ? `検査 ${checks.length}件（${ckBad}）`
      : `検査 ${checks.length}件：すべて成功`

  return (
    <details className="fold">
      <summary>{summary}</summary>
      {prov && (
        <>
          {(prov.document_title || prov.dataset_title || prov.resource_name) && (
            <div className="drow">
              <span className="dk">資料名</span>
              <span>
                {prov.document_title || prov.dataset_title || prov.resource_name}
                {year == null && provs.length > 1 ? ` ほか全 ${provs.length} 年度分` : ""}
              </span>
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
          {year == null && provs.length > 1 ? (
            provs.map((i) => (
              <div className="drow" key={`${i.fiscal_year}-${i.request_url}`}>
                <span className="dk">{i.fiscal_year}年度</span>
                <span>
                  <a href={i.request_url} target="_blank" rel="noreferrer">
                    {i.request_url}
                  </a>
                </span>
              </div>
            ))
          ) : (
            <div className="drow">
              <span className="dk">取得元</span>
              <span>
                <a href={prov.request_url} target="_blank" rel="noreferrer">
                  {prov.request_url}
                </a>
              </span>
            </div>
          )}
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
                  `・宣言: ${a.source === "source_amount_unit" ? "証跡" : "誤読の罠"}`}
              </span>
            </div>
          ))}
        </>
      )}
      <CheckList checks={checks} code={code} />
    </details>
  )
}

/** `.origin` ノードから、ぶら下がっている source ノードの id を引く */
function srcIdOf(originId: string): string {
  return originId.endsWith(".origin") ? originId.slice(0, -".origin".length) : originId
}

export function IoPanel({
  report,
  code,
  pair,
  year,
  selectedKey,
  onSelectRow,
  hoverKey,
  onHoverRow,
  pdfDocId,
  pdfPage,
  onPdfNavigate,
}: {
  report: ReportData
  code: string
  pair: Pair | null
  year: number | null
  selectedKey: string | null
  onSelectRow: (key: string | null) => void
  hoverKey: string | null
  onHoverRow: (key: string | null) => void
  /** PDF 側が見ている文書・頁（行選択時の遷移で親が更新） */
  pdfDocId: string | null
  pdfPage: number | null
  onPdfNavigate: (docId: string, page: number) => void
}) {
  const nodeById = useMemo(
    () => new Map(report.topology.nodes.map((n) => [n.id, n])),
    [report.topology.nodes],
  )
  const a = pair ? nodeById.get(pair.from) : null
  const b = pair ? nodeById.get(pair.to) : null
  const dir = pair ? edgeDir(pair.from, pair.to) : null

  const inRows = useRows(pair?.from ?? null, code, year, dir)
  const outRows = useRows(pair?.to ?? null, code, year, dir)
  const inHits = useHitMap(inRows, pair?.from ?? null)
  const outHits = useHitMap(outRows, pair?.to ?? null)

  const inTable = useRef<RowTableHandle>(null)
  const outTable = useRef<RowTableHandle>(null)

  /**
   * 対応バッジの母数 = それぞれの側に実在する行キーの集合。
   * 表↔表は鍵空間（source_row 系 / ordinal 系）が同じときだけ対応を付ける。
   * PDF 側は hit の鍵集合 — hit の鍵は取り込み側と同じ鍵列（source_row / ordinal）で
   * `<年度>|<鍵>` に修飾してあるので、そのまま表の修飾キーと比べられる。
   */
  const sameSpace =
    inRows?.kind === "table" && outRows?.kind === "table"
      ? keySpaceOf(inRows) === keySpaceOf(outRows)
      : true
  const keysIn = useMemo<Set<string> | null>(() => {
    if (inHits) return new Set(inHits.keys())
    if (inRows?.kind === "table") return sameSpace ? linkSetOf(inRows) : null
    return null
  }, [inHits, inRows, sameSpace])
  const keysOut = useMemo<Set<string> | null>(() => {
    if (outHits) return new Set(outHits.keys())
    if (outRows?.kind === "table") return sameSpace ? linkSetOf(outRows) : null
    return null
  }, [outHits, outRows, sameSpace])

  // 行選択。PDF が片側に居る組では、行が属する年度の文書の hit 頁へ飛ぶ
  const pick = (side: "in" | "out") => (key: string) => {
    if (!pair) return
    const next = selectedKey === key ? null : key
    onSelectRow(next)
    if (next === null) return
    ;(side === "in" ? outTable : inTable).current?.scrollToKey(next)
    const h = (side === "in" ? outHits : inHits)?.get(next)
    if (h) onPdfNavigate(h.docId, h.page)
  }

  if (!pair || !a || !b) {
    return (
      <p className="text-muted-foreground" style={{ padding: "8px 0" }}>
        図の線、またはノードを選んで組を指定すると、ここに入力と出力の行が並びます。
      </p>
    )
  }

  const inName = a.kind === "origin" ? "原典" : nodeLabel(a)
  const bName = nodeLabel(b)
  const dirShown = dir && (inName.includes(DIR_JA[dir]) || bName.includes(DIR_JA[dir]))
  const meta = [dir && !dirShown && DIR_JA[dir], year != null && `${year}年度`].filter(Boolean).join(" ／ ")
  const inH3 =
    a.kind === "origin"
      ? `原典${inRows?.kind === "pdf" ? "（PDF）" : inRows?.kind === "table" ? "（CSV）" : ""}`
      : `入力 — ${inName}`

  return (
    <>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
        <h2 style={{ fontSize: 14, margin: 0 }}>
          {inName} <span className="text-muted-foreground">→</span> {bName}
        </h2>
        {meta && <span className="text-muted-foreground text-xs">{meta}</span>}
        {selectedKey != null && (
          <button className="linky text-xs" onClick={() => onSelectRow(null)}>
            行 {bareKey(selectedKey)} の選択を解除
          </button>
        )}
      </div>
      <div className="io">
        <div className="side">
          <h3>{inH3}</h3>
          {inRows === null ? (
            <p className="text-xs text-muted-foreground">読み込み中…</p>
          ) : inRows.kind === "pdf" ? (
            <PdfSide
              docs={inRows.docs}
              hits={inHits}
              year={year}
              docId={pdfDocId}
              page={pdfPage}
              onNavigate={onPdfNavigate}
              flagKeys={keysOut}
              selectedKey={selectedKey}
              hoverKey={hoverKey}
              onSelectRow={(k) => pick("in")(k)}
              onHoverRow={onHoverRow}
            />
          ) : inRows.kind === "table" ? (
            <RowTable
              ref={inTable}
              table={inRows}
              linkedKeys={keysOut}
              selectedKey={selectedKey}
              hoverKey={hoverKey}
              onSelectRow={(k) => pick("in")(k)}
              onHoverRow={onHoverRow}
            />
          ) : (
            <p className="text-xs text-muted-foreground">行データなし（{inRows.reason}）</p>
          )}
          <SideDetail node={a} dir={dir} year={year} rows={inRows} report={report} code={code} />
        </div>
        <div className="side">
          <h3>{bName}</h3>
          {outRows === null ? (
            <p className="text-xs text-muted-foreground">読み込み中…</p>
          ) : outRows.kind === "table" ? (
            <RowTable
              ref={outTable}
              table={outRows}
              linkedKeys={keysIn}
              selectedKey={selectedKey}
              hoverKey={hoverKey}
              onSelectRow={(k) => pick("out")(k)}
              onHoverRow={onHoverRow}
            />
          ) : outRows.kind === "pdf" ? (
            // 系統上「出力側が PDF 原典」の組は無いが、防御的に同じビューアを出す
            <PdfSide
              docs={outRows.docs}
              hits={outHits}
              year={year}
              docId={pdfDocId}
              page={pdfPage}
              onNavigate={onPdfNavigate}
              flagKeys={keysIn}
              selectedKey={selectedKey}
              hoverKey={hoverKey}
              onSelectRow={(k) => pick("out")(k)}
              onHoverRow={onHoverRow}
            />
          ) : (
            <p className="text-xs text-muted-foreground">行データなし（{outRows.reason}）</p>
          )}
          <SideDetail node={b} dir={dir} year={year} rows={outRows} report={report} code={code} />
        </div>
      </div>
    </>
  )
}
