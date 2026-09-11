# @fudoki/mcp

fudoki（区市町村の予算）を AI アシスタントから問い合わせるための MCP サーバ。

**本番は remote（Cloudflare Workers 上の `/mcp`）。このパッケージ（stdio）はローカル開発用。**
tool の定義（[`apps/api/src/mcp/`](../api/src/mcp/)）は両方で共有しており、集計も判断も持たない ──
tool は [`apps/api`](../api) の oRPC router をプロセス内でそのまま呼び、応答をそのまま返すだけ
（AGENTS.md の「集計は1箇所」）。このパッケージが持つのは、Workers 版の `ASSETS` binding の代わりに
`apps/api/dist/assets/` をファイルシステムから読む Env（[`src/env.ts`](./src/env.ts)）と、
`StdioServerTransport` に繋ぐだけの薄いエントリ（[`src/index.ts`](./src/index.ts)）。

対応する MCP 仕様は **2025-11-25 まで**（`@modelcontextprotocol/sdk` 1.30.0 がこの版までしか知らない。
現行版の 2026-07-28 には未対応 ── 詳細は `.agent/prd/mcp-server/prd.md` の実測メモ）。

## remote への登録（本番）

鍵の設定は不要（PRD の Goal: 「MCP client に URL を登録するだけで、鍵の設定なしに使える」）。

```bash
claude mcp add --transport http fudoki https://api.fudoki.dev/mcp
```

Claude Desktop など他の MCP client でも、URL を remote（Streamable HTTP）サーバとして登録すれば同様に使える。

## stdio への登録（ローカル開発用）

配布物をリビルドするたびに remote へデプロイしなくても手元の変更をすぐ試せる。
先に `apps/api` の配布物をビルドしておく必要がある（このサーバは自分ではデータを持たない）。

```bash
bun run --cwd apps/api build.ts --allow-dirty
```

`dist/assets/` が無いまま起動すると、上のコマンドを案内するメッセージを出して終了する。

```bash
bun run apps/mcp/src/index.ts
# または root から
bun run mcp
```

Claude Code なら:

```bash
claude mcp add fudoki -- bun run /path/to/fudoki/apps/mcp/src/index.ts
```

## いまある tool

apps/api の `Contract`（`apps/api/src/contract/`）にある procedure を、そのまま薄く出している。
定義は [`apps/api/src/mcp/tools/`](../api/src/mcp/tools/) にあり、remote と stdio の両方がそこを import する
（[`apps/api/src/mcp/server.ts`](../api/src/mcp/server.ts) の `createMcpServer`）。

| tool | 対応する procedure | 何を返すか |
|---|---|---|
| `list_jurisdictions` | `listJurisdictions` | 収録団体（東京都3団体だけ）と caveats |
| `list_budgets` | `listBudgets` | 収録範囲（団体×年度）そのもの。予算段階・会計範囲・COFOG 到達度を含む |
| `get_budget_lines` | `getBudgetLines` | 予算の明細（ページングあり）。単一 budget か、`-` で全予算横断 |
| `aggregate_budgets` | `aggregateBudgets` | 予算を COFOG（大分類・中分類・小分類）別、または科目階層（款・項・目）別に集計した結果 |
| `search_budget_lines` | `searchBudgetLines` | 名称（原典の科目階層名 / fudoki が対応づけた事業名）の部分一致による横断検索 |

収録団体は三鷹市（132047）・狛江市（132195）・多摩市（132241）の3団体だけで、
予算段階が団体で違う（三鷹市・多摩市は当初予算、狛江市は決算）。tool の description に
数値付きで書いてあるので、詳細はそちらを参照。

⚠️ `aggregate_budgets` の `direction` と `phase` は必須（既定値なし）。段階は団体で違うので、
先に `list_budgets` で対象団体の `scopes[direction].phases` を見て、実在する phase を選んでから呼ぶこと。
複数団体にまたがる集計（filter に jurisdiction を指定しない）は `groupBy` に `jurisdiction` を含める必要がある。

⚠️ `aggregate_budgets` は v1 では `direction=expenditure` のみ対応。`revenue` を指定すると 400 になる ──
理由は「歳入に COFOG が無いから」ではなく「歳入の集計自体を v1 でまだ実装していないから」（PR #27
レビュー指摘。以前のメッセージは COFOG が理由であるかのように読めた）。応答・エラー応答の
`supportedDirections` が、その時点で対応する direction を示す。

