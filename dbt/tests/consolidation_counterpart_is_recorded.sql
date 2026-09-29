-- **連結消去の相手方会計が収録した会計であること。**
-- 相手方がこの団体の収録範囲に無い会計（都・他の基金など）を消すと、
-- 受け側が存在しないまま支払側だけが消えて全会計の合計が壊れる。
with funds as (
    select distinct jurisdiction_code, fund_label from {{ ref('fund_directory') }}
),

eliminated as (
    select jurisdiction_code, cofog_counterpart_fund as counterpart, 'expenditure' as side
    from {{ ref('core_budget_cofog') }}
    where cofog_consolidation = 'eliminated'
    union all
    select jurisdiction_code, cofog_counterpart_fund, 'revenue'
    from {{ ref('core_revenue_consolidation') }}
    where cofog_consolidation = 'eliminated'
)

select e.jurisdiction_code, e.side, e.counterpart
from eliminated as e
left join funds as f
    on f.jurisdiction_code = e.jurisdiction_code and f.fund_label = e.counterpart
where e.counterpart is null or f.fund_label is null
