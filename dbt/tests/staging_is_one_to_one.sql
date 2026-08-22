-- **staging が原典と1対1であることの検査。**
--
-- 境界はディレクトリ名では守れない。以前 Load を「中間表現へ」と宣言しながら
-- FDP の正規化まで実装していたのは、宣言が守られているかを誰も検査していなかったから。
--
-- これが落ちたら staging に判断が混ざった合図で、intermediate 層を切る時期。
with raw_counts as (
    select direction, count(*) as n
    from read_parquet('../data/budget/raw/jurisdiction=132047/year=*/phase=*/direction=*/data.parquet', hive_partitioning=true)
    group by direction
),
staged as (
    select 'expenditure' as direction, count(*) as n from {{ ref('stg_132047__expenditure') }}
    union all
    select 'revenue', count(*) from {{ ref('stg_132047__revenue') }}
)
select r.direction, r.n as raw_rows, s.n as staged_rows
from raw_counts r
join staged s using (direction)
where r.n <> s.n
