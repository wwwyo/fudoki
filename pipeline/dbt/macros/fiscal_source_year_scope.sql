{# A column can be absent only for a declared year and original account label. #}
{% macro fiscal_source_year_filter(spec) %}
  {%- set predicates = [] -%}
  {%- if spec.get('years') -%}
    {%- do predicates.append('year in (' ~ spec['years'] | join(', ') ~ ')') -%}
  {%- endif -%}
  {%- for absent in spec.get('absent', []) -%}
    {%- do predicates.append('not (year = ' ~ absent['year'] ~ ' and "' ~ absent['column'] ~ '" = ' ~ "'" ~ absent['value'] | replace("'", "''") ~ "')") -%}
  {%- endfor -%}
  {{ return(predicates | join(' and ') or 'true') }}
{% endmacro %}
