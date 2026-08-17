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
      // 報告の型はパイプライン本体から取る（web/ 側で写しを持たない）
      "@pipeline": path.resolve(import.meta.dirname, "../src/budget"),
    },
  },
})
