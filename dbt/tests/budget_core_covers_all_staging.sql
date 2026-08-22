-- **staging に登録した団体が core に届いているか。**
--
-- core は団体ごとの staging を明示的に参照する。2団体目の staging を足しても
-- core を直し忘れると**エラーにならず、派生から黙って落ちる**。
-- 検査が通ったまま配布物だけ欠ける状態は、母集団の誤りと同じで後段では救えない。
--
-- graph からモデルを数えるので、団体を足せば自動でこの検査の対象になる。
{% set staged = [] %}
{% for node in graph.nodes.values() %}
  {% if node.resource_type == 'model' and 'staging/budget' in node.path and 'expenditure' in node.name %}
    {% do staged.append(node.name) %}
  {% endif %}
{% endfor %}

with staged_total as (
    select {{ staged | length }} as models,
           {% for m in staged %}(select count(*) from {{ ref(m) }}){% if not loop.last %} + {% endif %}{% endfor %} as rows
),
in_core as (
    select count(*) as rows from {{ ref('core_budget_cofog') }}
)
select s.models as staging_models, s.rows as staging_rows, c.rows as core_rows
from staged_total s cross join in_core c
where s.rows <> c.rows
