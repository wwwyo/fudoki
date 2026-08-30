import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

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
      // MPA（React Router は入れない）。3つの HTML を個別の entry として登録する。
      // `base` は "/" のままなので、置き場所（サブディレクトリ）を変えてもここを直すだけでよい。
      input: {
        main: path.resolve(import.meta.dirname, "index.html"),
        pipeline: path.resolve(import.meta.dirname, "pipeline/index.html"),
        terms: path.resolve(import.meta.dirname, "terms/index.html"),
      },
    },
  },
})
