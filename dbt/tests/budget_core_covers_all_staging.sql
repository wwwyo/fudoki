-- **staging に登録した団体が core に届いているか。**
--
-- core は団体ごとの staging を明示的に参照する。2団体目の staging を足しても
-- core を直し忘れると**エラーにならず、派生から黙って落ちる**。
-- 検査が通ったまま配布物だけ欠ける状態は、母集団の誤りと同じで後段では救えない。
--
-- 団体の一覧は dbt_project.yml の `budget_levels` から取る。
-- ⚠️ `graph.nodes` から数える書き方は採らない — パース時に ref() を解決できず、
-- 完全再パースになった時点で落ちる（部分パースの間だけ通っていた）。
{% set codes = var('budget_levels').keys() | list %}

with staged as (
    {% for code in codes %}
    select count(*) as rows from {{ ref('stg_' ~ code ~ '__expenditure') }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

staged_total as (
    select {{ codes | length }} as models, sum(rows) as rows from staged
),

in_core as (
    select count(*) as rows from {{ ref('core_budget_cofog') }}
)

select s.models as staging_models, s.rows as staging_rows, c.rows as core_rows
from staged_total as s
cross join in_core as c
where s.rows <> c.rows
