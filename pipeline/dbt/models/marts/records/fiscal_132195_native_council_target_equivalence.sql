{{ config(materialized='table') }}
select dataset_id,fiscal_line_id,source_row,fiscal_year,fund_label,amendment_number,origin_sha256,
       native_namespace_budget_item_id,budget_item_id,target_identity_json,
       exact_initial_fiscal_line_id,exact_initial_compatibility_identity_json,
       exact_existing_fiscal_line_id,exact_existing_target_identity_json,
       'confirmed-whole-exact-identity-json-including-sourceGrain'::varchar as equivalence_status
from {{ ref('int_132195_native_council_expenditure_changes') }}
where exact_initial_fiscal_line_id is not null or exact_existing_fiscal_line_id is not null
order by fiscal_line_id
