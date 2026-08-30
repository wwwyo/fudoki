import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import { PipelinePage } from "@/pages/pipeline"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PipelinePage />
  </StrictMode>
)
