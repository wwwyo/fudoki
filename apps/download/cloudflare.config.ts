import { bindings, defineConfig } from '@cloudflare/config/public'

export default defineConfig({
  worker: {
    name: 'fudoki-download',
    compatibilityDate: '2026-08-18',
    entrypoint: 'src/index.ts',
    observability: {
      enabled: true,
    },
    domains: ['download.fudoki.dev'],
    env: {
      RELEASES: bindings.r2({
        name: 'fudoki-releases',
      }),
    },
  },
})
