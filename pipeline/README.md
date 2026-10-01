# データ構築

原典・取り込み済みの表は非公開 R2、宣言・判断・採用した入力一覧と証跡は Git が保持する。DuckDB と D1 は再生成できる表であり、入力の正本ではない。配布物は団体別の内容版に固定して R2 から提供する。採用する収録範囲と配布先は Git の `publish/manifest.json` 一つにまとめ、過去の一覧は Git 履歴で辿る。

## 固定入力からの build

```bash
mise install
bun install --frozen-lockfile
uv sync --frozen
bun run pipeline:inputs
bun run pipeline:build
bun run dev
```

`pipeline:inputs` は schema 2 の `ingestion/fiscal/sources.lock.json` が指定する個別キー・SHA-256・サイズを検査し、`.cache/inputs/<入力一覧のハッシュ>/raw/` に表と証跡を復元する。表は R2、証跡は lock と同じディレクトリの `provenance/<論理入力パス>/provenance.json` から読む。原典は `.cache/objects/inputs/origin/sha256/<hash>` に保存する。入力欠落・異なるハッシュ・文書版と証跡の不一致は失敗とする。Git の証跡が無い場合に R2 で補わない。build は自治体サイトにも Cloudflare にも接続しない。

`build.ts` は dbt build、FDP descriptor、Git manifest、内部の検査記録の生成・検査を順に実行する。配布 CSV と D1 取込表の数値・識別子・分類は dbt の marts が確定する。完成した候補は `build/releases/r-<hash>/`。manifest とファイルを照合する `complete.json` がある候補だけを publish できる。完成済み候補は書き換えない。候補の `manifest.json` を `publish/manifest.json` に反映し、D1 の照合情報は候補の `verification.json` に分ける。

`build/latest.json` はローカルで最後に検査した候補の参照であり、公開版の指定ではない。warehouse・dbt の manifest/検査結果・ローカル報告も `build/` に入る。Git 管理しない。

`bun run pipeline:build --rebuild` は同じコード・固定入力を別の作業場所で再構築し、完成済み候補の manifest と一致することを検査する。`build/warehouse.json` が現在の warehouse と候補の対応を記録し、報告の取り違えを防ぐ。DuckDB が参照する再構築用ファイルも `build/` に残す。

## 新しい原典の取得

`bun run pipeline` は原典の再取得 → 非公開 R2 への保管 → 抽出 → 表の保管・GET によるハッシュ照合 → Git の証跡と入力一覧の更新 → build → 報告を実行する。公開版は変更しない。

再取得は HTTP キャッシュを使わず、実際のバイト列を比較する。原典が同じなら同じ内容アドレスを使い、異なれば別の原典版として保存する。原典を保存できなければ抽出を開始しない。原典・表は別オブジェクトであり、異なる内容で既存のハッシュキーを上書きしない。抽出や遠隔照合の失敗で Git の採用証跡・`sources.lock.json` を更新しない。作業ツリーの証跡は採用した入力だけとし、過去の採用版は Git 履歴で辿る。全取得履歴を残す場合は別途 R2 に保存する。

既存の証跡は取得時点の記録であり、旧パスや当時の保存方針の記述も保持する。現在の保存方式は [ADR 0012](../docs/adr/0012-git-input-provenance.md) を参照する。移行用の lock と証跡は `.cache/migration/` に用意し、原典・表の遠隔保管を照合してから正規 lock を固定する。

文書種別は budget / supplementary / settlement、金額段階は approved / adjusted / adjusted-before-transfer / executed。決算書にある予算現額と決算額を区別する。dataset は団体・年度・歳入歳出・文書種別・原典版を含み、明細 ID は dataset を含めて一意にする。

D1 の `jurisdictions` は団体コードを主キーとする共通マスタで、公開版に依存しない。`release_jurisdictions` は公開版ごとの注意点と名称・OCD ID の記録を持つ。build はそれぞれの JSONL を生成し、publish は共通マスタを更新してから7表の公開版別データを検査・転送する。候補が失敗しても、API は公開中の版の記録を読むため名称は変わらない。

COFOG のコード・名称・階層は `packages/fiscal/detail.ts` が正本。現在使用するコードと祖先37件を `cofog_codes` 共通マスタへ生成し、明細の `cofog_code` から外部キー参照する。状態・規則・根拠・連結の判断は明細に保持する。D1 の1対1の `cofog` 表は作らない。割当を dbt で一度決め、配布 CSV と D1 の全明細の分類・連結判断が一致することを検査する。R2/D1 は直接編集しない。

## 全体の release と団体別の配布物

Git manifest は採用する収録一覧とコード・入力・判断の対応、`packageId` は団体別の配布内容を識別する。未変更の配布物は同じ R2 キーを参照し、publish は既存の内容を照合して転送を省く。

