with expected as (
{% for code, direction in fiscal_units() %}
select fiscal_line_id, cofog_status, coalesce(cofog_division::varchar, '') as cofog_division,
       coalesce(cofog_group::varchar, '') as cofog_group, coalesce(cofog_class::varchar, '') as cofog_class,
       cofog_consolidation, cofog_decided_at_level, coalesce(cofog_rule_id::varchar, '') as cofog_rule_id,
       coalesce(cofog_counterpart_fund::varchar, '') as counterpart_fund
from {{ ref('pkg_' ~ code ~ '__cofog') }}
where direction = '{{ direction }}'
{% if not loop.last %}union all{% endif %}
{% endfor %}
), actual as (
select l.fiscal_line_id, l.cofog_status,
       coalesce(case c.level when 'division' then c.code when 'group' then p.code else g.code end, '') as cofog_division,
       coalesce(case c.level when 'group' then c.code when 'class' then p.code else '' end, '') as cofog_group,
       coalesce(case c.level when 'class' then c.code else '' end, '') as cofog_class,
       l.consolidation as cofog_consolidation, l.cofog_decided_at_level, l.cofog_rule_id, l.counterpart_fund
from {{ ref('api_fiscal_lines') }} l
left join {{ ref('api_cofog_codes') }} c on c.code=l.cofog_code
left join {{ ref('api_cofog_codes') }} p on p.code=c.parent_code
left join {{ ref('api_cofog_codes') }} g on g.code=p.parent_code
)
select * from (select * from expected except select * from actual)
union all
select * from (select * from actual except select * from expected)
