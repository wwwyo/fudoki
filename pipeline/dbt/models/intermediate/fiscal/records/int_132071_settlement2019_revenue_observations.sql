-- Revenue detail rows are nonadditive until the leaf grain is proved:
-- executed (=収入済額) stays a printed reference, never a canonical amount here.
select s.*,
       executed as reference_amount_yen,
       'JPY' as currency,
       null::varchar as canonical_phase,
       null::bigint as canonical_financial_amount,
       'unconfirmed' as project_setsu_linkage,
       to_json(s)::varchar as original_raw_and_staging_json
from {{ ref('stg_132071__settlement2019_revenue') }} s
