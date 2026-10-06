-- Every original row must have a declaration for each amount name, at its year and document kind.
{% for code, direction in fiscal_units() %}
{% for name in fiscal_amount_names(code, direction) %}
{% set predicates = [] %}
{% for a in fiscal_amount_variants(code, direction, name) %}
{% do predicates.append('(' ~ (fiscal_amount_year_filter(a, 'year') or 'true') ~ ')') %}
{% endfor %}
select '{{ code }}' as jurisdiction, '{{ direction }}' as direction, '{{ name }}' as amount,
       year as fiscal_year, document_kind, count(*) as rows
from {{ source('raw_' ~ code, direction) }}
where not ({{ predicates | join(' or ') }})
group by 1, 2, 3, 4, 5
union all
{% endfor %}
{% endfor %}
select null, null, null, null, null, null where false
