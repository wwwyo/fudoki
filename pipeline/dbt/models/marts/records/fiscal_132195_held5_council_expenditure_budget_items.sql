{{ config(materialized='table') }}
select distinct budget_item_id,jurisdiction_code,fiscal_year,fund_code,fund_label,expenditure_setsu_id,
       case when expenditure_setsu_id is not null then 'expenditure_setsu' else 'origin_line' end as line_granularity,
       account_path_json,dimensions_json,
       to_json([
         struct_pack(kind:='hierarchy',level:='moku',value:=moku_label,nameSource:='origin',basis:=''),
         struct_pack(kind:='hierarchy',level:='project',value:=project_label,nameSource:='origin',basis:=''),
         struct_pack(kind:='hierarchy',level:='setsu',value:=setsu_label,nameSource:='origin',basis:='')
       ])::varchar as names_json,initial_state
from {{ ref('int_132195_held5_council_expenditure_changes') }}
order by budget_item_id
