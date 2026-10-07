# 財政データのAPIの設計を再開する条件

現在はingestion〜martsの完成を優先する。この機能の保存先・公開方式・URL・応答契約は未決定である。旧D1・配布版・API・toolの設計は採用しない。

公開WorkerはHTTP 500と`Cache-Control: no-store`を返す。[PRD](prd.md) の再開条件を満たしてから、完成した提供用データに基づいて設計する。現在のパイプラインは [財政データの設計](../fiscal-records/design-doc.md) と `docs/adr/` の各決定に従う。
