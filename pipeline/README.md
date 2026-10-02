# 財政データを構築して配る

原典・取り込み済み Parquet は非公開 R2、コード・宣言・判断・入力一覧・証跡は Git に置く。dbt が提供モデルを確定し、団体別の配布物を公開 R2、検索用の派生表を D1 へ反映する。公開 web とローカル検証画面の UI は共有しない。

全体設計は [monorepo の設計](../docs/design-doc-monorepo.md)、D1 の版と再実行は [自治体データ版の設計](../docs/design-doc-jurisdiction-versions.md)、金額・対応は [財政明細の設計](../docs/design-doc-fiscal-records.md) にある。

## 固定入力から構築する

ツールは root の mise、依存は Bun と uv で管理する。Python は3.13。

```bash
mise install
bun install --frozen-lockfile
uv sync --frozen
bun run pipeline:inputs
bun run pipeline:build
bun run pipeline:build --rebuild
```

`pipeline:inputs` は ingestion の `sources.lock.json` が指定する原典・表を R2 から復元し、Git にある証跡も含めてハッシュを照合する。復元先は `.cache/inputs/<入力一覧のhash>/raw/`。必要な入力が欠けた場合は停止し、自治体サイトの最新版で補わない。

`build.ts` は復元済みの固定入力を使い、ネットワークなしで dbt・FDP descriptor・manifest・D1/API の検査を実行する。結果は `.build/builds/r-<内部構築ID>/` に入り、`complete.json` がある候補だけを publish できる。`--rebuild` は別の作業領域で再生成し、同じ入力・コードから同じ内容を生成できるか照合する。`.build/warehouse.duckdb` は検証画面用の再生成可能な DB である。

配布物と D1 は決算・当初予算・変更・対応を分ける。決算明細は実績の `amount` 一つを持ち、歳出の COFOG コード・状態・根拠は明細・変更と同じ CSV に含める。歳出の分類は当面 COFOG のみとし、GFSM は提供しない。歳出明細 CSV の節・その内訳のコードと名称は配布から外す。原典の節は取り込み・内部検証と予算対象の原典経路に残し、歳入の節は財源の内訳として保持する。規則ファイル・規則 ID は公開しない。原典の複数金額列は取り込み表と候補の `internal/fiscal/` に残し、公開する実績と混在させない。

補正・繰越等の実資料と、資料間の確認済み対応は現在未収録である。変更・対応表が空でも、変更ゼロ・予算と決算の一致を意味しない。dataset の `coverage.budgetHistory` は `unconfirmed` として提供する。収録・照合の条件は [予算変更履歴 PRD](../docs/prd/fiscal-budget-history/prd.md) に残す。

採用済みの設計では、歳出の節マスタ `fiscal_expenditure_setsu` を追加し、歳出予算を事業×歳出の節へ集約する。参照は `expenditure_setsu_id`、下位内訳と原典行への対応は金額明細の `details_json` とする。この変更は未実装であり、上記は現在の構築結果を説明している。移行の契約と検査条件は [財政データの設計](../docs/design-doc-fiscal-records.md) を参照。

## 収録範囲を Git に記録する

build は採用する団体・dataset・出典・注意点・配布先を `publish/manifest.json` に生成する。過去の一覧は Git 履歴で辿る。manifest を R2 に複製しない。

- `versionId`: 団体の正規化データ・公開メタデータ・配布参照の内容。コードだけが変わっても内容が同じなら維持する。
- `packageId`: 団体の配布ファイルの内容。未変更のファイル群は同じ R2 キーを再利用する。
- 内部構築 ID: コード・固定入力・処理定義に対応するローカル候補。D1/API の公開版ではない。

コード・入力・処理規則との対応、表のハッシュ、検査結果は候補の `verification.json` と検査 JSON に保持する。

## 団体ごとに直接反映する

```bash
bun run pipeline:publish schema
bun run pipeline:publish init --dry-run
bun run pipeline:publish init
bun run pipeline:publish publish --build-id r-<32桁のhash> --dry-run
bun run pipeline:publish publish --build-id r-<32桁のhash>
bun run pipeline:publish publish --build-id r-<32桁のhash> --jurisdiction 132195
```

