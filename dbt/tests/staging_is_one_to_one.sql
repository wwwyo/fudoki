-- **staging が原典と1対1であることの検査。**
--
-- 境界はディレクトリ名では守れない。以前 Load を「中間表現へ」と宣言しながら
-- FDP の正規化まで実装していたのは、宣言が守られているかを誰も検査していなかったから。
--
-- これが落ちたら staging に判断が混ざった合図で、intermediate 層を切る時期。
--
-- 団体の一覧は dbt_project.yml の `budget_levels` から取る。手で並べない。
{% set codes = var('budget_levels').keys() | list | sort %}
with raw_counts as (
    {% for code in codes %}
    select '{{ code }}' as jurisdiction, direction, count(*) as n
    from read_parquet('../data/budget/raw/jurisdiction={{ code }}/year=*/phase=*/direction=*/data.parquet',
                      hive_partitioning=true)
    group by 1, 2
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),
staged as (
    {% for code in codes %}{% for direction in var('budget_levels')[code].keys() %}
    select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, count(*) as n
    from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
    union all
    {% endfor %}{% endfor %}
    select null, null, null where false
)
select
    coalesce(r.jurisdiction, s.jurisdiction) as jurisdiction,
    coalesce(r.direction, s.direction)       as direction,
    r.n as raw_rows, s.n as staged_rows
from raw_counts as r
full outer join staged as s using (jurisdiction, direction)
where coalesce(r.n, -1) is distinct from coalesce(s.n, -2)
