{{ config(materialized='table') }}
select dataset_id,fiscal_line_id,source_row,source_observation_row,jurisdiction_code,fiscal_year,
 fund_code,fund_label,kan_code,kan_label,kou_code,kou_label,moku_code,moku_label,
 left_setsu_code,left_setsu_label,expenditure_setsu_id,
 delta_yen as amount_delta,'supplementary'::varchar as source_amount_kind,
 null::varchar as financial_phase,approval_status,approval_date,approval_proof_json,effective_at,
 amendment_number,physical_page,bbox_json,printed_text,words_json,context_json,raw_original_json,
 true as nonadditive,'independent_breakdowns'::varchar as project_setsu_linkage,
 'unclassified'::varchar as cofog_status,null::varchar as cofog_code
from {{ ref('int_132047__supplementary_native') }}
where observation_role='left_setsu_delta'
order by dataset_id,source_row
