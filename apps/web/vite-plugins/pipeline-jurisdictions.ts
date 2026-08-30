import fs from "node:fs"
import path from "node:path"
import type { Plugin } from "vite"

/**
 * `/pipeline/<団体コード>/` を62団体分そろえる vite plugin。
 *
 * 62個の HTML を手で置くことはできないので、`ingestion/shared/jurisdictions.json`
 * （団体の同一性の正本。①②③すべてが同じキーで束ねる）から実行時に生成する。
 * 生成物は commit しない（`.gitignore` 参照）。
 *
 * ⚠️ **`config` フックで書く。** `buildStart` は Rollup が `rollupOptions.input` を
 * 読んだ後に発火するため、そこで書いても新しいページはバンドル対象に間に合わない。
 * `config` フックは vite dev / vite build のどちらでも最初に呼ばれるので、
 * dev サーバでも生成物が揃った状態でリクエストを受けられる。
 */
export function pipelineJurisdictionPages(root: string): Plugin {
  return {
    name: "fudoki-pipeline-jurisdiction-pages",
    config() {
      const jurisdictions = loadJurisdictions(root)
      const pipelineDir = path.join(root, "pipeline")
      const input: Record<string, string> = {}

      for (const [code, j] of Object.entries(jurisdictions)) {
        const dir = path.join(pipelineDir, code)
        fs.mkdirSync(dir, { recursive: true })
        const file = path.join(dir, "index.html")
        fs.writeFileSync(file, renderHtml(code, j.name))
        input[`pipeline-${code}`] = file
      }

      writeSitemap(root, Object.keys(jurisdictions))

      return { build: { rollupOptions: { input } } }
    },
  }
}

type Jurisdiction = { name: string }

function loadJurisdictions(root: string): Record<string, Jurisdiction> {
  // 正本は ingestion/shared/jurisdictions.json（team 単体のファイルに同居させない。AGENTS.md）
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

function renderHtml(code: string, name: string): string {
  // 団体名・コードは window 経由で main-pipeline.tsx へ渡す。jurisdictions.json を
  // 画面側からも fetch させると同じデータを2箇所（生成物と実行時 fetch）で持つことになるため、
  // このページが担当する1団体分だけをビルド時に埋め込む。
  const injected = escapeJsonForScript({ code, name })
  const safeName = escapeHtml(name)
  return `<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />

    <!-- ⚠️ document.title はここから団体・年度に応じて実行時に書き換わる
         （src/pages/pipeline.tsx）。ここに書くのは JS 実行前 / SEO 用の既定値 -->
    <title>${safeName} のELTパイプライン報告 | fudoki（風土記）</title>
    <meta
      name="description"
      content="${safeName} の予算データについて、fudoki の ELT パイプラインが何を検査し、どこで判断を加えているかを追う報告。原典・変換・配布物の系統は dbt の manifest から生成する。"
    />
    <link rel="canonical" href="https://fudoki.dev/pipeline/${code}/" />

    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="theme-color" media="(prefers-color-scheme: light)" content="#f4f1e6" />
    <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0b0f14" />
    <script>window.__FUDOKI_PIPELINE_JURISDICTION__ = ${injected}</script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main-pipeline.tsx"></script>
  </body>
</html>
`
}

function writeSitemap(root: string, codes: string[]): void {
  // 手書きだと3 URL のまま古びる（実際にそうなっていた）。62団体分をここで同時に生成する
  const urls = [
    "https://fudoki.dev/",
    "https://fudoki.dev/pipeline/",
    ...codes.map((c) => `https://fudoki.dev/pipeline/${c}/`),
    "https://fudoki.dev/terms/",
  ]
  const body = urls.map((u) => `  <url>\n    <loc>${u}</loc>\n  </url>`).join("\n")
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`
  fs.writeFileSync(path.join(root, "public", "sitemap.xml"), xml)
}
