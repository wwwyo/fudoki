import { existsSync, readdirSync } from "node:fs"
import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const ROOT = import.meta.dirname

// MPA（React Router は入れない）。ページを1つ足すたびに `input` へ手で列挙すると、
// 登録し忘れても vite build はエラーにならず、そのページだけ静かにビルドから漏れて
// 本番で 404 になる（AGENTS.md の「足し忘れはエラーで止まる」設計から外れる）。
// `apps/web/` 直下を走査して `index.html` を持つディレクトリを拾えば、
// HTML を置いた時点でビルド対象に入り、この失敗経路自体が無くなる。
const EXCLUDED_DIRS = new Set(["node_modules", "dist", "public", "src", "brand"])
const pageInput = Object.fromEntries(
  readdirSync(ROOT, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.name.startsWith(".") && !EXCLUDED_DIRS.has(e.name))
    .filter((e) => existsSync(path.join(ROOT, e.name, "index.html")))
    .map((e) => [e.name, path.resolve(ROOT, e.name, "index.html")])
)

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
      // 報告の型は workspace 依存 @fudoki/report から取る（web 側で写しを持たない）
    },
  },
  build: {
    rollupOptions: {
      // ⚠️ `base` を "/" のまま置ける（AGENTS.md）のはルート配信が前提だからで、
      // それだけでは足りない。HTML・コンポーネントには `/favicon.svg` `/pipeline/` `/terms/`
      // のようなルート絶対パスも残っているので、置き場所をサブディレクトリへ移すときは
      // `base` に加えてそれらのリンクも直す必要がある。
      input: {
        main: path.resolve(ROOT, "index.html"),
        ...pageInput,
      },
    },
  },
})
