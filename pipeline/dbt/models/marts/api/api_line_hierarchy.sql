{{ api_model('line_hierarchy') }}
{% set ns = namespace(first=true) %}
{% for code, direction in fiscal_units() %}
{% for level in var('fiscal_levels')[code][direction] %}
{% if not ns.first %}union all{% endif %}{% set ns.first=false %}
select s.fiscal_line_id, {{ loop.index0 }} as ordinal, '{{ level }}' as level,
       coalesce(s.{{ level }}_code, '') as code,
{% if level in ['kan', 'kou', 'moku'] %}
       coalesce(nullif(s.{{ level }}_label, ''), a.{{ level }}_name, '') as label,
       case when nullif(s.{{ level }}_label, '') is not null then 'canonical'
            when nullif(a.{{ level }}_name, '') is not null then coalesce(a.name_source, '') else '' end as name_source
{% else %}
       coalesce(s.{{ level }}_label, '') as label,
       case when nullif(s.{{ level }}_label, '') is not null then 'canonical' else '' end as name_source
{% endif %}
from {{ ref('stg_' ~ code ~ '__' ~ direction) }} as s
{% if level in ['kan', 'kou', 'moku'] %}
left join {{ ref('core_fiscal_accounts') }} as a
using (jurisdiction_code, fiscal_year, direction, fund_code, fund_label, kan_code, kou_code, moku_code)
{% endif %}
{% endfor %}
{% endfor %}
order by fiscal_line_id, ordinal
