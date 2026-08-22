-- **core の判断が派生の配布物へ全部届いているか。**
--
-- 派生は core と staging を join して作る。2団体目を core へ足しても
-- 派生モデルの join を直し忘れると、**エラーにならず配布物から消える**。
-- core を守る検査（budget_core_covers_all_staging）は staging→core しか見ていない。
{#- read_csv は dbt に依存として見えないので、配布物を書くモデルを依存として宣言する -#}
-- depends_on: {{ ref('pkg_derived__cofog') }}

with in_core as (
    select budget_line_id from {{ ref('core_budget_cofog') }}
    union all
    select budget_line_id from {{ ref('core_revenue_consolidation') }}
),

in_package as (
    select budget_line_id
    from read_csv('../data/budget/packages/derived/cofog.csv', header = true, all_varchar = true)
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