```text
fiscal/<団体コード>/p-<64桁のhash>/
  datapackage.json
  expenditure.csv
  ...
Git: pipeline/publish/manifest.json
  # 団体・年度・文書・出典・注意点・packages・files[].objectKey
ローカル: build/releases/r-<内部構築ID>/verification.json
  # D1 全行照合のための chunk hash・件数・合計
```

団体別 FDP は収録する全年度を含み、CSV の `dataset_id` で年度・文書・原典版を区別する。一年度の更新でもその団体の配布物全体が新しい版になり、他の団体の配布物は再利用する。D1 の派生表は構築 ID で候補と公開中の表を区別する。R2 の release ディレクトリと catalog は廃止し、Git に最新の manifest 一つを置く。[ADR 0014](../docs/adr/0014-git-distribution-manifest.md) を参照。[ADR 0013](../docs/adr/0013-jurisdiction-package-versions.md) を参照。

補正予算の複数原典は別 dataset として識別できるが、現行の取得対象には補正予算を含めていない。第1号・第2号等の号数、差額なのか補正後総額なのか、有効な時点を取得元の宣言で定めてから追加する。同じ年度の当初・補正・決算を自動で足さず、API の集計は同じ団体・年度・歳入歳出から複数 dataset を選んだ場合に拒否する。

## publish と切り戻し

Cloudflare の操作には mise 管理の `cf` と既存の認証を使う。 Worker の宣言は各 `cloudflare.config.ts`、ビルダーの設定は `wrangler.config.ts`。公開 web は Vite のビルド後に `apps/web/deploy/` の静的 Worker を `cf` で構築・配備する。生成される Build Output は各 `.cloudflare/output/v0/` に入り、Git 管理しない。先に非公開 `fudoki-inputs` と配布用 `fudoki-releases` を用意する。公開 bucket には配布物だけを置き、manifest・候補記録・検証結果を入れない。直接配信への接続は移行条件の検証後に設定する。入力 bucket の公開 URL と自動削除 lifecycle は設定しない。入力 bucket は公開 Worker に bind しない。

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

publish は clean な commit・正規の入力一覧・そのコードで作った完成済み候補・commit 内の Git manifest と候補の一致を要求する。生成 manifest だけの commit は構築版を変えない。コードと固定入力の変更を commit → build → 採用 manifest を commit → publish の順に行う。転送・取込を再生成と混ぜない。ファイルは内容ハッシュで照合し、D1 は最大500行の主キー順ページごとに全内容を照合する。同じ行がある場合も照合を省略しない。

検証 Worker は公開 route / workers.dev / preview URL を持たず、認証された Cloudflare service binding の RPC だけを使う。公開 API と同じ SQL・契約コードで候補を検査する。Node の Wrangler proxy は publish の間だけ起動し、終了時に閉じる。秘密を出力しない。

manifest を R2 に転送しない。非公開検証 Worker の RPC セッションに候補の検査情報を渡し、D1 の登録済みハッシュと照合する。全ファイル・D1 の全行・公開 API の契約と金額・公開 URL の内容を確かめた結果を候補の `publication-verification.json` に保存する。最後に D1 の一括更新で公開状態と `active_release` を切り替え、Git commit に固定した manifest URL を記録する。検査や切替の失敗では API は旧版を返す。R2 の転送済み配布物は取得できる。

API の `listFiles` は公開中の Git manifest の URL と R2 の団体別配布 URL を返す。Git の最新 manifest が公開前の候補であることもあるため、Git の commit を公開成功の証拠にしない。download の `/releases` と R2 の版一覧は廃止した。

publish と rollback は同じ lease・fence・公開世代を使い、期限切れの処理による上書きを拒否する。rollback は保持中の D1 とローカルの同じ構築候補を使い、ファイル・D1 の全行・API の件数と金額・Worker 契約を再検査する。ローカル候補を消した場合は過去の Git と固定入力から再構築する。API の cursor は保持中の公開 release と問い合わせに固定され、公開切り替えで次ページの版が変わらない。

## 保持・容量・バックアップ

公開中と処理中の候補を保持する。`publish/control.ts` の `protectedReleases` は active と処理中候補を返す。最低3版の保持要件は廃止した。旧 D1 はページングと切り戻しの猶予として扱い、保持期間と削除手順は運用開始前に決める。自動 cleanup はまだ導入していない。共有配布物は保持中の全 release と処理中候補からの参照が無くなってから削除する。release の削除だけを理由に団体別配布物を削除しない。入力と証跡を配布物の削除に連動させない。

