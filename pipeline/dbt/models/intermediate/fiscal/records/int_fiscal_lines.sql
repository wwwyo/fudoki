{% for code, direction in fiscal_units() %}
select fiscal_line_id, s.dataset_id, s.source_row,
       coalesce(s.fund_code, '') as fund_code, coalesce(s.fund_label, '') as fund_label,
       nullif(coalesce(nullif(c.cofog_class, ''), nullif(c.cofog_group, ''), c.cofog_division), '') as cofog_code,
       c.cofog_status, c.cofog_consolidation as consolidation,
       c.cofog_decided_at_level, coalesce(c.cofog_rule_id, '') as cofog_rule_id,
       coalesce(c.cofog_basis, '') as cofog_basis,
       coalesce(c.cofog_counterpart_fund, '') as counterpart_fund
from {{ ref('stg_' ~ code ~ '__' ~ direction) }} s
join {{ ref('core_fiscal_cofog' if direction == 'expenditure' else 'core_revenue_consolidation') }} c using (fiscal_line_id)
{% if not loop.last %}union all{% endif %}
{% endfor %}
order by fiscal_line_id
