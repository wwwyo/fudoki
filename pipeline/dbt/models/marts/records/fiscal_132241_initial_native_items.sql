{{ config(materialized='table') }}
select distinct budget_item_id,jurisdiction_code,fiscal_year,fund_code,fund_label,
 expenditure_setsu_id,line_granularity,account_path_json,dimensions_json,
 to_json([
 struct_pack(kind:='hierarchy',level:='moku',value:=moku_label,nameSource:='origin',basis:=''),
 struct_pack(kind:='hierarchy',level:='project',value:=project_label,nameSource:='origin',basis:='')
 ] || case when expenditure_setsu_id is null then [] else [
 struct_pack(kind:='hierarchy',level:='setsu',value:=left_setsu_label,nameSource:='origin',basis:='同じ目の左節コード・名称とFY2026法定節マスタの一致')
 ] end)::varchar as names_json, 'recorded'::varchar as initial_state
from {{ ref('int_132241__initial_native') }}
order by budget_item_id
