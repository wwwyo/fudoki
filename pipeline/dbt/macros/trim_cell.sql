{% macro trim_cell(col) -%}
    staging_text(cast({{ col }} as varchar))
{%- endmacro %}
