import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import { AnalysisPage } from "@/pages/analysis"

// 団体ごとの `/analysis/<団体コード>/index.html` は、その団体のコード・名称を
// window 経由でビルド時に埋め込む（apps/web/vite-plugins/jurisdiction-pages.ts）。
// コードなしの `/analysis/` にはこの global が無いので undefined のまま扱う。
declare global {
  interface Window {
    __FUDOKI_ANALYSIS_JURISDICTION__?: { code: string; name: string }
  }
}
const injected = window.__FUDOKI_ANALYSIS_JURISDICTION__

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AnalysisPage urlCode={injected?.code ?? null} jurisdictionName={injected?.name} />
  </StrictMode>
)
