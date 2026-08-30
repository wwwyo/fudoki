import fs from "node:fs"
import path from "node:path"
import type { Plugin } from "vite"

/**
 * `/pipeline/<団体コード>/` と `/analysis/<団体コード>/` を62団体分ずつそろえる vite plugin。
 *
 * 124個の HTML を手で置くことはできないので、`ingestion/shared/jurisdictions.json`
 * （団体の同一性の正本。①②③すべてが同じキーで束ねる）から実行時に生成する。
 * 生成物は commit しない（`.gitignore` 参照）。
 *
 * ⚠️ **プラグインは1つのまま。** 2つに分けると sitemap.xml を書くタイミングが2箇所になり、
 * 後から書いた側が先に書いた側を上書きして片方の URL 群が消える（実際にその形になりかけた）。
 * 62団体 × 2種類をまとめて1回の `config` フックで生成し、sitemap もここで1回だけ書く。
 *
 * ⚠️ **`config` フックで書く。** `buildStart` は Rollup が `rollupOptions.input` を
 * 読んだ後に発火するため、そこで書いても新しいページはバンドル対象に間に合わない。
 * `config` フックは vite dev / vite build のどちらでも最初に呼ばれるので、
 * dev サーバでも生成物が揃った状態でリクエストを受けられる。
 */
export function jurisdictionPages(root: string): Plugin {
  return {
    name: "fudoki-jurisdiction-pages",
    config() {
      const jurisdictions = loadJurisdictions(root)
      const input: Record<string, string> = {}

      for (const kind of ROUTE_KINDS) {
        const dir = path.join(root, kind.segment)
        for (const [code, j] of Object.entries(jurisdictions)) {
          const codeDir = path.join(dir, code)
          fs.mkdirSync(codeDir, { recursive: true })
          const file = path.join(codeDir, "index.html")
          fs.writeFileSync(file, kind.renderHtml(code, j.name))
          input[`${kind.segment}-${code}`] = file
        }
      }

      writeSitemap(root, Object.keys(jurisdictions))

      return { build: { rollupOptions: { input } } }
    },
  }
}

type Jurisdiction = { name: string }

function loadJurisdictions(root: string): Record<string, Jurisdiction> {
  // 正本は ingestion/shared/jurisdictions.json（団体の同一性を1層のファイルに同居させない。AGENTS.md）
  const file = path.resolve(root, "../../ingestion/shared/jurisdictions.json")
  const parsed = JSON.parse(fs.readFileSync(file, "utf-8")) as {
    jurisdictions: Record<string, Jurisdiction>
  }
  return parsed.jurisdictions
}

/** HTML のテキストと属性値に入れる文字。`"` まで含めるのは属性値に埋めるため */
function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string)
}

/**
 * `<script>` の中へ JSON を埋めるためのエスケープ。
 *
 * ⚠️ `JSON.stringify` だけでは足りない。値に `</script>` が入ると HTML パーサが
 * そこでスクリプトを閉じてしまい、JSON として妥当でもページが壊れる。
 * いまの `jurisdictions.json` は日本語の団体名しか持たないが、
 * 生成する側がその前提に寄りかかる理由が無い。
 */
function escapeJsonForScript(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003C")
}

/** 種類ごとに違うのは HTML の中身（タイトル・description・埋め込む global・entry script）だけ */
type RouteKind = {
  /** URL のセグメント。`pipeline` / `analysis` */
  segment: string
  renderHtml: (code: string, name: string) => string
}

const ROUTE_KINDS: RouteKind[] = [
  {
    segment: "pipeline",
    renderHtml: (code, name) => {
      const injected = escapeJsonForScript({ code, name })
      const safeName = escapeHtml(name)
      return page({
        // ⚠️ document.title はここから団体・年度に応じて実行時に書き換わる（src/pages/pipeline.tsx）。
        // ここに書くのは JS 実行前 / SEO 用の既定値
        title: `${safeName}の予算が配布物になるまで | fudoki（風土記）`,
        description: `${safeName}の予算データが原典からどう取得され、何を検査され、どこで fudoki の判断（COFOG への分類）が入って配布物になるかを、年度ごとの収録状況まで含めて追う報告。系統は dbt の manifest から生成する。`,
        canonical: `https://fudoki.dev/pipeline/${code}/`,
        globalName: "__FUDOKI_PIPELINE_JURISDICTION__",
        injected,
        entry: "/src/main-pipeline.tsx",
      })
    },
  },
  {
    segment: "analysis",
    renderHtml: (code, name) => {
      const injected = escapeJsonForScript({ code, name })
      const safeName = escapeHtml(name)
      return page({
        // ⚠️ document.title はここから団体・年度に応じて実行時に書き換わる（src/pages/analysis.tsx）。
        title: `${safeName} の支出分析 | fudoki（風土記）`,
        description: `${safeName} の予算を COFOG（政府支出の機能別分類）の10区分ごとに集計した分析。fudoki の budget API から取得する。`,
        canonical: `https://fudoki.dev/analysis/${code}/`,
        globalName: "__FUDOKI_ANALYSIS_JURISDICTION__",
        injected,
        entry: "/src/main-analysis.tsx",
      })
    },
  },
]

function page(opts: {
  title: string
  description: string
  canonical: string
  globalName: string
  injected: string
  entry: string
}): string {
  return `<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />

    <title>${opts.title}</title>
    <meta name="description" content="${opts.description}" />
    <link rel="canonical" href="${opts.canonical}" />

    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="theme-color" media="(prefers-color-scheme: light)" content="#f4f1e6" />
    <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0b0f14" />
    <script>window.${opts.globalName} = ${opts.injected}</script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="${opts.entry}"></script>
  </body>
</html>
`
}

function writeSitemap(root: string, codes: string[]): void {
  // 手書きだと URL がすぐ古びる（実際にそうなっていた）。62団体 × 2種類をここで同時に生成する
  const urls = [
    "https://fudoki.dev/",
    "https://fudoki.dev/pipeline/",
    ...codes.map((c) => `https://fudoki.dev/pipeline/${c}/`),
    "https://fudoki.dev/analysis/",
    ...codes.map((c) => `https://fudoki.dev/analysis/${c}/`),
    "https://fudoki.dev/terms/",
  ]
  const body = urls.map((u) => `  <url>\n    <loc>${u}</loc>\n  </url>`).join("\n")
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`
  fs.writeFileSync(path.join(root, "public", "sitemap.xml"), xml)
}