⚠️ `aggregate_budgets` の `groupBy` に `hierarchy` を含めるとき（科目階層＝款・項・目での集計）は、
`fund` を会計コード1つに絞ることが必須（既定の `"all"` は 400）。款・項のコードは会計の中でしか意味を
持たない（三鷹市の款コード `01` は一般会計では議会費、国民健康保険事業特別会計では総務費）。
会計コードは団体で違うので、先に `list_budgets` の `scopes[direction].funds` で実在する値を確認すること。
`hierarchyParent` は直下1段だけを返し、指定できるのは根（省略）・款・項までで、目を指定すると 400 になる。

⚠️ `search_budget_lines` の検索対象は2種類ある。`accountLabel`（原典の名称。`nameSource: canonical`）と
`projectName`（fudoki が決算資料等から対応づけた事業名。`nameSource: judgment`）。どちらを持つかは団体で違う
（`project_names.csv` があるのは狛江市だけで、三鷹市の事業名は原典の事項の名称にある）。応答の `coverage` を
必ず読むこと ── 0件が「存在しない」のか「名称が付いていない」のかは `coverage` でしか区別できない。

各 tool は `outputSchema` を持ち、`structuredContent` で返す（後方互換のため同じ JSON を
text content にも入れる）。API が 400 / 404 を返したときは例外にせず、`isError: true` の
結果として理由と代替の問い方を本文に入れて返す（MCP 仕様が tool 実行エラーを
言語モデルの自己修正の材料と位置づけているため）。

⚠️ MCP SDK 1.30.0 の `registerTool` はトップレベルが object 型でない `outputSchema` を扱えない
（実機で確認: `undefined.safeParseAsync` で落ちる）。`getBudgetLinesOutput`（`budgetLineSchema` を
view で使い分ける単一の object schema）はこの制約に元から当たらないため、`get_budget_lines` の
`outputSchema` は contract をそのまま流用できている。

## remote の構成（Workers）

`apps/api/src/index.ts` の `app.all(MCP_PATH, ...)`（`MCP_PATH` は `apps/api/src/spec.ts` の唯一の宣言元）。

- transport は SDK の `WebStandardStreamableHTTPServerTransport`（Request/Response ベース。外部依存ゼロで
  Cloudflare Workers 上で直接動く。Node 版の `StreamableHTTPServerTransport` は `@hono/node-server` に
  依存するので使わない）
- **stateless**。Workers はリクエストをまたいで状態を持てない（同じ isolate が次のリクエストも
  処理するとは限らない）ので、transport と McpServer は**リクエストごとに作り直す**
  （`sessionIdGenerator` を渡さない = SDK の既定でセッション管理が無効になる）
- `enableJsonResponse: true` で応答は SSE ではなく単発の JSON。この tool 群はサーバ発の通知を送らない
  参照専用の request/response なので、ストリームを維持する理由が無い
- アクセス制御（`access-control.ts`）は `/v0/*` と同じ「キー任意・匿名レート制限あり」（`classifyPath` の
  既定 `keyed`）。MCP 独自の認証は設けない（PRD の Non-Goal）
- CORS は `/v0/*` と同じ全開。`mcp-session-id` / `mcp-protocol-version` / `Last-Event-ID` を
  allow/expose ヘッダに足している（MCP Streamable HTTP がクライアント→サーバ・サーバ→クライアントで使うため）
- **Origin ヘッダの検証を別に持つ**（`index.ts` の `app.all(MCP_PATH, ...)`、allowlist は
  `spec.ts` の `MCP_ALLOWED_ORIGINS`）。MCP Streamable HTTP 仕様の Security Considerations が
  Origin ヘッダの検証を MUST としており、不正なら 403 を返す。CORS の `origin: '*'` はブラウザに
  応答を読ませるかどうかしか決めず、リクエストそのものは拒否できない ── 検証が無いと、悪意ある
  サイトが被害者のブラウザ経由で `/mcp` を叩き、匿名のレート制限枠を被害者の IP で消費できてしまう
  （PR #27 レビュー指摘）。Origin ヘッダの無いリクエスト（curl・ネイティブの MCP client など
  非ブラウザ）は検証の対象外 ── ブラウザ由来でなければこの脅威が成立せず、締め出すと
  PRD の Goal「URL を登録するだけで鍵無しに使える」を壊す。

## 開発

```bash
cd apps/mcp
bun run typecheck
```

`apps/mcp` に `bun test` は無い（tool はロジックを持たず procedure を right-through で呼ぶだけで、
tool 定義自体は `apps/api/src/mcp/` に同居し、remote の HTTP テスト
（`apps/api/src/mcp/http.test.ts`）と `apps/api` 本体のテストが検証をカバーしている）。
stdio 固有の振る舞い（ファイルシステムからの ASSETS 読み込み・未ビルド時のエラーメッセージ）を
変えたときは、`bun run mcp` を実際に起動して `tools/list` が返ることを手で確認すること。
