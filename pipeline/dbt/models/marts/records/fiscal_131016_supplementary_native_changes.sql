{{ config(materialized='table') }}
with printed_details as (
  select dataset_id, project_source_row,
         to_json(list(json_object(
           'fiscalLineId', fiscal_line_id, 'sourceRow', source_row,
           'amountDelta', delta_yen, 'rawOriginal', raw_original_json::json,
           'physicalPage', physical_page, 'bbox', bbox_json::json,
           'nonadditive', true
         ) order by source_row))::varchar as printed_details_json
  from {{ ref('int_131016__supplementary_native') }}
  where record_kind = 'detail_delta'
  group by dataset_id, project_source_row
)
select 'c-' || sha256(h.fiscal_line_id) as change_id, h.dataset_id, h.budget_item_id,
       h.delta_yen as amount_delta, 'supplementary'::varchar as change_kind, h.effective_at,
       h.amendment_number::bigint as sequence, h.source_row,
       null::varchar as counterpart_budget_item_id,
       null::bigint as carryover_from_year, null::bigint as carryover_to_year,
       null::varchar as cofog_code, 'unclassified'::varchar as cofog_status,
       '原典の事業増減額。節との対応と当初予算の基準額は未確認。COFOGは未分類。'::varchar as cofog_basis,
       to_json([json_object(
         'path', h.account_path_json::json, 'dimensions', h.dimensions_json::json,
         'amount', h.delta_yen, 'fiscalLineId', h.fiscal_line_id, 'sourceRow', h.source_row,
         'rawOriginal', h.raw_original_json::json, 'targetIdentity', h.target_identity_json::json,
         'physicalPage', h.physical_page, 'bbox', h.bbox_json::json,
         'sourceAmountUnit', json_extract_string(h.source_json, '$.sourceAmountUnit'),
         'unitMultiplier', h.unit_multiplier, 'approvalDate', h.approval_date,
         'approvalProof', h.approval_proof_json::json,
         'projectSetsuLinkage', 'unconfirmed', 'initialState', 'unconfirmed',
         'printedDetailRows', coalesce(p.printed_details_json, '[]')::json
       )])::varchar as details_json
from {{ ref('int_131016__supplementary_native') }} h
left join printed_details p on p.dataset_id = h.dataset_id and p.project_source_row = h.source_row
where h.record_kind = 'project_delta' and h.canonical_changes and h.phases_json = '["adjusted"]'
order by change_id
