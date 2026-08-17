# raw データの git 保存形式

自治体の原典（raw）データを git 管理下に置く場合、**単一の DuckDB ファイルを commit しない**。

- 単一ファイル（例 `data/raw.duckdb`）は1つの塊なので、どこか1団体を再取得するたびにファイル全体が書き換わり、更新のたびにファイルサイズ分の新しい blob が git 履歴に積まれる。diff も効かない
- 団体・年度単位でパーティション分割した Parquet（例 `data/raw/<団体コード>/<年度>/expenditure.parquet`）なら、変更のない団体のファイルはバイト単位で同一のため再 commit されず、履歴が肥大化しない
- 実測（三鷹市 令和6年度 歳出 5,613行）: CSV 816KB → Parquet(zstd) 71KB（1/11.4）、DuckDB ファイル 524KB（1/1.6）。62団体×9年へ外挿すると Parquet で約40MB、DuckDB 単一ファイルなら約300MB
- dbt-duckdb は Parquet を source として直接読めるので、DuckDB ファイル自体は実行時の一時生成物（gitignore）にできる。commit するのは Parquet 側

**How to apply**: raw データを保存する仕組みを作る／変える前に、パーティション単位（団体×年度）で分割できているか確認する。単一バイナリファイルを版管理に置く設計が出てきたら、この履歴肥大化の問題を指摘する。
