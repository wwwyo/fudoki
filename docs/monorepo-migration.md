# monorepo 移行の検証記録

2026-10-01。設計 PR [#38](https://github.com/wwwyo/fudoki/pull/38) はマージ済み。実装の完了をこの記録の途中結果だけから判断しない。

## 確認できたこと

- ingestion・dbt・FDP・報告・ローカル検証画面を `pipeline/`、共有する純粋なデータ規則を `packages/`、slides を root に移した。
- 全36入力の33種類の原典 CSV/PDF を回収し、既存の証跡の SHA-256 と一致した。取り込み済みの表・証跡を別の内容アドレスとして保存し、固定入力のローカル復元で build した。原典の欠落は0。
- 全量 dbt build の156項目（85検査とモデル・seed の構築）が通過し、5団体・32配布 CSV を生成した。配布数値・出典・分類判断と元の配布物の比較を実施した。ID と dataset/document/edition の列は新契約に変更した。
- D1 取込用の8表は合計732,065行。SQLite の保存形式・外部キー・整数精度の検査に成功した。実際の release ID を使った DB は423,673,856 bytes、3版の単純推計は1,271,021,568 bytes。Cloudflare の保存容量・性能の実測値ではない。
- 公開 web の実ブラウザで狛江市の2023決算の集計と明細を確認した。公開 Worker のローカル D1 へ全量を入れて利用した。
- publish の転送失敗、D1 照合失敗、API の金額不一致、atomic な切り替え失敗、再実行、切り戻し、期限切れ処理を fixture で検査した。候補を完成前に API の公開参照へ切り替えない。
- 実際の Cloudflare D1 を APAC・read replication 無効で作成し、schema を適用した。REST batch が制約違反で失敗したとき、前の書込も残らないことを確認した。全量の遠隔取込は未実施。

- 固定入力のバックアップから空の別キャッシュへ全オブジェクトを復元し、33種類の原典のハッシュを照合した。PDF のローカル文字層・行対応を原典ハッシュに固定して生成した（千代田区1,235行）。

- バックアップから復元した固定入力で再 build し、完成済み候補の manifest が完全一致した。macOS のネットワーク拒否 sandbox 内でも全量 build と再 build が成功した。
- ローカル download Worker から配布38ファイルを GET し、内容の SHA-256・サイズ・ETag が一致した。
- download の版一覧は公開用 manifest のある版だけを列挙し、D1 を使わず次ページと個別 manifest へ辿れる。未完成の版だけのページ、入力不正、ストレージ障害を検査した。全量 CI に同一コード・固定入力の再 build と manifest 一致検査を追加した。
- TypeScript の92テスト・各 workspace の型検査・Python の11テスト・公開アプリの依存境界検査が通過した。API のコードを誤って除外する ignore を修正し、公開 web の component 検査も CI の実行対象に含めた。修正後の GitHub の新規 checkout の fixture・コード CI も成功した。
- ローカル download Worker の manifest と配布38ファイルを比較元として取得し、内容ハッシュを確認したうえで全46範囲の金額・ID・分類・注意点・出典に変更がないことを確認した。相殺される金額変更、版変更による ID の交代、出典・分類変更、壊れた比較元を Python の3検査で区別した。全量 CI は比較元を取得してから通信を禁止して build する。
- publish の検証結果を非公開 R2 に保存し、GET の内容を確認してから公開切替する処理を追加した。fixture では保存済み記録のハッシュ・download の非公開境界を確認し、記録の内容が壊れた場合は旧公開版が維持されること、再実行で復旧できることを検査した。
- ローカル view の実画面で、狛江市2023決算の原典 CSV と取り込み済みの表の行2が同時に選択されることを確認した。千代田区2026予算では、表の行4から PDF 45頁の該当行へ移動し、PDF の行5の文字から表の行5を選択できた。画面の repo 案内も新配置・R2/D1 の役割に更新した。

## Cloudflare CLI への移行

公開 API・download・docs・web の配信と非公開検証 Worker を `cloudflare.config.ts` / `cf` に移行し、旧 `wrangler.jsonc` を削除した。全5 Worker の `cf deploy --dry-run`、各 workspace の型検査、92個の Bun 検査を実施した。Web は Vite で画面を build し、`apps/web/deploy/` で静的配信用の Build Output を作る。

`cf dev` の API と download をループバックで起動し、狛江市2023決算の retained / executed を 2,217行・48,685,415,877円と照合した。download の38ファイルは全てハッシュ・サイズが一致した。ローカル D1 の投入、KV のキー発行・失効も確認した。ビルダーの既定保存先 `.wrangler/state/v3/` を共有し、ローカル投入と RPC に使う一時 JSON は cf の宣言から生成する。

新規依存の追加には cooldown 7日を指定した。公式設定ライブラリ 0.17.0・ビルダー 4.137.0 は exact pin、既存の mise CLI 1.0.0-beta.6 は維持した。現在の CLI でローカル D1 query が未対応、ローカル KV/R2 コマンドが書込後に終了しないことを確認したため、その操作だけはビルダーの proxy ライブラリを使う。CLI での本番配備・遠隔 RPC 接続は、下記の公開前検証で実施する。

## 未完了の移行条件

- R2 の有効化。CLI は現在「Please enable R2 through the Cloudflare Dashboard」（HTTP403 / 10042）を返す。cf の account subscription 作成・更新 API は存在するが、R2 の契約 ID と有効化の可否は未確認であり、Dashboard 専用とは断定しない。
- Workers Paid の確認。全量を Free の日次書込上限内で一度に取り込むことはできず、3版は Free の単一 DB 容量にも収まらない。
- 原典・取り込み・証跡の全量 R2 転送、GET での内容ハッシュ照合、空のキャッシュからの復元と再構築。現在の入力一覧は `.cache/migration/sources.lock.json` にあり、遠隔保管を検証するまでは正規の Git 入力一覧として固定していない。
- download / API / 非公開検証 Worker が同じ契約を持つ候補環境での全量 publish、D1 の読取行数・問い合わせ時間・複数版の保持容量の測定。
- 上記を確認してから既存 `data/` の tracking を外す。既存 Git 履歴を書き換えない。

全量 build は移行キャッシュから実行しており、新規 checkout と R2 のみでの再現はまだ検証していない。fixture の CI は全量検証の代用ではない。
