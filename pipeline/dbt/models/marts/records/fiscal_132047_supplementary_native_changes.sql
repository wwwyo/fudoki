{{ config(materialized='table') }}
with printed_details as (
 select dataset_id, json_extract(context_json,'$.project.row')::bigint as project_source_row,
  to_json(list(json_object('sourceRow',source_row,'physicalPage',physical_page,'rawOriginal',raw_original_json::json,'nonadditive',true) order by source_row))::varchar as rows_json
 from {{ ref('int_132047__supplementary_native') }}
 where observation_role='project_observations' and json_extract(context_json,'$.project.row') is not null
 group by dataset_id,project_source_row
)
select 'c-'||sha256(f.dataset_id||':'||budget_item_id) as change_id,
 f.dataset_id,budget_item_id,delta_yen::bigint as amount_delta,
 'supplementary'::varchar as change_kind,effective_at,amendment_number::bigint as sequence,
 source_row,null::varchar as counterpart_budget_item_id,
 null::bigint as carryover_from_year,null::bigint as carryover_to_year,
 null::varchar as cofog_code,'unclassified'::varchar as cofog_status,
 '原典の事業増減額。目×節は独立内訳で対応不明。当初基準額・COFOGは未確認。'::varchar as cofog_basis,
 to_json([json_object('path',account_path_json::json,'dimensions',dimensions_json::json,
  'amount',delta_yen,'fiscalLineId',fiscal_line_id,'sourceRow',source_row,
  'sourceObservationRow',source_observation_row,'rawOriginal',raw_original_json::json,
  'targetIdentity',target_identity_json::json,'physicalPage',physical_page,'bbox',bbox_json::json,
  'sourceAmountUnit','千円','unitMultiplier',unit_multiplier,'sourceAmountKind','supplementary',
  'approvalDate',approval_date,'approvalProof',approval_proof_json::json,
  'initialState','unconfirmed','projectSetsuLinkage','independent_breakdowns',
  'statutorySetsuId',null,'financialPhase',null,
  'printedDetailRows',coalesce(details.rows_json,'[]')::json
 )])::varchar as details_json
from {{ ref('int_132047__supplementary_native') }} f
left join printed_details details on details.dataset_id=replace(f.dataset_id,'-project_delta','-project_observations')
 and details.project_source_row=json_extract(f.context_json,'$.project.row')::bigint
where observation_role='project_delta' and canonical_changes
 and source_amount_kind='supplementary' and phases_json='[]'
order by change_id
