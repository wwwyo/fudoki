import fs from 'node:fs'
import path from 'node:path'
import type { Plugin } from 'vite'

/** 団体マスタからローカル検証ページを生成する Vite plugin。 */
export function jurisdictionPages(root: string): Plugin {
  return {
    name: 'fudoki-jurisdiction-pages',
    config(_config, _env) {
      const jurisdictions = loadJurisdictions(root)
      const input: Record<string, string> = {}

      const dir = path.join(root, 'pipeline')
      for (const [code, jurisdiction] of Object.entries(jurisdictions)) {
        const codeDir = path.join(dir, code)
        fs.mkdirSync(codeDir, { recursive: true })
        const file = path.join(codeDir, 'index.html')
        writeIfChanged(file, renderHtml(code, jurisdiction.name))
        input[`pipeline-${code}`] = file
      }

      return { build: { rollupOptions: { input } } }
    },
  }
}

/** 内容が変わったときだけ書き直す。生成物は vite build の入力でもあり、無条件で
 *  書き直すとファイル監視・インクリメンタルな作業が毎起動で走り直しになる */
function writeIfChanged(file: string, content: string): void {
  if (fs.existsSync(file) && fs.readFileSync(file, 'utf-8') === content) return
  fs.writeFileSync(file, content)
}

type Jurisdiction = { name: string }

function loadJurisdictions(root: string): Record<string, Jurisdiction> {
  // 正本は packages/jurisdictions/jurisdictions.json（団体の同一性を1層のファイルに同居させない。AGENTS.md）
  const file = path.resolve(
    root,
    '../../../packages/jurisdictions/jurisdictions.json'
  )
  const parsed = JSON.parse(fs.readFileSync(file, 'utf-8')) as {
    jurisdictions: Record<string, Jurisdiction>
  }
  return parsed.jurisdictions
}

/** HTML のテキストと属性値に入れる文字。`"` まで含めるのは属性値に埋めるため */
function escapeHtml(s: string): string {
  return s.replace(
    /[&<>"]/g,
    (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string
  )
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
  return JSON.stringify(value).replace(/</g, '\\u003C')
}

function renderHtml(code: string, name: string): string {
  const safeName = escapeHtml(name)
  return page({
    title: `${safeName} の提供用データの検証 | 風土記`,
    description: `${safeName}の原典・取り込み表・提供用データの対応と検査結果を確認する。系統は dbt の manifest から生成する。`,
    globalName: '__FUDOKI_PIPELINE_JURISDICTION__',
    injected: escapeJsonForScript({ code, name }),
    entry: '/src/main-pipeline.tsx',
  })
}

function page(opts: {
  title: string
  description: string
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
