import { defineConfig } from '@cloudflare/config/public'

export default defineConfig({
  worker: {
    name: 'fudoki',
    compatibilityDate: '2026-08-23',
    assets: {
      notFoundHandling: 'none',
    },
    domains: ['fudoki.dev'],
  },
})
