---
status: accepted
---

# 明細の版を自治体ごとに持ち、公開一覧は参照だけを固定する

D1 の全体構築版に全明細を複製する構造を廃止し、自治体別の内容版と、その組合せを固定した小さな公開一覧を分ける。R2 の `packageId` は配布ファイルの内容版として維持し、API 用の内容だけが変わる場合は D1 の自治体データ版だけを追加する。未変更の団体のデータを再利用しながら、横断検索・ページ取得・切り戻しの参照を固定するためである。

## Consequences

- `releases`、`active_release`、`release_history`、`release_jurisdictions` を廃止する。団体別のデータ版、公開一覧と所属参照、公開参照を持つ `fiscal_publish_control` に役割を整理する。
- 公開参照は小さな一覧として全体単位で切り替えるが、データの生成・保存・保持は自治体単位とする。団体一つの切り戻しで他団体を巻き戻さない。
- 内容が同じ再構築では版を増やさず、コード・入力・検証結果の履歴は構築記録と Git から辿る。
- この決定は [ADR 0013](0013-jurisdiction-package-versions.md) の D1 全体版、[ADR 0014](0014-git-distribution-manifest.md) の内部構築 ID による公開切替、[ADR 0015](0015-jurisdiction-master.md) の `release_jurisdictions` の配置を置き換える。Git manifest 一つ、R2 の団体別固定キー、共通団体マスタという方針は維持する。
- 実装と検証は未完了である。テーブル境界、公開・削除条件、移行と検証項目は [再設計書](../design-doc-jurisdiction-versions.md) を正本とする。
