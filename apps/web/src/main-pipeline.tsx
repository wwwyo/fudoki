import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import { PipelinePage } from "@/pages/pipeline"

// 団体ごとの `/pipeline/<団体コード>/index.html` は、その団体のコード・名称を
// window 経由でビルド時に埋め込む（apps/web/vite-plugins/pipeline-jurisdictions.ts）。
// コードなしの `/pipeline/` にはこの global が無いので undefined のまま扱う。
declare global {
  interface Window {
    __FUDOKI_PIPELINE_JURISDICTION__?: { code: string; name: string }
  }
}
const injected = window.__FUDOKI_PIPELINE_JURISDICTION__

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PipelinePage urlCode={injected?.code ?? null} jurisdictionName={injected?.name} />
  </StrictMode>
)
