with expected as (
{% for code, direction in fiscal_units() %}
select fiscal_line_id, phase_id as phase, value, source_amount
from {{ ref('pkg_' ~ code ~ '__' ~ direction) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
)
select coalesce(e.fiscal_line_id, a.fiscal_line_id) as fiscal_line_id
from expected as e full outer join {{ ref('api_amounts') }} as a using (fiscal_line_id, phase)
where e.value is distinct from a.value or e.source_amount is distinct from a.source_amount
