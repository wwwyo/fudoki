import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'
import { REPO } from '../../paths'
import { jurisdictionPages } from './vite-plugins/jurisdiction-pages'
import { localData } from './vite-plugins/local-data'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    jurisdictionPages(import.meta.dirname),
    localData(import.meta.dirname),
  ],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: { host: '127.0.0.1', port: 5174, strictPort: true, fs: { allow: [REPO] } },
  preview: { host: '127.0.0.1', port: 5174 },
  build: {
    rollupOptions: {
      input: { main: path.resolve(import.meta.dirname, 'pipeline/index.html') },
    },
  },
})
