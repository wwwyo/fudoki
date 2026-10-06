{{ config(materialized='table') }}
with g as (
  select g.* from {{ ref('int_expenditure_setsu_groups') }} g
  where not exists (select 1 from {{ ref('fiscal_132195_initial_moku_reference') }} r
                    where r.fiscal_line_id=g.fiscal_line_id and r.superseded_by_full_initial_detail)
), aggregated as (
  select g.group_line_id as fiscal_line_id, g.dataset_id, g.budget_item_id,
         min(g.source_row) as source_row, sum(g.amount) as amount,
         cast(to_json(list(
           struct_pack(
             path := from_json(g.sub_path_json, '[{"level":"VARCHAR","code":"VARCHAR","label":"VARCHAR"}]'),
             amount := g.amount,
             fiscalLineId := g.fiscal_line_id,
             sourceRow := g.source_row)
           order by g.source_row, g.fiscal_line_id)) as varchar) as details_json,
         any_value(g.consolidation) as consolidation,
         any_value(g.counterpart_fund) as counterpart_fund,
         any_value(g.cofog_code) as cofog_code,
         any_value(g.cofog_status) as cofog_status,
         any_value(g.cofog_basis) as cofog_basis
  from g
  where g.line_granularity = 'expenditure_setsu'
  group by g.dataset_id, g.group_line_id, g.budget_item_id
), origin as (
  select g.fiscal_line_id, g.dataset_id, g.budget_item_id, g.source_row, g.amount,
         cast(to_json([struct_pack(
           path := from_json(g.sub_path_json, '[{"level":"VARCHAR","code":"VARCHAR","label":"VARCHAR"}]'),
           amount := g.amount,
           fiscalLineId := g.fiscal_line_id,
           sourceRow := g.source_row)]) as varchar) as details_json,
         g.consolidation, g.counterpart_fund, g.cofog_code, g.cofog_status, g.cofog_basis
  from g
  where g.line_granularity = 'origin_line'
)
select * from aggregated
union all
select * from origin
union all
select * from {{ ref('fiscal_132195_initial_detail_lines') }}
union all
select * from {{ ref('fiscal_132071_initial445_lines') }}
union all
select * from {{ ref('fiscal_132241_initial_native_lines') }}
order by fiscal_line_id
