# raw データの git 保存形式

自治体の原典（raw）データを git 管理下に置く場合、**単一の DuckDB ファイルを commit しない**。

- 単一ファイル（例 `data/raw.duckdb`）は1つの塊なので、どこか1団体を再取得するたびにファイル全体が書き換わり、更新のたびにファイルサイズ分の新しい blob が git 履歴に積まれる。diff も効かない
- 団体・年度単位でパーティション分割した Parquet（例 `data/raw/<団体コード>/<年度>/expenditure.parquet`）なら、変更のない団体のファイルはバイト単位で同一のため再 commit されず、履歴が肥大化しない
- 実測（三鷹市 令和6年度 歳出 5,613行）: CSV 816KB → Parquet(zstd) 71KB（1/11.4）、DuckDB ファイル 524KB（1/1.6）。62団体×9年へ外挿すると Parquet で約40MB、DuckDB 単一ファイルなら約300MB
- dbt-duckdb は Parquet を source として直接読めるので、DuckDB ファイル自体は実行時の一時生成物（gitignore）にできる。commit するのは Parquet 側
- パーティションの粒度は「取得の単位（団体コード, 年度, direction）」に合わせる。これより細かく切っても速くならず、これより粗いと部分再取得のたびに無関係な団体まで巻き込んで書き換わる。団体ごとに列構成（事項の有無など）が違うため、そもそも1つのテーブルとして扱えず、ソースごとに別ファイルにするのが正直な形
- Hive 形式のパス（例 `data/raw/jurisdiction=132047/year=2024/direction=expenditure/data.parquet`）にしておくと、DuckDB は `read_parquet('data/raw/**/*.parquet', hive_partitioning=true, union_by_name=true)` で団体間のスキーマ差（列の有無）を吸収しながら一括で読める

**How to apply**: raw データを保存する仕組みを作る／変える前に、パーティション単位（団体×年度×direction）で分割できているか確認する。単一バイナリファイルを版管理に置く設計が出てきたら、この履歴肥大化の問題を指摘する。横断クエリを書くときは `union_by_name=true` を忘れず、団体間の列差でエラーにならないようにする。
