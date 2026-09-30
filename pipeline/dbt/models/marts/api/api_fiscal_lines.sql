{{ api_model('fiscal_lines') }}
{% for code, direction in fiscal_units() %}
select fiscal_line_id, dataset_id, source_row,
       coalesce(fund_code, '') as fund_code, coalesce(fund_label, '') as fund_label
from {{ ref('stg_' ~ code ~ '__' ~ direction) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
order by fiscal_line_id
