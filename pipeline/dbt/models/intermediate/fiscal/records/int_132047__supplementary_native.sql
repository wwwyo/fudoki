with decoded as (
 select s.*,
  json_extract_string(context_json,'$.kan[0]') as kan_code,
  json_extract_string(context_json,'$.kan[1]') as kan_label,
  json_extract_string(context_json,'$.kou[0]') as kou_code,
  json_extract_string(context_json,'$.kou[1]') as kou_label,
  json_extract_string(context_json,'$.moku.code') as moku_code,
  json_extract_string(context_json,'$.moku.label') as moku_label,
  json_extract_string(context_json,'$.project.code') as project_code,
  json_extract_string(context_json,'$.project.label') as project_label,
  nullif(json_extract_string(context_json,'$.department'),'') as department,
  json_extract_string(context_json,'$.setsu.code') as left_setsu_code,
  json_extract_string(context_json,'$.setsu.label') as left_setsu_label,
  to_json(struct_pack(source_row:=source_row,source_observation_row:=source_observation_row,
   record_kind:=record_kind,code:=code,label:=label,amount:=amount,amount_text:=amount_text,
   physical_page:=physical_page,bbox_json:=bbox_json,printed_text:=printed_text,
   words_json:=words_json,context_json:=context_json,source_grain:=source_grain,
   printed_setsu_code:=printed_setsu_code))::varchar as raw_original_json
 from {{ ref('stg_132047__supplementary_native') }} s
), enriched as (
 select f.*,d.jurisdiction_code,d.fiscal_year,
  null::varchar as fund_code,json_extract_string(d.source_json,'$.fundLabel') as fund_label,
  json_extract_string(d.source_json,'$.observationRole') as observation_role,
  json_extract_string(d.source_json,'$.canonicalChanges')='true' as canonical_changes,
  d.phases_json,d.source_json,
  json_extract_string(d.source_json,'$.sourceAmountKind') as source_amount_kind,
  json_extract_string(d.source_json,'$.approvalStatus') as approval_status,
  json_extract_string(d.source_json,'$.approvalDate') as approval_date,
  json_extract(d.source_json,'$.approvalProof')::varchar as approval_proof_json,
  json_extract(d.source_json,'$.unitMultiplier')::bigint as unit_multiplier,
  json_extract_string(d.source_json,'$.effectiveAt') as effective_at,
  json_extract(d.source_json,'$.amendmentNumber')::bigint as amendment_number,
  f.amount*unit_multiplier as delta_yen,
  master.expenditure_setsu_id,
  'origin_line'::varchar as line_granularity,
  to_json([
   struct_pack(level:='kan',code:=f.kan_code,label:=f.kan_label,nameSource:='origin'),
   struct_pack(level:='kou',code:=f.kou_code,label:=f.kou_label,nameSource:='origin'),
   struct_pack(level:='moku',code:=f.moku_code,label:=f.moku_label,nameSource:='origin')
  ] || case when f.project_code is null then [] else [
   struct_pack(level:='project',code:=f.project_code,label:=f.project_label,nameSource:='origin')
  ] end)::varchar as account_path_json,
  '[]'::varchar as dimensions_json
 from decoded f
 join {{ ref('int_132047__supplementary_native_datasets') }} d using(dataset_id)
 left join {{ ref('fiscal_expenditure_setsu_master') }} master
  on json_extract_string(d.source_json,'$.observationRole') in ('left_setsu_observations','left_setsu_delta')
  and master.code=lpad(f.left_setsu_code,2,'0')
  and regexp_replace(master.label,'[、，,・･]','','g')=regexp_replace(f.left_setsu_label,'[、，,・･]','','g')
  and (master.valid_from_fiscal_year is null or master.valid_from_fiscal_year<=d.fiscal_year)
  and (master.valid_to_fiscal_year is null or master.valid_to_fiscal_year>=d.fiscal_year)
), identities as (
 select *,json_object('identityNamespace','mitaka-supplementary-printed-target',
  'datasetId',dataset_id,'hierarchy',account_path_json::json,'dimensions',dimensions_json::json,
  'legalSetsuId',null,'originLine',fiscal_line_id)::varchar as target_identity_json
 from enriched
)
select *,{{ fiscal_budget_item_id('target_identity_json') }} as budget_item_id
from identities
order by dataset_id,source_row
