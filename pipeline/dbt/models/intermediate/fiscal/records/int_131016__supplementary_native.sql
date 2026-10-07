with decoded as (
  select s.*,
         json_extract_string(context_json, '$.kan[0]') as kan_code,
         json_extract_string(context_json, '$.kan[1]') as kan_label,
         json_extract_string(context_json, '$.kou[0]') as kou_code,
         json_extract_string(context_json, '$.kou[1]') as kou_label,
         json_extract_string(context_json, '$.moku.code') as moku_code,
         json_extract_string(context_json, '$.moku.label') as moku_label,
         json_extract(context_json, '$.moku.row')::bigint as moku_source_row,
         json_extract_string(context_json, '$.project.code') as project_code,
         json_extract_string(context_json, '$.project.label') as project_label,
         json_extract(context_json, '$.project.row')::bigint as project_source_row,
         to_json(struct_pack(
           source_row := source_row, record_kind := record_kind, code := code, label := label,
           amount_before := amount_before, amount_delta := amount_delta, amount_after := amount_after,
           physical_page := physical_page, bbox_json := bbox_json, printed_text := printed_text,
           words_json := words_json, context_json := context_json
         ))::varchar as raw_original_json
  from {{ ref('stg_131016__supplementary_native') }} s
), observed as (
  select s.*, d.jurisdiction_code, d.fiscal_year,
         null::varchar as fund_code, json_extract_string(d.source_json, '$.fundLabel') as fund_label,
         null::varchar as expenditure_setsu_id, 'origin_line'::varchar as line_granularity,
         json_extract_string(d.source_json, '$.canonicalChanges') = 'true' as canonical_changes,
         d.phases_json, json_extract_string(d.source_json, '$.approvalStatus') as approval_status,
         json_extract_string(d.source_json, '$.approvalDate') as approval_date,
         json_extract(d.source_json, '$.approvalProof')::varchar as approval_proof_json,
         json_extract(d.source_json, '$.unitMultiplier')::bigint as unit_multiplier,
         h.effective_at, h.amendment_number,
         s.amount_before * unit_multiplier as before_yen,
         s.amount_delta * unit_multiplier as delta_yen,
         s.amount_after * unit_multiplier as after_yen,
         to_json([
           struct_pack(level := 'kan', code := s.kan_code, label := s.kan_label, nameSource := 'origin'),
           struct_pack(level := 'kou', code := s.kou_code, label := s.kou_label, nameSource := 'origin'),
           struct_pack(level := 'moku', code := s.moku_code, label := s.moku_label, nameSource := 'origin'),
           struct_pack(level := 'project', code := s.project_code, label := s.project_label, nameSource := 'origin')
         ])::varchar as account_path_json,
         '[]'::varchar as dimensions_json
  from decoded s
  join {{ ref('int_131016__supplementary_native_datasets') }} d using (dataset_id)
  left join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/history.json') h using (dataset_id)
), identities as (
  select *, json_object(
    'identityNamespace', 'chiyoda-supplementary-native-origin-line',
    'datasetId', dataset_id, 'originLine', fiscal_line_id,
    'hierarchy', account_path_json::json, 'dimensions', dimensions_json::json,
    'legalSetsuId', expenditure_setsu_id
  )::varchar as target_identity_json
  from observed
)
select *, {{ fiscal_budget_item_id('target_identity_json') }} as budget_item_id
from identities
order by dataset_id, source_row
