with observed as (
 select s.*, amount * 1000::bigint as initial_yen,
        null::varchar as fund_code, account_name as fund_label,
        null::varchar as expenditure_setsu_id,
        'unconfirmed-no-printed-explanation-code'::varchar as expenditure_setsu_status,
        to_json([
         struct_pack(level:='kan',code:=kan_code,label:=kan_name,nameSource:='origin'),
         struct_pack(level:='kou',code:=kou_code,label:=kou_name,nameSource:='origin'),
         struct_pack(level:='moku',code:=moku_code,label:=moku_name,nameSource:='origin')
        ] || case when nullif(project_name,'') is null then [] else [struct_pack(level:='project',code:=project_code,label:=project_name,nameSource:='origin')] end
          || case when nullif(setsu_name,'') is null then [] else [struct_pack(level:='setsu',code:=printed_setsu_code,label:=setsu_name,nameSource:='origin')] end
          || case when nullif(detail_name,'') is null then [] else [struct_pack(level:='detail',code:=null::varchar,label:=detail_name,nameSource:='origin')] end)::varchar as account_path_json,
        case when department is null then '[]' else to_json([struct_pack(dimension:='department',code:=null::varchar,label:=department)])::varchar end as dimensions_json,
        to_json(s)::varchar as original_raw_and_staging_json
 from {{ ref('stg_132071__initial445_explanation') }} s
), identities as (
 select *, json_object('identityNamespace','akishima-initial445-observed-origin-row',
   'jurisdiction',jurisdiction_code,'year',fiscal_year,'account',account_name,
   'observedHierarchy',account_path_json::json,'dimensions',dimensions_json::json,
   'printedSetsuCode',printed_setsu_code,'sourceGrain',source_grain,
   'originalSourceRowIdentity',source_row_id)::varchar as target_identity_json
 from observed
)
select *, {{ fiscal_budget_item_id('target_identity_json') }} as budget_item_id,
       'recorded'::varchar as initial_state,
       'unconfirmed-other-namespace-correspondence'::varchar as target_correspondence_status
from identities
