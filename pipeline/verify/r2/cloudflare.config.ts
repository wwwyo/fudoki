import { bindings, defineConfig } from '@cloudflare/config/public'

export default defineConfig((ctx) => {
  if (ctx.mode !== 'development')
    throw new Error(
      'The R2 preview is local only; production uses the R2 custom domain'
    )
  return {
    worker: {
      name: 'fudoki-local-r2',
      compatibilityDate: '2026-08-18',
      entrypoint: 'index.ts',
      env: { RELEASES: bindings.r2({ name: 'fudoki-releases' }) },
    },
  }
})
