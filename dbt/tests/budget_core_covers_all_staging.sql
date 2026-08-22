-- **staging に登録した団体が core に届いているか。**
--
-- core は団体ごとの staging を union して作る。2団体目の staging を足しても
-- union を直し忘れると**エラーにならず、派生から黙って落ちる**。
-- 検査が通ったまま配布物だけ欠ける状態は、母集団の誤りと同じで後段では救えない。
--
-- 歳出（core_budget_cofog）と歳入（core_revenue_consolidation）の両方を見る。
-- 片方だけだと、歳入の union を直し忘れたときに通ってしまう。
--
-- 団体の一覧は dbt_project.yml の `budget_levels` から取る。
-- ⚠️ `graph.nodes` から数える書き方は採らない — パース時に ref() を解決できず、
-- 完全再パースになった時点で落ちる（部分パースの間だけ通っていた）。
{% set codes = var('budget_levels').keys() | list | sort %}

with staged as (
    {% for code in codes %}{% for direction in var('budget_levels')[code].keys() %}
    select '{{ direction }}' as direction, count(*) as rows
    from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
    union all
    {% endfor %}{% endfor %}
    select null, null where false
),

staged_total as (
    select direction, count(*) as models, sum(rows) as rows from staged group by 1
),

in_core as (
    select 'expenditure' as direction, count(*) as rows from {{ ref('core_budget_cofog') }}
    union all
    select 'revenue', count(*) from {{ ref('core_revenue_consolidation') }}
)

select
    coalesce(s.direction, c.direction) as direction,
    s.models as staging_models, s.rows as staging_rows, c.rows as core_rows
from staged_total as s
full outer join in_core as c using (direction)
where coalesce(s.rows, -1) is distinct from coalesce(c.rows, -2)
