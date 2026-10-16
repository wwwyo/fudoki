# 公開 web

入口の1枚（`landing.ts`）と、favicon・OG 画像・robots.txt・sitemap.xml・見出しの明朝だけを返す（画像は `public/` を `assets.ts` に、明朝は `font.generated.ts` に写して Worker が返す）。ホームの録画と原典の切り抜きのような重いファイルは `static/` に置き、Workers static assets で配る。他は 404。main に入ると `.github/workflows/deploy-web.yml` が自動で deploy する（手元からは `bun run --cwd apps/web deploy`）。

```bash
bun run dev:web
bun run build:web
```

## 見出しの明朝は `landing.ts` の字から作る

`public/fonts/mincho.woff2`（＝Worker が返すため `font.generated.ts` に base64 で写したもの）は、`bun run --cwd apps/web build:font` が `landing.ts` の本文に出てくる字だけを BIZ UDP明朝から集めて作る。**ホームの文言を変えたら `build:font` を回す。** 回さないと新しい字だけ配信フォントに無く、閲覧者の OS の明朝に落ちる（`build:web` も CI もこの再生成をしないので気づけない）。Google Fonts を使わないのは、読み手の IP を第三者へ渡さないため（`brand/home_font.py`）。
