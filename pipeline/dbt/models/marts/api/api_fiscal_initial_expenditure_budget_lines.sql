{{ api_model('fiscal_initial_expenditure_budget_lines') }}
with g as (
  select * from {{ ref('int_expenditure_setsu_groups') }}
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
order by fiscal_line_id
