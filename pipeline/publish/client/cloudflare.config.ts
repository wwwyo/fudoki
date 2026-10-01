import { bindings, defineConfig } from '@cloudflare/config/public'

export default defineConfig({
  worker: {
    name: 'fudoki-publish-client',
    compatibilityDate: '2026-08-18',
    workersDev: false,
    previewUrls: false,
    env: {
      VERIFICATION: bindings.worker({
        worker: 'fudoki-pipeline-verification',
        exportName: 'PipelineVerification',
        dev: { remote: true },
      }),
    },
  },
})
