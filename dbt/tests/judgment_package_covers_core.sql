-- **core の判断が配布物へ全部届いているか。**
--
-- 判断の配布物は core から作る。2団体目を core へ足しても
-- package モデルを足し忘れると、**エラーにならず配布物から消える**。
-- core を守る検査（budget_core_covers_all_staging）は staging→core しか見ていない。
{#- read_csv は dbt に依存として見えないので、配布物を書くモデルを依存として宣言する -#}
{% for code in var('budget_levels').keys() | list | sort %}
-- depends_on: {{ ref('pkg_' ~ code ~ '__cofog') }}
{% endfor %}

with in_core as (
    select budget_line_id from {{ ref('core_budget_cofog') }}
    union all
    select budget_line_id from {{ ref('core_revenue_consolidation') }}
),

-- ⚠️ **団体ごとの配布物を全部束ねて見る。** 判断の配布物は自治体パッケージへ移したので、
-- 1ファイルを読むのでは足りない。glob ではなく宣言から回すのは、
-- 取りこぼした団体が「ファイルが無い」ではなく「行が足りない」として出るようにするため。
in_package as (
    {% for code in var('budget_levels').keys() | list | sort %}
    select budget_line_id
    from read_csv('../data/budget/datapackages/{{ code }}/cofog.csv', header = true, all_varchar = true)
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select 'core にあって配布物に無い' as problem, count(*) as n
from (select budget_line_id from in_core except select budget_line_id from in_package)
having count(*) > 0

union all

select '配布物にあって core に無い', count(*)
from (select budget_line_id from in_package except select budget_line_id from in_core)
having count(*) > 0

union all

select 'core が空', count(*) from in_core having count(*) = 0
