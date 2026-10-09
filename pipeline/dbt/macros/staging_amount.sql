{% macro staging_amount(col) -%}
    staging_amount(cast({{ col }} as varchar))
{%- endmacro %}
