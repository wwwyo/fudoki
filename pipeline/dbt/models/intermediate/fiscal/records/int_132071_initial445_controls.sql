select s.*, amount * 1000::bigint as reference_amount_yen,
       null::varchar as canonical_phase, null::bigint as canonical_financial_amount,
       to_json(s)::varchar as original_raw_and_staging_json
from {{ ref('stg_132071__initial445_controls') }} s
