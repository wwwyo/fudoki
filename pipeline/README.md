# データ構築

原典・取り込み済みの表・証跡は非公開 R2、宣言・判断・採用した入力一覧は Git が保持する。DuckDB と D1 は再生成できる表であり、入力の正本ではない。配布物は release を固定して R2 から提供する。

## 固定入力からの build

```bash
mise install
bun install --frozen-lockfile
uv sync --frozen
bun run pipeline:inputs
bun run pipeline:build
bun run dev
```

`pipeline:inputs` は `ingestion/fiscal/sources.lock.json` の個別キー・SHA-256・サイズを検査し、`.cache/inputs/<入力一覧のハッシュ>/raw/` に表と証跡を復元する。原典は `.cache/objects/inputs/origin/sha256/<hash>` に保存する。入力欠落・異なるハッシュ・文書版と証跡の不一致は失敗とする。build は自治体サイトにも Cloudflare にも接続しない。

`build.ts` は dbt build、FDP descriptor、catalog、manifest の生成・検査を順に実行する。配布 CSV と D1 取込表の数値・識別子・分類は dbt の marts が確定する。完成した候補は `build/releases/r-<hash>/`。manifest とファイルを照合する `complete.json` がある候補だけを publish できる。完成済み候補は書き換えない。

`build/latest.json` はローカルで最後に検査した候補の参照であり、公開版の指定ではない。warehouse・dbt の manifest/検査結果・ローカル報告も `build/` に入る。Git 管理しない。

`bun run pipeline:build --rebuild` は同じコード・固定入力を別の作業場所で再構築し、完成済み候補の manifest と一致することを検査する。`build/warehouse.json` が現在の warehouse と候補の対応を記録し、報告の取り違えを防ぐ。DuckDB が参照する再構築用ファイルも `build/` に残す。

## 新しい原典の取得

`bun run pipeline` は原典の再取得 → 非公開 R2 への保管 → 抽出 → 表と証跡の保管・GET によるハッシュ照合 → 入力一覧の固定 → build → 報告を実行する。公開版は変更しない。

再取得は HTTP キャッシュを使わず、実際のバイト列を比較する。原典が同じなら同じ内容アドレスを使い、異なれば別の原典版として保存する。原典を保存できなければ抽出を開始しない。原典・表・証跡は別オブジェクトであり、異なる内容で既存のハッシュキーを上書きしない。抽出の失敗で `sources.lock.json` を更新しない。

文書種別は budget / supplementary / settlement、金額段階は approved / adjusted / adjusted-before-transfer / executed。決算書にある予算現額と決算額を区別する。dataset は団体・年度・歳入歳出・文書種別・原典版を含み、明細 ID は dataset を含めて一意にする。

## publish と切り戻し

Cloudflare の操作には mise 管理の `cf` と既存の認証を使う。先に非公開 `fudoki-inputs` と配布用 `fudoki-releases` を用意する。bucket の公開 URL・自動削除 lifecycle は設定しない。入力 bucket は公開 Worker に bind しない。

```bash
bun run pipeline:publish schema
bun run pipeline:publish init --dry-run
bun run pipeline:publish init
bun run build:api
bun run build:download
bun run build:verification
# 検証済みのコードを commit してから各 Worker を deploy
bun run deploy:api
bun run deploy:download
bun run deploy:verification
# 同じ commit と入力一覧から明示的に build
bun run pipeline:build
bun run pipeline:publish publish --release-id r-<32桁のhash> --dry-run
bun run pipeline:publish publish --release-id r-<32桁のhash>
bun run pipeline:publish rollback --release-id r-<保持中のhash>
```

publish は clean な commit・正規の入力一覧・そのコードで作った完成済み候補を要求する。転送・取込を再生成と混ぜない。ファイルは内容ハッシュで照合し、D1 は最大500行の主キー順ページごとに全内容を照合する。同じ行がある場合も照合を省略しない。

