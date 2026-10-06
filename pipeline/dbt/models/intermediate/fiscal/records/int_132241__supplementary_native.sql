with decoded as (
  select s.*,
         json_extract_string(context_json, '$.kan[0]') as kan_code,
         json_extract_string(context_json, '$.kan[1]') as kan_label,
         json_extract_string(context_json, '$.kou[0]') as kou_code,
         json_extract_string(context_json, '$.kou[1]') as kou_label,
         json_extract_string(context_json, '$.moku.code') as moku_code,
         json_extract_string(context_json, '$.moku.label') as moku_label,
         json_extract(context_json, '$.moku.key')::varchar as moku_key,
         json_extract_string(context_json, '$.project.code') as project_code,
         json_extract_string(context_json, '$.project.label') as project_label,
         json_extract_string(context_json, '$.department') as department,
         to_json(struct_pack(
           source_row := source_row, source_observation_row := source_observation_row,
           record_kind := record_kind, code := code, label := label, amount := amount,
           amount_text := amount_text, physical_page := physical_page,
           bbox_json := bbox_json, printed_text := printed_text, words_json := words_json,
           context_json := context_json, source_grain := source_grain,
           printed_setsu_code := printed_setsu_code
         ))::varchar as raw_original_json
  from {{ ref('stg_132241__supplementary_native') }} s
), left_names as (
  select _partition_origin_sha256, _partition_fiscal_year,
         replace(table_id, '-observations', '-expenditure') as financial_table_id,
         moku_key, try_cast(code as integer) as setsu_code, min(label) as left_setsu_label
  from decoded
  where record_kind = 'left-setsu' and code is not null
  group by _partition_origin_sha256, _partition_fiscal_year, financial_table_id, moku_key, setsu_code
  having count(distinct label) = 1
), observed as (
  select f.*, d.jurisdiction_code, d.fiscal_year,
         null::varchar as fund_code, json_extract_string(d.source_json, '$.fundLabel') as fund_label,
         json_extract_string(d.source_json, '$.observationRole') as observation_role,
         json_extract_string(d.source_json, '$.canonicalChanges') = 'true' as canonical_changes,
         d.phases_json, json_extract_string(d.source_json, '$.approvalStatus') as approval_status,
         json_extract_string(d.source_json, '$.approvalDate') as approval_date,
         json_extract(d.source_json, '$.approvalProof')::varchar as approval_proof_json,
         json_extract(d.source_json, '$.unitMultiplier')::bigint as unit_multiplier,
         d.source_json, h.effective_at, h.amendment_number,
         f.amount * unit_multiplier as delta_yen,
         l.setsu_code as left_setsu_code, l.left_setsu_label, master.expenditure_setsu_id,
         case when master.expenditure_setsu_id is not null then 'expenditure_setsu'
              else 'origin_line' end as line_granularity,
         to_json([
           struct_pack(level := 'kan', code := f.kan_code, label := f.kan_label, nameSource := 'origin'),
           struct_pack(level := 'kou', code := f.kou_code, label := f.kou_label, nameSource := 'origin'),
           struct_pack(level := 'moku', code := f.moku_code, label := f.moku_label, nameSource := 'origin'),
           struct_pack(level := 'project', code := f.project_code, label := f.project_label, nameSource := 'origin')
         ])::varchar as account_path_json,
         to_json([struct_pack(dimension := 'department', code := null::varchar,
                              label := f.department)])::varchar as dimensions_json
  from decoded f
  join {{ ref('int_132241__supplementary_native_datasets') }} d using (dataset_id)
  left join read_json_auto('{{ env_var("FUDOKI_DECLARATIONS_DIR") }}/history.json') h using (dataset_id)
  left join left_names l on l._partition_origin_sha256 = f._partition_origin_sha256
    and l._partition_fiscal_year = f._partition_fiscal_year
    and l.financial_table_id = f.table_id and l.moku_key = f.moku_key
    and l.setsu_code = try_cast(f.printed_setsu_code as integer)
  left join {{ ref('fiscal_expenditure_setsu_master') }} master
    on try_cast(master.code as integer) = l.setsu_code
    and replace(replace(master.label, '、', ''), '・', '') = replace(replace(l.left_setsu_label, '、', ''), '・', '')
    and (master.valid_from_fiscal_year is null or master.valid_from_fiscal_year <= d.fiscal_year)
    and (master.valid_to_fiscal_year is null or master.valid_to_fiscal_year >= d.fiscal_year)
), identities as (
  select *, json_object(
    'identityNamespace', 'tama-supplementary-printed-target', 'datasetId', dataset_id,
    'hierarchy', account_path_json::json, 'dimensions', dimensions_json::json,
    'legalSetsuId', expenditure_setsu_id,
    'originLine', case when expenditure_setsu_id is null then fiscal_line_id else null end
  )::varchar as target_identity_json
  from observed
)
select *, {{ fiscal_budget_item_id('target_identity_json') }} as budget_item_id
from identities
order by dataset_id, source_row
