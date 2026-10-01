import { defineConfig } from '@cloudflare/config/public'

export default defineConfig({
  worker: {
    name: 'fudoki-docs',
    compatibilityDate: '2026-08-23',
    assets: {
      notFoundHandling: '404-page',
    },
    domains: ['docs.fudoki.dev'],
  },
})