publish は再構築せず、完成した候補の R2 ファイルと D1 の表を反映する。clean な commit、正規の遠隔検証済み入力一覧、現在のコードと候補の一致、commit した Git manifest を要求する。コード・固定入力を commit → build → manifest を commit → publish の順に実行する。

D1 は新しい22表の保存契約を使う。旧 schema は自動削除せず、新しい D1 を初期化して API の binding と合わせる。公開 API の契約・問い合わせ定義・接続先 DB を通常の HTTP 経路で確認してから取り込む。

団体の配布物を転送・照合し、D1 の版を登録して表を順に追加する。**登録済みの明細は取り込み途中も API から取得できる。** 全体 release、公開状態、guard、lease、公開切替は設けない。通常は団体ごとに最も新しく登録された版を読む。登録時刻は初回だけ記録し、古い版の再試行で最新版を変えない。

失敗しても登録済みの行を残す。同じ版・主キーの再実行は同じ内容だけを許容し、内容が違えば停止する。同じ団体・版への書き込みは実行側で直列にする。全行・公開 API の件数と金額・配布参照を取り込み後に照合し、候補に結果を保存する。この照合は公開を隠す条件にはしない。

過去の D1 版と R2 の配布物は当面保持し、自動削除・全体 rollback は実装しない。原典と証跡は配布物の寿命に連動させない。

公開 R2 は `download.fudoki.dev` の custom domain から直接配信する。公開用 download Worker と非公開検証 Worker は置かない。Cache Rules・rate limiting・`r2.dev` の無効化は [配布設定](../docs/adr/0011-public-r2-distribution.md) に従い、遠隔適用は移行記録で確認する。

## Cloudflare でローカル確認する

API・web・docs は `cloudflare.config.ts` と `cf` で dev/build/deploy する。local D1/R2 の投入だけは、cf の内部ビルダーである Wrangler の proxy ライブラリを使う。秘密は mise + age で管理し、平文の設定を追加しない。

```bash
bun run dev:setup             # API を停止してローカル D1 に完成候補を入れる
bun run dev:setup:download    # 配布ファイルだけをローカル R2 に入れる
bun run dev:api              # cf dev、127.0.0.1:8787
bun run dev:download         # 検証側のローカル専用 R2 配信、127.0.0.1:8788
bun run dev:web              # 公開 UI、127.0.0.1:5173
bun run dev                  # 原典・dbt の検証画面、127.0.0.1:5174
```

R2 の確認用 Worker は `verify/r2/` に閉じ、production mode では起動・デプロイを拒否する。PDF 閲覧レイヤは `.cache/pdf/`、報告は `.build/report/`。公開 web に原典や検証データを混ぜない。

## 検査する

```bash
bun run test
bun run typecheck:all
uv run python -m unittest discover -s pipeline -p '*_test.py'
bun run build:api
bun run build:web
bun run build:docs
bun run pipeline/verify/boundaries.ts
```

架空の fixture は保存制約・版の独立・途中の公開・再試行・過去版・API/MCP を検査する。全量 build は固定原典を使い、原典の行・金額・分類と D1/API・配布物の一致を別に検査する。

CI の全量 job は `FUDOKI_FIXED_INPUTS_READY=true` と非公開 R2 の読取権限がある場合だけ動く。`FUDOKI_REVIEW_BASELINE_URL` に比較元の Git commit 固定 manifest URL を置く。初回だけ `FUDOKI_REVIEW_INITIAL_RELEASE=true` を明示する。比較元の取得失敗を初回扱いにはしない。公開前の数値・ID・分類・出典の差分は `verify/summary.ts` が記録する。PR の CI は遠隔 publish を実行しない。

現在の遠隔適用状況と残る作業は [移行記録](../docs/monorepo-migration.md) を参照する。

公開 R2 の custom domain・キャッシュ・rate limit の設定は [cloudflare/README.md](publish/cloudflare/README.md) に従う。CDN/WAF の検証は遠隔で実施する。
