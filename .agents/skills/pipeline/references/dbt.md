# dbt build / seed のハマりどころ

- `pipeline/build/warehouse.duckdb` は再生成できる実行用の表。`bun run pipeline:build` は再構築時に warehouse を作り直すが、dbt を直接実行すると毎回作り直すわけではない。seed（`pipeline/dbt/seeds/fiscal/cofog_rules.csv` 等）の列を増減・変更したのに seed ステップが列数不一致で落ちるときは、warehouse 側に旧スキーマのテーブルが残っている可能性がある。直接 dbt を実行する場合は warehouse を作り直す。
  - Why: dbt seed は対象テーブルを毎回 CREATE OR REPLACE しない場面があり、duckdb ファイルを使い捨てだと思って残したままにすると古いスキーマが生き残る。
  - How to apply: seed の列構成を変えた回だけでよい。通常の `dbt build` 失敗の第一容疑者にはしない（まず実際のエラーメッセージ・列名を見る）。
