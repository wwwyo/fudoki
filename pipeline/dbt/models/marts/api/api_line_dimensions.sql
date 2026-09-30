{{ api_model('line_dimensions') }}
{% set ns = namespace(first=true) %}
{% for code, direction in fiscal_units() %}
{% for dimension in var('fiscal_extra_key_columns')[code][direction] %}
{% if not ns.first %}union all{% endif %}{% set ns.first=false %}
select fiscal_line_id, '{{ dimension }}' as dimension,
       coalesce({{ dimension }}_code, '') as code, coalesce({{ dimension }}_label, '') as label
from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
{% endfor %}
{% endfor %}
order by fiscal_line_id, dimension
