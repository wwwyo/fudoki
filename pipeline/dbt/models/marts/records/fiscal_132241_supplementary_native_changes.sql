{{ config(materialized='table') }}
select 'c-' || sha256(dataset_id || ':' || budget_item_id) as change_id,
       dataset_id, budget_item_id, sum(delta_yen)::bigint as amount_delta,
       'supplementary'::varchar as change_kind, effective_at, amendment_number::bigint as sequence,
       min(source_row) as source_row, null::varchar as counterpart_budget_item_id,
       null::bigint as carryover_from_year, null::bigint as carryover_to_year,
       null::varchar as cofog_code, 'unclassified'::varchar as cofog_status,
       '原典の事業×節の増減額。当初予算への対応とCOFOGは未確認。節の印字がない予備費は原典行を保持。'::varchar as cofog_basis,
       -- JSON merge-patch would delete NULL keys inside the replacement raw/context.
       to_json(list(case when replacement_dataset_id is null then json_object(
         'path', account_path_json::json, 'dimensions', dimensions_json::json,
         'amount', delta_yen, 'fiscalLineId', fiscal_line_id, 'sourceRow', source_row,
         'sourceObservationRow', source_observation_row, 'rawOriginal', raw_original_json::json,
         'targetIdentity', target_identity_json::json, 'physicalPage', effective_physical_page,
         'bbox', effective_bbox_json::json, 'sourceAmountUnit', json_extract_string(source_json, '$.sourceAmountUnit'),
         'unitMultiplier', unit_multiplier, 'approvalDate', approval_date,
         'approvalProof', approval_proof_json::json, 'printedSetsuCode', printed_setsu_code,
         'leftSetsuCode', left_setsu_code, 'leftSetsuName', left_setsu_label,
         'statutorySetsuId', expenditure_setsu_id,
         'otherTargetCorrespondence', 'unconfirmed-other-dataset-correspondence',
         'initialState', 'unconfirmed'
       ) else json_object(
         'path', account_path_json::json, 'dimensions', dimensions_json::json,
         'amount', delta_yen, 'fiscalLineId', fiscal_line_id, 'sourceRow', source_row,
         'sourceObservationRow', source_observation_row, 'rawOriginal', raw_original_json::json,
         'targetIdentity', target_identity_json::json, 'physicalPage', effective_physical_page,
         'bbox', effective_bbox_json::json, 'sourceAmountUnit', json_extract_string(source_json, '$.sourceAmountUnit'),
         'unitMultiplier', unit_multiplier, 'approvalDate', approval_date,
         'approvalProof', approval_proof_json::json, 'printedSetsuCode', printed_setsu_code,
         'leftSetsuCode', left_setsu_code, 'leftSetsuName', left_setsu_label,
         'statutorySetsuId', expenditure_setsu_id,
         'otherTargetCorrespondence', 'unconfirmed-other-dataset-correspondence',
         'initialState', 'unconfirmed',
         'replacementDatasetId', replacement_dataset_id, 'replacementSourceRow', replacement_source_row,
         'positionDatasetId', replacement_dataset_id,
         'replacementRaw', replacement_raw_json::json, 'effectiveContext', effective_context_json::json,
         'sameEventReplacement', true, 'originalProposalOnly', true
       ) end order by source_row))::varchar as details_json
from {{ ref('int_132241__supplementary_native') }}
where observation_role = 'expenditure' and canonical_changes
  and (phases_json = '["adjusted"]' or (composed_canonical_changes and phases_json = '[]'))
group by dataset_id, budget_item_id, effective_at, amendment_number
order by change_id
