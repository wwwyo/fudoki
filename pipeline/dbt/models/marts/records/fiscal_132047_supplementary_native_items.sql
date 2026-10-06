{{ config(materialized='table') }}
select budget_item_id,jurisdiction_code,fiscal_year,fund_code,fund_label,
 null::varchar as expenditure_setsu_id,line_granularity,account_path_json,dimensions_json,
 to_json([
 struct_pack(kind:='hierarchy',level:='moku',value:=moku_label,nameSource:='origin',basis:='')
 ] || case when project_label is null then [] else [
 struct_pack(kind:='hierarchy',level:='project',value:=project_label,nameSource:='origin',basis:='')
 ] end)::varchar as names_json,'unconfirmed'::varchar as initial_state
from {{ ref('int_132047__supplementary_native') }}
where observation_role='project_delta' and canonical_changes
 and source_amount_kind='supplementary' and phases_json='[]'
order by budget_item_id
