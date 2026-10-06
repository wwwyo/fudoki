{{ config(materialized='table') }}
{# 原典行の決算表は対応リンクの参照先として保持し、集約結果を別モデルで提供する。 #}
with grouped as (
  select settlement_group_id as fiscal_line_id, dataset_id,
         min(source_row) as source_row, min(fiscal_line_id) as representative_line_id,
         any_value(fund_code) as fund_code, any_value(fund_label) as fund_label,
         any_value(expenditure_setsu_id) as expenditure_setsu_id,
         any_value(line_granularity) as line_granularity,
         any_value(setsu_ordinal) as setsu_ordinal,
         sum(amount) as amount,
         to_json(list(struct_pack(
           path := from_json(sub_path_json, '[{"level":"VARCHAR","code":"VARCHAR","label":"VARCHAR"}]'),
           amount := amount, fiscalLineId := fiscal_line_id, sourceRow := source_row)
           order by source_row, fiscal_line_id))::varchar as details_json,
         any_value(consolidation) as consolidation,
         any_value(counterpart_fund) as counterpart_fund,
         any_value(cofog_code) as cofog_code,
         any_value(cofog_status) as cofog_status,
         any_value(cofog_basis) as cofog_basis
  from {{ ref('int_settlement_expenditure_setsu_groups') }}
  group by dataset_id, settlement_group_id
)
select g.* exclude (representative_line_id, setsu_ordinal),
       coalesce((select to_json(list(struct_pack(
         level := h.level, code := h.code, label := h.label, nameSource := h.name_source)
         order by h.ordinal))::varchar
         from {{ ref('int_fiscal_line_hierarchy') }} h
         where h.fiscal_line_id = g.representative_line_id
           and (g.line_granularity = 'origin_line' or h.ordinal < g.setsu_ordinal)), '[]') as account_path_json,
       coalesce((select to_json(list(struct_pack(
         dimension := h.dimension, code := h.code, label := h.label)
         order by h.dimension))::varchar
         from {{ ref('int_fiscal_line_dimensions') }} h
         where h.fiscal_line_id = g.representative_line_id), '[]') as dimensions_json
from grouped g
order by fiscal_line_id
