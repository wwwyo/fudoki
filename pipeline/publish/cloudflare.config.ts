import { bindings, defineConfig } from '@cloudflare/config/public'

import { queryFingerprint } from '../../apps/api/scripts/query-fingerprint.ts'

export default defineConfig(async () => ({
  worker: {
    name: 'fudoki-pipeline-verification',
    compatibilityDate: '2026-08-18',
    entrypoint: 'worker.ts',
    workersDev: false,
    previewUrls: false,
    limits: {
      cpuMs: 300000,
    },
    observability: {
      enabled: true,
    },
    env: {
      QUERY_FINGERPRINT: bindings.text(await queryFingerprint()),
      DB: bindings.d1({
        name: 'fudoki',
        id: 'ae57ff6e-9684-4730-a854-43c173306f85',
      }),
      RELEASES: bindings.r2({
        name: 'fudoki-releases',
      }),
      PUBLIC_API: bindings.worker({
        worker: 'fudoki-api',
      }),
      PUBLIC_DOWNLOAD: bindings.worker({
        worker: 'fudoki-download',
      }),
    },
  },
}))
