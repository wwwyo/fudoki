# 公開 web

入口の1枚（`landing.ts`）と会話の画面（`/s/:id`、下の「風土記の AI に聞く」）、favicon・OG 画像・robots.txt・sitemap.xml・見出しの明朝だけを返す（画像は `public/` を `assets.ts` に、明朝は `font.generated.ts` に写して Worker が返す）。ホームの録画と出典の切り抜きのような重いファイルは `static/` に置き、Workers static assets で配る。自治体ごとの頁（`/自治体`・`/:都道府県/:名称`）も返す（下の「自治体の個別ページ」）。PWA 用の `/manifest.webmanifest`・`/sw.js`・`/offline`（`pwa.ts`）も返す。service worker は繋がらないときの案内を出すだけで、頁・API はキャッシュしない。PWA のアイコンは `brand/pwa_icons.py` で `public/` に描き、`assets.ts` へ写す。他は 404。main に入ると `.github/workflows/deploy-web.yml` が自動で deploy する（手元からは `bun run --cwd apps/web deploy`）。web を変える PR は `.github/workflows/preview-web.yml` が `pr-<番号>.fudoki.dev` に preview を出す（push のたびに同じ URL を更新し、PR を閉じたら消す。Access で Cloudflare アカウントのログインだけを通す。利用状況は書かない）。

```bash
bun run dev:web
bun run build:web
```

## 自治体の個別ページ（`/:都道府県/:名称`）

`/自治体` が決算を収録している自治体の一覧、`/東京都/中野区` のように**都道府県名と自治体名を path に入れた**個別ページが検索（SEO）の入口。都道府県名と名称の一致で引く（`/s/:id` や `/api/*` とは都道府県名の形で見分け、形が違えば次の経路へ渡す）。名称は自治体マスタ（`/v1/jurisdictions`）のとおり。収録が無い自治体は noindex の案内、存在しない名称は 404。`/sitemap.xml` は収録のある自治体の頁を含む（API に繋がらないときは入口と一覧だけ）。

- **データ**: `server/jurisdiction.ts` が api（Service Binding）の歳出の検索から、一般会計の決算の款（年度ごと）・金額の大きい目（積立・公債・予備費の款を除く。前年度の同じ目との比較つき）・全款の流れ（款→項→目→節）を組む。金額は API の円のまま。流れ図では印字のない金額を「金額未記載」と表示し、表示済みの子の合計は親の帯の高さにだけ使う。足すのは同じ年度の款（兄弟）の和（歳出の総額）だけで、api の sum_rules に従う。結果は Worker の cache に1時間置く（`server/jurisdiction-routes.ts`）
- **描画**: サーバーが金額・款・事業を HTML に書き（`jurisdiction/html.ts`、JSON-LD の Dataset つき）、島（`jurisdiction/jurisdiction.tsx`、build で `static/_app/jurisdiction.js`）が同じデータを shadcn/ui の chart（recharts）と流れ図（`jurisdiction/sankey.tsx`）で描き直す。流れ図（`jurisdiction/flow.tsx`）は、初期表示が全款・全項の全体図で、横にスクロールすると snap して款が一つずつ開き、縦にスクロールすると款の中の項が一つずつ開く（クリックやタブは要らない）。目・節は図が近づいたときに `/api/jurisdictions/flow/:code/:year/setsu` で全款分を一度だけ取得する（誰でも読める GET。IP ごとの流量 `VIEW_RATE_LIMIT` と 入力と収録年度の検査で守る）。事業の節の上位は開閉せず最初から出す
- **仮の値**: 人口・将来推計・特色は API にまだ無いので `jurisdiction/dummy.ts` の仮の値で、画面に「仮」と出す。HTML（検索結果に出る説明・JSON-LD）には入れない。本物のデータを入れるときはここを置き換える
- **会話への導線**: 下の入力（`chat/start-form.tsx`、入口と共通）から会話を始めると、最初の質問に「自治体名について：」が付く

## 見出しの明朝は `landing.ts` の字から作る

`public/fonts/mincho.woff2`（＝Worker が返すため `font.generated.ts` に base64 で写したもの）は、`bun run --cwd apps/web build:font` が `landing.ts` の本文に出てくる字だけを BIZ UDP明朝から集めて作る。**ホームの文言を変えたら `build:font` を回す。** 回さないと新しい字だけ配信フォントに無く、閲覧者の OS の明朝に落ちる。CI（`verify.yml`）の `build:font:check` が、今の `landing.ts` の字を配信フォントがすべて含むかを確かめて、ずれていれば落とす。Google Fonts を使わないのは、読み手の IP を第三者へ渡さないため（`brand/home_font.py`）。

## 風土記の AI に聞く（`/` の入力と `/s/:id`）

