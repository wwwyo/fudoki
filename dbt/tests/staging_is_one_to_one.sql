-- **staging が原典と1対1であることの検査。**
--
-- 境界はディレクトリ名では守れない。以前 Load を「中間表現へ」と宣言しながら
-- FDP の正規化まで実装していたのは、宣言が守られているかを誰も検査していなかったから。
--
-- これが落ちたら staging に判断が混ざった合図で、intermediate 層を切る時期。
--
-- ⚠️ **宣言に無い raw はここでは見つからない**（宣言が母集団なので空振りする）。
-- そちらは declarations_cover_raw.sql が原典の partition と突き合わせる。
with raw_counts as (
    {% for code in var('budget_levels').keys() | list | sort %}
    select '{{ code }}' as jurisdiction, direction, count(*) as n
    from read_parquet('../data/budget/raw/jurisdiction={{ code }}/year=*/phase=*/direction=*/data.parquet',
                      hive_partitioning=true)
    group by 1, 2
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),
staged as (
    {% for code, direction in budget_units() %}
    select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, count(*) as n
    from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)
select
    coalesce(r.jurisdiction, s.jurisdiction) as jurisdiction,
    coalesce(r.direction, s.direction)       as direction,
    r.n as raw_rows, s.n as staged_rows
from raw_counts as r
full outer join staged as s using (jurisdiction, direction)
where coalesce(r.n, -1) is distinct from coalesce(s.n, -2)
