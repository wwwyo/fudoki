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
import { spawn } from "node:child_process"
import fs from "node:fs"
import path from "node:path"
import type { Connect, Plugin } from "vite"
import { provenanceForSource } from "@fudoki/report/common"

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

  // spawnSync で同期取りすると1クエリの間 dev server 全体が止まる（HMR・他リクエストも）ので、
  // 子プロセスは async にする。出力上限は従来と同じ — 超えたぶんは読み捨てて close で失敗にする
  const MAX_OUT = 512 * 1024 * 1024
  const duckdb = (sql: string, cwd = repo): Promise<Record<string, unknown>[]> =>
    new Promise((resolve, reject) => {
      const p = spawn("duckdb", ["-json", warehouse, "-c", sql], { cwd })
      const chunks: Buffer[] = []
      const err: Buffer[] = []
      let size = 0
      p.stdout.on("data", (c: Buffer) => {
        size += c.length
        if (size <= MAX_OUT) chunks.push(c)
      })
      p.stderr.on("data", (c: Buffer) => err.push(c))
      p.on("error", reject)
      p.on("close", (status) => {
        if (status !== 0) {
          return reject(new Error(`duckdb: ${Buffer.concat(err).toString().slice(0, 400)}`))
        }
        if (size > MAX_OUT) {
          return reject(new Error(`duckdb: 出力が ${MAX_OUT / (1 << 20)}MB を超えた`))
        }
        const out = Buffer.concat(chunks).toString().trim()
        resolve(out ? JSON.parse(out) : [])
      })
    })

  // 証跡 JSON の parse を mtime で使い回す。リクエストごとの全件 parse を避けるが、
  // ディレクトリ列挙自体は毎回やる（取り込み直しでファイルが増減しても追い付く）
  const provCache = new Map<string, { mtimeMs: number; json: any }>()
  const provenanceOf = (dir: string): any[] => {
    if (!fs.existsSync(dir)) return []
    return fs.readdirSync(dir, { recursive: true })
      .filter((f): f is string => typeof f === "string" && f.endsWith("provenance.json"))
      .sort()
      .map((f) => {
        const fp = path.join(dir, f)
        const mtimeMs = fs.statSync(fp).mtimeMs
        const c = provCache.get(fp)
        if (c && c.mtimeMs === mtimeMs) return c.json
        const json = JSON.parse(fs.readFileSync(fp, "utf8"))
        provCache.set(fp, { mtimeMs, json })
        return json
      })
  }

  /**
   * source ノード id に対応する証跡。規則の正本は `@fudoki/report/common` の
   * `provenanceForSource`（報告生成と同じもの — direction だけで引くと別団体や
   * 抽出物の証跡が混ざるので、団体・canonical・抽出種類の区別が要る）。
   */
  const provsForSource = (srcId: string): any[] => {
    const name = srcId.split(".").at(-1)!
    return provenanceForSource(srcId, name, provenanceOf(rawDir))?.ps ?? []
  }

  /** PDF 閲覧レイヤの索引。`bun run pdf:layer` が作る（無ければ null）。mtime で使い回す */
  let pdfIndexCache: { mtime: number; docs: Record<string, any> } | null = null
  const pdfIndex = (): Record<string, any> | null => {
    try {
      const f = path.join(pdfDir, "index.json")
      const mtime = fs.statSync(f).mtimeMs
      if (pdfIndexCache?.mtime !== mtime) {
        pdfIndexCache = { mtime, docs: JSON.parse(fs.readFileSync(f, "utf8")).docs ?? {} }
      }
      return pdfIndexCache!.docs
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
  const resolveRows = async (nodeId: string, year: number | null, dir: string | null, code: string | null) => {
    if (nodeId.endsWith(".origin")) {
      const srcId = nodeId.slice(0, -".origin".length)
      const provs = provsForSource(srcId)
      if (provs.some((p) => p.extractor || p.raw_form === "extracted")) {
        return { kind: "pdf", docs: pdfDocsFor(srcId), provs }
      }
      // 正本の CSV。原典ノードの中身は取り込み Parquet（= 原典の復元と一致が検査済み）
      return { ...(await serveTable(parquetFor(srcId), year, dir, code)), provs }
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
    /** 上限で打ち切ったか。検証ツールが「見えていない行がある」を黙らせないため返す */
    truncated: boolean
  }
  // 行数の上限。越えたらそのことを返す — 上限の中に収めるより「見えていない」と言うほうが重要
  const ROW_LIMIT = 200000
  const serveTable = async (rel: string, year: number | null, dir: string | null, code: string | null): Promise<TableReply> => {
    const cols = (await duckdb(`describe select * from ${rel}`)).map((r) => String(r.column_name))
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
    // 上限+1を取って打ち切りを判定する（count(*) をもう1本立てない）
    const rows = await duckdb(
      `select * from ${rel}${where.length ? ` where ${where.join(" and ")}` : ""}` +
      `${order.length ? ` order by ${order.map((c) => `"${c}"`).join(", ")}` : ""} limit ${ROW_LIMIT + 1}`)
    const truncated = rows.length > ROW_LIMIT
    if (truncated) rows.pop()
    return {
      kind: "table", columns: cols,
      rows: rows.map((r) => cols.map((c) => r[c])),
      keyColumn, totalRows: rows.length, truncated,
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
        // 行を出せない（表が無い・PDF 原典だがレイヤ未生成等）は失敗ではなく「無い」の情報
        resolveRows(node, year, dir, code)
          .then((r) => send(res, 200, r))
          .catch((e) => send(res, 200, { kind: "none", reason: String(e).slice(0, 300) }))
        return
      }
      if (url.pathname === "/local/pdf/index.json" || url.pathname === "/local/pdf-index") {
        try {
          return send(res, 200, fs.readFileSync(path.join(pdfDir, "index.json")))
        } catch {
          return send(res, 404, { error: "no pdf layer" })
        }
      }
      const pdfFile = /^\/local\/pdf\/([\w-]+)\/(meta\.json|hits\.json|p(\d+)\.(?:json|png))$/.exec(url.pathname)
      if (pdfFile) {
        const f = path.join(pdfDir, pdfFile[1]!, pdfFile[2]!)
        try {
          return send(res, 200, fs.readFileSync(f),
            f.endsWith(".png") ? "image/png" : "application/json")
        } catch {
          return send(res, 404, { error: "not found" })
        }
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
