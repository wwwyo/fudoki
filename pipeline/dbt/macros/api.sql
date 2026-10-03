{% macro fiscal_budget_item_id(identity) %}
'b-' || sha256({{ identity }})
{%- endmacro %}
{% macro api_model(table) %}
  {{ return(config(materialized='table', post_hook="COPY " ~ this ~ " TO '" ~ env_var('FUDOKI_API_DIR') ~ '/' ~ table ~ ".jsonl' (FORMAT JSON)")) }}
{% endmacro %}

{% macro fiscal_budget_items(direction) %}
select {{ fiscal_budget_item_id('l.fiscal_line_id') }} as budget_item_id,d.jurisdiction_code,d.fiscal_year,l.fund_code,l.fund_label,
 coalesce((select to_json(list(struct_pack(level:=h.level,code:=h.code,label:=h.label,nameSource:=h.name_source) order by h.ordinal))::varchar from {{ ref('int_fiscal_line_hierarchy') }} h where h.fiscal_line_id=l.fiscal_line_id),'[]') as account_path_json,
 coalesce((select to_json(list(struct_pack(dimension:=h.dimension,code:=h.code,label:=h.label) order by h.dimension))::varchar from {{ ref('int_fiscal_line_dimensions') }} h where h.fiscal_line_id=l.fiscal_line_id),'[]') as dimensions_json,
 coalesce((select to_json(list(struct_pack(kind:=h.name_kind,level:=h.level,value:=h.value,nameSource:=h.name_source,basis:=h.basis) order by h.name_kind,h.level))::varchar from {{ ref('int_fiscal_names') }} h where h.fiscal_line_id=l.fiscal_line_id),'[]') as names_json,
 'recorded' as initial_state
 from {{ ref('int_fiscal_lines') }} l join {{ ref('int_fiscal_datasets') }} d using(dataset_id)
 where d.direction='{{ direction }}' and d.document_kind='budget' order by budget_item_id
{% endmacro %}
