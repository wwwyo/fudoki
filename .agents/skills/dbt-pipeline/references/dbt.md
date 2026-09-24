# dbt build / seed のハマりどころ

- `data/fudoki.duckdb` は「実行時に組む一時ファイル」と説明されているが、dbt はこれを毎回作り直さない。seed（`dbt/seeds/budget/cofog_rules.csv` 等）の列を増減・変更したのに `dbt build` の seed ステップが列数不一致で落ちるときは、warehouse 側に旧スキーマのテーブルが残っているのが原因であることが多い。`data/fudoki.duckdb` を削除して作り直すと直る。
  - Why: dbt seed は対象テーブルを毎回 CREATE OR REPLACE しない場面があり、duckdb ファイルを使い捨てだと思って残したままにすると古いスキーマが生き残る。
  - How to apply: seed の列構成を変えた回だけでよい。通常の `dbt build` 失敗の第一容疑者にはしない（まず実際のエラーメッセージ・列名を見る）。
