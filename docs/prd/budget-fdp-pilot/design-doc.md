# 原典から提供用CSVを作る

[PRD](prd.md) の現行実装は [財政データの設計](../fiscal-records/design-doc.md) と `docs/adr/` の各決定に従う。

原典・取り込み表は非公開R2、採用した入力一覧・証跡・宣言・判断はGitに保持する。stagingは原典行と1対1、intermediateは構造・円単位・分類を揃え、martsは歳出歳入・予算決算を分けた提供モデルと団体別CSVを確定する。COFOGは歳出の金額と同じCSVに保持し、任意のFDP整形は別処理にする。

実行手順は [pipeline/README](../../../pipeline/README.md)、固定入力での検査と再構築の結果は PR の QA 欄に残す。
