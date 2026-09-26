/**
 * 検証画面（`/pipeline/<団体コード>/`）のローカル・データ口。
 *
 * 系統図の組（入力 → 出力）を選んだとき、その両側の**行そのもの**を返す。
 * 読むのは warehouse（`data/fudoki.duckdb`）・raw の Parquet・配布物 CSV・
 * 原典 PDF の閲覧レイヤ（`apps/web/.local/pdf/`）で、すべてローカルの正本への参照。
 *
 * ⚠️ **dev server（と `vite preview`）にだけ載せる。** `configureServer` /
 * `configurePreviewServer` の middleware として動き、ビルド成果物には何も書かない。
 * 原典の頁画像・語の文字層・行と頁の対応は再配布の判断が付いていないものを含むので
 * 公開アセット（`public/`）には置かない（`docs/prd/pipeline-verification-view/prd.md`）。
 */
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import path from "node:path"
import type { Connect, Plugin } from "vite"

export function localData(root: string): Plugin {
  const repo = path.resolve(root, "../..")
  const warehouse = path.join(repo, "data/fudoki.duckdb")
  const manifestPath = path.join(repo, "dbt/target/manifest.json")
  const rawDir = path.join(repo, "data/budget/raw")
  const pdfDir = path.join(root, ".local/pdf")

  // manifest は 5MB あるので mtime で使い回す（dbt を回し直したときだけ読み直す）
  let manifestCache: { mtime: number; manifest: any } | null = null
  const manifest = () => {
    const mtime = fs.statSync(manifestPath).mtimeMs
    if (manifestCache?.mtime !== mtime) {
      manifestCache = { mtime, manifest: JSON.parse(fs.readFileSync(manifestPath, "utf8")) }
    }
    return manifestCache!.manifest
  }

  const duckdb = (sql: string, cwd = repo): Record<string, unknown>[] => {
    const r = spawnSync("duckdb", ["-json", warehouse, "-c", sql], { cwd, maxBuffer: 512 * 1024 * 1024 })
    if (r.status !== 0) throw new Error(`duckdb: ${r.stderr?.toString().slice(0, 400)}`)
    const out = r.stdout.toString().trim()
    return out ? JSON.parse(out) : []
  }

  /** 証跡（取得物の隣にある JSON）を団体で拾う。lineage.ts と同じ集め方 */
  const provenanceOf = (dir: string): any[] =>
    fs.existsSync(dir)
      ? fs.readdirSync(dir, { recursive: true })
          .filter((f): f is string => typeof f === "string" && f.endsWith("provenance.json"))
          .sort()
          .map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")))
      : []

  const isCanonical = (p: any) => typeof p.rows === "number" && Number.isFinite(p.rows) && p.resource_name !== undefined
  const extractedKind = (p: any): string | null => {
    if (!p.extracted) return null
    if (p.extractor?.includes("extract_statement")) return "statement"
    if (p.extractor?.includes("extract_projects")) return "project-names"
    if (p.extractor?.includes("extract_revenue_accounts")) return "revenue-accounts"
    return null
  }

  /**
   * source ノード id に対応する証跡。**`report/lineage.ts` の `provenanceForSource` と
   * 同じ規則** — direction だけで引くと別団体の証跡が混ざるので団体コードから絞る。
   */
  const provsForSource = (srcId: string): any[] => {
    const code = /\.raw_(\d{6})/.exec(srcId)?.[1]
    if (!code) return []
    const name = srcId.split(".").at(-1)!
    const mine = provenanceOf(path.join(rawDir, `jurisdiction=${code}`))
    const canonical = mine.filter((p) => isCanonical(p) && p.direction === name)
    if (canonical.length) return canonical
    const kind = /_project_names\./.test(srcId) ? "project-names"
      : /_revenue_accounts\./.test(srcId) ? "revenue-accounts" : null
    if (!kind) return []
    return provenanceOf(path.join(rawDir, kind, `jurisdiction=${code}`))
      .filter((p) => extractedKind(p) === kind)
  }

  /** PDF 閲覧レイヤの索引。`bun run pdf:layer` が作る（無ければ null） */
  const pdfIndex = (): Record<string, any> | null => {
    const f = path.join(pdfDir, "index.json")
    if (!fs.existsSync(f)) return null
    try {
      return JSON.parse(fs.readFileSync(f, "utf8")).docs ?? {}
    } catch {
      return null
    }
  }
  /** そのソースを含む文書。**1ソースに複数文書がありえる**（狛江市の事業名 PDF は年度ごとに別ファイル） */
  const pdfDocsFor = (srcId: string) => {
    const docs = pdfIndex()
    if (!docs) return []
    return Object.entries(docs)
      .filter(([, d]: [string, any]) => (d.sources ?? []).includes(srcId))
      .map(([id, d]) => ({ id, ...(d as object) }))
      // 年度→文書の逆引きを UI がするので、年度順に揃えておく
      .sort((a: any, b: any) => (a.years?.[0] ?? 0) - (b.years?.[0] ?? 0))
  }

  /**
   * ノード id を「行を返せる表」へ解決する。
   * - model/seed → warehouse の表（pkg_* は external materialized で CSV が正本）
   * - source.* → manifest の `meta.external_location`（read_parquet の glob）
   * - *.origin → 原典。PDF 原典なら {kind:'pdf'}、CSV 原典なら取り込み Parquet
   *   （raw の Parquet は原典 CSV と復元一致が検査済みなので、そのまま原典の姿として出せる）
   */
  const resolveRows = (nodeId: string, year: number | null, dir: string | null, code: string | null) => {
    if (nodeId.endsWith(".origin")) {
      const srcId = nodeId.slice(0, -".origin".length)
      const provs = provsForSource(srcId)
      if (provs.some((p) => p.extractor || p.raw_form === "extracted")) {
        return { kind: "pdf", docs: pdfDocsFor(srcId), provs }
      }
      // 正本の CSV。原典ノードの中身は取り込み Parquet（= 原典の復元と一致が検査済み）
      return { ...serveTable(parquetFor(srcId), year, dir, code), provs }
    }
    const m = manifest()
    if (nodeId.startsWith("source.")) return serveTable(parquetFor(nodeId), year, dir, code)
    const node = m.nodes[nodeId]
    if (!node) return { kind: "none", reason: `unknown node: ${nodeId}` }
    if (node.resource_type === "model" && node.config?.location) {
      // package 段は warehouse の view ではなく配布物 CSV が正本
      // （view の相対パスは dbt 実行時の cwd でしか解けない）
      const csv = path.join(repo, "dbt", node.config.location)
      return serveTable(`read_csv('${csv}', header=true)`, year, dir, code)
    }
    return serveTable(`"${node.name}"`, year, dir, code)
  }

  const parquetFor = (srcId: string): string => {
    const src = manifest().sources[srcId]
    const loc: string | undefined = src?.meta?.external_location
    if (!loc) throw new Error(`${srcId} に external_location が無い`)
    // `read_parquet('../data/...', hive_partitioning=true, union_by_name=true)` の
    // 第1引数（glob）を取り出して絶対パスへ。{name} はソースの表名で埋める
    const glob = loc.match(/'([^']+)'/)?.[1]
    if (!glob) throw new Error(`external_location を読めない: ${loc}`)
    const resolved = path.join(repo, "dbt", glob.replace("{name}", src.name))
    return `read_parquet('${resolved}', hive_partitioning=true, union_by_name=true)`
  }

  type TableReply = {
    kind: "table"; columns: string[]; rows: unknown[][]
    keyColumn: string | null; totalRows: number
  }
  const serveTable = (rel: string, year: number | null, dir: string | null, code: string | null): TableReply => {
    const cols = duckdb(`describe select * from ${rel}`).map((r) => String(r.column_name))
    const where: string[] = []
    if (year !== null && (cols.includes("fiscal_year") || cols.includes("year"))) {
      const c = cols.includes("fiscal_year") ? "fiscal_year" : "year"
      where.push(`cast("${c}" as bigint) = ${year}`)
    }
    if (dir !== null && cols.includes("direction")) where.push(`direction = '${dir}'`)
    // ⚠️ core 系は全団体を1表に持つ。団体コードで切らないと、別の団体の行を見せることになる
    if (code !== null && cols.includes("jurisdiction_code")) where.push(`jurisdiction_code = '${code}'`)
    // source_row → ordinal → pdf_ordinal の順に、行を相互に辿れる鍵を探す
    const keyColumn = ["source_row", "ordinal", "pdf_ordinal"].find((c) => cols.includes(c)) ?? null
    const order = ["fiscal_year", "year", "direction", "source_row", "ordinal", "pdf_ordinal"]
      .filter((c) => cols.includes(c))
    const rows = duckdb(
      `select * from ${rel}${where.length ? ` where ${where.join(" and ")}` : ""}` +
      `${order.length ? ` order by ${order.map((c) => `"${c}"`).join(", ")}` : ""} limit 200000`)
    return {
      kind: "table", columns: cols,
      rows: rows.map((r) => cols.map((c) => r[c])),
      keyColumn, totalRows: rows.length,
    }
  }

  const send = (res: any, status: number, body: unknown, type = "application/json") => {
    res.statusCode = status
    res.setHeader("Content-Type", type)
    res.end(typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body))
  }

  const handler: Connect.NextHandleFunction = (req, res, next) => {
    try {
      const url = new URL(req.url ?? "", "http://localhost")
      if (url.pathname === "/local/rows") {
        const node = url.searchParams.get("node") ?? ""
        if (!/^(model|seed|source)\.fudoki\.[\w.]+$/.test(node)) return send(res, 400, { error: "bad node id" })
        const year = url.searchParams.get("year") ? Number(url.searchParams.get("year")) : null
        const dir = /^(expenditure|revenue)$/.test(url.searchParams.get("dir") ?? "") ? url.searchParams.get("dir") : null
        const code = /^\d{6}$/.test(url.searchParams.get("code") ?? "") ? url.searchParams.get("code") : null
        try {
          return send(res, 200, resolveRows(node, year, dir, code))
        } catch (e) {
          // 行を出せない（表が無い・PDF 原典だがレイヤ未生成等）は失敗ではなく「無い」の情報
          return send(res, 200, { kind: "none", reason: String(e).slice(0, 300) })
        }
      }
      if (url.pathname === "/local/pdf/index.json" || url.pathname === "/local/pdf-index") {
        const f = path.join(pdfDir, "index.json")
        return fs.existsSync(f) ? send(res, 200, fs.readFileSync(f)) : send(res, 404, { error: "no pdf layer" })
      }
      const pdfFile = /^\/local\/pdf\/([\w-]+)\/(meta\.json|hits\.json|p(\d+)\.(?:json|png))$/.exec(url.pathname)
      if (pdfFile) {
        const f = path.join(pdfDir, pdfFile[1]!, pdfFile[2]!)
        if (!fs.existsSync(f)) return send(res, 404, { error: "not found" })
        return send(res, 200, fs.readFileSync(f),
          f.endsWith(".png") ? "image/png" : "application/json")
      }
      next()
    } catch (e) {
      send(res, 500, { error: String(e).slice(0, 500) })
    }
  }

  return {
    name: "fudoki-local-data",
    configureServer: (server) => void server.middlewares.use(handler),
    // `vite preview`（ビルド済みの静的配信）でも同じ口を出す — 検証はローカルの話
    configurePreviewServer: (server) => void server.middlewares.use(handler),
  }
}
