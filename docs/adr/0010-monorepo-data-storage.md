# 0010: データ構築を pipeline に集め、実体を R2/D1 に保管する

- 日付: 2026-10-01
- 状態: Accepted（遠隔移行は継続中）

構築処理が ingestion・dbt・FDP・report と公開 web に分散し、Git 管理する生成データが増えていた。API は多数の JSON アセットを選び、Worker 内で走査・ページングしていた。

構築・公開・ローカル検証は `pipeline/` に集める。文書領域を fiscal とし、予算・決算・補正の文書種別と金額段階を区別する。純粋な型・名称・団体マスタ・保存形式は `packages/`、公開 web/API/download は `apps/`、slides は root に置く。web と view の UI は共有しない。

Git はコード・宣言・判断・採用した入力一覧と個別ハッシュを保持する。原典 CSV/PDF・取り込み Parquet・証跡の実体は非公開 R2、配布 CSV/FDP/catalog/manifest は版ごとの R2、検索用の派生表は D1 に置く。API は SQL で問い合わせ、R2 の配布 URL だけを返す。download Worker は API と独立して完成済み manifest の allowlist を配信する。

build は固定入力から生成して検査するローカル処理、publish は既存の完成候補を転送・再照合して公開参照を切り替える処理とする。lease・fence・世代で publish/rollback の競合を防ぎ、R2 と D1 をまたぐ transaction があるとは扱わない。

移動だけなら API の chunk 管理と Git の生成データ増加は残る。R2 だけに移す案ではファイル検索方式も残る。D1 のみでは独立した一括配布を失う。R2＋D1 は双方を支える一方、同じ入力・判断からの内容一致、版保持、Cloudflare の容量と性能の検証が必要になる。

外部利用者がいないため旧 API 名・列・URL の互換 adapter は設けない。原典由来の金額・分類判断・出典と利用条件は変えず検証する。遠隔保管と再構築を確認するまで旧データは保管し、履歴の書き換えは別作業とする。

詳細: [全体設計](../design-doc-monorepo.md)、[実行手順](../../pipeline/README.md)、[移行記録](../monorepo-migration.md)。