検証 Worker は公開 route / workers.dev / preview URL を持たず、認証された Cloudflare service binding の RPC だけを使う。公開 API と同じ SQL・契約コードで候補を検査する。Node の Wrangler proxy は publish の間だけ起動し、終了時に閉じる。秘密を出力しない。

R2 の最終 manifest は全量照合後に書き、その配布 URL と D1 のファイルメタデータを検査する。最後に D1 の一括更新で候補を published にして active_release を切り替える。転送途中や検査失敗では API の公開参照を変えない。最終 manifest の後で切り替えに失敗した場合、完成したダウンロードは利用可能だが、API は旧版を返す。再実行は既存の内容を再照合して切り替えを完了する。

`GET https://download.fudoki.dev/releases` は完成した公開用 manifest がある版だけを返す。D1 を参照しない。`manifestUrl` は同じ download origin に対する相対 URL。`nextCursor` があれば `?cursor=<値>` で続きを取得する。転送中の版だけが含まれるページは一覧が空でも続きを持つことがある。公開版一覧は変わるため、個別ファイルの不変キャッシュとは分ける。

publish と rollback は同じ lease・fence・公開世代を使い、期限切れの処理による上書きを拒否する。rollback はファイル・D1 の全行・API の件数と金額・Worker 契約を再検査する。API の cursor は保持中の公開 release と問い合わせに固定され、公開切り替えで次ページの版が変わらない。

## 保持・容量・バックアップ

公開版・次の候補・切り戻し用の最低3版を保持する。`publish/control.ts` の `protectedReleases` が active・直近3公開版・処理中候補を返す。自動 cleanup はまだ導入していない。入力と証跡を配布物の削除に連動させない。

現行全量の D1 用 SQLite は約424 MB、3版の単純推計は約1.27 GB。Free の単一 DB の容量と日次書込上限では全量運用できないため、Workers Paid と候補環境の容量・読取行数・性能の検証が必要。SQLite の計測を D1 の実測として扱わない。[D1 制限](https://developers.cloudflare.com/d1/platform/limits/)、[料金](https://developers.cloudflare.com/d1/platform/pricing/)。

バックアップには Git の入力一覧と、それが参照する全オブジェクトを一組にし、R2 と別の保存先に保管する。

```bash
uv run python -m ingestion.inputs backup --lock pipeline/ingestion/fiscal/sources.lock.json --output /保存先/fixed-inputs.zip
uv run python -m ingestion.inputs restore-backup --lock pipeline/ingestion/fiscal/sources.lock.json --archive /保存先/fixed-inputs.zip
```

復元は入力一覧の一致、全オブジェクトの個別ハッシュとサイズ、欠落・余分なファイルを検査する。原典 URL から別版を補わない。定期バックアップと空のキャッシュからの復元検証は移行記録に残す。

## ローカル検証と公開アプリ

`bun run dev` の view は 127.0.0.1:5174 のみで動かす。`bun run pdf:layer` は固定済み PDF から頁画像・文字層・行対応を `.cache/pdf/` に作る。最新の PDF を再取得せず、build / publish の前提にしない。

公開 web は 5173、API は 8787、download は 8788。`FUDOKI_API_PORT` で API のポートを変更できる。`dev:setup` は API を停止した状態で、`build/candidate.sqlite` を自分の Wrangler ローカル D1 にコピーする。公開画面は報告や原典を読まない。公開 web と view の UI は独立している。

`bun run dev:setup:download` は完成済み候補を検査してからローカル R2 に配布ファイルと最終 manifest を入れる。続いて `bun run dev:download` で配布 URL を確認できる。遠隔 R2 への転送は行わない。

fixture は `verify/fixture.ts` にある架空団体の501行で、境界をまたぐ取込・照合・再実行・切り戻しを検査する。自治体の原典を含まない。`bun run test` はこの fixture と単体検査を実行し、全量 dbt build は別に実行する。
