select budget_item_id,jurisdiction_code,fiscal_year,fund_code,fund_label,expenditure_setsu_id,
       'origin_line'::varchar as line_granularity,account_path_json,dimensions_json,
       to_json([
        struct_pack(kind:='hierarchy',level:='kan',value:=kan_name,nameSource:='origin',basis:=''),
        struct_pack(kind:='hierarchy',level:='kou',value:=kou_name,nameSource:='origin',basis:=''),
        struct_pack(kind:='hierarchy',level:='moku',value:=moku_name,nameSource:='origin',basis:=''),
        struct_pack(kind:='hierarchy',level:='project',value:=project_name,nameSource:='origin',basis:=''),
        struct_pack(kind:='hierarchy',level:='setsu',value:=setsu_name,nameSource:='origin',basis:=''),
        struct_pack(kind:='hierarchy',level:='detail',value:=detail_name,nameSource:='origin',basis:='')
       ])::varchar as names_json,initial_state
from {{ ref('int_132071_initial445') }}
