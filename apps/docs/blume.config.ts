/**
 * blume（https://useblume.dev/）の設定。
 * root（/）が docs、/reference が OpenAPI reference。
 * OpenAPI reference は apps/api の contract から生成した openapi.json（`bun run generate`、
 * commit しない派生物）を読む。手書きの API ドキュメントは持たない。
 */
import { readFileSync } from 'node:fs'
import { defineConfig } from 'blume'

// サイト名は生成済み spec の info.title（apps/api/src/spec.ts の API_TITLE）から取る。
// ここに直書きすると同じ名前の2箇所目の宣言になり、改名時に片方だけ直る。
// openapi.json は `bun run generate` が作る（dev / build は必ず generate を先に通す）
const spec = JSON.parse(readFileSync(new URL('./openapi.json', import.meta.url), 'utf8')) as {
  info: { title: string }
}

export default defineConfig({
  title: spec.info.title,
  description: '日本の地方自治体の予算を事業単位まで構造化して配布する、風土記の API ドキュメント。',

  // public/ のロゴと favicon は apps/web/public/ からのコピー（`bun run build:brand` の生成物）。
  // ブランドを変えたら build:brand を回してコピーし直す。
  // ロゴ画像がワードマーク（風土記）込みなので text は空にする。
  // ⚠️ ロゴを1枚にしない — SVG 内のメディアクエリは OS 設定しか見ないため（apps/web の header と同じ理由）。
  // ⚠️ href の既定は `/` で、それは docs 自身のトップを指す。
  // ロゴは PJ 全体のブランドなので、押した人が期待するのは fudoki のホームであって
  // 「いま見ている API ドキュメントのトップ」ではない。別サイトなので絶対 URL で書く。
  logo: {
    href: 'https://fudoki.dev/',
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
