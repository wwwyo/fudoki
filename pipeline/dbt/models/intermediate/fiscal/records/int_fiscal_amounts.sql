{% for code, direction in fiscal_units() %}
{% set amounts = var('fiscal_amounts')[code][direction] %}
select fiscal_line_id, phase_id as phase, value, source_amount,
{% if fiscal_amount_unit_is_column(code, direction) %}
       source_amount_unit,
{% else %}
       '{{ amounts[0]['unit'] }}' as source_amount_unit,
{% endif %}
       case when (
       {% for amount in amounts if amount['primary'] %}
         (phase_id = '{{ amount['phase'] }}' and {{ fiscal_amount_year_filter(amount) or 'true' }})
         {% if not loop.last %}or{% endif %}
       {% endfor %}
       ) then 1 else 0 end as is_primary
from {{ ref('pkg_' ~ code ~ '__' ~ direction) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
order by fiscal_line_id, phase
