{% macro fiscal_distribution_csv(jurisdiction_code, resource) %}
  {# DuckDB の表走査順は固定されないので、配布ハッシュを物理的な行配置に依存させない。 #}
  {{ config(
    materialized='table',
    post_hook="COPY (SELECT * FROM " ~ this ~ " ORDER BY ALL) TO '"
      ~ env_var('FUDOKI_PACKAGE_DIR') ~ '/' ~ jurisdiction_code ~ '/' ~ resource
      ~ ".csv' (FORMAT CSV, HEADER TRUE)"
  ) }}
{% endmacro %}
