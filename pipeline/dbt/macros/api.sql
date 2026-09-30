{% macro api_model(table) %}
  {{ return(config(materialized='external', format='json', location=env_var('FUDOKI_API_DIR') ~ '/' ~ table ~ '.jsonl')) }}
{% endmacro %}
