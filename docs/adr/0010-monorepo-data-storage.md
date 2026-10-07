# 0010: データ構築とローカル検証を pipeline に集める

- 日付: 2026-10-01（2026-10-03 に配布・検索のインフラ設計を後段へ戻す）
- 状態: Accepted（ingestion〜marts とローカル検証の配置）

取得・変換・ローカル検証を `pipeline/` に集める。文書領域を fiscal とし、予算・決算・補正の文書種別と金額の意味を区別する。純粋な型・名称・団体マスタは `packages/` に置き、公開 web とローカル view の UI は共有しない。

Git はコード・宣言・判断・採用した入力一覧と個別ハッシュを保持する。原典 CSV/PDF と取り込み Parquet は非公開 R2 に保管し、採用した証跡は [ADR 0012](0012-git-input-provenance.md) に従って Git 管理する。固定入力を復元して、原典の再取得なしに dbt の変換と検査を実行する。

先に ingestion → staging → intermediate → marts を完成させる。配布・検索の保存先と公開・反映の方式は後段で検討する。

詳細は [全体設計](../prd/monorepo/design-doc.md)、[実行手順](../../pipeline/README.md)。
