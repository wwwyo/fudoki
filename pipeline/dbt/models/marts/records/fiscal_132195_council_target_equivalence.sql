{{ config(materialized='table') }}
-- Separate from the frozen496 legacy equivalence proofs. No amount matching,
-- sourceGrain normalization, or new initial row is used for this lookup.
select c.dataset_id,c.fiscal_line_id,c.source_row,c.fiscal_year,c.fund_label,c.amendment_number,
       c.origin_sha256,c.council_namespace_budget_item_id,c.budget_item_id,
       c.target_identity_json as council_target_identity_json,
       c.exact_initial_fiscal_line_id as initial_fiscal_line_id,
       i.dataset_id as initial_dataset_id,i.origin_sha256 as initial_origin_sha256,
       i.initial_namespace_budget_item_id,
       c.exact_initial_compatibility_identity_json as initial_compatibility_identity_json,
       'confirmed-whole-exact-identity-json-including-sourceGrain'::varchar as equivalence_status
from {{ ref('int_132195_council_expenditure_changes') }} c
join {{ ref('int_132195_initial_detail') }} i
  on c.exact_initial_fiscal_line_id=i.fiscal_line_id
where c.target_identity_json=c.exact_initial_compatibility_identity_json
order by c.fiscal_line_id