入口の中央の入力（`chat/start.tsx`、React の島）から、風土記の MCP（apps/api）に繋いだ AI と会話する。会話の画面 `/s/:id` は React の SPA（`chat/session.tsx`）。チャットの部品は shadcn の chat 系（`chat/components/ui/`、`components.json`）で、apps/web の中に閉じる。

- **流れ**: 入力を送ると Turnstile で確かめ（`POST /api/sessions` がサーバー側で siteverify）、その会話だけに使える署名付き token（2時間）を受けて `/s/:id` に移る。`POST /api/chat` が Workers AI（`workers-ai-provider`、モデルは config の `CHAT_MODEL`、推論の深さは `CHAT_REASONING_EFFORT`）と AI SDK の MCP client で応答を stream する。apps/api とは Service Binding（`API`）で繋ぐ
- **表示**: AI が `render_expenditure_view` を呼んだ結果は、apps/api の MCP Apps の View を `srcdoc` + `sandbox="allow-scripts"` の iframe に置き、`AppBridge` + `PostMessageTransport` で渡す（`chat/view-frame.tsx`、土台は `apps/api/tests/host.ts`）。View が呼ぶ tool と resource の読み込みは `POST /api/mcp` が許可リスト（`server/limits.ts` の `VIEW_TOOLS`・`VIEW_RESOURCE`）で中継する
- **AI に渡すもの**: tool の結果は text の側だけ（`server/chat.ts` の `textOnly`）。structuredContent と `_meta` は View にだけ流れる（`_meta` の `fudoki.dev/suggestions` の候補だけは会話の画面も読み、回答の下にチップで出す。押すと候補の `prompt` を質問として送る。`packages/fiscal/suggestions.ts` が型と検査を共有する）
- **保存しない**: 会話の履歴と token はブラウザの sessionStorage だけに置く。サーバーは利用状況だけを Analytics Engine に書く（本文・IP・会話 ID は書かない）
- **上限**: IP ごとの流量（`CHAT_RATE_LIMIT`・`VIEW_RATE_LIMIT`、値は `server/limits.ts` と config で二重に持ち、試験が照合する）、段数・出力 token・文字数・件数・body の大きさ（`server/limits.ts`）。流量の binding・Turnstile の secret・site key のどれかが無ければ、チャットは止まる（入口は入力を出さない）
- **build**: `bun run --cwd apps/web client` が `static/_app/` に JS・CSS を書く（`build`・`deploy`・`dev` が先に回す。生成物は commit しない）

### 手で設定するもの

- Turnstile の widget を dashboard で作り（hostname は `fudoki.dev`）、site key を `deploy/cloudflare.config.ts` の `TURNSTILE_SITE_KEY` に書く（設定済み）。secret key は Worker の secret `TURNSTILE_SECRET_KEY` に置く（会話の token の署名の鍵もここから作る）
- 手元の `cf dev` は `deploy/.dev.vars.example` を `deploy/.dev.vars` に写す（secret は Cloudflare の試験用の鍵で通る）。site key は localhost / 127.0.0.1 のときだけ `worker.ts` が試験用の値に差し替える（本番の widget の hostname は `fudoki.dev` で、config の `TURNSTILE_SITE_KEY` は text の binding なので `.dev.vars` では上書きできない）
- preview（`pr-<番号>.fudoki.dev`、Cloudflare Access で保護）は config の `isPreview` で site key・secret を Cloudflare 公開の「常に通る」試験用の値に差し替える（AI エージェントが操作できる）。試験用の secret は action・hostname が合わないダミー値を返すので、`server/session.ts` はその secret のときだけ success のみを見る。本番は変えない

### 利用状況

dataset `fudoki_web_chat`（binding `CHAT_USAGE`）に1要求1行で書く。列は `server/usage.ts`: blob1 種類（`chat`・`relay`）・blob2 モデル・blob3 tool と回数（`name:count,...`）・blob4 失敗の種類、double1 入力 token・double2 出力 token・double3 tool 呼び出し数・double4 段数・double5 所要 ms・double6 失敗なら1。

```sql
-- 直近7日の、日ごと・モデルごとの会話の応答数・token・tool 呼び出し・失敗・平均所要時間（Analytics Engine の SQL API）
SELECT
  toStartOfDay(timestamp) AS day,
  blob2 AS model,
  SUM(_sample_interval) AS responses,
  SUM(_sample_interval * double1) AS input_tokens,
  SUM(_sample_interval * double2) AS output_tokens,
  SUM(_sample_interval * double3) AS tool_calls,
  SUM(_sample_interval * double6) AS errors,
  SUM(_sample_interval * double5) / SUM(_sample_interval) AS avg_ms
FROM fudoki_web_chat
WHERE blob1 = 'chat' AND timestamp > NOW() - INTERVAL '7' DAY
GROUP BY day, model
ORDER BY day
```
