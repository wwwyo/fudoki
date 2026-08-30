/**
 * blume（https://useblume.dev/）の設定。
 * root（/）が docs、/reference が OpenAPI reference。
 * OpenAPI reference は apps/api の contract から生成した openapi.json（`bun run generate`、
 * commit しない派生物）を読む。手書きの API ドキュメントは持たない。
 */
import { defineConfig } from 'blume'

export default defineConfig({
  title: '風土記 API',
  description: '日本の地方自治体の予算を事業単位まで構造化して配布する、風土記の API ドキュメント。',

  // public/ のロゴと favicon は apps/web/public/ からのコピー（`bun run build:brand` の生成物）。
  // ブランドを変えたら build:brand を回してコピーし直す。
  // ロゴ画像がワードマーク（風土記）込みなので text は空にする。
  // ⚠️ ロゴを1枚にしない — SVG 内のメディアクエリは OS 設定しか見ないため（apps/web の header と同じ理由）。
  logo: {
    image: { light: '/logo.svg', dark: '/logo-dark.svg', alt: '風土記' },
    text: '',
  },

  openapi: {
    enabled: true,
    spec: './openapi.json',
    route: '/reference',
  },

  navigation: {
    tabs: [
      { label: 'Docs', path: '/' },
      { label: 'API', path: '/reference' },
    ],
    sidebar: [
      {
        label: 'Get started',
        items: ['/', '/quickstart'],
      },
    ],
    // ダッシュボード（apps/web）への導線。外部 URL なので新しいタブで開く
    featured: [{ label: 'ダッシュボード', href: 'https://fudoki.dev/' }],
  },
})
