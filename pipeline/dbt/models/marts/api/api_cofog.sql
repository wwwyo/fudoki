{{ api_model('cofog') }}
select fiscal_line_id, cofog_status as status, coalesce(cofog_division, '') as division,
       coalesce(cofog_group, '') as "group", coalesce(cofog_class, '') as class,
       cofog_consolidation as consolidation, cofog_decided_at_level as decided_at_level,
       coalesce(cofog_rule_id, '') as rule_id, coalesce(cofog_basis, '') as basis,
       coalesce(cofog_counterpart_fund, '') as counterpart_fund
from (
    select * from {{ ref('core_fiscal_cofog') }}
    union all
    select * from {{ ref('core_revenue_consolidation') }}
)
order by fiscal_line_id
