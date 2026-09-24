# @fudoki/mcp

fudoki（区市町村の予算）を AI アシスタントから問い合わせるための MCP サーバ。

**本番は remote（Cloudflare Workers 上の `/mcp`）。このパッケージ（stdio）はローカル開発用。**
tool の定義（[`apps/api/src/mcp/`](../api/src/mcp/)）は両方で共有しており、集計も判断も持たない ──
tool は [`apps/api`](../api) の oRPC router をプロセス内でそのまま呼び、応答をそのまま返すだけ
（AGENTS.md の「集計は1箇所」）。このパッケージが持つのは、Workers 版の `ASSETS` binding の代わりに
`apps/api/dist/assets/` をファイルシステムから読む Env（[`src/env.ts`](./src/env.ts)）と、
`serveStdio` に繋ぐだけの薄いエントリ（[`src/index.ts`](./src/index.ts)）。

SDK は **`@modelcontextprotocol/server` 2.x**（typescript-sdk の v2 stable line）を使う。
`2026-07-28`（modern era）と `〜2025-11-25`（legacy era）の両方を出す ── どちらに振り分けるかは
リクエストが `_meta['io.modelcontextprotocol/protocolVersion']` の envelope を持つかで決まる
（remote は `isLegacyRequest`、stdio は `serveStdio` が era を決める）。modern には
`initialize` が無く、能力の probe は `server/discover`。

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
| `list_jurisdictions` | `listJurisdictions` | 収録団体と caveats |
| `list_budgets` | `listBudgets` | 収録範囲（団体×年度）そのもの。予算段階・会計範囲・COFOG 到達度を含む |
| `get_budget_lines` | `getBudgetLines` | 予算の明細（ページングあり）。単一 budget か、`-` で全予算横断 |
| `aggregate_budgets` | `aggregateBudgets` | 予算を COFOG（大分類・中分類・小分類）別、または科目階層（款・項・目）別に集計した結果 |
| `search_budget_lines` | `searchBudgetLines` | 名称（原典の科目階層名 / fudoki が対応づけた事業名）の部分一致による横断検索 |

収録団体と予算段階は `list_jurisdictions` / `list_budgets` の応答が正
（団体を足すたびにここが古くなるので数は書かない）。段階は団体で違う ──
当初予算の団体と決算の団体が混在する。

⚠️ `aggregate_budgets` の `direction` と `phase` は必須（既定値なし）。段階は団体で違うので、
先に `list_budgets` で対象団体の `scopes[direction].phases` を見て、実在する phase を選んでから呼ぶこと。
複数団体にまたがる集計（filter に jurisdiction を指定しない）は `groupBy` に `jurisdiction` を含める必要がある。

⚠️ `aggregate_budgets` で歳入（`direction=revenue`）を集計できるのは `hierarchy` / `fiscalYear`
の軸だけ。`groupBy` に COFOG 軸（`cofog.division` / `.group` / `.class`）を含めると 400 になる ──
`cofog_status` が歳入では常に `not-applicable` で、COFOG そのものが歳入に適用されないため
（v1 の制限ではなくデータの事実）。応答・エラー応答の `supportedGroupings` が、
groupBy ごとに対応する direction を示す。

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

⚠️ SDK v1 系（旧 `@modelcontextprotocol/sdk`）の `registerTool` はトップレベルが object 型でない
`outputSchema` を扱えなかった（実機で確認: `undefined.safeParseAsync` で落ちる）。
`getBudgetLinesOutput`（`budgetLineSchema` を view で使い分ける単一の object schema）は
この制約に元から当たらないため、`get_budget_lines` の `outputSchema` は contract を
そのまま流用できている（v2 でも同じ形を維持している）。

## remote の構成（Workers）

`apps/api/src/index.ts` の `app.all(MCP_PATH, ...)`（`MCP_PATH` は `apps/api/src/spec.ts` の唯一の宣言元）。

- **era で振り分ける**。`isLegacyRequest`（`createMcpHandler` と同じ分類コード）で
  legacy / modern を判別する。legacy leg は `WebStandardStreamableHTTPServerTransport`
  （Request/Response ベース。外部依存ゼロで Cloudflare Workers 上で直接動く）、
  modern leg は `createMcpHandler(factory, { legacy: 'reject', responseMode: 'json' })`
  を使う。fallback の legacy serving に任せないのは、そちらは transport に
  `enableJsonResponse` を渡せず応答が SSE になるため ── 現行の単発 JSON を保つ
- **stateless**。Workers はリクエストをまたいで状態を持てない（同じ isolate が次のリクエストも
  処理するとは限らない）ので、transport / handler / McpServer は**リクエストごとに作り直す**
  （`sessionIdGenerator` を渡さない = SDK の既定でセッション管理が無効になる）
- `enableJsonResponse: true` / `responseMode: 'json'` で応答は SSE ではなく単発の JSON。
  この tool 群はサーバ発の通知を送らない参照専用の request/response なので、
  ストリームを維持する理由が無い
- アクセス制御（`access-control.ts`）は `/v0/*` と同じ「キー任意・匿名レート制限あり」（`classifyPath` の
  既定 `keyed`）。MCP 独自の認証は設けない（PRD の Non-Goal）
- CORS は `/mcp` だけ `MCP_ALLOWED_ORIGINS` に絞る（`/v0/*` は全開のまま）。
  `mcp-session-id` / `mcp-protocol-version` / `Last-Event-ID` に加えて
  modern era が必須とする `mcp-method` / `mcp-name` も allow ヘッダに入れている
  （ブラウザの modern client が preflight で弾かれないため）
- **Origin ヘッダの検証を実リクエスト側にも持つ**（`index.ts` の `app.all(MCP_PATH, ...)`、
  allowlist は `spec.ts` の `MCP_ALLOWED_ORIGINS`）。MCP Streamable HTTP 仕様の
  Security Considerations が Origin ヘッダの検証を MUST としており、不正なら 403 を返す。
  CORS は preflight を出すブラウザ経路にしか効かないので、curl 等を含む実リクエスト側の
  検証が依然として必要 ── 検証が無いと、悪意あるサイトが被害者のブラウザ経由で `/mcp` を叩き、
  匿名のレート制限枠を被害者の IP で消費できてしまう（PR #27 レビュー指摘）。
  Origin ヘッダの無いリクエスト（curl・ネイティブの MCP client など非ブラウザ）は検証の対象外 ──
  ブラウザ由来でなければこの脅威が成立せず、締め出すと
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