現行全量の D1 用 SQLite は約424 MB、3版の単純推計は約1.27 GB。Free の単一 DB の容量と日次書込上限では全量運用できないため、Workers Paid と候補環境の容量・読取行数・性能の検証が必要。SQLite の計測を D1 の実測として扱わない。[D1 制限](https://developers.cloudflare.com/d1/platform/limits/)、[料金](https://developers.cloudflare.com/d1/platform/pricing/)。

バックアップには Git の入力一覧と、それが参照する全オブジェクトを一組にし、R2 と別の保存先に保管する。

```bash
uv run python -m ingestion.inputs backup --lock pipeline/ingestion/fiscal/sources.lock.json --output /保存先/fixed-inputs.zip
uv run python -m ingestion.inputs restore-backup --lock pipeline/ingestion/fiscal/sources.lock.json --archive /保存先/fixed-inputs.zip
```

復元は入力一覧の一致、全オブジェクトの個別ハッシュとサイズ、欠落・余分なファイルを検査する。原典 URL から別版を補わない。定期バックアップと空のキャッシュからの復元検証は移行記録に残す。

## ローカル検証と公開アプリ

`bun run dev` の view は 127.0.0.1:5174 のみで動かす。`bun run pdf:layer` は固定済み PDF から頁画像・文字層・行対応を `.cache/pdf/` に作る。最新の PDF を再取得せず、build / publish の前提にしない。

公開 web は 5173、API は 8787、download は 8788。`FUDOKI_API_PORT` で API のポートを変更できる。`dev:setup` は API を停止した状態で、`build/candidate.sqlite` を自分の開発 Worker のローカル D1 にコピーする。公開画面は報告や原典を読まない。公開 web と view の UI は独立している。

`bun run dev:setup:download` は完成済み候補を検査してからローカル R2 に団体別配布ファイルだけを入れる。続いて `bun run dev:download` で配布 URL を確認できる。遠隔 R2 への転送は行わない。

fixture は `verify/fixture.ts` にある架空団体の501行で、境界をまたぐ取込・照合・再実行・切り戻しを検査する。自治体の原典を含まない。`bun run test` はこの fixture と単体検査を実行し、全量 dbt build は別に実行する。

## 公開版との内容の変更を確認する

全量 CI は R2 の固定入力を復元し、Git commit に固定した比較元の manifest と R2 の配布ファイルを取得して内容ハッシュを照合する。その後はネットワーク namespace を分離して、全量 build・再 build・報告を生成する。PR の CI は publish を実行しない。

GitHub の `FUDOKI_REVIEW_BASELINE_URL` に比較元の Git commit に固定した raw manifest URL を指定する。初回公開だけは URL を空にして `FUDOKI_REVIEW_INITIAL_RELEASE=true` を明示する。比較元の取得失敗や改変を初回公開として扱わない。公開切替後は比較元 URL を D1 に記録した公開中の Git manifest URL へ更新する。`FUDOKI_DOWNLOAD_BASE_URL` は配布ファイルの origin で、既定は `https://download.fudoki.dev`。

`bun run pipeline/verify/summary.ts --prepare-baseline` が比較元を `.cache/review/` に固定し、`bun run pipeline/verify/summary.ts` が `build/review-summary.json` と Markdown を生成する。ローカルの完成済み候補との比較には `--baseline <候補ディレクトリ>` を使える。

変更報告は団体・年度・歳入歳出・文書・段階ごとの行数と円金額、追加・削除された明細 ID、金額変更、分類変更の行数と変更前後の金額を含む。原典の版が変わって ID が交代した場合、同じ明細との対応を推定せず追加・削除として示す。注意点・原典・出典・利用条件・名称・分類規則等の変更前後の内容も JSON に記録し、CI の artifact と概要から確認できる。

publish の公開前検証結果はローカルの `publication-verification.json` に記録し、書込内容の一致を確認してから公開を切り替える。これは Git や R2 の公開一覧には含めない。再実行で更新する検査記録は公開成功の履歴とは区別し、現在公開中の構築版は D1 で確認する。

## Cloudflare CLI とローカル保存

操作の入口は mise で固定した `cf`。プロジェクト依存には CLI を重複導入せず、`cloudflare.config.ts` が公式の `@cloudflare/config/public` を読み込む。設定ライブラリ 0.17.0 とビルダー 4.137.0 は cooldown 7 日を満たす版に exact pin した。CLI は既に導入済みの 1.0.0-beta.6 を維持している。

この構成の `cf` は内部で Wrangler ビルダーを使う。旧 `wrangler.jsonc` は廃止した。ローカルデータはビルダーの既定で各アプリの `.wrangler/state/v3/` に保存され、Git 管理しない。名前を変えるために別の保存先を作らない。

現在の cf CLI のローカル D1 query は未対応で、ローカル KV/R2 の操作では書込後にプロセスが終了しないため、ローカル投入と publish の RPC 接続にはビルダーの proxy ライブラリを使う。Worker と binding の名前・ID は `cloudflare.config.ts` から読み、一時 JSON は終了時に削除する。運用する遠隔 D1/R2/KV と Worker の dev/build/deploy は cf を使う。API のキー発行・失効も、remote を指定したときだけ cf による遠隔 KV 操作を行う。

団体別配布物の各 CSV の用途と、複数年度・補正予算の区別は [設計書のファイル説明](../docs/design-doc-monorepo.md#団体別配布物のファイルと使い方) を参照する。補正予算の実資料の取得と資料別の科目対応は未実装である。
