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

- バックアップから復元した固定入力で再 build し、完成済み候補の manifest が完全一致した。
- ローカル download Worker から配布38ファイルを GET し、内容の SHA-256・サイズ・ETag が一致した。
- TypeScript の89テスト・各 workspace の型検査・Python の8テスト・公開アプリの依存境界検査が通過した。

## 未完了の移行条件

- R2 の有効化。CLI は現在「Please enable R2 through the Cloudflare Dashboard」（HTTP403 / 10042）を返す。
- Workers Paid の確認。全量を Free の日次書込上限内で一度に取り込むことはできず、3版は Free の単一 DB 容量にも収まらない。
- 原典・取り込み・証跡の全量 R2 転送、GET での内容ハッシュ照合、空のキャッシュからの復元と再構築。現在の入力一覧は `.cache/migration/sources.lock.json` にあり、遠隔保管を検証するまでは正規の Git 入力一覧として固定していない。
- download / API / 非公開検証 Worker が同じ契約を持つ候補環境での全量 publish、D1 の読取行数・問い合わせ時間・複数版の保持容量の測定。
- CSV 団体と PDF 団体のローカル検証画面で原典・行対応の操作を追加確認する。
- 上記を確認してから既存 `data/` の tracking を外す。既存 Git 履歴を書き換えない。

全量 build は移行キャッシュから実行しており、新規 checkout と R2 のみでの再現はまだ検証していない。fixture の CI は全量検証の代用ではない。
