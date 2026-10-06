-- Metadata-only page inventory; no monetary fields are synthesized.
select s.*, null::bigint as canonical_financial_amount, null::varchar as canonical_phase
from {{ ref('stg_132071__settlement2020_2023_page_inventory') }} s
