import { defineConfig } from '@cloudflare/config/public'

export default defineConfig({
  worker: {
    name: 'fudoki-api',
    compatibilityDate: '2026-08-23',
    entrypoint: 'worker.ts',
    domains: ['api.fudoki.dev'],
  },
})
