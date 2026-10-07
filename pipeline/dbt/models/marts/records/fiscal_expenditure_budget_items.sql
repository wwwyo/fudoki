{{ config(materialized='table') }}
with g as (
  select g.* from {{ ref('int_expenditure_setsu_groups') }} g
  where not exists (select 1 from {{ ref('fiscal_132195_initial_moku_reference') }} r
                    where r.fiscal_line_id=g.fiscal_line_id and r.superseded_by_full_initial_detail)
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
         {# 同じ ord の名称も並べないと、並列走査で JSON 内の順序が変わる。 #}
         (select to_json(list(e order by t.ord, e))::varchar
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
union all
select * from {{ ref('int_132195_initial_budget_items') }}
union all
select distinct h.budget_item_id,h.jurisdiction_code,h.fiscal_year,h.fund_code,h.fund_label,
       h.expenditure_setsu_id,
       case when h.expenditure_setsu_id is not null then 'expenditure_setsu' else 'origin_line' end as line_granularity,
       h.account_path_json,h.dimensions_json,
       to_json([
         struct_pack(kind:='hierarchy',level:='moku',value:=h.moku_label,nameSource:='origin',basis:=''),
         struct_pack(kind:='hierarchy',level:='project',value:=h.project_label,nameSource:='origin',basis:=''),
         struct_pack(kind:='hierarchy',level:='setsu',value:=h.setsu_label,nameSource:='origin',basis:='')
       ])::varchar as names_json,h.initial_state
from {{ ref('int_supplementary_expenditure_changes') }} h
where not exists (select 1 from {{ ref('int_132195_initial_budget_items') }} i
                  where i.budget_item_id=h.budget_item_id)
union all
select c.* from {{ ref('fiscal_132195_council_expenditure_budget_items') }} c
where not exists (select 1 from g where g.budget_item_id=c.budget_item_id)
  and not exists (select 1 from {{ ref('int_132195_initial_budget_items') }} i where i.budget_item_id=c.budget_item_id)
  and not exists (select 1 from {{ ref('int_supplementary_expenditure_changes') }} s where s.budget_item_id=c.budget_item_id)
union all
select n.* from {{ ref('fiscal_132195_native_council_expenditure_budget_items') }} n
where not exists (select 1 from g where g.budget_item_id=n.budget_item_id)
  and not exists (select 1 from {{ ref('int_132195_initial_budget_items') }} i where i.budget_item_id=n.budget_item_id)
  and not exists (select 1 from {{ ref('int_supplementary_expenditure_changes') }} s where s.budget_item_id=n.budget_item_id)
  and not exists (select 1 from {{ ref('fiscal_132195_council_expenditure_budget_items') }} c where c.budget_item_id=n.budget_item_id)
union all
select * from {{ ref('int_132071_initial445_budget_items') }}
union all
select h.* from {{ ref('fiscal_132195_held5_council_expenditure_budget_items') }} h
where not exists (select 1 from g where g.budget_item_id=h.budget_item_id)
  and not exists (select 1 from {{ ref('int_132195_initial_budget_items') }} i where i.budget_item_id=h.budget_item_id)
  and not exists (select 1 from {{ ref('int_supplementary_expenditure_changes') }} s where s.budget_item_id=h.budget_item_id)
  and not exists (select 1 from {{ ref('fiscal_132195_council_expenditure_budget_items') }} c where c.budget_item_id=h.budget_item_id)
  and not exists (select 1 from {{ ref('fiscal_132195_native_council_expenditure_budget_items') }} n where n.budget_item_id=h.budget_item_id)
union all
select * from {{ ref('fiscal_132241_initial_native_items') }}
union all
select * from {{ ref('fiscal_131016_supplementary_native_items') }}
union all
select * from {{ ref('fiscal_132241_supplementary_native_items') }}
union all
select * from {{ ref('fiscal_132047_supplementary_native_items') }}
order by budget_item_id
