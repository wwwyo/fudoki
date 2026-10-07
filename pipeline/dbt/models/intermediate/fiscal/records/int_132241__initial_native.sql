with decoded as (
 select s.*, json_extract_string(context_json,'$.kan[0]') as kan_code,
 json_extract_string(context_json,'$.kan[1]') as kan_label,
 json_extract_string(context_json,'$.kou[0]') as kou_code,
 json_extract_string(context_json,'$.kou[1]') as kou_label,
 json_extract_string(context_json,'$.moku.code') as moku_code,
 json_extract_string(context_json,'$.moku.label') as moku_label,
 json_extract(context_json,'$.moku.key')::varchar as moku_key,
 json_extract_string(context_json,'$.project.code') as project_code,
 json_extract_string(context_json,'$.project.label') as project_label,
 json_extract_string(context_json,'$.department') as department
 from {{ ref('stg_132241__initial_native') }} s
), left_names as (
 select distinct replace(table_id,'-observations','-expenditure') as financial_table_id,
        moku_key, cast(code as integer) as setsu_code, label as left_setsu_label
 from decoded where record_kind='left-setsu' and code is not null
), observed as (
 select f.*, '132241'::varchar as jurisdiction_code, 2026::integer as fiscal_year,
        null::varchar as fund_code, json_extract_string(d.source_json,'$.fundLabel') as fund_label,
        f.amount * 1000::bigint as initial_yen, l.setsu_code as left_setsu_code,
        l.left_setsu_label, master.expenditure_setsu_id,
        case when master.expenditure_setsu_id is not null then 'expenditure_setsu' else 'origin_line' end as line_granularity,
        to_json([
          struct_pack(level:='kan',code:=f.kan_code,label:=f.kan_label,nameSource:='origin'),
          struct_pack(level:='kou',code:=f.kou_code,label:=f.kou_label,nameSource:='origin'),
          struct_pack(level:='moku',code:=f.moku_code,label:=f.moku_label,nameSource:='origin'),
          struct_pack(level:='project',code:=f.project_code,label:=f.project_label,nameSource:='origin')
        ])::varchar as account_path_json,
        to_json([struct_pack(dimension:='department',code:=null::varchar,label:=f.department)])::varchar as dimensions_json,
        to_json(f)::varchar as raw_original_json
 from decoded f
 join {{ ref('int_132241__initial_native_datasets') }} d using(dataset_id)
 left join left_names l on l.financial_table_id=f.table_id and l.moku_key=f.moku_key
                      and l.setsu_code=try_cast(f.printed_setsu_code as integer)
 left join {{ ref('fiscal_expenditure_setsu_master') }} master
   on try_cast(master.code as integer)=l.setsu_code
  and replace(replace(master.label,'、',''),'・','')=replace(replace(l.left_setsu_label,'、',''),'・','')
  and (master.valid_from_fiscal_year is null or master.valid_from_fiscal_year<=2026)
  and (master.valid_to_fiscal_year is null or master.valid_to_fiscal_year>=2026)
 where ends_with(f.table_id,'-expenditure') and d.phases_json='["approved"]'
), identities as (
 select *, json_object('identityNamespace','tama-initial-printed-target',
 'datasetId',dataset_id,'hierarchy',account_path_json::json,'dimensions',dimensions_json::json,
 'legalSetsuId',expenditure_setsu_id,
 'originLine',case when expenditure_setsu_id is null then fiscal_line_id else null end)::varchar as target_identity_json
 from observed
)
select *, {{ fiscal_budget_item_id('target_identity_json') }} as budget_item_id
from identities
