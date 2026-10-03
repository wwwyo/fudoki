{{ api_model('fiscal_expenditure_budget_items') }}
with g as (
  select * from {{ ref('int_expenditure_setsu_groups') }}
), rep as (
  select budget_item_id, fiscal_line_id as rep_line_id, setsu_ordinal, setsu_label,
         row_number() over (partition by budget_item_id order by dataset_id, fiscal_line_id) as rn
  from g where line_granularity = 'expenditure_setsu'
), setsu_items as (
  select i.budget_item_id, i.jurisdiction_code, i.fiscal_year, i.fund_code, i.fund_label,
         i.expenditure_setsu_id, 'expenditure_setsu' as line_granularity,
         coalesce((select to_json(list(struct_pack(level:=h.level, code:=h.code, label:=h.label, nameSource:=h.name_source) order by h.ordinal))::varchar
                   from {{ ref('int_fiscal_line_hierarchy') }} h
                   where h.fiscal_line_id = r.rep_line_id and h.ordinal < r.setsu_ordinal), '[]') as account_path_json,
         coalesce((select to_json(list(struct_pack(dimension:=h.dimension, code:=h.code, label:=h.label) order by h.dimension))::varchar
                   from {{ ref('int_fiscal_line_dimensions') }} h
                   where h.fiscal_line_id = r.rep_line_id), '[]') as dimensions_json,
         'recorded' as initial_state
  from (
    select distinct budget_item_id, jurisdiction_code, fiscal_year, fund_code, fund_label,
           expenditure_setsu_id
    from g where line_granularity = 'expenditure_setsu'
  ) i
  join rep r on r.budget_item_id = i.budget_item_id and r.rn = 1
), setsu_names as (
  select r.budget_item_id,
         (select to_json(list(e order by t.ord))::varchar
          from (
            select 1 as ord, struct_pack(kind:=n.name_kind, level:=n.level, value:=n.value, nameSource:=n.name_source, basis:=n.basis) as e
            from {{ ref('int_fiscal_names') }} n
            where n.fiscal_line_id = r.rep_line_id
              and (n.name_kind != 'hierarchy'
                   or n.level in (select level from {{ ref('int_fiscal_line_hierarchy') }} h
                                  where h.fiscal_line_id = r.rep_line_id and h.ordinal < r.setsu_ordinal))
            union all
            select 2 as ord, struct_pack(kind:='hierarchy', level:='setsu', value:=r.setsu_label, nameSource:='canonical', basis:='')
            from (select 1) x
          ) t) as names_json
  from rep r
  where r.rn = 1
), origin_items as (
  select g.budget_item_id, g.jurisdiction_code, g.fiscal_year, g.fund_code, g.fund_label,
         g.expenditure_setsu_id, 'origin_line' as line_granularity,
         coalesce((select to_json(list(struct_pack(level:=h.level, code:=h.code, label:=h.label, nameSource:=h.name_source) order by h.ordinal))::varchar
                   from {{ ref('int_fiscal_line_hierarchy') }} h where h.fiscal_line_id = g.fiscal_line_id), '[]') as account_path_json,
         coalesce((select to_json(list(struct_pack(dimension:=h.dimension, code:=h.code, label:=h.label) order by h.dimension))::varchar
                   from {{ ref('int_fiscal_line_dimensions') }} h where h.fiscal_line_id = g.fiscal_line_id), '[]') as dimensions_json,
         coalesce((select to_json(list(struct_pack(kind:=h.name_kind, level:=h.level, value:=h.value, nameSource:=h.name_source, basis:=h.basis) order by h.name_kind, h.level))::varchar
                   from {{ ref('int_fiscal_names') }} h where h.fiscal_line_id = g.fiscal_line_id), '[]') as names_json,
         'recorded' as initial_state
  from g where g.line_granularity = 'origin_line'
)
select s.budget_item_id, s.jurisdiction_code, s.fiscal_year, s.fund_code, s.fund_label,
       s.expenditure_setsu_id, s.line_granularity, s.account_path_json, s.dimensions_json,
       n.names_json, s.initial_state
from setsu_items s join setsu_names n using (budget_item_id)
union all
select * from origin_items
order by budget_item_id
