-- 三鷹市 歳出。原典と1対1。
-- **列名の付け替えと型付けだけ。** 判断（分類・名寄せ・推定）はここに書かない。
-- 行を増減させてもいけない（1対1は tests/staging_is_one_to_one.sql が縛る）。
--
-- 中身は `dbt_project.yml` の vars が宣言し、macros/budget_staging.sql が組み立てる。
-- 団体ごとに同じ SQL を写経すると片方だけ直る（検査が5箇所で階層を手書きしていたのと同じ形）。
{{ budget_staging('132047', 'expenditure') }}
