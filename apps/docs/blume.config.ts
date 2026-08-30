/**
 * blume（https://useblume.dev/）の設定。
 * OpenAPI reference は apps/api の contract から生成した openapi.json（`bun run generate`、
 * commit しない派生物）を読む。手書きの API ドキュメントは持たない。
 */
import { defineConfig } from 'blume'

export default defineConfig({
  title: 'fudoki budget API docs',
  description: '東京都の区市町村の予算を事業単位まで構造化して配布する budget API のドキュメント。',

  // public/ のマークと favicon は apps/web/public/ からのコピー（`bun run build:brand` の生成物）。
  // ブランドを変えたら build:brand を回してコピーし直す。
  // ⚠️ ロゴを1枚にしない — SVG 内のメディアクエリは OS 設定しか見ないため（apps/web の header と同じ理由）。
  logo: {
    image: { light: '/mark.svg', dark: '/mark-dark.svg', alt: '風土記' },
    text: 'fudoki budget API',
  },

  openapi: {
    enabled: true,
    spec: './openapi.json',
    route: '/reference',
  },

  navigation: {
    tabs: [{ label: 'API', path: '/reference' }],
    // ダッシュボード（apps/web）への導線。外部 URL なので新しいタブで開く
    featured: [{ label: 'ダッシュボード', href: 'https://fudoki.dev/' }],
  },
})
